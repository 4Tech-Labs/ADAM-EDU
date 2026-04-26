from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import os
import pathlib
import sys
import time
from typing import Any
import uuid
from zoneinfo import ZoneInfo

from pythonjsonlogger.json import JsonFormatter

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.exc import TimeoutError as SATimeoutError
from sqlalchemy.orm import Session

from case_generator.core.authoring import AuthoringService, derive_progress_percentage
from case_generator.suggest_service import SuggestRequest, SuggestResponse, generate_suggestion
from shared.admin_router import router as admin_router
from shared.course_access_router import router as course_access_router
from shared.student_router import router as student_router
from shared.teacher_router import router as teacher_router
from shared.auth import (
    AuthError,
    AuthDetailCode,
    AuthorizationError,
    CurrentActor,
    VerifiedIdentity,
    audit_log,
    ensure_password_rotation_cleared,
    ensure_legacy_teacher_bridge,
    get_verified_token,
    get_supabase_admin_auth_client,
    hash_invite_token,
    mask_email,
    normalize_email,
    require_current_actor,
    require_current_actor_password_ready,
    require_teacher_actor,
    require_verified_identity,
    resolve_current_actor,
)
from shared.identity_activation import (
    derive_activation_full_name,
    derive_oauth_full_name,
    ensure_course_membership as ensure_course_membership_impl,
    ensure_email_domain_allowed,
    promote_pending_teacher_courses as promote_pending_teacher_courses_impl,
    try_upsert_legacy_user as try_upsert_legacy_user_impl,
    upsert_legacy_user as upsert_legacy_user_impl,
    upsert_membership as upsert_membership_impl,
    upsert_profile as upsert_profile_impl,
)
from shared.database import (
    clean_authoring_runtime,
    dispose_database_engine,
    get_db,
    validate_runtime_database_configuration,
)
from shared.db_resilience import (
    AUTH_ME_ENDPOINT,
    AUTHORING_INTAKE_ENDPOINT,
    AUTHORING_PROGRESS_ENDPOINT,
    critical_endpoint_dependency,
    emit_metric,
    raise_db_unavailable,
)
from shared.invite_status import invite_effective_status
from shared.models import (
    AUTHORING_JOB_RETRYABLE_STATUSES,
    AUTHORING_JOB_STATUS_FAILED,
    AUTHORING_JOB_STATUS_FAILED_RESUMABLE,
    AUTHORING_JOB_STATUS_PENDING,
    AUTHORING_JOB_STATUS_PROCESSING,
    Assignment,
    AssignmentCourse,
    AuthoringJob,
    Course,
    CourseMembership,
    Invite,
    Membership,
    Profile,
    Tenant,
    User,
)
from shared.internal_tasks import process_authoring_job_task
from shared.syllabus_schema import SyllabusGroundingContext
from shared.teacher_context import resolve_teacher_context
from shared.teacher_reads import get_teacher_owned_course_with_syllabus, resolve_syllabus_selection_titles

load_dotenv()

_json_handler = logging.StreamHandler()
_json_handler.setFormatter(JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
logging.basicConfig(handlers=[_json_handler], level=logging.INFO, force=True)
logger = logging.getLogger(__name__)
_BOGOTA_TZ = ZoneInfo("America/Bogota")

_DEVELOPMENT_ENV = "development"
_DEFAULT_HOST = "0.0.0.0"
_DEFAULT_PORT = 8000
_DEFAULT_WORKERS = 2
_DEFAULT_TIMEOUT_KEEP_ALIVE = 30
_DEFAULT_TIMEOUT_GRACEFUL_SHUTDOWN = 60
_DEFAULT_RELOAD_EXCLUDES = [
    ".venv/*",
    "*/.venv/*",
    "*site-packages*",
    "node_modules/*",
    "*/node_modules/*",
    ".git/*",
    "*/.git/*",
    "build/*",
    "*/build/*",
    "dist/*",
    "*/dist/*",
]


@dataclass(frozen=True)
class UvicornRuntimeProfile:
    app_env: str
    host: str
    port: int
    reload: bool
    reload_dirs: list[str]
    reload_excludes: list[str]
    workers: int
    timeout_keep_alive: int
    timeout_graceful_shutdown: int


def _effective_app_env() -> str:
    app_env_override = os.getenv("APP_ENV", "").strip().lower()
    if app_env_override:
        return app_env_override
    environment = os.getenv("ENVIRONMENT", _DEVELOPMENT_ENV).strip().lower()
    return environment or _DEVELOPMENT_ENV


def _read_int_env(name: str, default: int, *, minimum: int = 1) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        parsed_value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer value") from exc
    if parsed_value < minimum:
        raise RuntimeError(f"{name} must be >= {minimum}")
    return parsed_value


def _build_uvicorn_runtime_profile(argv: list[str] | None = None) -> UvicornRuntimeProfile:
    app_env = _effective_app_env()
    cli_args = argv if argv is not None else sys.argv[1:]
    reload_requested = "--reload" in cli_args
    if reload_requested and app_env != _DEVELOPMENT_ENV:
        raise RuntimeError("Reload is forbidden when APP_ENV/ENVIRONMENT is not 'development'")

    source_dir = pathlib.Path(__file__).resolve().parents[1]
    return UvicornRuntimeProfile(
        app_env=app_env,
        host=os.getenv("APP_HOST", _DEFAULT_HOST),
        port=_read_int_env("APP_PORT", _DEFAULT_PORT),
        reload=app_env == _DEVELOPMENT_ENV,
        reload_dirs=[str(source_dir)],
        reload_excludes=list(_DEFAULT_RELOAD_EXCLUDES),
        workers=_read_int_env("APP_WORKERS", _DEFAULT_WORKERS),
        timeout_keep_alive=_read_int_env("APP_TIMEOUT_KEEP_ALIVE", _DEFAULT_TIMEOUT_KEEP_ALIVE),
        timeout_graceful_shutdown=_read_int_env(
            "APP_TIMEOUT_GRACEFUL_SHUTDOWN",
            _DEFAULT_TIMEOUT_GRACEFUL_SHUTDOWN,
        ),
    )


def _run_uvicorn_profile(profile: UvicornRuntimeProfile) -> None:
    import uvicorn

    logger.info(
        "runtime_profile",
        extra={
            "runtime_profile": {
                "app_env": profile.app_env,
                "reload_enabled": profile.reload,
                "reload_dirs": profile.reload_dirs,
                "reload_excludes": profile.reload_excludes,
                "workers": profile.workers if not profile.reload else 1,
                "timeout_keep_alive": profile.timeout_keep_alive,
                "timeout_graceful_shutdown": profile.timeout_graceful_shutdown,
            }
        },
    )

    run_kwargs: dict[str, Any] = {
        "app": "shared.app:app",
        "host": profile.host,
        "port": profile.port,
        "reload": profile.reload,
        "reload_dirs": profile.reload_dirs,
        "reload_excludes": profile.reload_excludes,
        "timeout_keep_alive": profile.timeout_keep_alive,
        "timeout_graceful_shutdown": profile.timeout_graceful_shutdown,
    }
    if not profile.reload:
        run_kwargs["workers"] = profile.workers

    uvicorn.run(**run_kwargs)


def main() -> None:
    validate_runtime_database_configuration()
    runtime_profile = _build_uvicorn_runtime_profile()
    _run_uvicorn_profile(runtime_profile)

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_optional_assignment_datetime(
    raw_value: str | None,
    *,
    invalid_detail: str,
) -> tuple[datetime | None, str | None]:
    if raw_value is None:
        return None, None

    stripped_value = raw_value.strip()
    if not stripped_value:
        return None, None

    try:
        parsed_value = datetime.fromisoformat(stripped_value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=invalid_detail,
        ) from exc

    localized_value = (
        parsed_value.replace(tzinfo=_BOGOTA_TZ)
        if parsed_value.tzinfo is None
        else parsed_value
    )
    value_utc = localized_value.astimezone(timezone.utc)
    return value_utc, value_utc.isoformat()


def _normalize_deadline_input(raw_due_at: str | None) -> tuple[datetime | None, str | None]:
    return _normalize_optional_assignment_datetime(raw_due_at, invalid_detail="invalid_due_at")


def _normalize_available_from_input(raw_available_from: str | None) -> tuple[datetime | None, str | None]:
    return _normalize_optional_assignment_datetime(
        raw_available_from,
        invalid_detail="invalid_available_from",
    )


def _dedupe_course_ids(course_ids: list[str]) -> list[str]:
    deduped_course_ids: list[str] = []
    seen_course_ids: set[str] = set()
    for course_id in course_ids:
        normalized_course_id = course_id.strip()
        if not normalized_course_id or normalized_course_id in seen_course_ids:
            continue
        deduped_course_ids.append(normalized_course_id)
        seen_course_ids.add(normalized_course_id)
    return deduped_course_ids


def _resolve_target_courses_or_404(db: Session, context, target_course_ids: list[str]) -> list[Course]:
    deduped_course_ids = _dedupe_course_ids(target_course_ids)
    if not deduped_course_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="target_courses_required",
        )

    target_courses = db.scalars(
        select(Course).where(
            Course.id.in_(deduped_course_ids),
            Course.university_id == context.university_id,
            Course.teacher_membership_id == context.teacher_membership_id,
        )
    ).all()
    target_courses_by_id = {course.id: course for course in target_courses}
    missing_course_ids = [course_id for course_id in deduped_course_ids if course_id not in target_courses_by_id]
    if missing_course_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="course_not_found")

    return [target_courses_by_id[course_id] for course_id in deduped_course_ids]


def _course_target_group_label(course: Course) -> str:
    return f"{course.title} ({course.code})" if course.code else course.title


def get_legacy_teacher_or_500(db: Session, actor: CurrentActor) -> User:
    return ensure_legacy_teacher_bridge(db, actor)


def get_owned_job_or_404(db: Session, job_id: str, actor: CurrentActor) -> AuthoringJob:
    context = resolve_teacher_context(actor)
    stmt = (
        select(AuthoringJob)
        .join(Assignment, AuthoringJob.assignment_id == Assignment.id)
        .outerjoin(Course, Assignment.course_id == Course.id)
        .where(
            AuthoringJob.id == job_id,
            or_(
                and_(
                    Assignment.course_id.is_(None),
                    Assignment.teacher_id == actor.auth_user_id,
                ),
                and_(
                    Assignment.course_id.is_not(None),
                    Course.university_id == context.university_id,
                    Course.teacher_membership_id == context.teacher_membership_id,
                ),
            ),
        )
    )
    job = db.scalar(stmt)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


def get_invite_by_token(db: Session, invite_token: str) -> Invite | None:
    return db.scalar(select(Invite).where(Invite.token_hash == hash_invite_token(invite_token)))


def get_invite_by_token_for_update(db: Session, invite_token: str) -> Invite | None:
    return db.scalar(
        select(Invite)
        .where(Invite.token_hash == hash_invite_token(invite_token))
        .with_for_update()
    )


def require_invite_email_match(invite: Invite, email: str | None) -> None:
    if normalize_email(invite.email) != normalize_email(email):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid_invite_actor")


def upsert_profile(db: Session, auth_user_id: str, full_name: str | None) -> Profile:
    return upsert_profile_impl(db, auth_user_id, full_name)


def upsert_membership(db: Session, auth_user_id: str, university_id: str, role: str) -> Membership:
    return upsert_membership_impl(db, auth_user_id, university_id, role)


def upsert_legacy_user(
    db: Session,
    *,
    auth_user_id: str,
    university_id: str,
    email: str,
    role: str,
) -> User:
    return upsert_legacy_user_impl(
        db,
        auth_user_id=auth_user_id,
        university_id=university_id,
        email=email,
        role=role,
    )


def upsert_legacy_teacher_user(db: Session, *, auth_user_id: str, university_id: str, email: str) -> User:
    return upsert_legacy_user(
        db,
        auth_user_id=auth_user_id,
        university_id=university_id,
        email=email,
        role="teacher",
    )


def try_upsert_legacy_user(
    db: Session,
    *,
    auth_user_id: str,
    university_id: str,
    email: str,
    role: str,
    context: str,
) -> bool:
    return try_upsert_legacy_user_impl(
        db,
        auth_user_id=auth_user_id,
        university_id=university_id,
        email=email,
        role=role,
        context=context,
    )


def promote_pending_teacher_courses(db: Session, invite_id: str, membership_id: str, university_id: str) -> None:
    promote_pending_teacher_courses_impl(
        db,
        invite_id=invite_id,
        membership_id=membership_id,
        university_id=university_id,
    )


def upsert_course_membership(db: Session, course_id: str, membership_id: str) -> tuple[CourseMembership, bool]:
    return ensure_course_membership_impl(db, course_id=course_id, membership_id=membership_id)


def consume_invite_if_pending(db: Session, invite: Invite) -> bool:
    stmt = (
        update(Invite)
        .where(Invite.id == invite.id, Invite.status == "pending")
        .values(status="consumed", consumed_at=utc_now())
        .returning(Invite.id)
    )
    return db.execute(stmt).scalar_one_or_none() is not None


def activation_state_exists(db: Session, invite: Invite, auth_user_id: str) -> bool:
    profile = db.scalar(select(Profile).where(Profile.id == auth_user_id))
    if profile is None:
        return False

    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == auth_user_id,
            Membership.university_id == invite.university_id,
            Membership.role == invite.role,
        )
    )
    if membership is None:
        return False

    if invite.role == "student" and invite.course_id:
        course_membership = db.scalar(
            select(CourseMembership).where(
                CourseMembership.course_id == invite.course_id,
                CourseMembership.membership_id == membership.id,
            )
        )
        return course_membership is not None

    return True


def _get_activation_membership(db: Session, invite: Invite, auth_user_id: str) -> Membership | None:
    return db.scalar(
        select(Membership).where(
            Membership.user_id == auth_user_id,
            Membership.university_id == invite.university_id,
            Membership.role == invite.role,
        )
    )


def repair_consumed_activation_state(
    db: Session,
    *,
    invite: Invite,
    auth_user_id: str,
    email: str,
) -> None:
    membership = _get_activation_membership(db, invite, auth_user_id)
    if membership is None:
        raise RuntimeError("activation_membership_missing_during_repair")

    if invite.role == "teacher":
        upsert_legacy_teacher_user(
            db,
            auth_user_id=auth_user_id,
            university_id=invite.university_id,
            email=email,
        )
        promote_pending_teacher_courses(db, invite.id, membership.id, invite.university_id)
    elif invite.role == "student":
        try_upsert_legacy_user(
            db,
            auth_user_id=auth_user_id,
            university_id=invite.university_id,
            email=email,
            role="student",
            context="activate.repair_consumed_student",
        )

def _check_student_email_domain(db: Session, invite: Invite) -> None:
    """Raise 422 if the invite email domain is not in the university's allow-list.

    A university with no configured domains has an open allow-list (all domains
    accepted). This preserves backward-compatibility for existing universities
    that have not yet configured allowed_email_domains.
    """
    ensure_email_domain_allowed(
        db,
        university_id=invite.university_id,
        email=invite.email,
    )


_auth_me_budget_dependency = critical_endpoint_dependency(AUTH_ME_ENDPOINT)
_authoring_intake_budget_dependency = critical_endpoint_dependency(AUTHORING_INTAKE_ENDPOINT)
_authoring_progress_budget_dependency = critical_endpoint_dependency(AUTHORING_PROGRESS_ENDPOINT)


def require_current_actor_auth_me(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> CurrentActor:
    try:
        return require_current_actor(
            authorization=authorization,
            db=db,
            require_profile_fields=False,
        )
    except AuthError:
        raise
    except (SATimeoutError, OperationalError, DBAPIError) as exc:
        raise_db_unavailable(exc, endpoint_code=AUTH_ME_ENDPOINT)


def require_teacher_actor_authoring_intake(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> CurrentActor:
    try:
        actor = require_current_actor(authorization=authorization, db=db)
        actor = ensure_password_rotation_cleared(actor)
        return require_teacher_actor(actor=actor)
    except AuthError:
        raise
    except (SATimeoutError, OperationalError, DBAPIError) as exc:
        raise_db_unavailable(exc, endpoint_code=AUTHORING_INTAKE_ENDPOINT)


def require_teacher_actor_authoring_progress(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> CurrentActor:
    try:
        actor = require_current_actor(authorization=authorization, db=db)
        actor = ensure_password_rotation_cleared(actor)
        return require_teacher_actor(actor=actor)
    except AuthError:
        raise
    except (SATimeoutError, OperationalError, DBAPIError) as exc:
        raise_db_unavailable(exc, endpoint_code=AUTHORING_PROGRESS_ENDPOINT)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    validate_runtime_database_configuration()
    try:
        yield
    finally:
        await clean_authoring_runtime(
            reason="fastapi_lifespan_shutdown",
            timeout_seconds=5.0,
            clear_active_jobs=True,
        )
        dispose_database_engine()


app = FastAPI(title="adam-v8.0 - Case Generation API", lifespan=lifespan)
app.include_router(admin_router)
app.include_router(course_access_router)
app.include_router(student_router)
app.include_router(teacher_router)


@app.middleware("http")
async def structured_logging_middleware(request: Request, call_next: Any) -> Any:
    """Emit a structured JSON log line for every HTTP request.

    Fields: request_id (UUID4), method, path, status_code, latency_ms.
    request_id is stored in request.state for downstream use.
    """
    request_id = str(uuid.uuid4())
    start = time.monotonic()
    request.state.request_id = request_id
    response = await call_next(request)
    latency_ms = round((time.monotonic() - start) * 1000)
    logger.info(
        "request",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
        },
    )
    return response


_cors_origins = [
    "http://localhost:5173",
    "http://localhost:3000",
    "https://smith.langchain.com",
]
if _prod_origin := os.getenv("CORS_ALLOWED_ORIGIN"):
    _cors_origins.append(_prod_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AuthError)
async def handle_auth_error(_: Request, exc: AuthError) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == status.HTTP_401_UNAUTHORIZED else None
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail_code}, headers=headers)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "adam-v8.0"}


class IntakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignment_title: str
    course_id: str
    subject: str = ""
    academic_level: str = "Pregrado"
    industry: str = "General"
    student_profile: str = "business"
    case_type: str = "harvard_only"
    syllabus_module: str = ""
    scenario_description: str = ""
    guiding_question: str = ""
    topic_unit: str = ""
    target_groups: list[str] = []
    target_course_ids: list[str] = []
    eda_depth: str | None = None
    include_python_code: bool = False
    suggested_techniques: list[str] = []
    available_from: str | None = None
    due_at: str | None = None


class JobCreatedResponse(BaseModel):
    job_id: str
    status: str
    message: str


class RetryJobResponse(BaseModel):
    job_id: str
    status: str
    message: str


@app.post(
    "/api/authoring/jobs",
    response_model=JobCreatedResponse,
    status_code=202,
    dependencies=[Depends(_authoring_intake_budget_dependency)],
)
def create_authoring_job(
    req: IntakeRequest,
    background_tasks: BackgroundTasks,
    actor: CurrentActor = Depends(require_teacher_actor_authoring_intake),
    db: Session = Depends(get_db),
) -> JobCreatedResponse:
    started = time.monotonic()
    try:
        context = resolve_teacher_context(actor)
        teacher = get_legacy_teacher_or_500(db, actor)
        owned_course = get_teacher_owned_course_with_syllabus(db, context, req.course_id, lock=True)
        target_course_ids = req.target_course_ids or [req.course_id]
        target_courses = _resolve_target_courses_or_404(db, context, target_course_ids)
        target_groups = (
            [_course_target_group_label(course) for course in target_courses]
            if req.target_course_ids
            else list(req.target_groups)
        )
        SyllabusGroundingContext.model_validate(owned_course.syllabus.ai_grounding_context)
        available_from, normalized_available_from = _normalize_available_from_input(req.available_from)
        deadline, normalized_due_at = _normalize_deadline_input(req.due_at)
        try:
            module_title, unit_title = resolve_syllabus_selection_titles(
                owned_course.syllabus.modules,
                module_id=req.syllabus_module,
                unit_id=req.topic_unit,
                strict=True,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Seleccion invalida de modulo o unidad del syllabus",
            ) from exc

        assignment = Assignment(
            teacher_id=teacher.id,
            course_id=owned_course.course.id,
            title=req.assignment_title,
            status="draft",
            available_from=available_from,
            deadline=deadline,
            assignment_courses=[AssignmentCourse(course_id=course.id) for course in target_courses],
        )
        db.add(assignment)
        db.commit()
        db.refresh(assignment)

        idempotency_key = f"job-init-{assignment.id}-{uuid.uuid4()}"
        job = AuthoringJob(
            assignment_id=assignment.id,
            idempotency_key=idempotency_key,
            status=AUTHORING_JOB_STATUS_PENDING,
            task_payload={
                "step": "authoring",
                "course_id": owned_course.course.id,
                "syllabus_revision": owned_course.syllabus.revision,
                "syllabus_module_id": req.syllabus_module,
                "topic_unit_id": req.topic_unit,
                "asignatura": owned_course.course.title,
                "nivel": owned_course.course.academic_level,
                "industria": req.industry,
                "studentProfile": req.student_profile,
                "caseType": req.case_type,
                "modulo": module_title,
                "escenario": req.scenario_description,
                "pregunta_guia": req.guiding_question,
                "topicUnit": unit_title,
                "targetCourseIds": [course.id for course in target_courses],
                "targetGroups": target_groups,
                "edaDepth": req.eda_depth,
                "includePythonCode": req.include_python_code,
                "algoritmos": req.suggested_techniques,
                "availableFrom": normalized_available_from,
                "dueAt": normalized_due_at,
            },
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        logger.info("Intake complete. Job %s enqueued. Assignment: %s", job.id, assignment.id)
        background_tasks.add_task(AuthoringService.run_job, job.id)

        return JobCreatedResponse(
            job_id=job.id,
            status="accepted",
            message="Authoring job accepted and dispatched to queue.",
        )
    except (SATimeoutError, OperationalError, DBAPIError) as exc:
        raise_db_unavailable(exc, endpoint_code=AUTHORING_INTAKE_ENDPOINT)
    finally:
        emit_metric(
            "authoring_intake_latency_ms",
            round((time.monotonic() - started) * 1000, 3),
            endpoint=AUTHORING_INTAKE_ENDPOINT,
        )


@app.post(
    "/api/authoring/jobs/{job_id}/retry",
    response_model=RetryJobResponse,
    status_code=202,
)
def retry_authoring_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    actor: CurrentActor = Depends(require_teacher_actor_authoring_intake),
    db: Session = Depends(get_db),
) -> RetryJobResponse:
    job = get_owned_job_or_404(db, job_id, actor)

    if job.status == AUTHORING_JOB_STATUS_PROCESSING:
        return RetryJobResponse(
            job_id=job.id,
            status="accepted",
            message="Authoring job already in progress.",
        )

    if job.status not in AUTHORING_JOB_RETRYABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job not retryable",
            headers={"X-Job-Status": job.status},
        )

    logger.info(
        "Authoring retry accepted for job %s (status=%s)",
        job.id,
        job.status,
    )
    background_tasks.add_task(AuthoringService.run_job, job.id)
    return RetryJobResponse(
        job_id=job.id,
        status="accepted",
        message="Authoring retry accepted and dispatched to queue.",
    )


# Cloud Tasks internal endpoint — handler lives in shared.internal_tasks
# to avoid import side effects when worker_app.py mounts the same route.
app.add_api_route(
    "/api/internal/tasks/authoring_step",
    process_authoring_job_task,
    methods=["POST"],
    status_code=200,
)


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    assignment_id: str
    created_at: str
    updated_at: str
    error_trace: str | None = None


class JobResultResponse(BaseModel):
    job_id: str
    assignment_id: str
    blueprint: dict[str, Any]
    canonical_output: dict[str, Any] | None = None


class JobProgressResponse(BaseModel):
    job_id: str
    status: str
    current_step: str | None = None
    progress_percentage: int | None = None
    bootstrap_state: str | None = None
    progress_seq: int | None = None
    progress_ts: str | None = None
    error_code: str | None = None
    error_trace: str | None = None


@app.get("/api/authoring/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(
    job_id: str,
    actor: CurrentActor = Depends(require_teacher_actor),
    db: Session = Depends(get_db),
) -> JobStatusResponse:
    job = get_owned_job_or_404(db, job_id, actor)
    error_trace = None
    if job.status in {AUTHORING_JOB_STATUS_FAILED, AUTHORING_JOB_STATUS_FAILED_RESUMABLE} and job.task_payload:
        error_trace = job.task_payload.get("error_trace")

    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        assignment_id=job.assignment_id,
        created_at=job.created_at.isoformat() if job.created_at else "",
        updated_at=job.updated_at.isoformat() if job.updated_at else "",
        error_trace=error_trace,
    )


@app.get("/api/authoring/jobs/{job_id}/result", response_model=JobResultResponse)
def get_job_result(
    job_id: str,
    actor: CurrentActor = Depends(require_teacher_actor),
    db: Session = Depends(get_db),
) -> JobResultResponse:
    job = get_owned_job_or_404(db, job_id, actor)
    if job.status != "completed":
        raise HTTPException(
            status_code=409,
            detail="Job not ready",
            headers={"X-Job-Status": job.status},
        )

    assignment = db.scalar(select(Assignment).where(Assignment.id == job.assignment_id))
    if not assignment or not assignment.blueprint:
        raise HTTPException(
            status_code=409,
            detail="Job completed but blueprint not yet available",
        )

    canonical = dict(assignment.canonical_output or {})
    canonical["caseId"] = str(assignment.id)
    return JobResultResponse(
        job_id=job.id,
        assignment_id=assignment.id,
        blueprint=assignment.blueprint,
        canonical_output=canonical,
    )


@app.get(
    "/api/authoring/jobs/{job_id}/progress",
    response_model=JobProgressResponse,
    dependencies=[Depends(_authoring_progress_budget_dependency)],
)
def get_job_progress(
    job_id: str,
    actor: CurrentActor = Depends(require_teacher_actor_authoring_progress),
    db: Session = Depends(get_db),
) -> JobProgressResponse:
    started = time.monotonic()
    try:
        job = get_owned_job_or_404(db, job_id, actor)
        payload = job.task_payload or {}

        current_step = payload.get("current_step")
        progress_seq = payload.get("progress_seq")
        progress_ts = payload.get("progress_ts")
        error_code = payload.get("error_code")
        error_trace = payload.get("error_trace")
        bootstrap_state = payload.get("bootstrap_state")
        current_step_value = current_step if isinstance(current_step, str) else None

        emit_metric("progress_snapshot_reads_total", 1, endpoint=AUTHORING_PROGRESS_ENDPOINT)
        return JobProgressResponse(
            job_id=job.id,
            status=job.status,
            current_step=current_step_value,
            progress_percentage=derive_progress_percentage(
                payload,
                current_step=current_step_value,
                status=job.status,
            ),
            bootstrap_state=bootstrap_state if isinstance(bootstrap_state, str) else None,
            progress_seq=progress_seq if isinstance(progress_seq, int) else None,
            progress_ts=progress_ts if isinstance(progress_ts, str) else None,
            error_code=error_code if isinstance(error_code, str) else None,
            error_trace=error_trace if isinstance(error_trace, str) else None,
        )
    except (SATimeoutError, OperationalError, DBAPIError) as exc:
        raise_db_unavailable(exc, endpoint_code=AUTHORING_PROGRESS_ENDPOINT)
    finally:
        emit_metric(
            "progress_snapshot_latency_ms",
            round((time.monotonic() - started) * 1000, 3),
            endpoint=AUTHORING_PROGRESS_ENDPOINT,
        )


class MembershipResponse(BaseModel):
    id: str
    university_id: str
    role: str
    status: str
    must_rotate_password: bool


class AuthMeProfileResponse(BaseModel):
    id: str
    full_name: str


class AuthMeResponse(BaseModel):
    auth_user_id: str
    profile: AuthMeProfileResponse
    memberships: list[MembershipResponse]
    must_rotate_password: bool
    primary_role: str


@app.get(
    "/api/auth/me",
    response_model=AuthMeResponse,
    dependencies=[Depends(_auth_me_budget_dependency)],
)
def get_auth_me(actor: CurrentActor = Depends(require_current_actor_auth_me)) -> AuthMeResponse:
    started = time.monotonic()
    audit_log(
        "session.verified",
        "success",
        auth_user_id=actor.auth_user_id,
        http_status=200,
    )
    response = AuthMeResponse(
        auth_user_id=actor.auth_user_id,
        profile=AuthMeProfileResponse(id=actor.profile.id, full_name=actor.profile.full_name),
        memberships=[
            MembershipResponse(
                id=membership.id,
                university_id=membership.university_id,
                role=membership.role,
                status=membership.status,
                must_rotate_password=membership.must_rotate_password,
            )
            for membership in actor.memberships
        ],
        must_rotate_password=actor.must_rotate_password,
        primary_role=actor.primary_role,
    )
    emit_metric(
        "auth_me_latency_ms",
        round((time.monotonic() - started) * 1000, 3),
        endpoint=AUTH_ME_ENDPOINT,
    )
    return response


class ChangePasswordRequest(BaseModel):
    new_password: str


class ChangePasswordResponse(BaseModel):
    status: str


@app.post("/api/auth/change-password", response_model=ChangePasswordResponse)
def change_admin_password(
    req: ChangePasswordRequest,
    actor: CurrentActor = Depends(require_current_actor),
    db: Session = Depends(get_db),
) -> ChangePasswordResponse:
    """Rotate password for a university_admin with must_rotate_password=True.

        Shared auth guard exemption:
            verified_identity -> profile_state -> membership_state -> role/context -> handler
            password_rotation_required is enforced on protected business routes, but NOT here.

    FAIL-CLOSED flow:
      [D] update_user_password → Supabase Auth API   (if fails: 500, DB untouched)
      [E] UPDATE memberships SET must_rotate_password=False  (if fails: 500, Auth updated)

    Auth update intentionally precedes DB update. If Auth succeeds but DB fails,
    the admin retries with the new password — flag still True, flow repeats safely.
    """
    # [B] Role guard
    if not actor.has_active_role("university_admin"):
        audit_log(
            "admin.change_password",
            "denied",
            auth_user_id=actor.auth_user_id,
            http_status=403,
            reason=AuthDetailCode.ADMIN_ROLE_REQUIRED,
        )
        raise AuthorizationError(AuthDetailCode.ADMIN_ROLE_REQUIRED)

    # [C] Rotation guard — 403 if flag already cleared
    if not actor.must_rotate_password:
        audit_log(
            "admin.change_password",
            "denied",
            auth_user_id=actor.auth_user_id,
            http_status=403,
            reason=AuthDetailCode.PASSWORD_ROTATION_NOT_REQUIRED,
        )
        raise AuthorizationError(AuthDetailCode.PASSWORD_ROTATION_NOT_REQUIRED)

    # [D] Update Supabase Auth FIRST — fail-closed: DB untouched if this raises
    admin_client = get_supabase_admin_auth_client()
    try:
        admin_client.update_user_password(actor.auth_user_id, req.new_password)
    except Exception as exc:
        audit_log(
            "admin.change_password",
            "error",
            auth_user_id=actor.auth_user_id,
            http_status=500,
            reason=AuthDetailCode.PASSWORD_UPDATE_FAILED,
        )
        raise AuthError(status.HTTP_500_INTERNAL_SERVER_ERROR, AuthDetailCode.PASSWORD_UPDATE_FAILED) from exc

    # [E] Clear must_rotate_password for ALL university_admin memberships of this user.
    # Auth password is global (not per-university), so all flags clear together.
    db.execute(
        update(Membership)
        .where(
            Membership.user_id == actor.auth_user_id,
            Membership.role == "university_admin",
            Membership.must_rotate_password == True,  # noqa: E712
        )
        .values(must_rotate_password=False)
    )
    db.commit()

    audit_log(
        "admin.change_password",
        "success",
        auth_user_id=actor.auth_user_id,
        http_status=200,
    )
    return ChangePasswordResponse(status="password_rotated")


class InviteResolveRequest(BaseModel):
    invite_token: str


class InviteResolveResponse(BaseModel):
    role: str
    email_masked: str
    university_name: str
    course_title: str | None
    teacher_name: str | None
    status: str
    expires_at: str


@app.post("/api/invites/resolve", response_model=InviteResolveResponse)
def resolve_invite(req: InviteResolveRequest, db: Session = Depends(get_db)) -> InviteResolveResponse:
    invite = get_invite_by_token(db, req.invite_token)
    invite_hash_prefix = hash_invite_token(req.invite_token)[:12]
    if invite is None:
        audit_log(
            "invite.resolve.invalid",
            "invalid",
            invite_hash_prefix=invite_hash_prefix,
            http_status=status.HTTP_404_NOT_FOUND,
            reason=AuthDetailCode.INVITE_INVALID,
        )
        raise AuthError(status.HTTP_404_NOT_FOUND, AuthDetailCode.INVITE_INVALID)

    tenant = db.scalar(select(Tenant).where(Tenant.id == invite.university_id))
    course_title = None
    teacher_name = None
    if invite.course_id:
        course = db.scalar(select(Course).where(Course.id == invite.course_id))
        if course is not None:
            course_title = course.title
            if course.teacher_membership_id:
                membership = db.get(Membership, course.teacher_membership_id)
                if membership is not None:
                    profile = db.get(Profile, membership.user_id)
                    teacher_name = profile.full_name if profile is not None else None
            elif course.pending_teacher_invite_id:
                pending_invite = db.get(Invite, course.pending_teacher_invite_id)
                teacher_name = pending_invite.full_name if pending_invite is not None else None

    effective_status = invite_effective_status(invite)
    audit_log(
        "invite.resolve.valid",
        "resolved",
        invite_id=invite.id,
        invite_hash_prefix=invite.token_hash[:12],
        http_status=status.HTTP_200_OK,
        reason=effective_status,
    )
    return InviteResolveResponse(
        role=invite.role,
        email_masked=mask_email(invite.email),
        university_name=tenant.name if tenant else invite.university_id,
        course_title=course_title,
        teacher_name=teacher_name,
        status=effective_status,
        expires_at=invite.expires_at.isoformat(),
    )


class InviteRedeemRequest(BaseModel):
    invite_token: str


class InviteRedeemResponse(BaseModel):
    status: str


@app.post("/api/invites/redeem", response_model=InviteRedeemResponse)
def redeem_invite(
    req: InviteRedeemRequest,
    actor: CurrentActor = Depends(require_current_actor_password_ready),
    db: Session = Depends(get_db),
) -> InviteRedeemResponse:
    if not actor.has_active_role("student"):
        audit_log(
            "invite.redeem",
            "denied",
            auth_user_id=actor.auth_user_id,
            http_status=status.HTTP_403_FORBIDDEN,
            reason=AuthDetailCode.MEMBERSHIP_REQUIRED,
        )
        raise AuthorizationError(AuthDetailCode.MEMBERSHIP_REQUIRED)

    invite = get_invite_by_token(db, req.invite_token)
    if invite is None or invite.role != "student" or invite.course_id is None:
        audit_log(
            "invite.redeem",
            "invalid",
            auth_user_id=actor.auth_user_id,
            invite_hash_prefix=hash_invite_token(req.invite_token)[:12],
            http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
            reason=AuthDetailCode.INVITE_INVALID,
        )
        raise AuthError(status.HTTP_422_UNPROCESSABLE_CONTENT, AuthDetailCode.INVITE_INVALID)

    require_invite_email_match(invite, actor.email)
    membership = next(
        (
            membership
            for membership in actor.active_memberships
            if membership.role == "student" and membership.university_id == invite.university_id
        ),
        None,
    )
    if membership is None:
        audit_log(
            "invite.redeem",
            "denied",
            auth_user_id=actor.auth_user_id,
            invite_id=invite.id,
            invite_hash_prefix=invite.token_hash[:12],
            http_status=status.HTTP_403_FORBIDDEN,
            reason=AuthDetailCode.MEMBERSHIP_REQUIRED,
        )
        raise AuthorizationError(AuthDetailCode.MEMBERSHIP_REQUIRED)

    existing_course_membership = db.scalar(
        select(CourseMembership).where(
            CourseMembership.course_id == invite.course_id,
            CourseMembership.membership_id == membership.id,
        )
    )
    if existing_course_membership is not None:
        consume_invite_if_pending(db, invite)
        db.commit()
        audit_log(
            "invite.redeem",
            "already_enrolled",
            auth_user_id=actor.auth_user_id,
            invite_id=invite.id,
            invite_hash_prefix=invite.token_hash[:12],
            http_status=status.HTTP_200_OK,
            reason="already_enrolled",
        )
        return InviteRedeemResponse(status="already_enrolled")

    if invite_effective_status(invite) != "pending":
        audit_log(
            "invite.redeem",
            "invalid",
            auth_user_id=actor.auth_user_id,
            invite_id=invite.id,
            invite_hash_prefix=invite.token_hash[:12],
            http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
            reason=AuthDetailCode.INVITE_INVALID,
        )
        raise AuthError(status.HTTP_422_UNPROCESSABLE_CONTENT, AuthDetailCode.INVITE_INVALID)

    try:
        _, created_course_membership = upsert_course_membership(db, invite.course_id, membership.id)
        consumed = consume_invite_if_pending(db, invite)
        if not consumed:
            db.rollback()
            existing_after_rollback = db.scalar(
                select(CourseMembership).where(
                    CourseMembership.course_id == invite.course_id,
                    CourseMembership.membership_id == membership.id,
                )
            )
            if existing_after_rollback is not None or not created_course_membership:
                audit_log(
                    "invite.redeem",
                    "already_enrolled",
                    auth_user_id=actor.auth_user_id,
                    invite_id=invite.id,
                    invite_hash_prefix=invite.token_hash[:12],
                    http_status=status.HTTP_200_OK,
                    reason="already_enrolled",
                )
                return InviteRedeemResponse(status="already_enrolled")
            audit_log(
                "invite.redeem",
                "invalid",
                auth_user_id=actor.auth_user_id,
                invite_id=invite.id,
                invite_hash_prefix=invite.token_hash[:12],
                http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
                reason=AuthDetailCode.INVITE_INVALID,
            )
            raise AuthError(status.HTTP_422_UNPROCESSABLE_CONTENT, AuthDetailCode.INVITE_INVALID)
        db.commit()
    except IntegrityError:
        db.rollback()
        audit_log(
            "invite.redeem",
            "already_enrolled",
            auth_user_id=actor.auth_user_id,
            invite_id=invite.id,
            invite_hash_prefix=invite.token_hash[:12],
            http_status=status.HTTP_200_OK,
            reason="already_enrolled",
        )
        return InviteRedeemResponse(status="already_enrolled")

    audit_log(
        "invite.redeem",
        "redeemed",
        auth_user_id=actor.auth_user_id,
        invite_id=invite.id,
        invite_hash_prefix=invite.token_hash[:12],
        http_status=status.HTTP_200_OK,
        reason="redeemed",
    )
    return InviteRedeemResponse(status="redeemed")


class ActivatePasswordRequest(BaseModel):
    invite_token: str
    full_name: str | None = None
    password: str
    confirm_password: str


class ActivatePasswordResponse(BaseModel):
    status: str
    next_step: str
    email: str


@app.post("/api/auth/activate/password", response_model=ActivatePasswordResponse, status_code=201)
def activate_password(
    req: ActivatePasswordRequest,
    db: Session = Depends(get_db),
) -> ActivatePasswordResponse:
    if req.password != req.confirm_password:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="password_mismatch")

    invite = get_invite_by_token_for_update(db, req.invite_token)
    if invite is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid_invite")

    admin_client = get_supabase_admin_auth_client()
    existing_user = admin_client.find_user_by_email(invite.email)
    effective_status = invite_effective_status(invite)
    if effective_status == "consumed" and existing_user and activation_state_exists(db, invite, existing_user.id):
        try:
            repair_consumed_activation_state(
                db,
                invite=invite,
                auth_user_id=existing_user.id,
                email=invite.email,
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="activation_failed",
            ) from exc
        return ActivatePasswordResponse(status="activated", next_step="sign_in", email=invite.email)
    if effective_status != "pending":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid_invite")

    # B1: full_name is required for student activation (not teacher)
    if invite.role == "student" and not (req.full_name and req.full_name.strip()):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="full_name_required")

    # B2: validate institutional email domain for students
    if invite.role == "student":
        _check_student_email_domain(db, invite)

    created_new_user = False
    auth_user = existing_user
    if auth_user is None:
        admin_user_result = admin_client.get_or_create_user_by_email(invite.email, req.password)
        auth_user = admin_user_result.user
        created_new_user = admin_user_result.created

    try:
        upsert_profile(
            db,
            auth_user.id,
            derive_activation_full_name(req.full_name or invite.full_name, invite.email),
        )
        membership = upsert_membership(
            db,
            auth_user.id,
            invite.university_id,
            invite.role,
        )
        if invite.role == "teacher":
            upsert_legacy_teacher_user(
                db,
                auth_user_id=auth_user.id,
                university_id=invite.university_id,
                email=invite.email,
            )
            promote_pending_teacher_courses(db, invite.id, membership.id, invite.university_id)
        if invite.role == "student":
            try_upsert_legacy_user(
                db,
                auth_user_id=auth_user.id,
                university_id=invite.university_id,
                email=invite.email,
                role="student",
                context="activate.password.student",
            )
        if invite.role == "student" and invite.course_id:
            upsert_course_membership(db, invite.course_id, membership.id)
        if not consume_invite_if_pending(db, invite):
            if activation_state_exists(db, invite, auth_user.id):
                repair_consumed_activation_state(
                    db,
                    invite=invite,
                    auth_user_id=auth_user.id,
                    email=invite.email,
                )
                db.commit()
                return ActivatePasswordResponse(status="activated", next_step="sign_in", email=invite.email)
            db.rollback()
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid_invite")
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        if created_new_user:
            try:
                admin_client.delete_user(auth_user.id)
            except Exception:
                audit_log(
                    "activate.password",
                    "partial_failure",
                    auth_user_id=auth_user.id,
                    invite_id=invite.id,
                    invite_hash_prefix=invite.token_hash[:12],
                    http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    reason="compensation_failed",
                )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="activation_failed") from exc

    audit_log(
        "activate.password",
        "activated",
        auth_user_id=auth_user.id,
        invite_id=invite.id,
        invite_hash_prefix=invite.token_hash[:12],
        http_status=status.HTTP_201_CREATED,
        reason="activated",
    )
    return ActivatePasswordResponse(status="activated", next_step="sign_in", email=invite.email)


class ActivateOAuthCompleteRequest(BaseModel):
    invite_token: str


class ActivateOAuthCompleteResponse(BaseModel):
    status: str


@app.post("/api/auth/activate/oauth/complete", response_model=ActivateOAuthCompleteResponse)
def activate_oauth_complete(
    req: ActivateOAuthCompleteRequest,
    identity: VerifiedIdentity = Depends(require_verified_identity),
    db: Session = Depends(get_db),
) -> ActivateOAuthCompleteResponse:
    invite = get_invite_by_token_for_update(db, req.invite_token)
    if invite is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid_invite")

    effective_status = invite_effective_status(invite)
    if effective_status == "consumed" and activation_state_exists(db, invite, identity.auth_user_id):
        try:
            repair_consumed_activation_state(
                db,
                invite=invite,
                auth_user_id=identity.auth_user_id,
                email=invite.email,
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="activation_failed",
            ) from exc
        return ActivateOAuthCompleteResponse(status="activated")
    if effective_status != "pending":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid_invite")

    if normalize_email(identity.email) != normalize_email(invite.email):
        audit_log(
            "activate.oauth.mismatch_delete",
            "skipped",
            auth_user_id=identity.auth_user_id,
            invite_id=invite.id,
            invite_hash_prefix=invite.token_hash[:12],
            http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
            reason="invite_email_mismatch",
        )
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invite_email_mismatch")

    # B3: validate institutional email domain for students
    if invite.role == "student":
        _check_student_email_domain(db, invite)

    try:
        upsert_profile(
            db,
            identity.auth_user_id,
            derive_oauth_full_name(identity) or invite.full_name or invite.email.split("@", maxsplit=1)[0],
        )
        membership = upsert_membership(
            db,
            identity.auth_user_id,
            invite.university_id,
            invite.role,
        )
        if invite.role == "teacher":
            upsert_legacy_teacher_user(
                db,
                auth_user_id=identity.auth_user_id,
                university_id=invite.university_id,
                email=invite.email,
            )
            promote_pending_teacher_courses(db, invite.id, membership.id, invite.university_id)
        if invite.role == "student":
            try_upsert_legacy_user(
                db,
                auth_user_id=identity.auth_user_id,
                university_id=invite.university_id,
                email=invite.email,
                role="student",
                context="activate.oauth.student",
            )
        if invite.role == "student" and invite.course_id:
            upsert_course_membership(db, invite.course_id, membership.id)
        if not consume_invite_if_pending(db, invite):
            if activation_state_exists(db, invite, identity.auth_user_id):
                repair_consumed_activation_state(
                    db,
                    invite=invite,
                    auth_user_id=identity.auth_user_id,
                    email=invite.email,
                )
                db.commit()
                return ActivateOAuthCompleteResponse(status="activated")
            db.rollback()
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid_invite")
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="activation_failed") from exc

    audit_log(
        "activate.oauth",
        "activated",
        auth_user_id=identity.auth_user_id,
        invite_id=invite.id,
        invite_hash_prefix=invite.token_hash[:12],
        http_status=status.HTTP_200_OK,
        reason="activated",
    )
    return ActivateOAuthCompleteResponse(status="activated")


@app.post("/api/suggest", response_model=SuggestResponse)
async def suggest_context(req: SuggestRequest) -> SuggestResponse:
    try:
        return await generate_suggestion(req)
    except json.JSONDecodeError:
        logger.error("JSONDecodeError in suggest", exc_info=True)
        raise HTTPException(status_code=500, detail="Invalid JSON from LLM.")
    except Exception as exc:
        logger.error("Error in suggest: %s", str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def create_frontend_router(build_dir: str = "../frontend/dist") -> Any:
    build_path = pathlib.Path(__file__).parent.parent.parent / build_dir
    if not build_path.is_dir() or not (build_path / "index.html").is_file():
        from starlette.routing import Route

        async def dummy_frontend(request: Any) -> Response:
            return Response("Frontend not built.", media_type="text/plain", status_code=503)

        return Route("/{path:path}", endpoint=dummy_frontend)
    return StaticFiles(directory=build_path, html=True)


app.mount("/app", create_frontend_router(), name="frontend")


if __name__ == "__main__":
    main()
