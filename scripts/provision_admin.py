#!/usr/bin/env python3
"""
provision_admin.py — Aprovisionamiento CLI de administrador universitario.

Uso:
    python scripts/provision_admin.py \\
        --email admin@universidad.edu \\
        --university-id <uuid> \\
        --full-name "Ana García"

Reglas de seguridad:
- Service Role key leída del entorno (.env) — nunca de args CLI.
- Contraseña temporal impresa en stdout UNA sola vez (solo para usuario nuevo).
- Sin endpoint HTTP — este script es el único punto de aprovisionamiento.
- El admin DEBE cambiar contraseña en el primer login (must_rotate_password=True).
"""
from __future__ import annotations

import argparse
import secrets
import string
import sys
from pathlib import Path

# Agregar backend/src al path para imports del proyecto
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / "backend" / ".env")

from shared.auth import (
    audit_event,
    ensure_membership,
    ensure_profile,
    get_supabase_admin_client,
)
from shared.database import SessionLocal
from shared.models import Tenant


def _generate_temp_password(length: int = 20) -> str:
    """Generate a cryptographically secure temporary password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def provision_admin(email: str, university_id: str, full_name: str) -> None:
    """Provision a university_admin account.

    Steps:
      [1] Validate the university exists in tenants — fail before touching Auth
      [2] get_or_create_user_by_email in Supabase Auth
      [3] ensure_profile + ensure_membership(must_rotate_password=True)
      [4] commit + audit
    """
    db = SessionLocal()
    try:
        # [1] Validate university exists — fail-fast before creating Auth user
        tenant = db.query(Tenant).filter(Tenant.id == university_id).first()
        if tenant is None:
            print(
                f"ERROR: No se encontró la universidad con id '{university_id}'.",
                file=sys.stderr,
            )
            sys.exit(1)

        # [2] Create or reuse Supabase Auth user
        admin_client = get_supabase_admin_client()
        temp_password = _generate_temp_password()
        result = admin_client.get_or_create_user_by_email(email, temp_password)
        auth_user_id = result.user.id

        # [3] Ensure Profile and Membership exist
        ensure_profile(db, user_id=auth_user_id, full_name=full_name)
        ensure_membership(
            db,
            user_id=auth_user_id,
            university_id=university_id,
            role="university_admin",
            must_rotate_password=True,
        )
        db.commit()

        # [4] Audit
        audit_event("admin.provision", outcome="success", auth_user_id=auth_user_id)

        if result.created:
            print(f"✓ Cuenta de administrador creada: {email}")
            print(f"  Universidad: {tenant.name} ({university_id})")
            print(f"\n  Contraseña temporal: {temp_password}")
            print(
                "\n  IMPORTANTE: Comunica esta contraseña al administrador por un canal"
                " seguro fuera de banda. No se mostrará de nuevo."
            )
        else:
            print(f"✓ El usuario ya existía en Supabase Auth: {email}")
            print(f"  Membresía university_admin actualizada (must_rotate_password=True).")
            print(
                "  NOTA: La contraseña NO fue modificada."
                " Usa el dashboard de Supabase para resetearla si es necesario."
            )

    except SystemExit:
        raise
    except Exception as exc:
        db.rollback()
        audit_event("admin.provision", outcome="error", reason=str(exc))
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Provisionar administrador universitario (CLI-only, sin endpoint HTTP)"
    )
    parser.add_argument("--email", required=True, help="Email del administrador")
    parser.add_argument(
        "--university-id",
        required=True,
        dest="university_id",
        help="UUID de la universidad (tenants.id)",
    )
    parser.add_argument("--full-name", required=True, dest="full_name", help="Nombre completo del administrador")
    args = parser.parse_args()

    provision_admin(
        email=args.email,
        university_id=args.university_id,
        full_name=args.full_name,
    )


if __name__ == "__main__":
    main()
