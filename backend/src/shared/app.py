from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import asyncio
import json
import logging
import os
import pathlib
import threading
import time
from typing import Any
import uuid

from pythonjsonlogger.json import JsonFormatter

from cachetools import TTLCache

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from case_generator.core.authoring import AuthoringService
from case_generator.suggest_service import SuggestRequest, SuggestResponse, generate_suggestion
from shared.auth import (
    AuthError,
    CurrentActor,
    VerifiedIdentity,
    audit_log,
    ensure_legacy_teacher_bridge,
    get_supabase_admin_auth_client,
    hash_invite_token,
    mask_email,
    normalize_email,
    require_current_actor,
    require_teacher_actor,
    require_verified_identity,
)
from shared.database import SessionLocal, get_db
from shared.models import (
    AllowedEmailDomain,
    Assignment,
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
from shared.progress_bus import subscribe, unsubscribe

load_dotenv()

_json_handler = logging.StreamHandler()
_json_handler.setFormatter(JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
logging.basicConfig(handlers=[_json_handler], level=logging.INFO, force=True)
logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def invite_effective_status(invite: Invite) -> str:
    if invite.status == "pending" and invite.expires_at <= utc_now():
        return "expired"
    return invite.status


def get_legacy_teacher_or_500(db: Session, actor: CurrentActor) -> User:
    return ensure_legacy_teacher_bridge(db, actor)


def get_owned_job_or_404(db: Session, job_id: str, actor: CurrentActor) -> AuthoringJob:
    stmt = (
        select(AuthoringJob)
        .join(Assignment, AuthoringJob.assignment_id == Assignment.id)
        .where(
            AuthoringJob.id == job_id,
            Assignment.teacher_id == actor.auth_user_id,
        )
    )
    job = db.scalar(stmt)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


def get_invite_by_token(db: Session, invite_token: str) -> Invite | None:
    return db.scalar(select(Invite).where(Invite.token_hash == hash_invite_token(invite_token)))


def require_invite_email_match(invite: Invite, email: str | None) -> None:
    if normalize_email(invite.email) != normalize_email(email):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid_invite_actor")


def upsert_profile(db: Session, auth_user_id: str, full_name: str | None) -> Profile:
    profile = db.scalar(select(Profile).where(Profile.id == auth_user_id))
    if profile is None:
        if not full_name:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="full_name_required")
        profile = Profile(id=auth_user_id, full_name=full_name.strip())
        db.add(profile)
        db.flush()
        return profile

    if full_name and profile.full_name != full_name.strip():
        profile.full_name = full_name.strip()
        db.flush()
    return profile


def upsert_membership(db: Session, auth_user_id: str, university_id: str, role: str) -> Membership:
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == auth_user_id,
            Membership.university_id == university_id,
            Membership.role == role,
        )
    )
    if membership is not None:
        membership.status = "active"
        membership.must_rotate_password = False
        db.flush()
        return membership

    membership = Membership(
        user_id=auth_user_id,
        university_id=university_id,
        role=role,
        status="active",
        must_rotate_password=False,
    )
    db.add(membership)
    db.flush()
    return membership


def upsert_course_membership(db: Session, course_id: str, membership_id: str) -> tuple[CourseMembership, bool]:
    course_membership = db.scalar(
        select(CourseMembership).where(
            CourseMembership.course_id == course_id,
            CourseMembership.membership_id == membership_id,
        )
    )
    if course_membership is not None:
        return course_membership, False

    inserted_id = db.execute(
        pg_insert(CourseMembership)
        .values(course_id=course_id, membership_id=membership_id)
        .on_conflict_do_nothing(constraint="uix_course_membership")
        .returning(CourseMembership.id)
    ).scalar_one_or_none()

    if inserted_id is None:
        existing = db.scalar(
            select(CourseMembership).where(
                CourseMembership.course_id == course_id,
                CourseMembership.membership_id == membership_id,
            )
        )
        if existing is None:  # pragma: no cover
            raise RuntimeError("course_membership_upsert_failed")
        return existing, False

    created_membership = db.get(CourseMembership, inserted_id)
    if created_membership is None:  # pragma: no cover
        raise RuntimeError("course_membership_inserted_but_missing")
    return created_membership, True


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


def derive_oauth_full_name(identity: VerifiedIdentity) -> str | None:
    user_metadata = identity.claims.get("user_metadata")
    if isinstance(user_metadata, dict):
        for key in ("full_name", "name"):
            value = user_metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if identity.email:
        return identity.email.split("@", maxsplit=1)[0]
    return None


def derive_activation_full_name(full_name: str | None, email: str) -> str:
    normalized = (full_name or "").strip()
    if normalized:
        return normalized
    return email.split("@", maxsplit=1)[0]


# ---------------------------------------------------------------------------
# Domain validation cache — TTL 5 min, thread-safe via explicit lock.
# Empty list means no domain restriction configured for that university.
# ---------------------------------------------------------------------------
_allowed_domains_cache: TTLCache[str, list[str]] = TTLCache(maxsize=100, ttl=300)
_allowed_domains_lock = threading.Lock()


def _get_allowed_domains(db: Session, university_id: str) -> list[str]:
    """Return allowed email domains for a university, with TTL caching."""
    with _allowed_domains_lock:
        if university_id in _allowed_domains_cache:
            return _allowed_domains_cache[university_id]
    domains = db.scalars(
        select(AllowedEmailDomain.domain).where(
            AllowedEmailDomain.university_id == university_id,
        )
    ).all()
    result = [d.lower() for d in domains]
    with _allowed_domains_lock:
        _allowed_domains_cache[university_id] = result
    return result


def _check_student_email_domain(db: Session, invite: Invite) -> None:
    """Raise 422 if the invite email domain is not in the university's allow-list.

    A university with no configured domains has an open allow-list (all domains
    accepted). This preserves backward-compatibility for existing universities
    that have not yet configured allowed_email_domains.
    """
    email_domain = invite.email.split("@")[-1].lower()
    allowed = _get_allowed_domains(db, invite.university_id)
    if allowed and email_domain not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="email_domain_not_allowed",
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    logger.info("Cleaning up resources...")


app = FastAPI(title="adam-v8.0 - Case Generation API", lifespan=lifespan)


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
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.code}, headers=headers)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "adam-v8.0"}


class IntakeRequest(BaseModel):
    assignment_title: str
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
    eda_depth: str | None = None
    include_python_code: bool = False
    suggested_techniques: list[str] = []
    available_from: str | None = None
    due_at: str | None = None


class JobCreatedResponse(BaseModel):
    job_id: str
    status: str
    message: str


@app.post("/api/authoring/jobs", response_model=JobCreatedResponse, status_code=202)
def create_authoring_job(
    req: IntakeRequest,
    background_tasks: BackgroundTasks,
    actor: CurrentActor = Depends(require_teacher_actor),
    db: Session = Depends(get_db),
) -> JobCreatedResponse:
    teacher = get_legacy_teacher_or_500(db, actor)

    assignment = Assignment(teacher_id=teacher.id, title=req.assignment_title, status="draft")
    db.add(assignment)
    db.commit()
    db.refresh(assignment)

    idempotency_key = f"job-init-{assignment.id}-{uuid.uuid4()}"
    job = AuthoringJob(
        assignment_id=assignment.id,
        idempotency_key=idempotency_key,
        status="pending",
        task_payload={
            "step": "authoring",
            "asignatura": req.subject or req.assignment_title,
            "nivel": req.academic_level,
            "industria": req.industry,
            "studentProfile": req.student_profile,
            "caseType": req.case_type,
            "modulo": req.syllabus_module,
            "escenario": req.scenario_description,
            "pregunta_guia": req.guiding_question,
            "topicUnit": req.topic_unit,
            "targetGroups": req.target_groups,
            "edaDepth": req.eda_depth,
            "includePythonCode": req.include_python_code,
            "algoritmos": req.suggested_techniques,
            "availableFrom": req.available_from,
            "dueAt": req.due_at,
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


@app.get("/api/authoring/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(
    job_id: str,
    actor: CurrentActor = Depends(require_teacher_actor),
    db: Session = Depends(get_db),
) -> JobStatusResponse:
    job = get_owned_job_or_404(db, job_id, actor)
    error_trace = None
    if job.status == "failed" and job.task_payload:
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

    return JobResultResponse(
        job_id=job.id,
        assignment_id=assignment.id,
        blueprint=assignment.blueprint,
        canonical_output=assignment.canonical_output,
    )


@app.get("/api/authoring/jobs/{job_id}/progress", response_class=EventSourceResponse, response_model=None)
async def stream_job_progress(
    job_id: str,
    actor: CurrentActor = Depends(require_teacher_actor),
    db: Session = Depends(get_db),
) -> EventSourceResponse:
    get_owned_job_or_404(db, job_id, actor)

    async def event_publisher() -> AsyncIterator[dict[str, str]]:
        queue = subscribe(job_id)
        try:
            db_local = SessionLocal()
            try:
                job = db_local.scalar(select(AuthoringJob).where(AuthoringJob.id == job_id))
                if not job:
                    yield {"event": "error", "data": json.dumps({"detail": "Job no encontrado"})}
                    return
                if job.status == "completed":
                    assignment = db_local.scalar(select(Assignment).where(Assignment.id == job.assignment_id))
                    result_data = assignment.canonical_output if assignment and assignment.canonical_output else {}
                    yield {"event": "result", "data": json.dumps({"canonical_output": result_data})}
                    return
                if job.status == "failed":
                    error_msg = job.task_payload.get("error_trace", "Error en generacion") if job.task_payload else "Error en generacion"
                    yield {"event": "error", "data": json.dumps({"detail": error_msg})}
                    return
                yield {"event": "metadata", "data": json.dumps({"status": job.status})}
                current_step = (job.task_payload or {}).get("current_step")
                if current_step:
                    yield {"event": "message", "data": json.dumps({"node": current_step})}
            finally:
                db_local.close()

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=25.0)
                except asyncio.TimeoutError:
                    db_local = SessionLocal()
                    try:
                        job = db_local.scalar(select(AuthoringJob).where(AuthoringJob.id == job_id))
                        if job and job.status == "completed":
                            assignment = db_local.scalar(select(Assignment).where(Assignment.id == job.assignment_id))
                            result_data = assignment.canonical_output if assignment and assignment.canonical_output else {}
                            yield {"event": "result", "data": json.dumps({"canonical_output": result_data})}
                            return
                        if job and job.status == "failed":
                            error_msg = job.task_payload.get("error_trace", "Error en generacion") if job.task_payload else "Error en generacion"
                            yield {"event": "error", "data": json.dumps({"detail": error_msg})}
                            return
                    finally:
                        db_local.close()
                    yield {"event": "metadata", "data": json.dumps({"status": "processing"})}
                    continue

                etype = event.get("type")
                if etype == "step":
                    yield {"event": "message", "data": json.dumps({"node": event["node"]})}
                elif etype == "metadata":
                    yield {"event": "metadata", "data": json.dumps({"status": event["status"]})}
                elif etype == "completed":
                    yield {"event": "result", "data": json.dumps({"canonical_output": event["result"]})}
                    return
                elif etype == "failed":
                    yield {"event": "error", "data": json.dumps({"detail": event["error"]})}
                    return
        finally:
            unsubscribe(job_id, queue)

    return EventSourceResponse(event_publisher())


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


@app.get("/api/auth/me", response_model=AuthMeResponse)
def get_auth_me(actor: CurrentActor = Depends(require_current_actor)) -> AuthMeResponse:
    audit_log(
        "session.verified",
        "success",
        auth_user_id=actor.auth_user_id,
        http_status=200,
    )
    return AuthMeResponse(
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
            reason="not_admin",
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin_role_required")

    # [C] Rotation guard — 403 if flag already cleared
    if not actor.must_rotate_password:
        audit_log(
            "admin.change_password",
            "denied",
            auth_user_id=actor.auth_user_id,
            http_status=403,
            reason="rotation_not_required",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="password_rotation_not_required",
        )

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
            reason="auth_update_failed",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="password_update_failed",
        ) from exc

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
            reason="invalid_invite",
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invalid_invite")

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
    actor: CurrentActor = Depends(require_current_actor),
    db: Session = Depends(get_db),
) -> InviteRedeemResponse:
    if not actor.has_active_role("student"):
        audit_log(
            "invite.redeem",
            "denied",
            auth_user_id=actor.auth_user_id,
            http_status=status.HTTP_403_FORBIDDEN,
            reason="student_membership_required",
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="membership_required")

    invite = get_invite_by_token(db, req.invite_token)
    if invite is None or invite.role != "student" or invite.course_id is None:
        audit_log(
            "invite.redeem",
            "invalid",
            auth_user_id=actor.auth_user_id,
            invite_hash_prefix=hash_invite_token(req.invite_token)[:12],
            http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
            reason="invalid_invite",
        )
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid_invite")

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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="membership_required")

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
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid_invite")

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
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid_invite")
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

    invite = get_invite_by_token(db, req.invite_token)
    if invite is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid_invite")

    admin_client = get_supabase_admin_auth_client()
    existing_user = admin_client.find_user_by_email(invite.email)
    effective_status = invite_effective_status(invite)
    if effective_status == "consumed" and existing_user and activation_state_exists(db, invite, existing_user.id):
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
        upsert_profile(db, auth_user.id, derive_activation_full_name(req.full_name, invite.email))
        membership = upsert_membership(db, auth_user.id, invite.university_id, invite.role)
        if invite.role == "student" and invite.course_id:
            upsert_course_membership(db, invite.course_id, membership.id)
        if not consume_invite_if_pending(db, invite):
            db.rollback()
            if activation_state_exists(db, invite, auth_user.id):
                return ActivatePasswordResponse(status="activated", next_step="sign_in", email=invite.email)
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
    invite = get_invite_by_token(db, req.invite_token)
    if invite is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid_invite")

    effective_status = invite_effective_status(invite)
    if effective_status == "consumed" and activation_state_exists(db, invite, identity.auth_user_id):
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
        upsert_profile(db, identity.auth_user_id, derive_oauth_full_name(identity))
        membership = upsert_membership(db, identity.auth_user_id, invite.university_id, invite.role)
        if invite.role == "student" and invite.course_id:
            upsert_course_membership(db, invite.course_id, membership.id)
        if not consume_invite_if_pending(db, invite):
            db.rollback()
            if activation_state_exists(db, invite, identity.auth_user_id):
                return ActivateOAuthCompleteResponse(status="activated")
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
