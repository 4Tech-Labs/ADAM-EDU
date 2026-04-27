from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json
import logging
from typing import Any, Literal, Mapping, Sequence
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session, joinedload, load_only

from shared.auth import CurrentActor, ensure_legacy_teacher_bridge, get_supabase_admin_auth_client
from shared.case_sanitization import (
    build_teacher_case_review_payload,
    sanitize_canonical_output_for_student,
)
from shared.course_access_schema import TeacherCourseAccessLinkResponse
from shared.identity_activation import upsert_legacy_user
from shared.models import (
    Assignment,
    AssignmentCourse,
    AuthoringJob,
    CaseGrade,
    Course,
    CourseAccessLink,
    CourseMembership,
    Membership,
    Profile,
    StudentCaseResponse,
    StudentCaseResponseSubmission,
    Syllabus,
    User,
)
from shared.syllabus_schema import (
    TeacherCourseConfigurationResponse,
    TeacherCourseDetailResponse,
    TeacherCourseInstitutionalResponse,
    TeacherSyllabusResponse,
    TeacherSyllabusRevisionMetadataResponse,
)
from shared.teacher_context import TeacherContext
from shared.teacher_gradebook_schema import (
    TeacherCaseSubmissionDetailCase,
    TeacherCaseSubmissionDetailGradeSummary,
    TeacherCaseSubmissionDetailModule,
    TeacherCaseSubmissionDetailQuestion,
    TeacherCaseSubmissionDetailResponse,
    TeacherCaseSubmissionDetailResponseState,
    TeacherCaseSubmissionDetailStudent,
    TeacherCaseSubmissionRow,
    TeacherCaseSubmissionsResponse,
    TeacherCourseGradebookCase,
    TeacherCourseGradebookCell,
    TeacherCourseGradebookCourse,
    TeacherCourseGradebookResponse,
    TeacherCourseGradebookStatus,
    TeacherCourseGradebookStudent,
)

_BOGOTA_TZ = ZoneInfo("America/Bogota")
_DEFAULT_CASE_MAX_SCORE = 5.0
_DEFAULT_CASE_MAX_SCORE_DECIMAL = Decimal("5.00")
_logger = logging.getLogger(__name__)
_DETAIL_PAYLOAD_MAX_BYTES = 1_500_000
_DETAIL_EXPECTED_SOLUTION_TRUNCATION_CHARS = 8_000
_MODULE_TITLES: Mapping[str, str] = {
    "M1": "Módulo 1 · Comprensión del caso",
    "M2": "Módulo 2 · Análisis de datos",
    "M3": "Módulo 3 · Diagnóstico",
    "M4": "Módulo 4 · Recomendación",
    "M5": "Módulo 5 · Reflexión",
}


class TeacherCourseItemResponse(BaseModel):
    id: str
    title: str
    code: str
    semester: str
    academic_level: str
    status: Literal["active", "inactive"]
    students_count: int
    active_cases_count: int


class TeacherCoursesResponse(BaseModel):
    courses: list[TeacherCourseItemResponse]
    total: int


@dataclass(slots=True)
class TeacherCaseItem:
    id: str
    title: str
    available_from: datetime | None
    deadline: datetime | None
    status: str
    course_codes: list[str]


@dataclass(slots=True)
class TeacherOwnedCourseSyllabus:
    course: Course
    syllabus: Syllabus


def _decimal_to_float(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _display_name(*, profile_full_name: str | None, email: str) -> str:
    candidate = profile_full_name.strip() if profile_full_name is not None else ""
    return candidate or email


def _stringify_review_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    return str(value)


def _question_context(question: dict[str, Any]) -> str | None:
    context_parts: list[str] = []

    title = question.get("titulo")
    if isinstance(title, str) and title.strip():
        context_parts.append(title.strip())

    bloom_level = question.get("bloom_level")
    if isinstance(bloom_level, str) and bloom_level.strip():
        context_parts.append(f"Bloom: {bloom_level.strip()}")

    exhibit_ref = question.get("exhibit_ref")
    if isinstance(exhibit_ref, str) and exhibit_ref.strip():
        context_parts.append(f"Exhibito: {exhibit_ref.strip()}")

    chart_ref = question.get("chart_ref")
    if isinstance(chart_ref, str) and chart_ref.strip():
        context_parts.append(f"Grafico: {chart_ref.strip()}")

    task_type = question.get("task_type")
    if isinstance(task_type, str) and task_type.strip():
        context_parts.append(f"Tipo: {task_type.strip()}")

    modules_integrated = question.get("modules_integrated")
    if isinstance(modules_integrated, list):
        normalized_modules = [str(module).strip() for module in modules_integrated if str(module).strip()]
        if normalized_modules:
            context_parts.append(f"Integra: {', '.join(normalized_modules)}")

    if not context_parts:
        return None
    return "\n".join(context_parts)


def _detail_question_id(module_id: str, question: dict[str, Any], order: int) -> str:
    numero = question.get("numero")
    if numero is not None:
        normalized_numero = str(numero).strip()
        if normalized_numero:
            return f"{module_id}-Q{normalized_numero}"
    return f"{module_id}.{order}"


def _lookup_student_answer(
    answers: dict[str, str],
    *,
    module_id: str,
    question: dict[str, Any],
    order: int,
) -> str | None:
    question_id = _detail_question_id(module_id, question, order)
    answer = answers.get(question_id)
    if answer is not None:
        return answer

    numero = question.get("numero")
    if numero is not None:
        legacy_answer = answers.get(f"q{str(numero).strip()}")
        if legacy_answer is not None:
            return legacy_answer

    return None


def _m5_solution_lookup(content: dict[str, Any]) -> dict[str, str]:
    raw_solutions = content.get("m5QuestionsSolutions")
    if not isinstance(raw_solutions, list):
        return {}

    solutions: dict[str, str] = {}
    for item in raw_solutions:
        if not isinstance(item, dict):
            continue
        numero = item.get("numero")
        if numero is None:
            continue
        normalized_numero = str(numero).strip()
        if not normalized_numero:
            continue
        solutions[normalized_numero] = _stringify_review_value(item.get("solucion_esperada"))
    return solutions


def _truncate_detail_modules_if_needed(
    modules: list[TeacherCaseSubmissionDetailModule],
    *,
    assignment_id: str,
    membership_id: str,
) -> list[TeacherCaseSubmissionDetailModule]:
    serialized_modules = json.dumps(
        [module.model_dump(mode="json") for module in modules],
        ensure_ascii=False,
    )
    if len(serialized_modules) <= _DETAIL_PAYLOAD_MAX_BYTES:
        return modules

    for module in modules:
        for question in module.questions:
            if len(question.expected_solution) > _DETAIL_EXPECTED_SOLUTION_TRUNCATION_CHARS:
                question.expected_solution = (
                    question.expected_solution[:_DETAIL_EXPECTED_SOLUTION_TRUNCATION_CHARS]
                    + "... [truncado por tamano]"
                )

    _logger.warning(
        "teacher_case_submission_detail_payload_truncated",
        extra={
            "assignment_id": assignment_id,
            "membership_id": membership_id,
            "payload_size": len(serialized_modules),
        },
    )
    return modules


def _build_submission_detail_modules(
    *,
    canonical_output: dict[str, Any],
    answers: dict[str, str],
    is_answer_from_draft: bool,
    assignment_id: str,
    membership_id: str,
) -> list[TeacherCaseSubmissionDetailModule]:
    from shared.student_reads import QUESTION_FIELD_TO_MODULE

    teacher_payload = build_teacher_case_review_payload(canonical_output)
    content = teacher_payload.get("content")
    if not isinstance(content, dict):
        return []

    m5_solution_lookup = _m5_solution_lookup(content)
    modules: list[TeacherCaseSubmissionDetailModule] = []
    for field_name, module_id in QUESTION_FIELD_TO_MODULE.items():
        raw_questions = content.get(field_name)
        if not isinstance(raw_questions, list) or not raw_questions:
            continue

        questions: list[TeacherCaseSubmissionDetailQuestion] = []
        for order, raw_question in enumerate(raw_questions, start=1):
            if not isinstance(raw_question, dict):
                continue

            question_id = _detail_question_id(module_id, raw_question, order)
            student_answer = _lookup_student_answer(
                answers,
                module_id=module_id,
                question=raw_question,
                order=order,
            )
            expected_solution = _stringify_review_value(raw_question.get("solucion_esperada"))
            if not expected_solution and module_id == "M5":
                numero = raw_question.get("numero")
                if numero is not None:
                    expected_solution = m5_solution_lookup.get(str(numero).strip(), "")

            questions.append(
                TeacherCaseSubmissionDetailQuestion(
                    id=question_id,
                    order=order,
                    statement=_stringify_review_value(raw_question.get("enunciado")),
                    context=_question_context(raw_question),
                    expected_solution=expected_solution,
                    student_answer=student_answer,
                    student_answer_chars=len(student_answer) if student_answer is not None else 0,
                    is_answer_from_draft=is_answer_from_draft,
                )
            )

        if questions:
            modules.append(
                TeacherCaseSubmissionDetailModule(
                    id=module_id,
                    title=_MODULE_TITLES[module_id],
                    questions=questions,
                )
            )

    return _truncate_detail_modules_if_needed(
        modules,
        assignment_id=assignment_id,
        membership_id=membership_id,
    )


def _load_teacher_submission_assignment(
    db: Session,
    context: TeacherContext,
    *,
    assignment_id: str,
) -> Assignment | None:
    assignment_target_courses = _build_assignment_target_courses_subquery()
    return (
        db.execute(
            select(Assignment)
            .options(
                load_only(
                    Assignment.id,
                    Assignment.course_id,
                    Assignment.title,
                    Assignment.status,
                    Assignment.available_from,
                    Assignment.deadline,
                    Assignment.canonical_output,
                ),
                joinedload(Assignment.course).load_only(
                    Course.id,
                    Course.code,
                    Course.title,
                    Course.university_id,
                    Course.teacher_membership_id,
                ),
                joinedload(Assignment.assignment_courses)
                .joinedload(AssignmentCourse.course)
                .load_only(
                    Course.id,
                    Course.code,
                    Course.title,
                    Course.university_id,
                    Course.teacher_membership_id,
                ),
            )
            .where(
                Assignment.id == assignment_id,
                Assignment.status == "published",
                exists(
                    select(1)
                    .select_from(assignment_target_courses)
                    .join(
                        Course,
                        and_(
                            assignment_target_courses.c.course_id == Course.id,
                            Course.university_id == context.university_id,
                            Course.teacher_membership_id == context.teacher_membership_id,
                        ),
                    )
                    .where(assignment_target_courses.c.assignment_id == Assignment.id)
                ),
            )
        )
        .unique()
        .scalar_one_or_none()
    )


def get_teacher_case_submission_detail(
    db: Session,
    context: TeacherContext,
    assignment_id: str,
    membership_id: str,
) -> TeacherCaseSubmissionDetailResponse:
    assignment = _load_teacher_submission_assignment(
        db,
        context,
        assignment_id=assignment_id,
    )
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")

    target_course_ids, _course_codes = _assignment_target_course_metadata(assignment)
    if not target_course_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")

    _ensure_supported_gradebook_topology(
        db,
        context,
        assignments=[assignment],
        student_membership_ids=[membership_id],
    )

    detail_row = (
        db.execute(
            select(
                Membership.id.label("membership_id"),
                Membership.user_id.label("user_id"),
                CourseMembership.created_at.label("enrolled_at"),
                Profile.full_name.label("profile_full_name"),
                User.email.label("email"),
                Course.id.label("course_id"),
                Course.code.label("course_code"),
                Course.title.label("course_name"),
                StudentCaseResponse.id.label("response_id"),
                StudentCaseResponse.status.label("student_case_status"),
                StudentCaseResponse.answers.label("student_answers"),
                StudentCaseResponse.first_opened_at.label("first_opened_at"),
                StudentCaseResponse.last_autosaved_at.label("last_autosaved_at"),
                StudentCaseResponse.submitted_at.label("submitted_at"),
                CaseGrade.status.label("case_grade_status"),
                CaseGrade.score.label("score"),
                CaseGrade.max_score.label("max_score"),
                CaseGrade.graded_at.label("graded_at"),
            )
            .select_from(CourseMembership)
            .join(
                Membership,
                and_(
                    CourseMembership.membership_id == Membership.id,
                    Membership.university_id == context.university_id,
                    Membership.role == "student",
                    Membership.status == "active",
                ),
            )
            .join(
                Course,
                and_(
                    CourseMembership.course_id == Course.id,
                    Course.university_id == context.university_id,
                    Course.teacher_membership_id == context.teacher_membership_id,
                ),
            )
            .outerjoin(User, User.id == Membership.user_id)
            .outerjoin(Profile, Profile.id == Membership.user_id)
            .outerjoin(
                StudentCaseResponse,
                and_(
                    StudentCaseResponse.membership_id == Membership.id,
                    StudentCaseResponse.assignment_id == assignment.id,
                ),
            )
            .outerjoin(
                CaseGrade,
                and_(
                    CaseGrade.membership_id == Membership.id,
                    CaseGrade.assignment_id == assignment.id,
                    CaseGrade.course_id == Course.id,
                ),
            )
            .where(
                Membership.id == membership_id,
                CourseMembership.course_id.in_(target_course_ids),
            )
        )
        .mappings()
        .first()
    )
    if detail_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="submission_not_found")

    repaired_row = _repair_gradebook_student_rows(db, context, student_rows=[detail_row])[0]

    response_id = repaired_row["response_id"]
    latest_submission = None
    if response_id is not None:
        latest_submission = db.execute(
            select(StudentCaseResponseSubmission)
            .where(StudentCaseResponseSubmission.response_id == response_id)
            .order_by(
                StudentCaseResponseSubmission.submitted_at.desc(),
                StudentCaseResponseSubmission.id.desc(),
            )
            .limit(1)
        ).scalar_one_or_none()

    canonical_output = assignment.canonical_output
    try:
        if not isinstance(canonical_output, dict):
            raise TypeError("assignment canonical_output must be a dict")
        student_safe_payload = sanitize_canonical_output_for_student(canonical_output)
        teacher_payload = build_teacher_case_review_payload(canonical_output)
    except Exception:
        _logger.exception(
            "teacher_case_submission_detail_invalid_canonical_output",
            extra={
                "assignment_id": assignment.id,
                "membership_id": membership_id,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="case_canonical_output_invalid",
        )

    if latest_submission is not None:
        from shared.student_reads import _canonical_output_hash

        current_hash = _canonical_output_hash(student_safe_payload)
        if latest_submission.canonical_output_hash != current_hash:
            _logger.warning(
                "teacher_case_submission_detail_hash_drift",
                extra={
                    "assignment_id": assignment.id,
                    "membership_id": membership_id,
                    "snapshot_hash": latest_submission.canonical_output_hash,
                    "current_hash": current_hash,
                },
            )

    derived_status: TeacherCourseGradebookStatus = _derive_grade_cell_status(
        repaired_row["student_case_status"],
        repaired_row["case_grade_status"],
    )

    response_answers = (
        dict(repaired_row["student_answers"])
        if isinstance(repaired_row["student_answers"], dict)
        else {}
    )
    if latest_submission is not None:
        answer_source = dict(latest_submission.answers_snapshot or {})
        is_answer_from_draft = False
    elif response_id is not None:
        answer_source = response_answers
        is_answer_from_draft = True
        if derived_status in {"submitted", "graded"}:
            _logger.warning(
                "teacher_case_submission_detail_missing_snapshot",
                extra={
                    "assignment_id": assignment.id,
                    "membership_id": membership_id,
                    "response_id": response_id,
                    "derived_status": derived_status,
                },
            )
    else:
        answer_source = {}
        is_answer_from_draft = False

    modules = _build_submission_detail_modules(
        canonical_output=canonical_output,
        answers=answer_source,
        is_answer_from_draft=is_answer_from_draft,
        assignment_id=assignment.id,
        membership_id=membership_id,
    )

    available_from, deadline = resolve_assignment_schedule_values(assignment)
    teacher_content = teacher_payload.get("content") if isinstance(teacher_payload, dict) else None
    teaching_note = None
    if isinstance(teacher_content, dict) and teacher_content.get("teachingNote") is not None:
        teaching_note = _stringify_review_value(teacher_content.get("teachingNote")) or None

    return TeacherCaseSubmissionDetailResponse(
        case=TeacherCaseSubmissionDetailCase(
            id=assignment.id,
            title=_resolve_assignment_title(assignment),
            deadline=deadline,
            available_from=available_from,
            course_id=repaired_row["course_id"],
            course_code=repaired_row["course_code"],
            course_name=repaired_row["course_name"],
            teaching_note=teaching_note,
        ),
        student=TeacherCaseSubmissionDetailStudent(
            membership_id=repaired_row["membership_id"],
            full_name=_display_name(
                profile_full_name=repaired_row["profile_full_name"],
                email=repaired_row["email"],
            ),
            email=repaired_row["email"],
            enrolled_at=repaired_row["enrolled_at"],
        ),
        response_state=TeacherCaseSubmissionDetailResponseState(
            status=derived_status,
            first_opened_at=repaired_row["first_opened_at"],
            last_autosaved_at=repaired_row["last_autosaved_at"],
            submitted_at=(
                latest_submission.submitted_at
                if latest_submission is not None
                else repaired_row["submitted_at"]
            ),
            snapshot_id=latest_submission.id if latest_submission is not None else None,
            snapshot_hash=(
                latest_submission.canonical_output_hash
                if latest_submission is not None
                else None
            ),
        ),
        grade_summary=TeacherCaseSubmissionDetailGradeSummary(
            status=repaired_row["case_grade_status"],
            score=repaired_row["score"],
            max_score=repaired_row["max_score"] or _DEFAULT_CASE_MAX_SCORE_DECIMAL,
            graded_at=repaired_row["graded_at"],
        ),
        modules=modules,
    )


def _derive_grade_cell_status(
    student_case_status: str | None,
    case_grade_status: str | None,
) -> Literal["not_started", "in_progress", "submitted", "graded"]:
    if case_grade_status == "graded":
        return "graded"
    if case_grade_status == "submitted" or student_case_status == "submitted":
        return "submitted"
    if case_grade_status == "in_progress" or student_case_status == "draft":
        return "in_progress"
    return "not_started"


def _map_student_case_status(status_value: str) -> Literal["in_progress", "submitted"]:
    if _derive_grade_cell_status(status_value, None) == "submitted":
        return "submitted"
    return "in_progress"


def _resolve_assignment_title(assignment: Assignment) -> str:
    canonical_output = assignment.canonical_output if isinstance(assignment.canonical_output, dict) else {}
    candidate = canonical_output.get("title")
    if isinstance(candidate, str) and candidate.strip():
        return candidate
    return assignment.title


def _ensure_supported_gradebook_topology(
    db: Session,
    context: TeacherContext,
    *,
    assignments: Sequence[Assignment],
    student_membership_ids: list[str],
) -> None:
    multi_course_targets = {
        assignment.id: {assignment_course.course_id for assignment_course in assignment.assignment_courses}
        for assignment in assignments
        if len({assignment_course.course_id for assignment_course in assignment.assignment_courses}) > 1
    }
    if not multi_course_targets or not student_membership_ids:
        return

    relevant_course_ids = sorted({
        target_course_id
        for target_course_ids in multi_course_targets.values()
        for target_course_id in target_course_ids
    })
    enrollment_rows = (
        db.execute(
            select(
                CourseMembership.membership_id.label("membership_id"),
                CourseMembership.course_id.label("course_id"),
            )
            .select_from(CourseMembership)
            .join(
                Membership,
                and_(
                    CourseMembership.membership_id == Membership.id,
                    Membership.university_id == context.university_id,
                    Membership.role == "student",
                    Membership.status == "active",
                ),
            )
            .where(
                CourseMembership.membership_id.in_(student_membership_ids),
                CourseMembership.course_id.in_(relevant_course_ids),
            )
        )
        .mappings()
        .all()
    )

    memberships_to_courses: dict[str, set[str]] = {}
    for row in enrollment_rows:
        memberships_to_courses.setdefault(row["membership_id"], set()).add(row["course_id"])

    for target_course_ids in multi_course_targets.values():
        for enrolled_course_ids in memberships_to_courses.values():
            if len(enrolled_course_ids & target_course_ids) > 1:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="course_gradebook_cross_enrollment_unsupported",
                )


def _build_student_counts_subquery(context: TeacherContext):
    return (
        select(
            CourseMembership.course_id.label("course_id"),
            func.count().label("students_count"),
        )
        .select_from(CourseMembership)
        .join(
            Membership,
            and_(
                CourseMembership.membership_id == Membership.id,
                Membership.university_id == context.university_id,
                Membership.role == "student",
                Membership.status == "active",
            ),
        )
        .group_by(CourseMembership.course_id)
        .subquery()
    )


def _resolve_reference_now(now: datetime | None = None) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


def _normalize_grade_score(*, score: float, max_score: float) -> float:
    if max_score <= 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="course_gradebook_invalid_max_score",
        )
    return round((score / max_score) * _DEFAULT_CASE_MAX_SCORE, 2)


def _missing_gradebook_email(*, user_id: str | None) -> str:
    identifier = (user_id or "desconocido")[:8]
    return f"Correo no disponible ({identifier})"


def _repair_gradebook_student_rows(
    db: Session,
    context: TeacherContext,
    *,
    student_rows: Sequence[RowMapping],
) -> list[dict[str, Any]]:
    resolved_rows = [dict(row) for row in student_rows]
    missing_rows = [row for row in resolved_rows if not row["email"]]
    if not missing_rows:
        return sorted(
            resolved_rows,
            key=lambda row: (
                _display_name(profile_full_name=row["profile_full_name"], email=row["email"]).lower(),
                row["membership_id"],
            ),
        )

    admin_client = None
    try:
        admin_client = get_supabase_admin_auth_client()
    except Exception:
        _logger.warning(
            "gradebook_identity_repair_admin_client_unavailable",
            extra={"university_id": context.university_id},
            exc_info=True,
        )

    persisted_repair = False
    for row in missing_rows:
        fallback_email = _missing_gradebook_email(user_id=row["user_id"])
        if admin_client is None:
            row["email"] = fallback_email
            continue

        try:
            auth_user = admin_client.get_user_by_id(row["user_id"])
            if auth_user is None or not auth_user.email:
                row["email"] = fallback_email
                _logger.warning(
                    "gradebook_identity_repair_missing_auth_user",
                    extra={
                        "university_id": context.university_id,
                        "course_membership_id": row["membership_id"],
                        "auth_user_id": row["user_id"],
                    },
                )
                continue

            row["email"] = auth_user.email
            upsert_legacy_user(
                db,
                auth_user_id=row["user_id"],
                university_id=context.university_id,
                email=auth_user.email,
                role="student",
            )
            persisted_repair = True
        except Exception:
            db.rollback()
            persisted_repair = False
            row["email"] = fallback_email
            _logger.warning(
                "gradebook_identity_repair_failed",
                extra={
                    "university_id": context.university_id,
                    "course_membership_id": row["membership_id"],
                    "auth_user_id": row["user_id"],
                },
                exc_info=True,
            )

    if persisted_repair:
        try:
            db.commit()
        except Exception:
            db.rollback()
            _logger.warning(
                "gradebook_identity_repair_commit_failed",
                extra={"university_id": context.university_id},
                exc_info=True,
            )

    return sorted(
        resolved_rows,
        key=lambda row: (
            _display_name(profile_full_name=row["profile_full_name"], email=row["email"]).lower(),
            row["membership_id"],
        ),
    )


def _active_assignment_predicate(*, now: datetime):
    return and_(
        Assignment.status == "published",
        or_(Assignment.deadline.is_(None), Assignment.deadline >= now),
    )


def _build_active_case_counts_subquery(
    context: TeacherContext,
    *,
    now: datetime,
):
    assignment_target_courses = _build_assignment_target_courses_subquery()
    return (
        select(
            assignment_target_courses.c.course_id.label("course_id"),
            func.count(func.distinct(Assignment.id)).label("active_cases_count"),
        )
        .select_from(assignment_target_courses)
        .join(Assignment, assignment_target_courses.c.assignment_id == Assignment.id)
        .join(
            Course,
            and_(
                assignment_target_courses.c.course_id == Course.id,
                Course.university_id == context.university_id,
                Course.teacher_membership_id == context.teacher_membership_id,
            ),
        )
        .where(
            _active_assignment_predicate(now=now),
        )
        .group_by(assignment_target_courses.c.course_id)
        .subquery()
    )


def _build_assignment_target_courses_subquery():
    persisted_targets = select(
        AssignmentCourse.assignment_id.label("assignment_id"),
        AssignmentCourse.course_id.label("course_id"),
    )
    legacy_targets = (
        select(
            Assignment.id.label("assignment_id"),
            Assignment.course_id.label("course_id"),
        )
        .where(
            Assignment.course_id.is_not(None),
            ~exists(select(1).where(AssignmentCourse.assignment_id == Assignment.id)),
        )
    )
    return persisted_targets.union_all(legacy_targets).subquery()


def _assignment_course_codes(assignment: Assignment) -> list[str]:
    if assignment.assignment_courses:
        course_codes = sorted(
            {
                link.course.code
                for link in assignment.assignment_courses
                if link.course is not None and link.course.code
            }
        )
        if course_codes:
            return course_codes

    if assignment.course is not None and assignment.course.code:
        return [assignment.course.code]

    return []


def _assignment_target_course_metadata(assignment: Assignment) -> tuple[list[str], list[str]]:
    if assignment.assignment_courses:
        course_pairs = sorted(
            {
                (link.course_id, link.course.code if link.course is not None else None)
                for link in assignment.assignment_courses
                if link.course_id
            },
            key=lambda pair: ((pair[1] or ""), pair[0]),
        )
        course_ids = [course_id for course_id, _code in course_pairs]
        course_codes = [code for _course_id, code in course_pairs if code]
        if course_ids:
            return course_ids, course_codes

    course_ids = [assignment.course_id] if assignment.course_id else []
    course_codes = [assignment.course.code] if assignment.course is not None and assignment.course.code else []
    return course_ids, course_codes


def _serialize_teacher_course_configuration(
    *,
    access_link_status: str | None,
    access_link_id: str | None,
    access_link_created_at: datetime | None,
) -> TeacherCourseConfigurationResponse:
    return TeacherCourseConfigurationResponse(
        access_link_status="active" if access_link_status == "active" else "missing",
        access_link_id=access_link_id,
        access_link_created_at=access_link_created_at,
    )


def _serialize_syllabus_response(syllabus: Syllabus | None) -> TeacherSyllabusResponse | None:
    if syllabus is None:
        return None

    return TeacherSyllabusResponse.model_validate(
        {
            "department": syllabus.department,
            "knowledge_area": syllabus.knowledge_area,
            "nbc": syllabus.nbc,
            "version_label": syllabus.version_label,
            "academic_load": syllabus.academic_load,
            "course_description": syllabus.course_description,
            "general_objective": syllabus.general_objective,
            "specific_objectives": syllabus.specific_objectives,
            "modules": syllabus.modules,
            "evaluation_strategy": syllabus.evaluation_strategy,
            "didactic_strategy": syllabus.didactic_strategy,
            "integrative_project": syllabus.integrative_project,
            "bibliography": syllabus.bibliography,
            "teacher_notes": syllabus.teacher_notes,
            "ai_grounding_context": syllabus.ai_grounding_context,
        }
    )


def list_teacher_courses(
    db: Session,
    context: TeacherContext,
    *,
    now: datetime | None = None,
) -> TeacherCoursesResponse:
    """Return the teacher-scoped course directory for the authenticated membership."""
    reference_now = _resolve_reference_now(now)
    student_counts = _build_student_counts_subquery(context)
    active_case_counts = _build_active_case_counts_subquery(context, now=reference_now)

    rows = (
        db.execute(
            select(
                Course.id.label("id"),
                Course.title.label("title"),
                Course.code.label("code"),
                Course.semester.label("semester"),
                Course.academic_level.label("academic_level"),
                Course.status.label("status"),
                func.coalesce(student_counts.c.students_count, 0).label("students_count"),
                func.coalesce(active_case_counts.c.active_cases_count, 0).label("active_cases_count"),
            )
            .select_from(Course)
            .outerjoin(student_counts, student_counts.c.course_id == Course.id)
            .outerjoin(active_case_counts, active_case_counts.c.course_id == Course.id)
            .where(
                Course.university_id == context.university_id,
                Course.teacher_membership_id == context.teacher_membership_id,
            )
            .order_by(Course.title.asc(), Course.id.asc())
        )
        .mappings()
        .all()
    )

    courses = [
        TeacherCourseItemResponse(
            id=row["id"],
            title=row["title"],
            code=row["code"],
            semester=row["semester"],
            academic_level=row["academic_level"],
            status=row["status"],
            students_count=int(row["students_count"]),
            active_cases_count=int(row["active_cases_count"]),
        )
        for row in rows
    ]

    return TeacherCoursesResponse(courses=courses, total=len(courses))


def get_teacher_course_detail(
    db: Session,
    context: TeacherContext,
    course_id: str,
    *,
    now: datetime | None = None,
) -> TeacherCourseDetailResponse:
    """Return the teacher-owned composed course detail payload."""
    reference_now = _resolve_reference_now(now)
    student_counts = _build_student_counts_subquery(context)
    active_case_counts = _build_active_case_counts_subquery(context, now=reference_now)

    row = (
        db.execute(
            select(
                Course.id.label("id"),
                Course.title.label("title"),
                Course.code.label("code"),
                Course.semester.label("semester"),
                Course.academic_level.label("academic_level"),
                Course.status.label("status"),
                Course.max_students.label("max_students"),
                func.coalesce(student_counts.c.students_count, 0).label("students_count"),
                func.coalesce(active_case_counts.c.active_cases_count, 0).label("active_cases_count"),
                CourseAccessLink.id.label("access_link_id"),
                CourseAccessLink.status.label("access_link_status"),
                CourseAccessLink.created_at.label("access_link_created_at"),
            )
            .select_from(Course)
            .outerjoin(student_counts, student_counts.c.course_id == Course.id)
            .outerjoin(active_case_counts, active_case_counts.c.course_id == Course.id)
            .outerjoin(
                CourseAccessLink,
                and_(
                    CourseAccessLink.course_id == Course.id,
                    CourseAccessLink.status == "active",
                ),
            )
            .where(
                Course.id == course_id,
                Course.university_id == context.university_id,
                Course.teacher_membership_id == context.teacher_membership_id,
            )
            .limit(1)
        )
        .mappings()
        .first()
    )

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="course_not_found")

    syllabus = db.scalar(select(Syllabus).where(Syllabus.course_id == course_id))
    current_revision = syllabus.revision if syllabus is not None else 0
    saved_at = syllabus.saved_at if syllabus is not None else None
    saved_by_membership_id = syllabus.saved_by_membership_id if syllabus is not None else None

    return TeacherCourseDetailResponse(
        course=TeacherCourseInstitutionalResponse(
            id=row["id"],
            title=row["title"],
            code=row["code"],
            semester=row["semester"],
            academic_level=row["academic_level"],
            status=row["status"],
            max_students=int(row["max_students"]),
            students_count=int(row["students_count"]),
            active_cases_count=int(row["active_cases_count"]),
        ),
        syllabus=_serialize_syllabus_response(syllabus),
        revision_metadata=TeacherSyllabusRevisionMetadataResponse(
            current_revision=current_revision,
            saved_at=saved_at,
            saved_by_membership_id=saved_by_membership_id,
        ),
        configuration=_serialize_teacher_course_configuration(
            access_link_status=row["access_link_status"],
            access_link_id=row["access_link_id"],
            access_link_created_at=row["access_link_created_at"],
        ),
    )


def get_teacher_course_gradebook(
    db: Session,
    context: TeacherContext,
    course_id: str,
) -> TeacherCourseGradebookResponse:
    student_counts = _build_student_counts_subquery(context)
    course_row = (
        db.execute(
            select(
                Course.id.label("id"),
                Course.title.label("title"),
                Course.code.label("code"),
                func.coalesce(student_counts.c.students_count, 0).label("students_count"),
            )
            .select_from(Course)
            .outerjoin(student_counts, student_counts.c.course_id == Course.id)
            .where(
                Course.id == course_id,
                Course.university_id == context.university_id,
                Course.teacher_membership_id == context.teacher_membership_id,
            )
            .limit(1)
        )
        .mappings()
        .first()
    )
    if course_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="course_not_found")

    student_row_records = (
        db.execute(
            select(
                CourseMembership.membership_id.label("membership_id"),
                Membership.user_id.label("user_id"),
                CourseMembership.created_at.label("enrolled_at"),
                Profile.full_name.label("profile_full_name"),
                User.email.label("email"),
            )
            .select_from(CourseMembership)
            .join(
                Membership,
                and_(
                    CourseMembership.membership_id == Membership.id,
                    Membership.university_id == context.university_id,
                    Membership.role == "student",
                    Membership.status == "active",
                ),
            )
            .outerjoin(User, User.id == Membership.user_id)
            .outerjoin(Profile, Profile.id == Membership.user_id)
            .where(CourseMembership.course_id == course_id)
        )
        .mappings()
        .all()
    )
    student_rows = _repair_gradebook_student_rows(db, context, student_rows=student_row_records)

    assignment_target_courses = _build_assignment_target_courses_subquery()
    assignments = (
        db.execute(
            select(Assignment)
            .options(
                load_only(
                    Assignment.id,
                    Assignment.title,
                    Assignment.canonical_output,
                    Assignment.status,
                    Assignment.available_from,
                    Assignment.deadline,
                    Assignment.created_at,
                ),
                joinedload(Assignment.assignment_courses).load_only(AssignmentCourse.course_id),
            )
            .join(
                assignment_target_courses,
                assignment_target_courses.c.assignment_id == Assignment.id,
            )
            .where(
                assignment_target_courses.c.course_id == course_id,
                Assignment.status == "published",
            )
            .order_by(
                Assignment.available_from.asc().nullslast(),
                Assignment.created_at.asc(),
                Assignment.id.asc(),
            )
        )
        .unique()
        .scalars()
        .all()
    )

    student_membership_ids = [row["membership_id"] for row in student_rows]
    assignment_ids = [assignment.id for assignment in assignments]

    _ensure_supported_gradebook_topology(
        db,
        context,
        assignments=assignments,
        student_membership_ids=student_membership_ids,
    )

    progress_by_key: dict[tuple[str, str], str] = {}
    if student_membership_ids and assignment_ids:
        progress_rows = (
            db.execute(
                select(
                    StudentCaseResponse.membership_id.label("membership_id"),
                    StudentCaseResponse.assignment_id.label("assignment_id"),
                    StudentCaseResponse.status.label("status"),
                )
                .where(
                    StudentCaseResponse.membership_id.in_(student_membership_ids),
                    StudentCaseResponse.assignment_id.in_(assignment_ids),
                )
            )
            .mappings()
            .all()
        )
        progress_by_key = {
            (row["membership_id"], row["assignment_id"]): row["status"]
            for row in progress_rows
        }

    grade_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    max_score_by_assignment: dict[str, float] = {}
    if student_membership_ids and assignment_ids:
        grade_rows = (
            db.execute(
                select(
                    CaseGrade.membership_id.label("membership_id"),
                    CaseGrade.assignment_id.label("assignment_id"),
                    CaseGrade.status.label("status"),
                    CaseGrade.score.label("score"),
                    CaseGrade.max_score.label("max_score"),
                    CaseGrade.graded_at.label("graded_at"),
                )
                .where(
                    CaseGrade.course_id == course_id,
                    CaseGrade.membership_id.in_(student_membership_ids),
                    CaseGrade.assignment_id.in_(assignment_ids),
                )
            )
            .mappings()
            .all()
        )
        for grade_row in grade_rows:
            score = _decimal_to_float(grade_row["score"])
            max_score = _decimal_to_float(grade_row["max_score"])
            grade_by_key[(grade_row["membership_id"], grade_row["assignment_id"])] = {
                "status": grade_row["status"],
                "score": score,
                "max_score": max_score,
                "graded_at": grade_row["graded_at"],
            }
            if max_score is not None:
                existing_max_score = max_score_by_assignment.get(grade_row["assignment_id"])
                if existing_max_score is not None and existing_max_score != max_score:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="course_gradebook_inconsistent_max_score",
                    )
                max_score_by_assignment[grade_row["assignment_id"]] = max_score

    cases = [
        TeacherCourseGradebookCase(
            assignment_id=assignment.id,
            title=_resolve_assignment_title(assignment),
            status="published",
            available_from=assignment.available_from,
            deadline=assignment.deadline,
            max_score=max_score_by_assignment.get(assignment.id, _DEFAULT_CASE_MAX_SCORE),
        )
        for assignment in assignments
    ]

    students: list[TeacherCourseGradebookStudent] = []
    for student_row in student_rows:
        membership_id = student_row["membership_id"]
        grades: list[TeacherCourseGradebookCell] = []
        scored_values: list[float] = []

        for assignment in assignments:
            grade = grade_by_key.get((membership_id, assignment.id))
            if grade is not None:
                score = grade["score"]
                if score is not None and grade["status"] == "graded":
                    normalized_score = _normalize_grade_score(
                        score=score,
                        max_score=grade["max_score"] or max_score_by_assignment.get(assignment.id, _DEFAULT_CASE_MAX_SCORE),
                    )
                    scored_values.append(normalized_score)
                grades.append(
                    TeacherCourseGradebookCell(
                        assignment_id=assignment.id,
                        status=_derive_grade_cell_status(None, grade["status"]),
                        score=score,
                        graded_at=grade["graded_at"],
                    )
                )
                continue

            progress_status = _derive_grade_cell_status(
                progress_by_key.get((membership_id, assignment.id)),
                None,
            )
            grades.append(
                TeacherCourseGradebookCell(
                    assignment_id=assignment.id,
                    status=progress_status,
                    score=None,
                    graded_at=None,
                )
            )

        average_score = round(sum(scored_values) / len(scored_values), 2) if scored_values else None
        students.append(
            TeacherCourseGradebookStudent(
                membership_id=membership_id,
                full_name=_display_name(
                    profile_full_name=student_row["profile_full_name"],
                    email=student_row["email"],
                ),
                email=student_row["email"],
                enrolled_at=student_row["enrolled_at"],
                average_score=average_score,
                grades=grades,
            )
        )

    return TeacherCourseGradebookResponse(
        course=TeacherCourseGradebookCourse(
            id=course_row["id"],
            title=course_row["title"],
            code=course_row["code"],
            students_count=int(course_row["students_count"]),
            cases_count=len(cases),
            average_score_scale=_DEFAULT_CASE_MAX_SCORE,
        ),
        cases=cases,
        students=students,
    )


def get_teacher_case_submissions(
    db: Session,
    context: TeacherContext,
    assignment: Assignment,
) -> TeacherCaseSubmissionsResponse:
    if assignment.status != "published":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assignment not found",
        )

    target_course_ids, _course_codes = _assignment_target_course_metadata(assignment)
    if not target_course_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assignment not found",
        )

    submission_row_records = (
        db.execute(
            select(
                Membership.id.label("membership_id"),
                Membership.user_id.label("user_id"),
                CourseMembership.created_at.label("enrolled_at"),
                Profile.full_name.label("profile_full_name"),
                User.email.label("email"),
                CourseMembership.course_id.label("course_id"),
                Course.code.label("course_code"),
                StudentCaseResponse.status.label("student_case_status"),
                StudentCaseResponse.submitted_at.label("submitted_at"),
                CaseGrade.status.label("case_grade_status"),
                CaseGrade.score.label("score"),
                CaseGrade.max_score.label("max_score"),
                CaseGrade.graded_at.label("graded_at"),
            )
            .select_from(CourseMembership)
            .join(
                Membership,
                and_(
                    CourseMembership.membership_id == Membership.id,
                    Membership.university_id == context.university_id,
                    Membership.role == "student",
                    Membership.status == "active",
                ),
            )
            .join(
                Course,
                and_(
                    CourseMembership.course_id == Course.id,
                    Course.university_id == context.university_id,
                    Course.teacher_membership_id == context.teacher_membership_id,
                ),
            )
            .outerjoin(User, User.id == Membership.user_id)
            .outerjoin(Profile, Profile.id == Membership.user_id)
            .outerjoin(
                StudentCaseResponse,
                and_(
                    StudentCaseResponse.membership_id == Membership.id,
                    StudentCaseResponse.assignment_id == assignment.id,
                ),
            )
            .outerjoin(
                CaseGrade,
                and_(
                    CaseGrade.membership_id == Membership.id,
                    CaseGrade.assignment_id == assignment.id,
                ),
            )
            .where(CourseMembership.course_id.in_(target_course_ids))
        )
        .mappings()
        .all()
    )

    submission_rows = _repair_gradebook_student_rows(
        db,
        context,
        student_rows=submission_row_records,
    )

    student_membership_ids = [row["membership_id"] for row in submission_rows]
    _ensure_supported_gradebook_topology(
        db,
        context,
        assignments=[assignment],
        student_membership_ids=student_membership_ids,
    )

    assignment_max_score = _DEFAULT_CASE_MAX_SCORE
    for row in submission_rows:
        max_score = _decimal_to_float(row["max_score"])
        if max_score is None:
            continue
        if assignment_max_score != _DEFAULT_CASE_MAX_SCORE and assignment_max_score != max_score:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="course_gradebook_inconsistent_max_score",
            )
        assignment_max_score = max_score

    submissions: list[TeacherCaseSubmissionRow] = []
    for row in submission_rows:
        derived_status: TeacherCourseGradebookStatus = _derive_grade_cell_status(
            row["student_case_status"],
            row["case_grade_status"],
        )
        score = _decimal_to_float(row["score"])
        submissions.append(
            TeacherCaseSubmissionRow(
                membership_id=row["membership_id"],
                full_name=_display_name(
                    profile_full_name=row["profile_full_name"],
                    email=row["email"],
                ),
                email=row["email"],
                course_id=row["course_id"],
                course_code=row["course_code"],
                enrolled_at=row["enrolled_at"],
                status=derived_status,
                submitted_at=row["submitted_at"],
                score=score if derived_status == "graded" else None,
                max_score=assignment_max_score,
                graded_at=row["graded_at"],
            )
        )

    submissions.sort(
        key=lambda row: (
            row.course_code.lower(),
            row.full_name.lower(),
            row.email.lower(),
            row.membership_id,
        )
    )

    available_from = assignment.available_from
    deadline = assignment.deadline
    if available_from is None or deadline is None:
        latest_task_payload = db.scalar(
            select(AuthoringJob.task_payload)
            .where(AuthoringJob.assignment_id == assignment.id)
            .order_by(AuthoringJob.created_at.desc())
            .limit(1)
        )
        available_from, deadline = _resolve_schedule_values_from_payload(
            available_from=available_from,
            deadline=deadline,
            task_payload=latest_task_payload if isinstance(latest_task_payload, dict) else None,
        )

    return TeacherCaseSubmissionsResponse(
        case=TeacherCourseGradebookCase(
            assignment_id=assignment.id,
            title=_resolve_assignment_title(assignment),
            status="published",
            available_from=available_from,
            deadline=deadline,
            max_score=assignment_max_score,
        ),
        submissions=submissions,
    )


def get_teacher_course_access_link(
    db: Session,
    context: TeacherContext,
    course_id: str,
) -> TeacherCourseAccessLinkResponse:
    row = (
        db.execute(
            select(
                Course.id.label("course_id"),
                CourseAccessLink.id.label("access_link_id"),
                CourseAccessLink.status.label("access_link_status"),
                CourseAccessLink.created_at.label("access_link_created_at"),
            )
            .select_from(Course)
            .outerjoin(
                CourseAccessLink,
                and_(
                    CourseAccessLink.course_id == Course.id,
                    CourseAccessLink.status == "active",
                ),
            )
            .where(
                Course.id == course_id,
                Course.university_id == context.university_id,
                Course.teacher_membership_id == context.teacher_membership_id,
            )
            .limit(1)
        )
        .mappings()
        .first()
    )

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="course_not_found")

    configuration = _serialize_teacher_course_configuration(
        access_link_status=row["access_link_status"],
        access_link_id=row["access_link_id"],
        access_link_created_at=row["access_link_created_at"],
    )
    return TeacherCourseAccessLinkResponse(
        course_id=row["course_id"],
        **configuration.model_dump(),
    )


def get_teacher_owned_course_with_syllabus(
    db: Session,
    context: TeacherContext,
    course_id: str,
    *,
    lock: bool = False,
) -> TeacherOwnedCourseSyllabus:
    course_stmt = select(Course).where(
        Course.id == course_id,
        Course.university_id == context.university_id,
        Course.teacher_membership_id == context.teacher_membership_id,
    )
    syllabus_stmt = select(Syllabus).where(Syllabus.course_id == course_id)

    if lock:
        course_stmt = course_stmt.with_for_update()
        syllabus_stmt = syllabus_stmt.with_for_update()

    course = db.scalar(course_stmt)
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="course_not_found")

    syllabus = db.scalar(syllabus_stmt)
    if syllabus is None:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="Syllabus no configurado para este curso",
        )

    return TeacherOwnedCourseSyllabus(course=course, syllabus=syllabus)


def resolve_syllabus_selection_titles(
    modules: list[dict[str, Any]],
    *,
    module_id: str,
    unit_id: str,
    strict: bool = False,
) -> tuple[str, str]:
    module_title = ""
    unit_title = ""

    if not module_id:
        if strict:
            raise ValueError("invalid_syllabus_selection")
        return module_title, unit_title

    selected_module = next(
        (candidate for candidate in modules if str(candidate.get("module_id", "")) == module_id),
        None,
    )
    if selected_module is None:
        if strict:
            raise ValueError("invalid_syllabus_selection")
        return module_title, unit_title

    module_title = str(selected_module.get("module_title", ""))
    if not unit_id:
        return module_title, unit_title

    selected_unit = next(
        (
            candidate
            for candidate in selected_module.get("units", [])
            if str(candidate.get("unit_id", "")) == unit_id
        ),
        None,
    )
    if selected_unit is None:
        if strict:
            raise ValueError("invalid_syllabus_selection")
        return module_title, unit_title

    return module_title, str(selected_unit.get("title", ""))


def _normalize_schedule_value(raw_value: Any) -> datetime | None:
    if not isinstance(raw_value, str):
        return None

    stripped_value = raw_value.strip()
    if not stripped_value:
        return None

    normalized_value = stripped_value.replace("Z", "+00:00") if stripped_value.endswith("Z") else stripped_value
    try:
        parsed_value = datetime.fromisoformat(normalized_value)
    except ValueError:
        return None

    localized_value = (
        parsed_value.replace(tzinfo=_BOGOTA_TZ)
        if parsed_value.tzinfo is None
        else parsed_value
    )
    return localized_value.astimezone(timezone.utc)


def _resolve_schedule_values_from_payload(
    *,
    available_from: datetime | None,
    deadline: datetime | None,
    task_payload: dict[str, Any] | None,
) -> tuple[datetime | None, datetime | None]:
    normalized_payload = task_payload if isinstance(task_payload, dict) else {}

    if available_from is None:
        available_from = _normalize_schedule_value(normalized_payload.get("availableFrom"))
    if deadline is None:
        deadline = _normalize_schedule_value(normalized_payload.get("dueAt"))

    return available_from, deadline


def resolve_assignment_schedule_values(assignment: Assignment) -> tuple[datetime | None, datetime | None]:
    available_from = assignment.available_from
    deadline = assignment.deadline

    if available_from is not None and deadline is not None:
        return available_from, deadline

    if not assignment.authoring_jobs:
        return available_from, deadline

    latest_job = max(assignment.authoring_jobs, key=lambda job: job.created_at)
    task_payload = latest_job.task_payload if isinstance(latest_job.task_payload, dict) else {}
    return _resolve_schedule_values_from_payload(
        available_from=available_from,
        deadline=deadline,
        task_payload=task_payload,
    )


def list_teacher_active_cases(
    db: Session,
    actor: CurrentActor,
    *,
    now: datetime,
) -> list[TeacherCaseItem]:
    """Return active (deadline >= now) cases for the authenticated teacher.

    ``now`` must be injected by the caller so that the DB filter and the
    ``days_remaining`` calculation in the router share a single logical instant,
    eliminating drift between the two captures.

    Invariant: ``ensure_legacy_teacher_bridge`` raises HTTP 500
    (``legacy_bridge_missing``) when the legacy User row does not exist.  This
    should never happen in production because the bridge is created atomically
    with every Membership at sign-up.  A 500 here signals a data-integrity gap
    that requires a backfill, not a user-facing error.
    """
    legacy_user = ensure_legacy_teacher_bridge(db, actor)

    assignments = (
        db.execute(
            select(Assignment)
            .options(
                load_only(
                    Assignment.id,
                    Assignment.course_id,
                    Assignment.title,
                    Assignment.canonical_output,
                    Assignment.available_from,
                    Assignment.deadline,
                    Assignment.status,
                ),
                joinedload(Assignment.course).load_only(Course.code),
                joinedload(Assignment.assignment_courses)
                .joinedload(AssignmentCourse.course)
                .load_only(Course.code),
            )
            .where(
                Assignment.teacher_id == legacy_user.id,
                _active_assignment_predicate(now=now),
            )
            .order_by(Assignment.deadline.asc(), Assignment.id.asc())
        )
        .unique()
        .scalars()
        .all()
    )

    legacy_assignment_ids = [
        assignment.id
        for assignment in assignments
        if assignment.available_from is None or assignment.deadline is None
    ]
    legacy_schedule_payloads: dict[str, dict[str, Any]] = {}
    if legacy_assignment_ids:
        # Legacy-only bridge: records created before the #175 schedule persistence fix
        # may still carry dates only inside authoring_jobs.task_payload. Remove this
        # fallback in a future release once no assignments remain with null available_from.
        legacy_schedule_rows = db.execute(
            select(
                AuthoringJob.assignment_id,
                AuthoringJob.created_at,
                AuthoringJob.task_payload,
            )
            .where(AuthoringJob.assignment_id.in_(legacy_assignment_ids))
            .order_by(AuthoringJob.assignment_id.asc(), AuthoringJob.created_at.desc())
        ).all()
        for assignment_id, _created_at, task_payload in legacy_schedule_rows:
            if assignment_id not in legacy_schedule_payloads and isinstance(task_payload, dict):
                legacy_schedule_payloads[assignment_id] = task_payload

    items: list[TeacherCaseItem] = []
    for assignment in assignments:
        canonical_output = assignment.canonical_output if isinstance(assignment.canonical_output, dict) else {}
        canonical_title = canonical_output.get("title")
        title = canonical_title if isinstance(canonical_title, str) and canonical_title.strip() else assignment.title
        course_codes = _assignment_course_codes(assignment)
        available_from, deadline = _resolve_schedule_values_from_payload(
            available_from=assignment.available_from,
            deadline=assignment.deadline,
            task_payload=legacy_schedule_payloads.get(assignment.id),
        )
        items.append(
            TeacherCaseItem(
                id=assignment.id,
                title=title,
                available_from=available_from,
                deadline=deadline,
                status=assignment.status,
                course_codes=course_codes,
            )
        )

    return items
