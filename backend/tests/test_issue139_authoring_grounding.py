from __future__ import annotations

import asyncio
import uuid
from unittest.mock import patch

from case_generator.core.authoring import AuthoringService
from shared.models import Assignment, AuthoringJob


def _auth_headers(auth_headers_factory, *, user_id: str, email: str) -> dict[str, str]:
    return auth_headers_factory(sub=user_id, email=email)


def _build_authoring_payload(*, course_id: str, syllabus_module: str = "m1", topic_unit: str = "u1") -> dict[str, object]:
    return {
        "assignment_title": "Issue 139 Case",
        "course_id": course_id,
        "syllabus_module": syllabus_module,
        "topic_unit": topic_unit,
        "target_groups": ["Grupo 01"],
        "scenario_description": "Escenario de prueba",
        "guiding_question": "Pregunta de prueba",
    }


def test_issue139_authoring_intake_rejects_course_without_syllabus(
    client,
    db,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-no-syllabus@example.edu"
    teacher = seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    course = seed_course(
        university_id=teacher["membership"].university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Course Without Syllabus",
    )
    db.commit()

    with patch("fastapi.BackgroundTasks.add_task"):
        response = client.post(
            "/api/authoring/jobs",
            json=_build_authoring_payload(course_id=course.id),
            headers=_auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email),
        )

    assert response.status_code == 412
    assert response.json()["detail"] == "Syllabus no configurado para este curso"


def test_issue139_authoring_intake_rejects_foreign_course(
    client,
    db,
    seed_identity,
    seed_course_with_syllabus,
    auth_headers_factory,
) -> None:
    requester_id = str(uuid.uuid4())
    requester_email = "teacher-requester@example.edu"
    requester = seed_identity(user_id=requester_id, email=requester_email, role="teacher")

    owner_id = str(uuid.uuid4())
    owner_email = "teacher-owner@example.edu"
    owner = seed_identity(user_id=owner_id, email=owner_email, role="teacher")
    foreign_course = seed_course_with_syllabus(
        university_id=owner["membership"].university_id,
        teacher_membership_id=owner["membership"].id,
        title="Foreign Course",
    )
    db.commit()

    with patch("fastapi.BackgroundTasks.add_task"):
        response = client.post(
            "/api/authoring/jobs",
            json=_build_authoring_payload(course_id=foreign_course.id),
            headers=_auth_headers(auth_headers_factory, user_id=requester_id, email=requester_email),
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "course_not_found"


def test_issue139_authoring_intake_rejects_invalid_syllabus_selection(
    client,
    db,
    seed_identity,
    seed_course_with_syllabus,
    auth_headers_factory,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-invalid-selection@example.edu"
    teacher = seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    course = seed_course_with_syllabus(
        university_id=teacher["membership"].university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Invalid Selection Course",
    )
    db.commit()

    with patch("fastapi.BackgroundTasks.add_task"):
        response = client.post(
            "/api/authoring/jobs",
            json=_build_authoring_payload(course_id=course.id, syllabus_module="bogus-module"),
            headers=_auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email),
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "Seleccion invalida de modulo o unidad del syllabus"


def test_issue139_authoring_intake_rejects_client_grounding_injection(
    client,
    db,
    seed_identity,
    seed_course_with_syllabus,
    auth_headers_factory,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-grounding-injection@example.edu"
    teacher = seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    course = seed_course_with_syllabus(
        university_id=teacher["membership"].university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Grounding Injection Course",
    )
    db.commit()

    payload = _build_authoring_payload(course_id=course.id)
    payload["ai_grounding_context"] = {"forged": True}

    with patch("fastapi.BackgroundTasks.add_task"):
        response = client.post(
            "/api/authoring/jobs",
            json=payload,
            headers=_auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email),
        )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert any(item.get("loc") == ["body", "ai_grounding_context"] for item in detail)


def test_issue139_authoring_runtime_fails_closed_on_invalid_persisted_selection(
    db,
    seed_identity,
    seed_course_with_syllabus,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-runtime-invalid-selection@example.edu"
    teacher = seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    course = seed_course_with_syllabus(
        university_id=teacher["membership"].university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Runtime Invalid Selection Course",
    )

    assignment = Assignment(
        teacher_id=teacher_id,
        course_id=course.id,
        title="Runtime Invalid Selection",
        status="draft",
    )
    db.add(assignment)
    db.flush()

    job = AuthoringJob(
        assignment_id=assignment.id,
        idempotency_key=f"job-{uuid.uuid4()}",
        status="pending",
        task_payload={
            "step": "authoring",
            "course_id": course.id,
            "syllabus_revision": 1,
            "syllabus_module_id": "bogus-module",
            "topic_unit_id": "u1",
            "asignatura": course.title,
            "nivel": course.academic_level,
        },
    )
    db.add(job)
    db.commit()

    with patch("case_generator.core.authoring.get_storage_provider", return_value=object()):
        asyncio.run(AuthoringService.run_job(job.id))

    db.expire_all()
    refreshed = db.get(AuthoringJob, job.id)
    assert refreshed is not None
    payload = dict(refreshed.task_payload or {})
    assert refreshed.status == "failed"
    assert payload.get("error_code") == "syllabus_grounding_unavailable"
    assert "modulo o la unidad seleccionados" in str(payload.get("error_trace", ""))