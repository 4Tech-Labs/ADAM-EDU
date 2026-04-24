from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shared.auth import audit_log
from shared.course_access_links import regenerate_course_access_link, try_acquire_course_regeneration_lock
from shared.course_access_schema import CourseAccessLinkRegenerateResponse
from shared.models import Course, Syllabus, SyllabusRevision
from shared.syllabus_schema import (
    TeacherCourseDetailResponse,
    TeacherSyllabusPayload,
    TeacherSyllabusSaveRequest,
    derive_syllabus_grounding_context,
)
from shared.teacher_context import TeacherContext
from shared.teacher_reads import get_teacher_course_detail


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _build_syllabus_snapshot(
    *,
    syllabus: TeacherSyllabusPayload,
    ai_grounding_context: dict[str, Any],
    revision: int,
    saved_at: datetime,
    saved_by_membership_id: str,
) -> dict[str, Any]:
    return {
        "department": syllabus.department,
        "knowledge_area": syllabus.knowledge_area,
        "nbc": syllabus.nbc,
        "version_label": syllabus.version_label,
        "academic_load": syllabus.academic_load,
        "course_description": syllabus.course_description,
        "general_objective": syllabus.general_objective,
        "specific_objectives": list(syllabus.specific_objectives),
        "modules": [module.model_dump(mode="json") for module in syllabus.modules],
        "evaluation_strategy": [item.model_dump(mode="json") for item in syllabus.evaluation_strategy],
        "didactic_strategy": syllabus.didactic_strategy.model_dump(mode="json"),
        "integrative_project": syllabus.integrative_project,
        "bibliography": list(syllabus.bibliography),
        "teacher_notes": syllabus.teacher_notes,
        "ai_grounding_context": ai_grounding_context,
        "revision": revision,
        "saved_at": saved_at.isoformat(),
        "saved_by_membership_id": saved_by_membership_id,
    }


def save_teacher_course_syllabus(
    db: Session,
    context: TeacherContext,
    course_id: str,
    request: TeacherSyllabusSaveRequest,
) -> TeacherCourseDetailResponse:
    """
    Save pipeline
      validate request
        -> lock owned course
        -> compare expected revision
        -> derive grounding
        -> persist live syllabus
        -> append immutable snapshot
    """
    try:
        course = db.scalar(
            select(Course)
            .where(
                Course.id == course_id,
                Course.university_id == context.university_id,
                Course.teacher_membership_id == context.teacher_membership_id,
            )
            .with_for_update()
        )
        if course is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="course_not_found")

        syllabus = db.scalar(
            select(Syllabus)
            .where(Syllabus.course_id == course.id)
            .with_for_update()
        )
        current_revision = syllabus.revision if syllabus is not None else 0
        if request.expected_revision != current_revision:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="stale_syllabus_revision")

        next_revision = current_revision + 1
        saved_at = utc_now()
        grounding = derive_syllabus_grounding_context(
            course_id=course.id,
            course_title=course.title,
            academic_level=course.academic_level,
            syllabus=request.syllabus,
            revision=next_revision,
            saved_at=saved_at,
            saved_by_membership_id=context.teacher_membership_id,
        ).model_dump(mode="json")

        if syllabus is None:
            syllabus = Syllabus(
                course_id=course.id,
                revision=next_revision,
                department=request.syllabus.department,
                knowledge_area=request.syllabus.knowledge_area,
                nbc=request.syllabus.nbc,
                version_label=request.syllabus.version_label,
                academic_load=request.syllabus.academic_load,
                course_description=request.syllabus.course_description,
                general_objective=request.syllabus.general_objective,
                specific_objectives=list(request.syllabus.specific_objectives),
                modules=[module.model_dump(mode="json") for module in request.syllabus.modules],
                evaluation_strategy=[item.model_dump(mode="json") for item in request.syllabus.evaluation_strategy],
                didactic_strategy=request.syllabus.didactic_strategy.model_dump(mode="json"),
                integrative_project=request.syllabus.integrative_project,
                bibliography=list(request.syllabus.bibliography),
                teacher_notes=request.syllabus.teacher_notes,
                ai_grounding_context=grounding,
                saved_at=saved_at,
                saved_by_membership_id=context.teacher_membership_id,
            )
            db.add(syllabus)
            db.flush()
        else:
            syllabus.revision = next_revision
            syllabus.department = request.syllabus.department
            syllabus.knowledge_area = request.syllabus.knowledge_area
            syllabus.nbc = request.syllabus.nbc
            syllabus.version_label = request.syllabus.version_label
            syllabus.academic_load = request.syllabus.academic_load
            syllabus.course_description = request.syllabus.course_description
            syllabus.general_objective = request.syllabus.general_objective
            syllabus.specific_objectives = list(request.syllabus.specific_objectives)
            syllabus.modules = [module.model_dump(mode="json") for module in request.syllabus.modules]
            syllabus.evaluation_strategy = [item.model_dump(mode="json") for item in request.syllabus.evaluation_strategy]
            syllabus.didactic_strategy = request.syllabus.didactic_strategy.model_dump(mode="json")
            syllabus.integrative_project = request.syllabus.integrative_project
            syllabus.bibliography = list(request.syllabus.bibliography)
            syllabus.teacher_notes = request.syllabus.teacher_notes
            syllabus.ai_grounding_context = grounding
            syllabus.saved_at = saved_at
            syllabus.saved_by_membership_id = context.teacher_membership_id
            db.flush()

        db.add(
            SyllabusRevision(
                syllabus_id=syllabus.id,
                revision=next_revision,
                snapshot=_build_syllabus_snapshot(
                    syllabus=request.syllabus,
                    ai_grounding_context=grounding,
                    revision=next_revision,
                    saved_at=saved_at,
                    saved_by_membership_id=context.teacher_membership_id,
                ),
                saved_at=saved_at,
                saved_by_membership_id=context.teacher_membership_id,
            )
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="syllabus_save_failed",
        ) from exc

    audit_log(
        "teacher.syllabus.save",
        "success",
        university_id=context.university_id,
        membership_id=context.teacher_membership_id,
        course_id=course.id,
        revision=next_revision,
    )
    return get_teacher_course_detail(db, context, course.id)


def regenerate_teacher_course_access_link(
    db: Session,
    context: TeacherContext,
    course_id: str,
) -> CourseAccessLinkRegenerateResponse:
    course = db.scalar(
        select(Course)
        .where(
            Course.id == course_id,
            Course.university_id == context.university_id,
            Course.teacher_membership_id == context.teacher_membership_id,
        )
        .with_for_update()
    )
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="course_not_found")
    if course.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="course_inactive",
        )

    try:
        if not try_acquire_course_regeneration_lock(db, course.id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="course_link_regeneration_in_progress",
            )
        generated_link = regenerate_course_access_link(db, course.id)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="course_link_regeneration_failed",
        ) from exc

    audit_log(
        "teacher.course_link.regenerated",
        "success",
        auth_user_id=context.auth_user_id,
        university_id=context.university_id,
        membership_id=context.teacher_membership_id,
        course_id=course.id,
        link_id=generated_link.link_id,
        http_status=status.HTTP_200_OK,
    )
    return CourseAccessLinkRegenerateResponse(
        course_id=course.id,
        access_link=generated_link.access_link,
        access_link_status="active",
    )