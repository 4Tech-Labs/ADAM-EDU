"""Per-question manual grading writes for teacher submission review.

Writes `case_question_grades` rows and consolidates them into the case-level
`CaseGrade` rollup. This is the FIRST code path that writes `CaseGrade`.

Key contracts (see the approved plan):
  - Gated to submitted student responses (D1): grading an in-progress/never-submitted
    response is rejected with `response_not_submitted`.
  - Single source of truth for the gradeable question set (A1): every id comes from
    `teacher_reads.build_gradeable_question_ids` (same derivation the detail uses), so the
    set the teacher sees == the set validated == the rollup denominator on every path.
  - Concurrency-safe rollup (H2): the `CaseGrade` row is materialized race-free with
    INSERT ... ON CONFLICT DO NOTHING, then locked FOR UPDATE; only under that lock are the
    question rows read and the rollup computed, so concurrent saves cannot lose the
    "all graded" transition or collide on the first insert.
  - `CaseGrade.max_score` is ALWAYS 5.00 and `score` is ALWAYS pre-normalized to 0-5 (H5),
    matching the gradebook's read-time normalization and its max-score consistency guard.
  - `CaseGrade` rows are removed entirely when no question grade remains (H4).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import logging

from fastapi import HTTPException, status
from sqlalchemy import and_, delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shared.auth import audit_log
from shared.case_sanitization import build_teacher_case_review_payload
from shared.models import (
    Assignment,
    CaseGrade,
    CaseQuestionGrade,
    Course,
    CourseMembership,
    Membership,
    StudentCaseResponse,
    generate_uuid,
)
from shared.teacher_context import TeacherContext
from shared.teacher_gradebook_schema import (
    TeacherCaseSubmissionDetailGradeSummary,
    TeacherQuestionGradeUpsertRequest,
    TeacherQuestionGradeWriteResponse,
)
from shared.teacher_reads import (
    _DEFAULT_CASE_MAX_SCORE_DECIMAL,
    _assignment_target_course_metadata,
    _ensure_supported_gradebook_topology,
    _load_question_grades_by_qid,
    _load_teacher_submission_assignment,
    _normalize_grade_score,
    build_gradeable_question_ids,
)

_logger = logging.getLogger(__name__)


def _gradeable_question_ids(assignment: Assignment) -> set[str]:
    """Distinct, per-card gradeable question ids for an assignment (A1, fail-safe)."""
    canonical = assignment.canonical_output
    if not isinstance(canonical, dict):
        return set()
    try:
        teacher_payload = build_teacher_case_review_payload(canonical)
    except Exception:
        return set()
    return set(build_gradeable_question_ids(teacher_payload))


def _resolve_student_grading_context(
    db: Session,
    context: TeacherContext,
    *,
    assignment: Assignment,
    membership_id: str,
    target_course_ids: list[str],
) -> tuple[str, str | None]:
    """Resolve the student's owned course_id + response status, or 404.

    Mirrors the ownership JOIN of `get_teacher_case_submission_detail`: the student must
    be an active student in a course the teacher owns within the tenant. Closes IDOR.
    """
    row = (
        db.execute(
            select(
                Course.id.label("course_id"),
                StudentCaseResponse.status.label("student_case_status"),
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
            .outerjoin(
                StudentCaseResponse,
                and_(
                    StudentCaseResponse.membership_id == Membership.id,
                    StudentCaseResponse.assignment_id == assignment.id,
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
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="submission_not_found")
    return row["course_id"], row["student_case_status"]


def _recompute_case_grade_rollup(
    db: Session,
    *,
    assignment_id: str,
    course_id: str,
    membership_id: str,
    all_ids: set[str],
    now: datetime,
    graded_by: str,
) -> None:
    """Recompute the case-level rollup transactionally and race-free (H2/H4/H5/H11/H13).

    Order is load-bearing: materialize the CaseGrade row with ON CONFLICT DO NOTHING, then
    lock it FOR UPDATE, then read the question rows UNDER the lock so concurrent writers
    cannot compute "all graded" from a stale snapshot.
    """
    db.execute(
        pg_insert(CaseGrade)
        .values(
            id=generate_uuid(),
            membership_id=membership_id,
            assignment_id=assignment_id,
            course_id=course_id,
            status="submitted",
            score=None,
            max_score=_DEFAULT_CASE_MAX_SCORE_DECIMAL,
            graded_at=None,
            graded_by_membership_id=None,
            feedback=None,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(constraint="uix_case_grades_membership_assignment")
    )
    case_grade = db.execute(
        select(CaseGrade)
        .where(
            CaseGrade.membership_id == membership_id,
            CaseGrade.assignment_id == assignment_id,
        )
        .with_for_update()
    ).scalar_one()

    # H13: never grade through a course mismatch (defense-in-depth behind the topology guard).
    if case_grade.course_id != course_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="course_gradebook_cross_enrollment_unsupported",
        )

    rows = (
        db.execute(
            select(CaseQuestionGrade).where(
                CaseQuestionGrade.assignment_id == assignment_id,
                CaseQuestionGrade.membership_id == membership_id,
                CaseQuestionGrade.course_id == course_id,
            )
        )
        .scalars()
        .all()
    )
    kept = [row for row in rows if row.question_id in all_ids]
    stale_qids = [row.question_id for row in rows if row.question_id not in all_ids]
    if stale_qids:
        # H14: re-published/renumbered case left orphan grades — log-only signal, no UI yet.
        _logger.warning(
            "teacher_question_grade_stale_rows",
            extra={
                "assignment_id": assignment_id,
                "membership_id": membership_id,
                "stale_qids": stale_qids,
            },
        )

    if not kept:
        # H4: no remaining question grades -> drop the rollup so the gradebook reverts to
        # the student's real progress state instead of a stale 'submitted'.
        db.delete(case_grade)
        db.flush()
        return

    total = len(all_ids)
    is_complete = total > 0 and len(kept) == total

    if is_complete:
        sum_points = sum((row.points_awarded for row in kept), Decimal("0"))
        sum_max = sum((row.max_points for row in kept), Decimal("0"))
        normalized = _normalize_grade_score(score=float(sum_points), max_score=float(sum_max))
        case_grade.status = "graded"
        case_grade.score = Decimal(str(normalized))
        case_grade.graded_at = now
        case_grade.graded_by_membership_id = graded_by
    else:
        # Truthful under the D1 submitted-gate: the student really did submit.
        case_grade.status = "submitted"
        case_grade.score = None
        case_grade.graded_at = None
        case_grade.graded_by_membership_id = None
    case_grade.max_score = _DEFAULT_CASE_MAX_SCORE_DECIMAL
    case_grade.updated_at = now
    db.flush()


def _grade_summary(case_grade: CaseGrade | None) -> TeacherCaseSubmissionDetailGradeSummary:
    if case_grade is None:
        return TeacherCaseSubmissionDetailGradeSummary(
            status=None,
            score=None,
            max_score=_DEFAULT_CASE_MAX_SCORE_DECIMAL,
            graded_at=None,
        )
    return TeacherCaseSubmissionDetailGradeSummary(
        status=case_grade.status,
        score=case_grade.score,
        max_score=case_grade.max_score,
        graded_at=case_grade.graded_at,
    )


def _build_write_response(
    db: Session,
    *,
    assignment_id: str,
    membership_id: str,
    question_id: str,
    all_ids: set[str],
) -> TeacherQuestionGradeWriteResponse:
    grades = _load_question_grades_by_qid(
        db,
        assignment_id=assignment_id,
        membership_id=membership_id,
    )
    graded_count = sum(1 for qid in grades if qid in all_ids)
    total = len(all_ids)
    case_grade = db.scalar(
        select(CaseGrade).where(
            CaseGrade.membership_id == membership_id,
            CaseGrade.assignment_id == assignment_id,
        )
    )
    return TeacherQuestionGradeWriteResponse(
        grade=grades.get(question_id),
        grade_summary=_grade_summary(case_grade),
        is_case_fully_graded=total > 0 and graded_count == total,
        graded_question_count=graded_count,
        total_question_count=total,
    )


def _resolve_grading_target(
    db: Session,
    context: TeacherContext,
    *,
    assignment_id: str,
    membership_id: str,
    require_gradeable_questions: bool,
) -> tuple[str, set[str]]:
    """Shared guard chain for upsert/clear: ownership, topology, D1 gate, gradeable set.

    Returns ``(course_id, gradeable_question_ids)``.
    """
    assignment = _load_teacher_submission_assignment(db, context, assignment_id=assignment_id)
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")
    target_course_ids, _codes = _assignment_target_course_metadata(assignment)
    if not target_course_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")
    _ensure_supported_gradebook_topology(
        db,
        context,
        assignments=[assignment],
        student_membership_ids=[membership_id],
    )
    course_id, student_case_status = _resolve_student_grading_context(
        db,
        context,
        assignment=assignment,
        membership_id=membership_id,
        target_course_ids=target_course_ids,
    )
    # D1: only submitted responses can be graded.
    if student_case_status != "submitted":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="response_not_submitted",
        )
    all_ids = _gradeable_question_ids(assignment)
    if require_gradeable_questions and not all_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="case_has_no_gradeable_questions",
        )
    return course_id, all_ids


def upsert_question_grade(
    db: Session,
    context: TeacherContext,
    *,
    assignment_id: str,
    membership_id: str,
    question_id: str,
    request: TeacherQuestionGradeUpsertRequest,
) -> TeacherQuestionGradeWriteResponse:
    now = datetime.now(timezone.utc)
    try:
        course_id, all_ids = _resolve_grading_target(
            db,
            context,
            assignment_id=assignment_id,
            membership_id=membership_id,
            require_gradeable_questions=True,
        )
        if question_id not in all_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="invalid_question_id",
            )
        if request.max_points <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="invalid_max_points",
            )
        if request.points_awarded < 0 or request.points_awarded > request.max_points:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="points_out_of_range",
            )

        db.execute(
            pg_insert(CaseQuestionGrade)
            .values(
                id=generate_uuid(),
                membership_id=membership_id,
                assignment_id=assignment_id,
                course_id=course_id,
                question_id=question_id,
                points_awarded=request.points_awarded,
                max_points=request.max_points,
                feedback=request.feedback,
                graded_by_membership_id=context.teacher_membership_id,
                graded_at=now,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                constraint="uix_case_question_grades_membership_assignment_question",
                set_={
                    "points_awarded": request.points_awarded,
                    "max_points": request.max_points,
                    "feedback": request.feedback,
                    "graded_by_membership_id": context.teacher_membership_id,
                    "graded_at": now,
                    "updated_at": now,
                },
            )
        )
        _recompute_case_grade_rollup(
            db,
            assignment_id=assignment_id,
            course_id=course_id,
            membership_id=membership_id,
            all_ids=all_ids,
            now=now,
            graded_by=context.teacher_membership_id,
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="points_out_of_range",
        ) from exc

    audit_log(
        "teacher.question_grade.upsert",
        "success",
        university_id=context.university_id,
        membership_id=context.teacher_membership_id,
        assignment_id=assignment_id,
        course_id=course_id,
    )
    return _build_write_response(
        db,
        assignment_id=assignment_id,
        membership_id=membership_id,
        question_id=question_id,
        all_ids=all_ids,
    )


def clear_question_grade(
    db: Session,
    context: TeacherContext,
    *,
    assignment_id: str,
    membership_id: str,
    question_id: str,
) -> TeacherQuestionGradeWriteResponse:
    now = datetime.now(timezone.utc)
    try:
        course_id, all_ids = _resolve_grading_target(
            db,
            context,
            assignment_id=assignment_id,
            membership_id=membership_id,
            require_gradeable_questions=False,
        )
        # Idempotent: deleting a non-existent grade is a no-op.
        db.execute(
            delete(CaseQuestionGrade).where(
                CaseQuestionGrade.membership_id == membership_id,
                CaseQuestionGrade.assignment_id == assignment_id,
                CaseQuestionGrade.question_id == question_id,
            )
        )
        _recompute_case_grade_rollup(
            db,
            assignment_id=assignment_id,
            course_id=course_id,
            membership_id=membership_id,
            all_ids=all_ids,
            now=now,
            graded_by=context.teacher_membership_id,
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="question_grade_clear_failed",
        ) from exc

    audit_log(
        "teacher.question_grade.clear",
        "success",
        university_id=context.university_id,
        membership_id=context.teacher_membership_id,
        assignment_id=assignment_id,
        course_id=course_id,
    )
    return _build_write_response(
        db,
        assignment_id=assignment_id,
        membership_id=membership_id,
        question_id=question_id,
        all_ids=all_ids,
    )
