from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import hmac
import logging
from pathlib import Path
from typing import Any

import httpx
import jwt
from jwt import PyJWKClient
from jwt.exceptions import InvalidTokenError, PyJWKClientError
from fastapi import Depends, Header
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from supabase import Client, create_client

from shared.database import get_db
from shared.models import CourseMembership, Invite, Membership, Profile, User

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
AUTH_AUDIENCE = "authenticated"
_JWKS_ALGORITHMS = frozenset({"RS256", "ES256"})
PRIMARY_ROLE_ORDER = {"university_admin": 0, "teacher": 1, "student": 2}

logger = logging.getLogger(__name__)


class AuthError(Exception):
    def __init__(self, status_code: int, code: str) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code


class AuthSettings(BaseSettings):
    environment: str = "development"
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""
    auth_jwks_ttl_seconds: int = 300
    auth_http_timeout_seconds: float = 3.0

    model_config = SettingsConfigDict(env_file=str(ENV_FILE), env_file_encoding="utf-8", extra="ignore")

    @property
    def issuer(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1"

    @property
    def jwks_url(self) -> str:
        return f"{self.issuer}/.well-known/jwks.json"

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def can_use_local_secret_fallback(self) -> bool:
        return self.environment.lower() == "development" and bool(self.supabase_jwt_secret)


@dataclass(slots=True)
class MembershipSnapshot:
    id: str
    university_id: str
    role: str
    status: str
    must_rotate_password: bool
    created_at: datetime


@dataclass(slots=True)
class ProfileSnapshot:
    id: str
    full_name: str


@dataclass(slots=True)
class VerifiedToken:
    auth_user_id: str
    email: str | None
    claims: dict[str, Any]


VerifiedIdentity = VerifiedToken


@dataclass(slots=True)
class CurrentActor:
    """
    Actor resolved from JWT + DB.

    `primary_role` is a UX/debugging convenience only. Multi-university logic must
    use the full memberships array. Future endpoints such as
    POST /api/auth/change-password depend on this actor carrying
    `must_rotate_password` and reusing the same auth dependency path.
    """

    auth_user_id: str
    profile_id: str
    profile: ProfileSnapshot
    memberships: list[MembershipSnapshot]
    must_rotate_password: bool
    primary_role: str | None
    email: str | None

    @property
    def active_memberships(self) -> list[MembershipSnapshot]:
        return [membership for membership in self.memberships if membership.status == "active"]

    def has_active_role(self, role: str) -> bool:
        return any(membership.role == role for membership in self.active_memberships)


@dataclass(slots=True)
class AdminAuthUser:
    id: str
    email: str | None


@dataclass(slots=True)
class AdminUserResult:
    user: AdminAuthUser
    created: bool


@dataclass(slots=True)
class InviteResolution:
    invite: Invite
    token_hash: str


@dataclass(slots=True)
class ActivationResult:
    status: str
    auth_user_id: str


@lru_cache
def get_auth_settings() -> AuthSettings:
    return AuthSettings()


def hash_invite_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_email(email: str | None) -> str | None:
    if email is None:
        return None
    normalized = email.strip().lower()
    return normalized or None


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    if not domain:
        return "***"
    if len(local) <= 2:
        masked_local = f"{local[:1]}***"
    else:
        masked_local = f"{local[:2]}***"
    return f"{masked_local}@{domain}"


def email_equals(left: str | None, right: str | None) -> bool:
    left_normalized = normalize_email(left)
    right_normalized = normalize_email(right)
    if left_normalized is None or right_normalized is None:
        return False
    return hmac.compare_digest(left_normalized, right_normalized)


def audit_event(
    event: str,
    *,
    outcome: str,
    auth_user_id: str | None = None,
    invite_id: str | None = None,
    invite_hash_prefix: str | None = None,
    job_id: str | None = None,
    assignment_id: str | None = None,
    http_status: int | None = None,
    reason: str | None = None,
) -> None:
    payload = {
        "event": event,
        "outcome": outcome,
        "auth_user_id": auth_user_id,
        "invite_id": invite_id,
        "invite_hash_prefix": invite_hash_prefix,
        "job_id": job_id,
        "assignment_id": assignment_id,
        "http_status": http_status,
        "reason": reason,
    }
    logger.info("audit_event", extra={"audit_event": payload})


def audit_log(event: str, outcome: str, **fields: Any) -> None:
    audit_event(
        event,
        outcome=outcome,
        auth_user_id=fields.get("auth_user_id"),
        invite_id=fields.get("invite_id"),
        invite_hash_prefix=fields.get("invite_hash_prefix"),
        job_id=fields.get("job_id"),
        assignment_id=fields.get("assignment_id"),
        http_status=fields.get("http_status"),
        reason=fields.get("reason"),
    )


def _coerce_datetime(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    return value


def _primary_role(memberships: list[MembershipSnapshot]) -> str | None:
    if not memberships:
        return None
    ordered = sorted(
        memberships,
        key=lambda membership: (
            PRIMARY_ROLE_ORDER.get(membership.role, 99),
            _coerce_datetime(membership.created_at),
            membership.id,
        ),
    )
    return ordered[0].role


class JwtVerifier:
    def __init__(self, settings: AuthSettings) -> None:
        self.settings = settings
        self._jwks_client = PyJWKClient(
            self.settings.jwks_url,
            cache_jwk_set=True,
            lifespan=self.settings.auth_jwks_ttl_seconds,
            timeout=self.settings.auth_http_timeout_seconds,
        )

    def verify_token(self, token: str) -> VerifiedToken:
        try:
            header = jwt.get_unverified_header(token)
        except InvalidTokenError as exc:
            raise AuthError(401, "invalid_token") from exc

        algorithm = header.get("alg")
        kid = header.get("kid")
        logger.warning("[AUTH_DEBUG] JWT header: alg=%s kid=%s can_local_fallback=%s", algorithm, kid, self.settings.can_use_local_secret_fallback)
        try:
            if algorithm == "HS256" and self.settings.can_use_local_secret_fallback:
                claims = self._decode_with_secret(token)
            else:
                claims = self._decode_with_jwks(token, header)
        except AuthError as exc:
            logger.warning("[AUTH_DEBUG] JWT verification FAILED: %s", exc.code)
            raise

        auth_user_id = claims.get("sub")
        if not auth_user_id:
            raise AuthError(401, "invalid_token")

        return VerifiedToken(auth_user_id=auth_user_id, email=claims.get("email"), claims=claims)

    def _decode_with_secret(self, token: str) -> dict[str, Any]:
        try:
            return jwt.decode(
                token,
                self.settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience=AUTH_AUDIENCE,
                issuer=self.settings.issuer,
            )
        except InvalidTokenError as exc:
            raise AuthError(401, "invalid_token") from exc

    def _decode_with_jwks(self, token: str, header: dict[str, Any]) -> dict[str, Any]:
        kid = header.get("kid")
        algorithm = header.get("alg")
        if not kid or algorithm not in _JWKS_ALGORITHMS:
            raise AuthError(401, "invalid_token")

        try:
            signing_key = self._jwks_client.get_signing_key(kid)
        except (PyJWKClientError, httpx.HTTPError):
            try:
                self._jwks_client.get_signing_keys(refresh=True)
                signing_key = self._jwks_client.get_signing_key(kid)
            except (PyJWKClientError, httpx.HTTPError) as refresh_exc:
                raise AuthError(401, "invalid_token") from refresh_exc
        except Exception as exc:  # pragma: no cover
            raise AuthError(401, "invalid_token") from exc

        try:
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=list(_JWKS_ALGORITHMS),
                audience=AUTH_AUDIENCE,
                issuer=self.settings.issuer,
                leeway=timedelta(seconds=30),
            )
        except InvalidTokenError as exc:
            raise AuthError(401, "invalid_token") from exc


@lru_cache
def get_auth_verifier() -> JwtVerifier:
    return JwtVerifier(get_auth_settings())


@lru_cache
def get_jwt_verifier() -> JwtVerifier:
    return get_auth_verifier()


class SupabaseAdminAuthClient:
    def __init__(self, settings: AuthSettings) -> None:
        self._settings = settings
        self._client: Client | None = None

    @property
    def client(self) -> Client:
        if self._client is None:
            if not self._settings.supabase_url or not self._settings.supabase_service_role_key:
                raise RuntimeError("Supabase admin client is not configured")
            self._client = create_client(self._settings.supabase_url, self._settings.supabase_service_role_key)
        return self._client

    def get_user_by_email(self, email: str) -> AdminAuthUser | None:
        admin = getattr(self.client.auth, "admin", None)
        if admin is None:
            raise RuntimeError("Supabase admin API is unavailable")

        page = 1
        per_page = 200
        while True:
            response = admin.list_users(page=page, per_page=per_page)
            users = self._extract_users(response)
            for user in users:
                if email_equals(user.email, email):
                    return user
            if len(users) < per_page:
                break
            page += 1
        return None

    def get_or_create_user_by_email(self, email: str, password: str) -> AdminUserResult:
        existing = self.get_user_by_email(email)
        if existing is not None:
            return AdminUserResult(user=existing, created=False)

        admin = getattr(self.client.auth, "admin", None)
        if admin is None:
            raise RuntimeError("Supabase admin API is unavailable")

        response = admin.create_user({"email": email, "password": password, "email_confirm": True})
        user = self._extract_single_user(response)
        return AdminUserResult(user=user, created=True)

    def find_user_by_email(self, email: str) -> AdminAuthUser | None:
        return self.get_user_by_email(email)

    def create_password_user(self, email: str, password: str) -> AdminAuthUser:
        return self.get_or_create_user_by_email(email, password).user

    def get_user_by_id(self, user_id: str) -> AdminAuthUser | None:
        admin = getattr(self.client.auth, "admin", None)
        if admin is None:
            raise RuntimeError("Supabase admin API is unavailable")
        response = admin.get_user_by_id(user_id)
        return self._extract_single_user(response)

    def delete_user(self, user_id: str) -> None:
        admin = getattr(self.client.auth, "admin", None)
        if admin is None:
            raise RuntimeError("Supabase admin API is unavailable")
        admin.delete_user(user_id)

    def update_user_password(self, user_id: str, new_password: str) -> None:
        """Update the Auth password for an existing user via Service Role key.

        FAIL-CLOSED CONTRACT: This must be called BEFORE clearing must_rotate_password
        in the DB. If this raises, the DB flag must NOT be modified.
        """
        admin = getattr(self.client.auth, "admin", None)
        if admin is None:
            raise RuntimeError("Supabase admin API is unavailable")
        admin.update_user_by_id(user_id, {"password": new_password})

    @staticmethod
    def _extract_users(response: Any) -> list[AdminAuthUser]:
        payload = response
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump()
        elif hasattr(payload, "dict"):
            payload = payload.dict()

        if isinstance(payload, list):
            raw_users = payload
        elif isinstance(payload, dict):
            raw_users = payload.get("users") or payload.get("data") or []
        else:
            raw_users = getattr(payload, "users", None) or getattr(payload, "data", None) or []

        return [SupabaseAdminAuthClient._normalize_user(raw_user) for raw_user in raw_users]

    @staticmethod
    def _extract_single_user(response: Any) -> AdminAuthUser:
        payload = response
        if hasattr(payload, "user"):
            return SupabaseAdminAuthClient._normalize_user(payload.user)
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump()
        elif hasattr(payload, "dict"):
            payload = payload.dict()
        if isinstance(payload, dict) and "user" in payload:
            return SupabaseAdminAuthClient._normalize_user(payload["user"])
        return SupabaseAdminAuthClient._normalize_user(payload)

    @staticmethod
    def _normalize_user(raw_user: Any) -> AdminAuthUser:
        payload = raw_user
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump()
        elif hasattr(payload, "dict"):
            payload = payload.dict()
        if isinstance(payload, dict):
            return AdminAuthUser(id=payload["id"], email=payload.get("email"))
        return AdminAuthUser(id=getattr(payload, "id"), email=getattr(payload, "email", None))


@lru_cache
def get_supabase_admin_client() -> SupabaseAdminAuthClient:
    return SupabaseAdminAuthClient(get_auth_settings())


@lru_cache
def get_supabase_admin_auth_client() -> SupabaseAdminAuthClient:
    return get_supabase_admin_client()


def get_verified_token(authorization: str | None) -> VerifiedToken:
    if authorization is None or not authorization.startswith("Bearer "):
        raise AuthError(401, "invalid_token")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise AuthError(401, "invalid_token")
    return get_auth_verifier().verify_token(token)


def require_verified_identity(authorization: str | None = Header(None)) -> VerifiedToken:
    return get_verified_token(authorization)


def resolve_current_actor(db: Session, verified_token: VerifiedToken) -> CurrentActor:
    profile = (
        db.query(Profile)
        .options(joinedload(Profile.memberships))
        .filter(Profile.id == verified_token.auth_user_id)
        .first()
    )
    if profile is None:
        raise AuthError(403, "profile_incomplete")

    memberships = [
        MembershipSnapshot(
            id=membership.id,
            university_id=membership.university_id,
            role=membership.role,
            status=membership.status,
            must_rotate_password=membership.must_rotate_password,
            created_at=_coerce_datetime(membership.created_at),
        )
        for membership in profile.memberships
    ]
    active_memberships = [membership for membership in memberships if membership.status == "active"]
    if not active_memberships:
        if memberships and all(membership.status == "suspended" for membership in memberships):
            raise AuthError(403, "account_suspended")
        raise AuthError(403, "membership_required")

    return CurrentActor(
        auth_user_id=verified_token.auth_user_id,
        profile_id=profile.id,
        profile=ProfileSnapshot(id=profile.id, full_name=profile.full_name),
        memberships=memberships,
        must_rotate_password=any(membership.must_rotate_password for membership in active_memberships),
        primary_role=_primary_role(active_memberships),
        email=normalize_email(verified_token.email),
    )


def require_current_actor(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> CurrentActor:
    return resolve_current_actor(db, get_verified_token(authorization))


def require_teacher_actor(actor: CurrentActor = Depends(require_current_actor)) -> CurrentActor:
    if not actor.has_active_role("teacher"):
        audit_event(
            "authoring.access_denied",
            outcome="denied",
            auth_user_id=actor.auth_user_id,
            http_status=403,
            reason="authoring_forbidden",
        )
        raise AuthError(403, "authoring_forbidden")
    return actor


def ensure_legacy_teacher_bridge(db: Session, actor: CurrentActor) -> User:
    legacy_user = db.query(User).filter(User.id == actor.auth_user_id).first()
    if legacy_user is None or legacy_user.role != "teacher":
        audit_event(
            "legacy_bridge_missing",
            outcome="error",
            auth_user_id=actor.auth_user_id,
            http_status=500,
            reason="legacy_bridge_missing",
        )
        raise AuthError(500, "legacy_bridge_missing")
    return legacy_user


def resolve_invite_by_token(db: Session, invite_token: str) -> InviteResolution:
    token_hash = hash_invite_token(invite_token)
    invite = db.query(Invite).filter(Invite.token_hash == token_hash).first()
    if invite is None or not hmac.compare_digest(invite.token_hash, token_hash):
        raise AuthError(404, "invite_invalid")
    return InviteResolution(invite=invite, token_hash=token_hash)


def validate_pending_invite(invite: Invite) -> None:
    expires_at = _coerce_datetime(invite.expires_at)
    if invite.status != "pending":
        if invite.status == "expired" or expires_at <= datetime.now(timezone.utc):
            raise AuthError(410, "invite_expired")
        raise AuthError(404, "invite_invalid")
    if expires_at <= datetime.now(timezone.utc):
        raise AuthError(410, "invite_expired")


def consume_invite(db: Session, invite: Invite) -> bool:
    now = datetime.now(timezone.utc)
    result = db.execute(
        update(Invite)
        .where(Invite.id == invite.id, Invite.status == "pending")
        .values(status="consumed", consumed_at=now)
        .returning(Invite.id)
    )
    return result.scalar_one_or_none() is not None


def ensure_profile(db: Session, *, user_id: str, full_name: str) -> Profile:
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    if profile is None:
        profile = Profile(id=user_id, full_name=full_name)
        db.add(profile)
        db.flush()
        return profile
    profile.full_name = full_name
    db.flush()
    return profile


def ensure_membership(
    db: Session,
    *,
    user_id: str,
    university_id: str,
    role: str,
    must_rotate_password: bool = False,
) -> Membership:
    membership = (
        db.query(Membership)
        .filter(
            Membership.user_id == user_id,
            Membership.university_id == university_id,
            Membership.role == role,
        )
        .first()
    )
    if membership is None:
        membership = Membership(
            user_id=user_id,
            university_id=university_id,
            role=role,
            status="active",
            must_rotate_password=must_rotate_password,
        )
        db.add(membership)
        db.flush()
        return membership

    membership.status = "active"
    membership.must_rotate_password = must_rotate_password
    db.flush()
    return membership


def ensure_course_membership(db: Session, *, course_id: str, membership_id: str) -> tuple[CourseMembership, bool]:
    existing = (
        db.query(CourseMembership)
        .filter(CourseMembership.course_id == course_id, CourseMembership.membership_id == membership_id)
        .first()
    )
    if existing is not None:
        return existing, False

    enrollment = CourseMembership(course_id=course_id, membership_id=membership_id)
    db.add(enrollment)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(CourseMembership)
            .filter(CourseMembership.course_id == course_id, CourseMembership.membership_id == membership_id)
            .first()
        )
        if existing is None:  # pragma: no cover
            raise
        return existing, False
    return enrollment, True


def find_student_membership(actor: CurrentActor, university_id: str) -> MembershipSnapshot:
    for membership in actor.active_memberships:
        if membership.role == "student" and membership.university_id == university_id:
            return membership
    raise AuthError(403, "redeem_forbidden")


def activation_is_idempotent(
    db: Session,
    admin_client: SupabaseAdminAuthClient,
    invite: Invite,
) -> ActivationResult | None:
    auth_user = admin_client.get_user_by_email(invite.email)
    if auth_user is None:
        return None

    profile = db.query(Profile).filter(Profile.id == auth_user.id).first()
    if profile is None:
        return None

    membership = (
        db.query(Membership)
        .filter(
            Membership.user_id == auth_user.id,
            Membership.university_id == invite.university_id,
            Membership.role == invite.role,
            Membership.status == "active",
        )
        .first()
    )
    if membership is None:
        return None

    if invite.role == "student":
        if invite.course_id is None:
            return None
        enrollment = (
            db.query(CourseMembership)
            .filter(
                CourseMembership.course_id == invite.course_id,
                CourseMembership.membership_id == membership.id,
            )
            .first()
        )
        if enrollment is None:
            return None

    return ActivationResult(status="activated", auth_user_id=auth_user.id)
