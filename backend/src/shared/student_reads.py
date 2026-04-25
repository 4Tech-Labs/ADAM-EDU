from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Literal, Sequence

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, load_only

from shared.case_sanitization import sanitize_canonical_output_for_student
from shared.models import (
    Assignment,
    AssignmentCourse,
    AuthoringJob,
    Course,
    CourseMembership,
    Membership,
    Profile,
    StudentCaseResponse,
    StudentCaseResponseSubmission,
)
from shared.student_context import StudentContext
from shared.teacher_reads import _build_assignment_target_courses_subquery, _resolve_schedule_values_from_payload

StudentCaseStatus = Literal["available", "in_progress", "submitted", "upcoming", "closed"]
StudentCaseDraftStatus = Literal["draft", "submitted"]

MAX_STUDENT_ANSWER_CHARS = 10_000
MAX_STUDENT_ANSWERS_BYTES = 200_000

QUESTION_FIELD_TO_MODULE = {
    "caseQuestions": "M1",
    "edaQuestions": "M2",
    "m3Questions": "M3",
    "m4Questions": "M4",
    "m5Questions": "M5",
}


class StudentCourseItemResponse(BaseModel):
    id: str
    title: str
    code: str
    semester: str
    academic_level: str
    status: Literal["active", "inactive"]
    teacher_display_name: str
    pending_cases_count: int
    next_case_title: str | None
    next_deadline: datetime | None


class StudentCoursesResponse(BaseModel):
    courses: list[StudentCourseItemResponse]
    total: int


class StudentCaseItemResponse(BaseModel):
    id: str
    title: str
    available_from: datetime | None
    deadline: datetime | None
    status: StudentCaseStatus
    course_codes: list[str]


class StudentCasesResponse(BaseModel):
    cases: list[StudentCaseItemResponse]
    total: int


class StudentCaseAssignmentMeta(BaseModel):
    id: str
    title: str
    available_from: datetime | None
    deadline: datetime | None
    status: StudentCaseStatus
    course_codes: list[str]


class StudentCaseResponseState(BaseModel):
    status: StudentCaseDraftStatus
    answers: dict[str, str]
    version: int
    last_autosaved_at: datetime | None
    submitted_at: datetime | None


class StudentCaseDetailResponse(BaseModel):
    assignment: StudentCaseAssignmentMeta
    canonical_output: dict[str, Any]
    response: StudentCaseResponseState


class StudentCaseDraftRequest(BaseModel):
    answers: dict[str, str]
    version: int


class StudentCaseDraftResponse(BaseModel):
    version: int
    last_autosaved_at: datetime


class StudentCaseSubmitRequest(BaseModel):
    answers: dict[str, str]
    version: int


class StudentCaseSubmitResponse(BaseModel):
    status: Literal["submitted"]
    submitted_at: datetime
    version: int


@dataclass(slots=True)
class StudentVisibleCase:
    id: str
    title: str
    available_from: datetime | None
    deadline: datetime | None
    status: StudentCaseStatus
    course_ids: list[str]
    course_codes: list[str]


@dataclass(slots=True)
class StudentVisibleAssignmentDetail:
    assignment: Assignment
    title: str
    available_from: datetime | None
    deadline: datetime | None
    course_ids: list[str]
    course_codes: list[str]


def _resolve_reference_now(now: datetime | None = None) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


def _status_sort_rank(status: StudentCaseStatus) -> int:
    if status == "in_progress":
        return 0
    if status == "available":
        return 1
    if status == "upcoming":
        return 2
    if status == "submitted":
        return 3
    return 4


def _case_sort_key(case: StudentVisibleCase) -> tuple[Any, ...]:
    if case.status in {"in_progress", "available"}:
        return (
            _status_sort_rank(case.status),
            case.deadline is None,
            case.deadline or datetime.max.replace(tzinfo=timezone.utc),
            case.title.lower(),
            case.id,
        )
    if case.status == "upcoming":
        return (
            _status_sort_rank(case.status),
            case.available_from is None,
            case.available_from or datetime.max.replace(tzinfo=timezone.utc),
            case.deadline is None,
            case.deadline or datetime.max.replace(tzinfo=timezone.utc),
            case.title.lower(),
            case.id,
        )
    return (
        _status_sort_rank(case.status),
        case.deadline is None,
        -(case.deadline.timestamp()) if case.deadline is not None else 0,
        case.title.lower(),
        case.id,
    )


def _canonical_assignment_title(assignment: Assignment) -> str:
    canonical_output = assignment.canonical_output if isinstance(assignment.canonical_output, dict) else {}
    canonical_title = canonical_output.get("title")
    if isinstance(canonical_title, str) and canonical_title.strip():
        return canonical_title
    return assignment.title


def _student_case_status(
    available_from: datetime | None,
    deadline: datetime | None,
    *,
    now: datetime,
    response_status: StudentCaseDraftStatus | None = None,
    last_autosaved_at: datetime | None = None,
) -> StudentCaseStatus:
    if response_status == "submitted":
        return "submitted"
    if available_from is not None and available_from > now:
        return "upcoming"
    if deadline is not None and deadline < now:
        return "closed"
    if response_status == "draft" and last_autosaved_at is not None:
        return "in_progress"
    return "available"


def _student_course_status(value: Any) -> Literal["active", "inactive"]:
    return "active" if value == "active" else "inactive"


def _coerce_response_status(value: str | None) -> StudentCaseDraftStatus | None:
    if value == "draft":
        return "draft"
    if value == "submitted":
        return "submitted"
    return None


def _student_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _latest_legacy_schedule_payloads(
    db: Session,
    assignment_ids: list[str],
) -> dict[str, dict[str, Any]]:
    if not assignment_ids:
        return {}

    rows = db.execute(
        select(
            AuthoringJob.assignment_id,
            AuthoringJob.created_at,
            AuthoringJob.task_payload,
        )
        .where(AuthoringJob.assignment_id.in_(assignment_ids))
        .order_by(AuthoringJob.assignment_id.asc(), AuthoringJob.created_at.desc())
    ).all()

    payloads: dict[str, dict[str, Any]] = {}
    for assignment_id, _created_at, task_payload in rows:
        if assignment_id not in payloads and isinstance(task_payload, dict):
            payloads[assignment_id] = task_payload
    return payloads


def _resolve_assignment_schedule(
    db: Session,
    assignments: Sequence[Assignment],
) -> dict[str, tuple[datetime | None, datetime | None]]:
    legacy_assignment_ids = [
        assignment.id
        for assignment in assignments
        if assignment.available_from is None or assignment.deadline is None
    ]
    legacy_schedule_payloads = _latest_legacy_schedule_payloads(db, legacy_assignment_ids)

    return {
        assignment.id: _resolve_schedule_values_from_payload(
            available_from=assignment.available_from,
            deadline=assignment.deadline,
            task_payload=legacy_schedule_payloads.get(assignment.id),
        )
        for assignment in assignments
    }


def _canonical_output_question_ids(canonical_output: dict[str, Any]) -> set[str]:
    content = canonical_output.get("content")
    if not isinstance(content, dict):
        return set()

    question_ids: set[str] = set()
    for field_name, module_prefix in QUESTION_FIELD_TO_MODULE.items():
        questions = content.get(field_name)
        if not isinstance(questions, list):
            continue
        for question in questions:
            if not isinstance(question, dict):
                continue
            numero = question.get("numero")
            if numero is None:
                continue
            normalized_numero = str(numero).strip()
            if normalized_numero:
                question_ids.add(f"{module_prefix}-Q{normalized_numero}")
    return question_ids


def _validate_answers_payload(
    answers: dict[str, str],
    *,
    allowed_question_ids: set[str],
) -> dict[str, str]:
    normalized_answers = {str(key): value for key, value in answers.items()}

    payload_bytes = len(json.dumps(normalized_answers, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    if payload_bytes > MAX_STUDENT_ANSWERS_BYTES:
        raise _student_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "payload_too_large",
            f"Responses payload must be at most {MAX_STUDENT_ANSWERS_BYTES} bytes.",
        )

    for question_id, answer in normalized_answers.items():
        if allowed_question_ids and question_id not in allowed_question_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": "invalid_question_id",
                    "message": f"Question id '{question_id}' is not part of this case.",
                },
            )
        if len(answer) > MAX_STUDENT_ANSWER_CHARS:
            raise _student_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "payload_too_large",
                f"Each response must be at most {MAX_STUDENT_ANSWER_CHARS} characters.",
            )

    return normalized_answers


def _canonical_output_hash(canonical_output: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(canonical_output, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _response_state(response: StudentCaseResponse) -> StudentCaseResponseState:
    return StudentCaseResponseState(
        status=response.status,
        answers=dict(response.answers or {}),
        version=response.version,
        last_autosaved_at=response.last_autosaved_at,
        submitted_at=response.submitted_at,
    )


def _load_student_visible_assignment_detail(
    db: Session,
    context: StudentContext,
    assignment_id: str,
) -> StudentVisibleAssignmentDetail | None:
    enrolled_course_rows = _load_enrolled_courses(db, context)
    enrolled_course_id_set = {str(row["id"]) for row in enrolled_course_rows}
    if not enrolled_course_id_set:
        return None

    assignment = db.scalar(
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
            joinedload(Assignment.course).load_only(Course.id, Course.code, Course.university_id),
            joinedload(Assignment.assignment_courses)
            .joinedload(AssignmentCourse.course)
            .load_only(Course.id, Course.code, Course.university_id),
        )
        .where(
            Assignment.id == assignment_id,
            Assignment.status == "published",
        )
    )
    if assignment is None:
        return None

    schedule_map = _resolve_assignment_schedule(db, [assignment])
    available_from, deadline = schedule_map[assignment.id]

    target_university_ids: set[str] = set()
    visible_course_ids: list[str] = []
    visible_course_codes: list[str] = []

    if assignment.assignment_courses:
        for link in assignment.assignment_courses:
            if link.course is not None and link.course.university_id:
                target_university_ids.add(str(link.course.university_id))
            if link.course_id not in enrolled_course_id_set:
                continue
            visible_course_ids.append(link.course_id)
            if link.course is not None and link.course.code:
                visible_course_codes.append(link.course.code)
    elif assignment.course_id is not None:
        if assignment.course is not None and assignment.course.university_id:
            target_university_ids.add(str(assignment.course.university_id))
        if assignment.course_id in enrolled_course_id_set:
            visible_course_ids.append(assignment.course_id)
            if assignment.course is not None and assignment.course.code:
                visible_course_codes.append(assignment.course.code)

    if not visible_course_ids:
        return None

    if target_university_ids and target_university_ids != {context.university_id}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="assignment_forbidden")

    return StudentVisibleAssignmentDetail(
        assignment=assignment,
        title=_canonical_assignment_title(assignment),
        available_from=available_from,
        deadline=deadline,
        course_ids=sorted(set(visible_course_ids)),
        course_codes=sorted(set(visible_course_codes)),
    )


def _ensure_student_case_response(
    db: Session,
    *,
    membership_id: str,
    assignment_id: str,
    opened_at: datetime,
) -> StudentCaseResponse:
    response = db.scalar(
        select(StudentCaseResponse).where(
            StudentCaseResponse.membership_id == membership_id,
            StudentCaseResponse.assignment_id == assignment_id,
        )
    )
    if response is not None:
        return response

    response = StudentCaseResponse(
        membership_id=membership_id,
        assignment_id=assignment_id,
        answers={},
        status="draft",
        version=0,
        first_opened_at=opened_at,
    )
    db.add(response)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    else:
        db.refresh(response)
        return response

    existing_response = db.scalar(
        select(StudentCaseResponse).where(
            StudentCaseResponse.membership_id == membership_id,
            StudentCaseResponse.assignment_id == assignment_id,
        )
    )
    if existing_response is None:  # pragma: no cover
        raise RuntimeError("student case response could not be created")
    return existing_response


def _load_locked_student_case_response(
    db: Session,
    *,
    membership_id: str,
    assignment_id: str,
    opened_at: datetime,
) -> StudentCaseResponse:
    _ensure_student_case_response(
        db,
        membership_id=membership_id,
        assignment_id=assignment_id,
        opened_at=opened_at,
    )
    response = db.scalar(
        select(StudentCaseResponse)
        .where(
            StudentCaseResponse.membership_id == membership_id,
            StudentCaseResponse.assignment_id == assignment_id,
        )
        .with_for_update()
    )
    if response is None:  # pragma: no cover
        raise RuntimeError("student case response lock acquisition failed")
    return response


def _load_enrolled_courses(db: Session, context: StudentContext) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            select(
                Course.id.label("id"),
                Course.title.label("title"),
                Course.code.label("code"),
                Course.semester.label("semester"),
                Course.academic_level.label("academic_level"),
                Course.status.label("status"),
                Profile.full_name.label("teacher_display_name"),
            )
            .select_from(Course)
            .join(CourseMembership, CourseMembership.course_id == Course.id)
            .outerjoin(Membership, Membership.id == Course.teacher_membership_id)
            .outerjoin(Profile, Profile.id == Membership.user_id)
            .where(
                Course.university_id == context.university_id,
                CourseMembership.membership_id == context.student_membership_id,
            )
            .order_by(Course.status.asc(), Course.title.asc(), Course.id.asc())
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def list_student_visible_cases(
    db: Session,
    context: StudentContext,
    *,
    now: datetime | None = None,
    enrolled_course_rows: list[dict[str, Any]] | None = None,
) -> list[StudentVisibleCase]:
    reference_now = _resolve_reference_now(now)
    if enrolled_course_rows is None:
        enrolled_course_rows = _load_enrolled_courses(db, context)
    enrolled_course_ids = [str(row["id"]) for row in enrolled_course_rows]
    enrolled_course_id_set = set(enrolled_course_ids)
    if not enrolled_course_ids:
        return []

    assignment_target_courses = _build_assignment_target_courses_subquery()
    visible_assignment_ids = db.scalars(
        select(assignment_target_courses.c.assignment_id)
        .where(assignment_target_courses.c.course_id.in_(enrolled_course_ids))
        .distinct()
    ).all()
    if not visible_assignment_ids:
        return []

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
                joinedload(Assignment.course).load_only(Course.id, Course.code),
                joinedload(Assignment.assignment_courses)
                .joinedload(AssignmentCourse.course)
                .load_only(Course.id, Course.code),
            )
            .where(
                Assignment.id.in_(visible_assignment_ids),
                Assignment.status == "published",
            )
        )
        .unique()
        .scalars()
        .all()
    )

    schedule_map = _resolve_assignment_schedule(db, assignments)
    response_rows = db.execute(
        select(
            StudentCaseResponse.assignment_id,
            StudentCaseResponse.status,
            StudentCaseResponse.last_autosaved_at,
        ).where(
            StudentCaseResponse.membership_id == context.student_membership_id,
            StudentCaseResponse.assignment_id.in_([assignment.id for assignment in assignments]),
        )
    ).all()
    response_by_assignment_id = {
        assignment_id: {
            "status": response_status,
            "last_autosaved_at": last_autosaved_at,
        }
        for assignment_id, response_status, last_autosaved_at in response_rows
    }

    items: list[StudentVisibleCase] = []
    for assignment in assignments:
        available_from, deadline = schedule_map[assignment.id]

        visible_course_ids: list[str] = []
        visible_course_codes: list[str] = []
        if assignment.assignment_courses:
            for link in assignment.assignment_courses:
                if link.course_id not in enrolled_course_id_set:
                    continue
                visible_course_ids.append(link.course_id)
                if link.course is not None and link.course.code:
                    visible_course_codes.append(link.course.code)
        elif assignment.course_id is not None and assignment.course_id in enrolled_course_id_set:
            visible_course_ids.append(assignment.course_id)
            if assignment.course is not None and assignment.course.code:
                visible_course_codes.append(assignment.course.code)

        deduped_course_ids = sorted(set(visible_course_ids))
        deduped_course_codes = sorted(set(visible_course_codes))
        if not deduped_course_ids:
            continue

        response_meta = response_by_assignment_id.get(assignment.id)
        items.append(
            StudentVisibleCase(
                id=assignment.id,
                title=_canonical_assignment_title(assignment),
                available_from=available_from,
                deadline=deadline,
                status=_student_case_status(
                    available_from,
                    deadline,
                    now=reference_now,
                    response_status=_coerce_response_status(
                        str(response_meta["status"]) if response_meta is not None else None
                    ),
                    last_autosaved_at=(
                        response_meta["last_autosaved_at"] if response_meta is not None else None
                    ),
                ),
                course_ids=deduped_course_ids,
                course_codes=deduped_course_codes,
            )
        )

    items.sort(key=_case_sort_key)
    return items


def list_student_cases(
    db: Session,
    context: StudentContext,
    *,
    now: datetime | None = None,
) -> StudentCasesResponse:
    items = list_student_visible_cases(db, context, now=now)
    cases = [
        StudentCaseItemResponse(
            id=item.id,
            title=item.title,
            available_from=item.available_from,
            deadline=item.deadline,
            status=item.status,
            course_codes=item.course_codes,
        )
        for item in items
    ]
    return StudentCasesResponse(cases=cases, total=len(cases))


def list_student_courses(
    db: Session,
    context: StudentContext,
    *,
    now: datetime | None = None,
) -> StudentCoursesResponse:
    reference_now = _resolve_reference_now(now)
    course_rows = _load_enrolled_courses(db, context)
    if not course_rows:
        return StudentCoursesResponse(courses=[], total=0)

    visible_cases = list_student_visible_cases(
        db,
        context,
        now=reference_now,
        enrolled_course_rows=course_rows,
    )
    aggregates: dict[str, dict[str, Any]] = {
        str(row["id"]): {
            "pending_cases_count": 0,
            "next_case_title": None,
            "next_deadline": None,
        }
        for row in course_rows
    }

    for case in visible_cases:
        is_pending = case.status in {"available", "in_progress", "upcoming"}
        for course_id in case.course_ids:
            aggregate = aggregates.get(course_id)
            if aggregate is None:
                continue
            if is_pending:
                aggregate["pending_cases_count"] += 1

                current_deadline = aggregate["next_deadline"]
                should_replace = False
                if current_deadline is None:
                    should_replace = True
                elif case.deadline is not None and case.deadline < current_deadline:
                    should_replace = True

                if should_replace:
                    aggregate["next_case_title"] = case.title
                    aggregate["next_deadline"] = case.deadline

    courses: list[StudentCourseItemResponse] = []
    for row in course_rows:
        course_id = str(row["id"])
        aggregate = aggregates[course_id]
        courses.append(
            StudentCourseItemResponse(
                id=course_id,
                title=str(row["title"]),
                code=str(row["code"]),
                semester=str(row["semester"]),
                academic_level=str(row["academic_level"]),
                status=_student_course_status(row["status"]),
                teacher_display_name=(
                    str(row["teacher_display_name"])
                    if row["teacher_display_name"]
                    else "Docente asignado"
                ),
                pending_cases_count=int(aggregate["pending_cases_count"]),
                next_case_title=aggregate["next_case_title"],
                next_deadline=aggregate["next_deadline"],
            )
        )

    return StudentCoursesResponse(courses=courses, total=len(courses))


def get_student_case_detail(
    db: Session,
    context: StudentContext,
    assignment_id: str,
    *,
    now: datetime | None = None,
) -> StudentCaseDetailResponse:
    reference_now = _resolve_reference_now(now)
    detail = _load_student_visible_assignment_detail(db, context, assignment_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")
    if detail.available_from is not None and detail.available_from > reference_now:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")

    canonical_output = detail.assignment.canonical_output if isinstance(detail.assignment.canonical_output, dict) else {}
    sanitized_output = sanitize_canonical_output_for_student(canonical_output)
    response = _ensure_student_case_response(
        db,
        membership_id=context.student_membership_id,
        assignment_id=detail.assignment.id,
        opened_at=reference_now,
    )

    assignment_meta = StudentCaseAssignmentMeta(
        id=detail.assignment.id,
        title=detail.title,
        available_from=detail.available_from,
        deadline=detail.deadline,
        status=_student_case_status(
            detail.available_from,
            detail.deadline,
            now=reference_now,
            response_status=_coerce_response_status(response.status),
            last_autosaved_at=response.last_autosaved_at,
        ),
        course_codes=detail.course_codes,
    )
    return StudentCaseDetailResponse(
        assignment=assignment_meta,
        canonical_output=sanitized_output,
        response=_response_state(response),
    )


def save_student_case_draft(
    db: Session,
    context: StudentContext,
    assignment_id: str,
    request: StudentCaseDraftRequest,
    *,
    now: datetime | None = None,
) -> StudentCaseDraftResponse:
    reference_now = _resolve_reference_now(now)
    detail = _load_student_visible_assignment_detail(db, context, assignment_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")
    if detail.available_from is not None and detail.available_from > reference_now:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")
    if detail.deadline is not None and reference_now > detail.deadline:
        raise _student_error(
            status.HTTP_403_FORBIDDEN,
            "deadline_passed",
            "This case deadline has already passed.",
        )

    canonical_output = detail.assignment.canonical_output if isinstance(detail.assignment.canonical_output, dict) else {}
    allowed_question_ids = _canonical_output_question_ids(sanitize_canonical_output_for_student(canonical_output))
    normalized_answers = _validate_answers_payload(request.answers, allowed_question_ids=allowed_question_ids)

    response = _load_locked_student_case_response(
        db,
        membership_id=context.student_membership_id,
        assignment_id=detail.assignment.id,
        opened_at=reference_now,
    )

    if response.status == "submitted":
        raise _student_error(
            status.HTTP_403_FORBIDDEN,
            "already_submitted",
            "Submitted responses can no longer be edited.",
        )
    if request.version != response.version:
        raise _student_error(
            status.HTTP_409_CONFLICT,
            "version_conflict",
            "This draft was updated elsewhere. Reload to continue.",
        )

    response.answers = normalized_answers
    response.version += 1
    response.last_autosaved_at = reference_now
    response.updated_at = reference_now
    db.commit()
    db.refresh(response)
    return StudentCaseDraftResponse(
        version=response.version,
        last_autosaved_at=response.last_autosaved_at or reference_now,
    )


def submit_student_case(
    db: Session,
    context: StudentContext,
    assignment_id: str,
    request: StudentCaseSubmitRequest,
    *,
    now: datetime | None = None,
) -> StudentCaseSubmitResponse:
    reference_now = _resolve_reference_now(now)
    detail = _load_student_visible_assignment_detail(db, context, assignment_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")
    if detail.available_from is not None and detail.available_from > reference_now:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")
    if detail.deadline is not None and reference_now > detail.deadline:
        raise _student_error(
            status.HTTP_403_FORBIDDEN,
            "deadline_passed",
            "This case deadline has already passed.",
        )

    canonical_output = detail.assignment.canonical_output if isinstance(detail.assignment.canonical_output, dict) else {}
    sanitized_output = sanitize_canonical_output_for_student(canonical_output)
    allowed_question_ids = _canonical_output_question_ids(sanitized_output)
    normalized_answers = _validate_answers_payload(request.answers, allowed_question_ids=allowed_question_ids)

    response = _load_locked_student_case_response(
        db,
        membership_id=context.student_membership_id,
        assignment_id=detail.assignment.id,
        opened_at=reference_now,
    )

    if response.status == "submitted":
        raise _student_error(
            status.HTTP_409_CONFLICT,
            "already_submitted",
            "This case has already been submitted.",
        )
    if request.version != response.version:
        raise _student_error(
            status.HTTP_409_CONFLICT,
            "version_conflict",
            "This draft was updated elsewhere. Reload to continue.",
        )

    response.answers = normalized_answers
    response.status = "submitted"
    response.version += 1
    response.last_autosaved_at = reference_now
    response.submitted_at = reference_now
    response.updated_at = reference_now
    db.add(
        StudentCaseResponseSubmission(
            response=response,
            answers_snapshot=normalized_answers,
            submitted_at=reference_now,
            canonical_output_hash=_canonical_output_hash(sanitized_output),
        )
    )
    db.commit()
    db.refresh(response)
    return StudentCaseSubmitResponse(
        status="submitted",
        submitted_at=response.submitted_at or reference_now,
        version=response.version,
    )