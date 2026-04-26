from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import logging
from typing import Any, Literal, Sequence
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session, joinedload, load_only

from shared.auth import CurrentActor, ensure_legacy_teacher_bridge, get_supabase_admin_auth_client
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
    TeacherCourseGradebookCase,
    TeacherCourseGradebookCell,
    TeacherCourseGradebookCourse,
    TeacherCourseGradebookResponse,
    TeacherCourseGradebookStudent,
)

_BOGOTA_TZ = ZoneInfo("America/Bogota")
_DEFAULT_CASE_MAX_SCORE = 5.0
_logger = logging.getLogger(__name__)


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


def _map_student_case_status(status_value: str) -> Literal["in_progress", "submitted"]:
    if status_value == "submitted":
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

    progress_by_key: dict[tuple[str, str], Literal["in_progress", "submitted"]] = {}
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
            (row["membership_id"], row["assignment_id"]): _map_student_case_status(row["status"])
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
                        status=grade["status"],
                        score=score,
                        graded_at=grade["graded_at"],
                    )
                )
                continue

            progress_status = progress_by_key.get((membership_id, assignment.id), "not_started")
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
