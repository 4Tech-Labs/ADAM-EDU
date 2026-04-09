from __future__ import annotations

from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import os
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import close_all_sessions

from shared.app import app
from shared.auth import get_auth_settings, get_jwt_verifier, get_supabase_admin_auth_client
from shared.database import SessionLocal, engine, settings
from shared.models import Base, Course, CourseAccessLink, CourseMembership, Invite, Membership, Profile, Tenant, User


def _assert_local_schema_reset_target() -> None:
    db_url = make_url(settings.database_url)
    allowed_hosts = {"localhost", "127.0.0.1"}
    if settings.environment == "production":
        raise RuntimeError("Refusing to reset test schema against a production database URL.")
    is_repo_local_postgres = db_url.host in allowed_hosts and db_url.port == 5434
    is_github_actions_postgres = (
        os.getenv("GITHUB_ACTIONS") == "true"
        and db_url.host in allowed_hosts
        and db_url.port == 5432
        and db_url.database == "postgres"
        and db_url.username == "postgres"
    )
    if not (is_repo_local_postgres or is_github_actions_postgres):
        raise RuntimeError(
            "Refusing to reset test schema outside approved local test targets "
            "(repo-local localhost:5434 or GitHub Actions 127.0.0.1:5432/postgres, "
            f"got {db_url.host}:{db_url.port}/{db_url.database})."
        )


@pytest.fixture(scope="session", autouse=True)
def ensure_db_schema() -> None:
    """Recreate the ORM schema once so metadata changes are reflected in the test DB."""
    _assert_local_schema_reset_target()
    close_all_sessions()
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def configure_auth_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-jwt-secret-with-sufficient-length-123")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-service-role")
    get_auth_settings.cache_clear()
    get_jwt_verifier.cache_clear()
    get_supabase_admin_auth_client.cache_clear()
    yield
    get_auth_settings.cache_clear()
    get_jwt_verifier.cache_clear()
    get_supabase_admin_auth_client.cache_clear()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip live LLM tests unless they are explicitly enabled."""
    run_live = os.getenv("RUN_LIVE_LLM_TESTS") == "1"
    has_gemini_key = bool(os.getenv("GEMINI_API_KEY"))

    skip_live = pytest.mark.skip(reason="Set RUN_LIVE_LLM_TESTS=1 to run live Gemini tests.")
    skip_missing_key = pytest.mark.skip(reason="GEMINI_API_KEY is required for live Gemini tests.")

    for item in items:
        if "live_llm" not in item.keywords:
            continue
        if not run_live:
            item.add_marker(skip_live)
        elif not has_gemini_key:
            item.add_marker(skip_missing_key)


def pytest_configure(config: pytest.Config) -> None:
    numprocesses = getattr(config.option, "numprocesses", None)
    if getattr(config, "workerinput", None) is not None:
        raise pytest.UsageError(
            "The backend test suite uses a shared database and must run in serial. "
            "Do not use pytest-xdist (-n) until the harness isolates one database per worker."
        )
    if numprocesses == "auto" or (isinstance(numprocesses, int) and numprocesses > 0):
        raise pytest.UsageError(
            "The backend test suite uses a shared database and must run in serial. "
            "Do not use pytest-xdist (-n) until the harness isolates one database per worker."
        )


def _truncate_all_tables() -> None:
    table_names = ", ".join(table.name for table in Base.metadata.sorted_tables)
    if not table_names:
        return
    truncate_sql = text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE")
    close_all_sessions()
    # The backend suite assumes exclusive ownership of the local test DB while it runs.
    with engine.begin() as connection:
        connection.execute(truncate_sql)


@pytest.fixture(autouse=True)
def clean_db(ensure_db_schema: None, request: pytest.FixtureRequest) -> Generator[None, None, None]:
    if request.node.module.__name__.endswith("test_issue23_identity_schema"):
        yield
        return

    _truncate_all_tables()
    yield
    _truncate_all_tables()


@pytest.fixture
def db(ensure_db_schema: None):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def token_factory() -> Callable[..., str]:
    def _factory(
        *,
        sub: str,
        email: str,
        exp_delta_seconds: int = 3600,
        issuer: str | None = None,
        audience: str = "authenticated",
        claims: dict[str, object] | None = None,
        algorithm: str = "HS256",
    ) -> str:
        settings = get_auth_settings()
        payload: dict[str, object] = {
            "sub": sub,
            "email": email,
            "iss": issuer or settings.issuer,
            "aud": audience,
            "exp": datetime.now(timezone.utc) + timedelta(seconds=exp_delta_seconds),
        }
        if claims:
            payload.update(claims)
        return jwt.encode(payload, settings.supabase_jwt_secret, algorithm=algorithm)

    return _factory


@pytest.fixture
def auth_headers_factory(token_factory: Callable[..., str]) -> Callable[..., dict[str, str]]:
    def _factory(**kwargs: object) -> dict[str, str]:
        token = token_factory(**kwargs)
        return {"Authorization": f"Bearer {token}"}

    return _factory


@pytest.fixture
def seed_identity(db) -> Callable[..., dict[str, object]]:
    def _factory(
        *,
        user_id: str,
        email: str,
        role: str,
        university_id: str | None = None,
        university_name: str = "Test University",
        full_name: str = "Test User",
        membership_status: str = "active",
        create_profile: bool = True,
        create_legacy_user: bool = True,
        must_rotate_password: bool = False,
    ) -> dict[str, object]:
        tenant_id = university_id or "10000000-0000-0000-0000-000000000001"
        tenant = db.get(Tenant, tenant_id)
        if tenant is None:
            tenant = Tenant(id=tenant_id, name=university_name)
            db.add(tenant)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                tenant = db.get(Tenant, tenant_id)
                if tenant is None:  # pragma: no cover
                    raise

        profile = None
        if create_profile:
            profile = db.get(Profile, user_id)
            if profile is None:
                profile = Profile(id=user_id, full_name=full_name)
                db.add(profile)
                db.flush()

        membership = None
        membership = db.scalar(
            select(Membership).where(
                Membership.user_id == user_id,
                Membership.university_id == tenant_id,
                Membership.role == role,
            )
        )
        if membership is None and create_profile:
            membership = Membership(
                user_id=user_id,
                university_id=tenant_id,
                role=role,
                status=membership_status,
                must_rotate_password=must_rotate_password,
            )
            db.add(membership)
            db.flush()

        legacy_user = None
        if create_legacy_user:
            legacy_user = db.get(User, user_id)
            if legacy_user is None:
                legacy_user = User(id=user_id, tenant_id=tenant_id, email=email, role=role)
                db.add(legacy_user)
                db.flush()

        db.commit()
        return {
            "tenant": tenant,
            "profile": profile,
            "membership": membership,
            "legacy_user": legacy_user,
        }

    return _factory


@pytest.fixture
def seed_course(db):
    def _factory(
        *,
        university_id: str,
        teacher_membership_id: str | None = None,
        pending_teacher_invite_id: str | None = None,
        title: str = "Test Course",
        code: str | None = None,
        semester: str = "2026-I",
        academic_level: str = "Pregrado",
        max_students: int = 30,
        status: str = "active",
    ) -> Course:
        if (teacher_membership_id is None) == (pending_teacher_invite_id is None):
            raise ValueError("seed_course requires exactly one teacher assignment")

        course = Course(
            university_id=university_id,
            teacher_membership_id=teacher_membership_id,
            pending_teacher_invite_id=pending_teacher_invite_id,
            title=title,
            code=code or f"TEST-{uuid.uuid4().hex[:8].upper()}",
            semester=semester,
            academic_level=academic_level,
            max_students=max_students,
            status=status,
        )
        db.add(course)
        db.commit()
        db.refresh(course)
        return course

    return _factory


@pytest.fixture
def seed_invite(db):
    def _factory(
        *,
        email: str,
        university_id: str,
        role: str,
        course_id: str | None = None,
        full_name: str | None = None,
        status: str = "pending",
        expires_at: datetime | None = None,
        raw_token: str | None = None,
    ) -> tuple[Invite, str]:
        from shared.auth import hash_invite_token

        tenant = db.get(Tenant, university_id)
        if tenant is None:
            tenant = Tenant(id=university_id, name=f"Tenant {university_id[-6:]}")
            db.add(tenant)
            db.flush()

        token = raw_token or f"invite-{uuid.uuid4()}"
        invite = Invite(
            token_hash=hash_invite_token(token),
            email=email,
            full_name=full_name,
            university_id=university_id,
            course_id=course_id,
            role=role,
            status=status,
            expires_at=expires_at or (datetime.now(timezone.utc) + timedelta(days=1)),
        )
        db.add(invite)
        db.commit()
        db.refresh(invite)
        return invite, token

    return _factory


@pytest.fixture
def seed_course_access_link(db):
    def _factory(
        *,
        course_id: str,
        raw_token: str | None = None,
        status: str = "active",
        rotated_at: datetime | None = None,
    ) -> tuple[CourseAccessLink, str]:
        from shared.auth import hash_course_access_token

        token = raw_token or f"course-access-{uuid.uuid4()}"
        access_link = CourseAccessLink(
            course_id=course_id,
            token_hash=hash_course_access_token(token),
            status=status,
            rotated_at=rotated_at,
        )
        db.add(access_link)
        db.commit()
        db.refresh(access_link)
        return access_link, token

    return _factory


@pytest.fixture
def seed_course_membership(db):
    def _factory(*, course_id: str, membership_id: str) -> CourseMembership:
        course_membership = CourseMembership(
            course_id=course_id,
            membership_id=membership_id,
        )
        db.add(course_membership)
        db.commit()
        db.refresh(course_membership)
        return course_membership

    return _factory


@dataclass
class FakeAdminUser:
    id: str
    email: str


@dataclass
class FakeAdminUserResult:
    user: FakeAdminUser
    created: bool


@dataclass
class FakeAdminClient:
    users_by_id: dict[str, FakeAdminUser] = field(default_factory=dict)
    users_by_email: dict[str, FakeAdminUser] = field(default_factory=dict)
    fail_delete: bool = False
    fail_update_password: bool = False
    updated_passwords: dict[str, str] = field(default_factory=dict)
    get_user_by_id_calls: dict[str, int] = field(default_factory=dict)

    def find_user_by_email(self, email: str) -> FakeAdminUser | None:
        return self.users_by_email.get(email.lower())

    def get_or_create_user_by_email(self, email: str, password: str) -> FakeAdminUserResult:
        existing = self.find_user_by_email(email)
        if existing is not None:
            return FakeAdminUserResult(user=existing, created=False)

        user = FakeAdminUser(id=str(uuid.uuid4()), email=email)
        self.users_by_id[user.id] = user
        self.users_by_email[email.lower()] = user
        return FakeAdminUserResult(user=user, created=True)

    def create_password_user(self, email: str, password: str) -> FakeAdminUser:
        return self.get_or_create_user_by_email(email, password).user

    def get_user_by_id(self, user_id: str) -> FakeAdminUser | None:
        self.get_user_by_id_calls[user_id] = self.get_user_by_id_calls.get(user_id, 0) + 1
        return self.users_by_id.get(user_id)

    def delete_user(self, user_id: str) -> None:
        if self.fail_delete:
            raise RuntimeError("delete failed")
        user = self.users_by_id.pop(user_id, None)
        if user is not None:
            self.users_by_email.pop(user.email.lower(), None)

    def update_user_password(self, user_id: str, new_password: str) -> None:
        if self.fail_update_password:
            raise RuntimeError("Supabase Auth password update failed")
        self.updated_passwords[user_id] = new_password


@pytest.fixture
def fake_admin_client(monkeypatch: pytest.MonkeyPatch) -> FakeAdminClient:
    client = FakeAdminClient()
    monkeypatch.setattr("shared.auth.get_supabase_admin_auth_client", lambda: client)
    monkeypatch.setattr("shared.app.get_supabase_admin_auth_client", lambda: client)
    monkeypatch.setattr("shared.admin_reads.get_supabase_admin_auth_client", lambda: client)
    monkeypatch.setattr("shared.auth.get_supabase_admin_auth_client", lambda: client)
    return client
