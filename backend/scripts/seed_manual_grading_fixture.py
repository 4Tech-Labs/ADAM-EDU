#!/usr/bin/env python3
from __future__ import annotations

import argparse
import secrets
import string
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from shared.auth import ensure_course_membership, ensure_membership, ensure_profile, get_supabase_admin_client
from shared.database import SessionLocal, settings
from shared.identity_activation import upsert_legacy_user
from shared.models import Assignment, CaseGrade, Course, StudentCaseResponse, StudentCaseResponseSubmission, Tenant

FIXTURE_TENANT_ID = "10000000-0000-0000-0000-000000002219"
FIXTURE_COURSE_ID = "20000000-0000-0000-0000-000000002219"
FIXTURE_ASSIGNMENT_ID = "30000000-0000-0000-0000-000000002219"
FIXTURE_RESPONSE_ID = "40000000-0000-0000-0000-000000002219"
FIXTURE_SUBMISSION_ID = "50000000-0000-0000-0000-000000002219"
FIXTURE_CANONICAL_HASH = "hash-manual-grading-fixture"


@dataclass(slots=True)
class SeededAuthUser:
    user_id: str
    email: str
    password_to_report: str | None
    password_status: str


def _generate_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _build_answers() -> dict[str, str]:
    return {
        "M1-Q1": "La operación se frena por cuellos de botella en onboarding y soporte.",
        "M2-Q2": "La evidencia apunta a tiempos de activación inconsistentes por segmento.",
        "M3-Q3": "La causa raíz combina handoffs manuales y métricas de éxito mal alineadas.",
        "M4-Q4": "La recomendación es rediseñar el onboarding con ownership único y metas por cohorte.",
        "M5-Q5": "La implementación debe empezar por el flujo enterprise y luego escalar al resto.",
    }


def _build_canonical_output() -> dict[str, object]:
    return {
        "caseId": FIXTURE_ASSIGNMENT_ID,
        "title": "Caso Manual Grading Fixture",
        "subject": "Analítica Directiva",
        "syllabusModule": "Decisiones con datos",
        "guidingQuestion": "¿Qué cambio operativo desbloquea crecimiento sin degradar la experiencia?",
        "industry": "Tecnología",
        "academicLevel": "MBA",
        "caseType": "harvard_only",
        "studentProfile": "business",
        "generatedAt": "2026-06-01T15:00:00Z",
        "outputDepth": "standard",
        "content": {
            "instructions": "Lee el caso, revisa la evidencia y responde cada módulo.",
            "narrative": "Una empresa SaaS regional necesita estabilizar su onboarding antes de expandirse.",
            "caseQuestions": [
                {
                    "numero": 1,
                    "titulo": "Diagnóstico inicial",
                    "enunciado": "Describe el principal bloqueo operativo.",
                    "solucion_esperada": "Reconoce el cuello de botella entre ventas, onboarding y soporte.",
                }
            ],
            "edaQuestions": [
                {
                    "numero": 2,
                    "titulo": "Lectura de evidencia",
                    "enunciado": "Interpreta la señal más crítica de los datos disponibles.",
                    "solucion_esperada": "Identifica la variabilidad del tiempo a valor por segmento.",
                }
            ],
            "m3Questions": [
                {
                    "numero": 3,
                    "titulo": "Causa raíz",
                    "enunciado": "Explica la causa raíz del problema.",
                    "solucion_esperada": "Atribuye el problema a handoffs manuales y ownership difuso.",
                }
            ],
            "m4Questions": [
                {
                    "numero": 4,
                    "titulo": "Recomendación",
                    "enunciado": "Propón una recomendación priorizada.",
                    "solucion_esperada": "Plantea un rediseño del onboarding con KPIs de activación.",
                }
            ],
            "m5Questions": [
                {
                    "numero": 5,
                    "titulo": "Memo ejecutivo",
                    "enunciado": "Redacta un memo ejecutivo final.",
                    "solucion_esperada": "Sintetiza recomendación, riesgos y secuencia de ejecución.",
                }
            ],
            "m4Content": "Evalúa impactos de negocio y riesgos de ejecución.",
            "m5Content": "Cierra con una recomendación ejecutiva clara.",
            "teachingNote": "La revisión docente debe enfatizar coherencia entre diagnóstico, evidencia y recomendación.",
        },
    }


def _seed_auth_user(*, email: str, password: str | None) -> SeededAuthUser:
    admin_client = get_supabase_admin_client()
    password_to_apply = password or _generate_password()
    result = admin_client.get_or_create_user_by_email(email, password_to_apply)

    if result.created:
        return SeededAuthUser(
            user_id=result.user.id,
            email=email,
            password_to_report=password_to_apply,
            password_status="created",
        )

    if password is not None:
        admin_client.update_user_password(result.user.id, password)
        return SeededAuthUser(
            user_id=result.user.id,
            email=email,
            password_to_report=password,
            password_status="updated",
        )

    return SeededAuthUser(
        user_id=result.user.id,
        email=email,
        password_to_report=None,
        password_status="reused",
    )


def _upsert_tenant(db, *, name: str) -> Tenant:
    tenant = db.get(Tenant, FIXTURE_TENANT_ID)
    if tenant is None:
        tenant = Tenant(id=FIXTURE_TENANT_ID, name=name)
        db.add(tenant)
        db.flush()
        return tenant

    tenant.name = name
    db.flush()
    return tenant


def _upsert_course(db, *, title: str, code: str, teacher_membership_id: str) -> Course:
    course = db.get(Course, FIXTURE_COURSE_ID)
    if course is None:
        course = Course(
            id=FIXTURE_COURSE_ID,
            university_id=FIXTURE_TENANT_ID,
            teacher_membership_id=teacher_membership_id,
            pending_teacher_invite_id=None,
            title=title,
            code=code,
            semester="2026-I",
            academic_level="MBA",
            max_students=30,
            status="active",
        )
        db.add(course)
        db.flush()
        return course

    course.university_id = FIXTURE_TENANT_ID
    course.teacher_membership_id = teacher_membership_id
    course.pending_teacher_invite_id = None
    course.title = title
    course.code = code
    course.semester = "2026-I"
    course.academic_level = "MBA"
    course.max_students = 30
    course.status = "active"
    db.flush()
    return course


def _upsert_assignment(db, *, teacher_user_id: str, course_id: str, title: str) -> Assignment:
    now = datetime.now(timezone.utc)
    assignment = db.get(Assignment, FIXTURE_ASSIGNMENT_ID)
    if assignment is None:
        assignment = Assignment(
            id=FIXTURE_ASSIGNMENT_ID,
            teacher_id=teacher_user_id,
            course_id=course_id,
            title=title,
            canonical_output=_build_canonical_output(),
            status="published",
            available_from=now - timedelta(days=2),
            deadline=now + timedelta(days=6),
            weight_per_module={"M1": 0.2, "M2": 0.2, "M3": 0.2, "M4": 0.2, "M5": 0.2},
        )
        db.add(assignment)
        db.flush()
        return assignment

    assignment.teacher_id = teacher_user_id
    assignment.course_id = course_id
    assignment.title = title
    assignment.canonical_output = _build_canonical_output()
    assignment.status = "published"
    assignment.available_from = now - timedelta(days=2)
    assignment.deadline = now + timedelta(days=6)
    assignment.weight_per_module = {"M1": 0.2, "M2": 0.2, "M3": 0.2, "M4": 0.2, "M5": 0.2}
    db.flush()
    return assignment


def _upsert_response(db, *, membership_id: str, assignment_id: str) -> StudentCaseResponse:
    now = datetime.now(timezone.utc)
    response = db.get(StudentCaseResponse, FIXTURE_RESPONSE_ID)
    answers = _build_answers()
    if response is None:
        response = StudentCaseResponse(
            id=FIXTURE_RESPONSE_ID,
            membership_id=membership_id,
            assignment_id=assignment_id,
            answers=answers,
            status="submitted",
            version=1,
            first_opened_at=now - timedelta(hours=4),
            last_autosaved_at=now - timedelta(hours=3),
            submitted_at=now - timedelta(hours=2),
        )
        db.add(response)
        db.flush()
        return response

    response.membership_id = membership_id
    response.assignment_id = assignment_id
    response.answers = answers
    response.status = "submitted"
    response.version = 1
    response.first_opened_at = now - timedelta(hours=4)
    response.last_autosaved_at = now - timedelta(hours=3)
    response.submitted_at = now - timedelta(hours=2)
    db.flush()
    return response


def _upsert_submission_snapshot(db, *, response_id: str, submitted_at: datetime) -> StudentCaseResponseSubmission:
    snapshot = db.get(StudentCaseResponseSubmission, FIXTURE_SUBMISSION_ID)
    answers = _build_answers()
    if snapshot is None:
        snapshot = StudentCaseResponseSubmission(
            id=FIXTURE_SUBMISSION_ID,
            response_id=response_id,
            answers_snapshot=answers,
            submitted_at=submitted_at,
            canonical_output_hash=FIXTURE_CANONICAL_HASH,
        )
        db.add(snapshot)
        db.flush()
        return snapshot

    snapshot.response_id = response_id
    snapshot.answers_snapshot = answers
    snapshot.submitted_at = submitted_at
    snapshot.canonical_output_hash = FIXTURE_CANONICAL_HASH
    db.flush()
    return snapshot


def _reset_existing_grade(db, *, membership_id: str, assignment_id: str) -> None:
    existing_grade = db.scalar(
        select(CaseGrade).where(
            CaseGrade.membership_id == membership_id,
            CaseGrade.assignment_id == assignment_id,
        )
    )
    if existing_grade is not None:
        db.delete(existing_grade)
        db.flush()


def seed_manual_grading_fixture(args: argparse.Namespace) -> None:
    db = SessionLocal()
    try:
        tenant = _upsert_tenant(db, name=args.university_name)

        teacher_auth = _seed_auth_user(email=args.teacher_email, password=args.teacher_password)
        student_auth = _seed_auth_user(email=args.student_email, password=args.student_password)

        ensure_profile(db, user_id=teacher_auth.user_id, full_name=args.teacher_full_name)
        teacher_membership = ensure_membership(
            db,
            user_id=teacher_auth.user_id,
            university_id=tenant.id,
            role="teacher",
            must_rotate_password=False,
        )
        upsert_legacy_user(
            db,
            auth_user_id=teacher_auth.user_id,
            university_id=tenant.id,
            email=teacher_auth.email,
            role="teacher",
        )

        ensure_profile(db, user_id=student_auth.user_id, full_name=args.student_full_name)
        student_membership = ensure_membership(
            db,
            user_id=student_auth.user_id,
            university_id=tenant.id,
            role="student",
            must_rotate_password=False,
        )
        upsert_legacy_user(
            db,
            auth_user_id=student_auth.user_id,
            university_id=tenant.id,
            email=student_auth.email,
            role="student",
        )

        course = _upsert_course(
            db,
            title=args.course_title,
            code=args.course_code,
            teacher_membership_id=teacher_membership.id,
        )
        ensure_course_membership(db, course_id=course.id, membership_id=student_membership.id)

        assignment = _upsert_assignment(
            db,
            teacher_user_id=teacher_auth.user_id,
            course_id=course.id,
            title=args.assignment_title,
        )
        response = _upsert_response(
            db,
            membership_id=student_membership.id,
            assignment_id=assignment.id,
        )
        _upsert_submission_snapshot(
            db,
            response_id=response.id,
            submitted_at=response.submitted_at or datetime.now(timezone.utc),
        )
        _reset_existing_grade(
            db,
            membership_id=student_membership.id,
            assignment_id=assignment.id,
        )

        db.commit()

        print("Manual grading fixture ready.")
        print(f"  University: {tenant.name} ({tenant.id})")
        print(f"  Course: {course.title} [{course.code}] ({course.id})")
        print(f"  Assignment: {assignment.title} ({assignment.id})")
        print(f"  Student membership: {student_membership.id}")
        print(f"  Teacher login: http://localhost:5173/app/teacher/login")
        print(f"  Teacher submissions list: http://localhost:5173/app/teacher/cases/{assignment.id}/entregas")
        print(f"  Teacher submission detail: http://localhost:5173/app/teacher/cases/{assignment.id}/entregas/{student_membership.id}")
        print(f"  Student email: {student_auth.email}")
        if student_auth.password_to_report:
            print(f"  Student password ({student_auth.password_status}): {student_auth.password_to_report}")
        else:
            print("  Student password: unchanged (account reused without --student-password)")
        print(f"  Teacher email: {teacher_auth.email}")
        if teacher_auth.password_to_report:
            print(f"  Teacher password ({teacher_auth.password_status}): {teacher_auth.password_to_report}")
        else:
            print("  Teacher password: unchanged (account reused without --teacher-password)")
        if not settings.teacher_manual_grading_enabled:
            print("  WARNING: TEACHER_MANUAL_GRADING_ENABLED is false in backend/.env; enable it before opening the grading UI.")
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed a reproducible local manual grading fixture.")
    parser.add_argument("--teacher-email", default="teacher.manual-grading@example.edu")
    parser.add_argument("--teacher-full-name", default="Teacher Manual Grading")
    parser.add_argument("--teacher-password")
    parser.add_argument("--student-email", default="student.manual-grading@example.edu")
    parser.add_argument("--student-full-name", default="Student Manual Grading")
    parser.add_argument("--student-password")
    parser.add_argument("--university-name", default="Universidad Manual Grading Local")
    parser.add_argument("--course-title", default="Curso Fixture Manual Grading")
    parser.add_argument("--course-code", default="MG-219")
    parser.add_argument("--assignment-title", default="Caso Fixture Manual Grading")
    return parser


def main() -> None:
    seed_manual_grading_fixture(build_parser().parse_args())


if __name__ == "__main__":
    main()