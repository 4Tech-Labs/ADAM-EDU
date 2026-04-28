from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal, Sequence
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shared.models import Assignment, CaseGrade, CaseGradeModuleEntry, CaseGradeQuestionEntry
from shared.sanitization import sanitize_untrusted_text
from shared.teacher_context import TeacherContext
from shared.teacher_gradebook_schema import TeacherCaseSubmissionDetailResponse
from shared.teacher_grading_schema import (
    RUBRIC_TO_SCORE,
    PublicationState,
    TeacherGradeModulePayload,
    TeacherGradeModuleResponse,
    TeacherGradeQuestionPayload,
    TeacherGradeQuestionResponse,
    TeacherGradeRequestBody,
    TeacherGradeResponse,
)
from shared.teacher_reads import (
    _assignment_target_course_metadata,
    _load_teacher_submission_assignment,
    get_teacher_case_submission_detail,
)
from shared.teacher_writes import utc_now

_DEFAULT_MAX_SCORE = Decimal("5.0")
_DISPLAY_SCORE_QUANTUM = Decimal("0.1")
_NORMALIZED_SCORE_QUANTUM = Decimal("0.0001")
_WEIGHT_QUANTUM = Decimal("0.001")
_MODULE_FEEDBACK_MAX_CHARS = 2000
_QUESTION_FEEDBACK_MAX_CHARS = 2000
_GLOBAL_FEEDBACK_MAX_CHARS = 4000


@dataclass(slots=True)
class SnapshotConflictError(Exception):
    current_snapshot_hash: str


@dataclass(slots=True)
class IncompleteGradeError(Exception):
    missing_count: int


@dataclass(slots=True)
class ResolvedTeacherGradeContext:
    assignment: Assignment
    detail: TeacherCaseSubmissionDetailResponse


def get_teacher_case_grade(
    db: Session,
    context: TeacherContext,
    course_id: str,
    assignment_id: str,
    membership_id: str,
) -> TeacherGradeResponse:
    grade_context = _resolve_grade_context(
        db=db,
        context=context,
        course_id=course_id,
        assignment_id=assignment_id,
        membership_id=membership_id,
    )
    case_grade = _load_case_grade(
        db=db,
        assignment_id=assignment_id,
        membership_id=membership_id,
    )
    return _build_grade_response(
        assignment=grade_context.assignment,
        detail=grade_context.detail,
        case_grade=case_grade,
        module_entries=_load_module_entries(db, case_grade.id) if case_grade is not None else [],
        question_entries=_load_question_entries(db, case_grade.id) if case_grade is not None else [],
    )


def save_teacher_case_grade(
    db: Session,
    context: TeacherContext,
    course_id: str,
    assignment_id: str,
    membership_id: str,
    payload: TeacherGradeRequestBody,
) -> TeacherGradeResponse:
    _validate_human_only_payload(payload)
    grade_context = _resolve_grade_context(
        db=db,
        context=context,
        course_id=course_id,
        assignment_id=assignment_id,
        membership_id=membership_id,
    )
    _validate_payload_structure(payload, grade_context.detail)

    current_snapshot_hash = grade_context.detail.response_state.snapshot_hash
    if current_snapshot_hash is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="submission_not_found")
    if payload.snapshot_hash != current_snapshot_hash:
        raise SnapshotConflictError(current_snapshot_hash=current_snapshot_hash)

    missing_count = _count_ungraded_questions(payload.modules)
    if payload.intent == "publish" and missing_count > 0:
        raise IncompleteGradeError(missing_count=missing_count)

    now = utc_now()
    sanitized_global_feedback = _sanitize_optional_text(payload.feedback_global, _GLOBAL_FEEDBACK_MAX_CHARS)

    try:
        case_grade = _load_case_grade_for_update(
            db=db,
            assignment_id=assignment_id,
            membership_id=membership_id,
        )
        if case_grade is None:
            case_grade = CaseGrade(
                id=str(uuid4()),
                membership_id=membership_id,
                assignment_id=assignment_id,
                course_id=course_id,
                score=None,
                max_score=_DEFAULT_MAX_SCORE,
                status="submitted",
                graded_at=None,
                graded_by_membership_id=None,
                feedback=None,
                graded_by="human",
                ai_model_version=None,
                ai_suggested_at=None,
                human_reviewed_at=None,
                version=1,
                published_at=None,
                draft_feedback_global=None,
                last_modified_at=now,
            )
            db.add(case_grade)
            db.flush()

        if case_grade.course_id != course_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="submission_course_mismatch")

        publication_state: PublicationState
        score_normalized: float | None
        score_display: Decimal | None
        response_modules: list[TeacherGradeModuleResponse]

        if payload.intent == "save_draft":
            _replace_grade_state_entries(
                db=db,
                case_grade_id=case_grade.id,
                state="draft",
                modules=payload.modules,
                created_at=now,
            )
            case_grade.last_modified_at = now
            case_grade.graded_by = "human"
            case_grade.draft_feedback_global = sanitized_global_feedback
            if case_grade.status != "graded":
                case_grade.status = "submitted"
                case_grade.score = None
                case_grade.graded_at = None
                case_grade.graded_by_membership_id = None
                case_grade.feedback = None
                case_grade.published_at = None

            publication_state = "draft"
            response_modules = _build_response_modules_from_payload(payload.modules)
            score_normalized, score_display = _calculate_score(
                modules=response_modules,
                publish=False,
                max_score=case_grade.max_score,
            )
        else:
            response_modules = _build_response_modules_from_payload(payload.modules)
            score_normalized, score_display = _calculate_score(
                modules=response_modules,
                publish=True,
                max_score=case_grade.max_score,
            )

            _replace_grade_state_entries(
                db=db,
                case_grade_id=case_grade.id,
                state="published",
                modules=payload.modules,
                created_at=now,
            )
            _clear_grade_state_entries(db, case_grade.id, "draft")

            previous_publication_exists = bool(case_grade.published_at is not None or case_grade.status == "graded")
            case_grade.status = "graded"
            case_grade.score = score_display
            case_grade.graded_at = now
            case_grade.graded_by_membership_id = context.teacher_membership_id
            case_grade.feedback = sanitized_global_feedback
            case_grade.graded_by = "human"
            case_grade.human_reviewed_at = now
            case_grade.published_at = now
            case_grade.draft_feedback_global = None
            case_grade.last_modified_at = now
            if previous_publication_exists:
                case_grade.version += 1

            publication_state = "published"

        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="manual_grading_state_invalid",
        ) from exc

    return TeacherGradeResponse(
        payload_version=1,
        snapshot_hash=current_snapshot_hash,
        publication_state=publication_state,
        version=case_grade.version,
        score_normalized=score_normalized,
        score_display=score_display,
        max_score_display=case_grade.max_score,
        modules=response_modules,
        feedback_global=(
            sanitized_global_feedback
            if publication_state == "draft"
            else case_grade.feedback
        ),
        graded_at=case_grade.graded_at,
        published_at=case_grade.published_at,
        last_modified_at=case_grade.last_modified_at,
        graded_by="human",
    )


def _resolve_grade_context(
    *,
    db: Session,
    context: TeacherContext,
    course_id: str,
    assignment_id: str,
    membership_id: str,
) -> ResolvedTeacherGradeContext:
    assignment = _load_teacher_submission_assignment(db, context, assignment_id=assignment_id)
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")

    target_course_ids, _ = _assignment_target_course_metadata(assignment)
    if course_id not in target_course_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")

    detail = get_teacher_case_submission_detail(db, context, assignment_id, membership_id)
    if detail.case.course_id != course_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="submission_not_found")
    if detail.response_state.snapshot_hash is None or detail.response_state.status not in {"submitted", "graded"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="submission_not_found")

    return ResolvedTeacherGradeContext(assignment=assignment, detail=detail)


def _load_case_grade(
    db: Session,
    *,
    assignment_id: str,
    membership_id: str,
) -> CaseGrade | None:
    return db.scalar(
        select(CaseGrade).where(
            CaseGrade.assignment_id == assignment_id,
            CaseGrade.membership_id == membership_id,
        )
    )


def _load_case_grade_for_update(
    db: Session,
    *,
    assignment_id: str,
    membership_id: str,
) -> CaseGrade | None:
    return db.scalar(
        select(CaseGrade)
        .where(
            CaseGrade.assignment_id == assignment_id,
            CaseGrade.membership_id == membership_id,
        )
        .with_for_update()
    )


def _load_module_entries(db: Session, case_grade_id: str) -> list[CaseGradeModuleEntry]:
    return list(
        db.scalars(
            select(CaseGradeModuleEntry)
            .where(CaseGradeModuleEntry.case_grade_id == case_grade_id)
            .order_by(CaseGradeModuleEntry.module_id.asc())
        )
    )


def _load_question_entries(db: Session, case_grade_id: str) -> list[CaseGradeQuestionEntry]:
    return list(
        db.scalars(
            select(CaseGradeQuestionEntry)
            .where(CaseGradeQuestionEntry.case_grade_id == case_grade_id)
            .order_by(CaseGradeQuestionEntry.module_id.asc(), CaseGradeQuestionEntry.question_id.asc())
        )
    )


def _build_grade_response(
    *,
    assignment: Assignment,
    detail: TeacherCaseSubmissionDetailResponse,
    case_grade: CaseGrade | None,
    module_entries: list[CaseGradeModuleEntry],
    question_entries: list[CaseGradeQuestionEntry],
) -> TeacherGradeResponse:
    default_weights = _resolve_default_weights(assignment, detail)
    active_state: PublicationState = "draft"
    draft_module_entries = [entry for entry in module_entries if entry.state == "draft"]
    draft_question_entries = [entry for entry in question_entries if entry.state == "draft"]
    published_module_entries = [entry for entry in module_entries if entry.state == "published"]
    published_question_entries = [entry for entry in question_entries if entry.state == "published"]

    if draft_module_entries or draft_question_entries or (case_grade is not None and case_grade.draft_feedback_global is not None):
        active_state = "draft"
        active_module_entries = draft_module_entries
        active_question_entries = draft_question_entries
    elif case_grade is not None and case_grade.status == "graded":
        active_state = "published"
        active_module_entries = published_module_entries
        active_question_entries = published_question_entries
    else:
        active_module_entries = []
        active_question_entries = []

    response_modules = _build_response_modules_from_entries(
        detail=detail,
        module_entries=active_module_entries,
        question_entries=active_question_entries,
        default_weights=default_weights,
    )

    max_score_display = case_grade.max_score if case_grade is not None else _DEFAULT_MAX_SCORE
    score_normalized: float | None
    score_display: Decimal | None
    if active_state == "published" and not active_question_entries and case_grade is not None and case_grade.score is not None:
        score_display = case_grade.score
        score_normalized = float(
            (case_grade.score / max_score_display).quantize(_NORMALIZED_SCORE_QUANTUM, rounding=ROUND_HALF_UP)
        )
    else:
        score_normalized, score_display = _calculate_score(
            modules=response_modules,
            publish=active_state == "published",
            max_score=max_score_display,
        )

    return TeacherGradeResponse(
        payload_version=1,
        snapshot_hash=detail.response_state.snapshot_hash or "",
        publication_state=active_state,
        version=case_grade.version if case_grade is not None else 1,
        score_normalized=score_normalized,
        score_display=score_display,
        max_score_display=max_score_display,
        modules=response_modules,
        feedback_global=(
            case_grade.draft_feedback_global
            if case_grade is not None and active_state == "draft"
            else case_grade.feedback if case_grade is not None else None
        ),
        graded_at=case_grade.graded_at if case_grade is not None else None,
        published_at=case_grade.published_at if case_grade is not None else None,
        last_modified_at=case_grade.last_modified_at if case_grade is not None else detail.response_state.submitted_at or utc_now(),
        graded_by=case_grade.graded_by if case_grade is not None else "human",
    )


def _resolve_default_weights(
    assignment: Assignment,
    detail: TeacherCaseSubmissionDetailResponse,
) -> dict[str, Decimal]:
    module_ids = [module.id for module in detail.modules]
    configured_weights = assignment.weight_per_module if isinstance(assignment.weight_per_module, dict) else None
    if configured_weights is not None:
        parsed: dict[str, Decimal] = {}
        try:
            for module_id in module_ids:
                raw_value = configured_weights[module_id]
                parsed[module_id] = Decimal(str(raw_value)).quantize(_WEIGHT_QUANTUM, rounding=ROUND_HALF_UP)
        except (ArithmeticError, KeyError, TypeError, ValueError):
            parsed = {}
        if parsed:
            total = sum(parsed.values())
            if abs(total - Decimal("1.0")) <= _WEIGHT_QUANTUM:
                return parsed
    return _build_equal_weights(module_ids)


def _build_equal_weights(module_ids: Sequence[str]) -> dict[str, Decimal]:
    if not module_ids:
        return {}
    if len(module_ids) == 1:
        return {module_ids[0]: Decimal("1.000")}

    base_weight = (Decimal("1.0") / Decimal(len(module_ids))).quantize(_WEIGHT_QUANTUM, rounding=ROUND_HALF_UP)
    weights = {module_id: base_weight for module_id in module_ids}
    first_module_id = module_ids[0]
    weights[first_module_id] = Decimal("1.0") - sum(
        weight for module_id, weight in weights.items() if module_id != first_module_id
    )
    return weights


def _validate_human_only_payload(payload: TeacherGradeRequestBody) -> None:
    if payload.graded_by != "human":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="graded_by_not_supported",
        )

    for module in payload.modules:
        if module.source != "human":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="feedback_source_not_supported",
            )
        for question in module.questions:
            if question.source != "human":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="feedback_source_not_supported",
                )


def _validate_payload_structure(
    payload: TeacherGradeRequestBody,
    detail: TeacherCaseSubmissionDetailResponse,
) -> None:
    expected_modules = {module.id: [question.id for question in module.questions] for module in detail.modules}
    payload_module_ids = {module.module_id for module in payload.modules}
    if payload_module_ids != set(expected_modules):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid_question_id")

    for module in payload.modules:
        question_ids = [question.question_id for question in module.questions]
        if len(set(question_ids)) != len(question_ids):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid_question_id")
        if set(question_ids) != set(expected_modules[module.module_id]):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid_question_id")


def _count_ungraded_questions(modules: list[TeacherGradeModulePayload]) -> int:
    missing_count = 0
    for module in modules:
        for question in module.questions:
            if question.rubric_level is None:
                missing_count += 1
    return missing_count


def _replace_grade_state_entries(
    *,
    db: Session,
    case_grade_id: str,
    state: Literal["draft", "published"],
    modules: list[TeacherGradeModulePayload],
    created_at: datetime,
) -> None:
    _clear_grade_state_entries(db, case_grade_id, state)

    module_rows: list[CaseGradeModuleEntry] = []
    question_rows: list[CaseGradeQuestionEntry] = []
    for module in modules:
        module_rows.append(
            CaseGradeModuleEntry(
                id=str(uuid4()),
                case_grade_id=case_grade_id,
                module_id=module.module_id,
                weight=module.weight,
                feedback_module=_sanitize_optional_text(module.feedback_module, _MODULE_FEEDBACK_MAX_CHARS),
                state=state,
                source=module.source,
                ai_confidence=None,
                created_at=created_at,
                updated_at=created_at,
            )
        )
        for question in module.questions:
            score_normalized = (
                float(RUBRIC_TO_SCORE[question.rubric_level])
                if question.rubric_level is not None
                else None
            )
            question_rows.append(
                CaseGradeQuestionEntry(
                    id=str(uuid4()),
                    case_grade_id=case_grade_id,
                    question_id=question.question_id,
                    module_id=module.module_id,
                    rubric_level=question.rubric_level,
                    score_normalized=score_normalized,
                    feedback_question=_sanitize_optional_text(question.feedback_question, _QUESTION_FEEDBACK_MAX_CHARS),
                    state=state,
                    source=question.source,
                    ai_confidence=None,
                    created_at=created_at,
                    updated_at=created_at,
                )
            )

    db.add_all(module_rows)
    db.add_all(question_rows)
    db.flush()


def _clear_grade_state_entries(
    db: Session,
    case_grade_id: str,
    state: Literal["draft", "published"],
) -> None:
    db.execute(
        delete(CaseGradeQuestionEntry).where(
            CaseGradeQuestionEntry.case_grade_id == case_grade_id,
            CaseGradeQuestionEntry.state == state,
        )
    )
    db.execute(
        delete(CaseGradeModuleEntry).where(
            CaseGradeModuleEntry.case_grade_id == case_grade_id,
            CaseGradeModuleEntry.state == state,
        )
    )


def _build_response_modules_from_payload(
    modules: list[TeacherGradeModulePayload],
) -> list[TeacherGradeModuleResponse]:
    return [
        TeacherGradeModuleResponse(
            module_id=module.module_id,
            weight=module.weight,
            feedback_module=_sanitize_optional_text(module.feedback_module, _MODULE_FEEDBACK_MAX_CHARS),
            questions=[
                TeacherGradeQuestionResponse(
                    question_id=question.question_id,
                    rubric_level=question.rubric_level,
                    feedback_question=_sanitize_optional_text(question.feedback_question, _QUESTION_FEEDBACK_MAX_CHARS),
                )
                for question in module.questions
            ],
        )
        for module in modules
    ]


def _build_response_modules_from_entries(
    *,
    detail: TeacherCaseSubmissionDetailResponse,
    module_entries: list[CaseGradeModuleEntry],
    question_entries: list[CaseGradeQuestionEntry],
    default_weights: dict[str, Decimal],
) -> list[TeacherGradeModuleResponse]:
    module_entry_map = {entry.module_id: entry for entry in module_entries}
    question_entry_map = {entry.question_id: entry for entry in question_entries}

    response_modules: list[TeacherGradeModuleResponse] = []
    for module in detail.modules:
        module_entry = module_entry_map.get(module.id)
        response_modules.append(
            TeacherGradeModuleResponse(
                module_id=module.id,
                weight=module_entry.weight if module_entry is not None else default_weights[module.id],
                feedback_module=module_entry.feedback_module if module_entry is not None else None,
                questions=[
                    TeacherGradeQuestionResponse(
                        question_id=question.id,
                        rubric_level=question_entry_map[question.id].rubric_level if question.id in question_entry_map else None,
                        feedback_question=question_entry_map[question.id].feedback_question if question.id in question_entry_map else None,
                    )
                    for question in module.questions
                ],
            )
        )
    return response_modules


def _calculate_score(
    *,
    modules: list[TeacherGradeModuleResponse],
    publish: bool,
    max_score: Decimal,
) -> tuple[float | None, Decimal | None]:
    if not modules:
        return None, None

    weighted_total = Decimal("0")
    included_weight_total = Decimal("0")

    for module in modules:
        question_scores = [
            Decimal(str(RUBRIC_TO_SCORE[question.rubric_level]))
            for question in module.questions
            if question.rubric_level is not None
        ]
        if publish:
            denominator = len(module.questions)
            if denominator == 0:
                continue
            module_average = sum(question_scores, Decimal("0")) / Decimal(denominator)
            weighted_total += module_average * module.weight
            included_weight_total += module.weight
            continue

        if not question_scores:
            continue
        module_average = sum(question_scores, Decimal("0")) / Decimal(len(question_scores))
        weighted_total += module_average * module.weight
        included_weight_total += module.weight

    if publish:
        normalized_score = weighted_total
    else:
        if included_weight_total == 0:
            return None, None
        normalized_score = weighted_total / included_weight_total

    normalized_score = normalized_score.quantize(_NORMALIZED_SCORE_QUANTUM, rounding=ROUND_HALF_UP)
    score_display = (normalized_score * max_score).quantize(_DISPLAY_SCORE_QUANTUM, rounding=ROUND_HALF_UP)
    return float(normalized_score), score_display


def _sanitize_optional_text(value: str | None, max_chars: int) -> str | None:
    sanitized = sanitize_untrusted_text(value, max_chars)
    return sanitized or None