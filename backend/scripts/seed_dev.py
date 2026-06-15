"""Idempotent local dev seed: a working university, accounts, and courses.

Recreates a known baseline so you never have to click through the UI again after
a deliberate database reset or a fresh clone. Safe to re-run: every entity is a
get-or-create / upsert, so running it twice does not duplicate anything.

It seeds two planes at once:
  - Supabase Auth (local stack on :54321): the login users, via the same admin
    client that ``scripts/provision_admin.py`` uses.
  - App DB (local Postgres on :5434): profiles, memberships, the university, and
    the courses, via the ORM.

Prerequisites (see docs/runbooks/local-dev-auth.md):
    docker compose up -d adam-edu-postgres   # app DB on 5434
    supabase start                           # auth stack on 54321
    uv run --directory backend alembic upgrade head

Usage (from the repo root):
    uv run --directory backend python scripts/seed_dev.py

Login password: set ``SEED_DEV_PASSWORD`` in backend/.env for a stable password;
otherwise a random one is generated and printed once. Seeded accounts do NOT
require a password rotation, so you can log in immediately.
"""

# ruff: noqa: T201 — this is a CLI seeder; print is the intended output channel.

from __future__ import annotations

import secrets
import string
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load backend/.env so DATABASE_URL and SUPABASE_* are available before the
# shared.* singletons are constructed on import below.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from shared.auth import (  # noqa: E402 — must follow load_dotenv above
    ensure_membership,
    ensure_profile,
    get_supabase_admin_client,
)
from shared.database import SessionLocal  # noqa: E402
from shared.models import Course, Tenant  # noqa: E402

DEV_UNIVERSITY_ID = "10000000-0000-0000-0000-000000000001"
DEV_UNIVERSITY_NAME = "ADAM Dev University"

# Stable login accounts. Dedicated @adam.local emails so the seed never collides
# with accounts you create through the normal flow.
SEED_ACCOUNTS: list[dict[str, str]] = [
    {"email": "admin.dev@adam.local", "full_name": "Admin Dev", "role": "university_admin"},
    {"email": "teacher.dev@adam.local", "full_name": "Profesor Dev", "role": "teacher"},
    {"email": "student.dev@adam.local", "full_name": "Estudiante Dev", "role": "student"},
]

# Courses owned by the seeded teacher. Idempotent on (university_id, code, semester).
SEED_COURSES: list[dict[str, object]] = [
    {"code": "ADM-101", "title": "Analitica de Negocios I", "semester": "2026-I", "academic_level": "Pregrado", "max_students": 30},
    {"code": "ADM-201", "title": "Ciencia de Datos Aplicada", "semester": "2026-I", "academic_level": "Maestría", "max_students": 25},
]


def _generate_temp_password(length: int = 20) -> str:
    """Return a cryptographically secure temporary password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _resolve_password() -> tuple[str, bool]:
    """Return (password, was_generated) honoring the SEED_DEV_PASSWORD knob."""
    import os

    configured = os.environ.get("SEED_DEV_PASSWORD", "").strip()
    if configured:
        return configured, False
    return _generate_temp_password(), True


def seed_dev() -> None:
    """Create the dev university, login accounts, and courses (idempotent)."""
    password, generated = _resolve_password()

    try:
        admin_client = get_supabase_admin_client()
    except Exception as exc:  # pragma: no cover - environment guard
        print(f"ERROR: no se pudo inicializar el cliente admin de Supabase: {exc}", file=sys.stderr)
        print("Asegurate de que `supabase start` este corriendo y SUPABASE_* este en backend/.env.", file=sys.stderr)
        sys.exit(1)

    db = SessionLocal()
    try:
        # [1] University (tenant) — get-or-create.
        tenant = db.get(Tenant, DEV_UNIVERSITY_ID)
        if tenant is None:
            tenant = Tenant(id=DEV_UNIVERSITY_ID, name=DEV_UNIVERSITY_NAME)
            db.add(tenant)
            db.flush()

        # [2] Login accounts: Supabase Auth user + profile + membership.
        teacher_membership_id: str | None = None
        created_emails: list[str] = []
        for account in SEED_ACCOUNTS:
            result = admin_client.get_or_create_user_by_email(account["email"], password)
            auth_user_id = result.user.id
            if result.created:
                created_emails.append(account["email"])

            ensure_profile(db, user_id=auth_user_id, full_name=account["full_name"])
            membership = ensure_membership(
                db,
                user_id=auth_user_id,
                university_id=DEV_UNIVERSITY_ID,
                role=account["role"],
                must_rotate_password=False,
            )
            if account["role"] == "teacher":
                teacher_membership_id = membership.id

        db.flush()

        # [3] Courses owned by the seeded teacher — get-or-create.
        if teacher_membership_id is None:  # pragma: no cover - defensive
            raise RuntimeError("seed teacher membership was not created")

        created_courses: list[str] = []
        for course_spec in SEED_COURSES:
            existing = (
                db.query(Course)
                .filter(
                    Course.university_id == DEV_UNIVERSITY_ID,
                    Course.code == course_spec["code"],
                    Course.semester == course_spec["semester"],
                )
                .first()
            )
            if existing is not None:
                continue
            db.add(
                Course(
                    university_id=DEV_UNIVERSITY_ID,
                    teacher_membership_id=teacher_membership_id,
                    title=course_spec["title"],
                    code=course_spec["code"],
                    semester=course_spec["semester"],
                    academic_level=course_spec["academic_level"],
                    max_students=course_spec["max_students"],
                    status="active",
                )
            )
            created_courses.append(str(course_spec["code"]))

        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()

    # [4] Summary. Keep output ASCII-only so it prints on Windows cp1252 consoles.
    print("\n[OK] Seed de desarrollo aplicado (idempotente).")
    print(f"  Universidad: {DEV_UNIVERSITY_NAME} ({DEV_UNIVERSITY_ID})")
    print(f"  Cuentas: {', '.join(a['email'] for a in SEED_ACCOUNTS)}")
    if created_emails:
        print(f"  Nuevas en Supabase Auth: {', '.join(created_emails)}")
    else:
        print("  Las cuentas ya existian en Supabase Auth (contrasena sin cambios).")
    if created_courses:
        print(f"  Cursos creados: {', '.join(created_courses)}")
    else:
        print("  Los cursos ya existian.")
    if generated and created_emails:
        print(f"\n  Contrasena temporal (solo para cuentas nuevas): {password}")
        print("  Para una contrasena estable, define SEED_DEV_PASSWORD en backend/.env y vuelve a correr.")


if __name__ == "__main__":
    seed_dev()
