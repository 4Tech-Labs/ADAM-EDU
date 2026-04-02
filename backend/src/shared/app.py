from collections.abc import AsyncIterator
import json
import logging
import uuid
import pathlib
from dotenv import load_dotenv
import os

load_dotenv() 

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Response, Depends, Header, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Any, Dict, Optional
from sse_starlette.sse import EventSourceResponse
import asyncio

# Database and models
from shared.database import get_db, SessionLocal
from shared.models import Tenant, User, Assignment, AuthoringJob
from case_generator.core.authoring import AuthoringService
from shared.progress_bus import subscribe, unsubscribe

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def normalize_auth_user_id(raw_user_id: str) -> str:
    """Reject legacy fake ids and keep auth-compatible UUID text canonical."""
    try:
        return str(uuid.UUID(raw_user_id))
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="teacher_id must be a UUID string compatible with Supabase Auth",
        ) from exc

# Lifespan management
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Reserved for future startup hooks.
    yield
    # Reserved for future shutdown hooks.
    logger.info("Cleaning up resources...")

# FastAPI application root for the teacher authoring MVP.
app = FastAPI(title="adam-v8.0 - Case Generation API", lifespan=lifespan)

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


# =====================================================================
# HEALTH CHECK
# =====================================================================

@app.get("/health")
async def health_check() -> dict[str, str]:
    """Cloud Run liveness/readiness probe. Returns 200 when the service is up."""
    return {"status": "ok", "service": "adam-v8.0"}


# =====================================================================
# AUTHORING INTAKE AND INTERNAL EXECUTION SEAMS
# =====================================================================

class IntakeRequest(BaseModel):
    teacher_id: str
    assignment_title: str
    # Teacher authoring form fields aligned with the current frontend payload.
    subject: str = ""
    academic_level: str = "Pregrado"
    industry: str = "General"
    student_profile: str = "business"
    case_type: str = "harvard_only"
    syllabus_module: str = ""
    scenario_description: str = ""
    guiding_question: str = ""

    # Additional teacher form fields persisted into the authoring payload.
    topic_unit: str = ""
    target_groups: list[str] = []
    eda_depth: Optional[str] = None        # "charts_only" | "charts_plus_explanation" | "charts_plus_code"
    include_python_code: bool = False
    suggested_techniques: list[str] = []
    available_from: Optional[str] = None   # ISO date string
    due_at: Optional[str] = None           # ISO date string

class JobCreatedResponse(BaseModel):
    job_id: str
    status: str
    message: str

@app.post("/api/authoring/jobs", response_model=JobCreatedResponse, status_code=202)
def create_authoring_job(
    req: IntakeRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> JobCreatedResponse:
    """
    Public intake endpoint for the teacher UI.
    Persists the Assignment and queued AuthoringJob, then schedules local
    background execution through AuthoringService.
    """
    teacher_id = normalize_auth_user_id(req.teacher_id)

    # Resolve the teacher or create a local development record if missing.
    teacher = db.query(User).filter(User.id == teacher_id).first()
    if not teacher:
        tenant = db.query(Tenant).first()
        if not tenant:
            tenant = Tenant(name="Global Tenant")
            db.add(tenant)
            db.commit()
            db.refresh(tenant)
        teacher = User(id=teacher_id, tenant_id=tenant.id, email=f"{teacher_id}@adam.edu", role="teacher")
        db.add(teacher)
        db.commit()

    # Create the draft Assignment that will receive blueprint and canonical output.
    assignment = Assignment(teacher_id=teacher.id, title=req.assignment_title, status="draft")
    db.add(assignment)
    db.commit()
    db.refresh(assignment)

    # Create the queued AuthoringJob and persist the normalized intake payload.
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
            # Additional teacher form fields kept for downstream authoring.
            "topicUnit": req.topic_unit,
            "targetGroups": req.target_groups,
            "edaDepth": req.eda_depth,
            "includePythonCode": req.include_python_code,
            "algoritmos": req.suggested_techniques,
            "availableFrom": req.available_from,
            "dueAt": req.due_at,
        }
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Local and dev execution run immediately through BackgroundTasks.
    # The internal task endpoint remains available as an orchestration seam.
    logger.info(f"Intake complete. Job {job.id} enqueued (mock). Assignment: {assignment.id}")
    
    background_tasks.add_task(AuthoringService.run_job, job.id)

    return JobCreatedResponse(
        job_id=job.id,
        status="accepted",
        message="Authoring job accepted and dispatched to queue."
    )



class InternalTaskPayload(BaseModel):
    job_id: str
    idempotency_key: str

@app.post("/api/internal/tasks/authoring_step", status_code=200)
async def process_authoring_job_task(
    payload: InternalTaskPayload,
    db: Session = Depends(get_db),
    # Cloud Tasks may provide this header; local orchestration may omit it.
    x_cloudtasks_taskname: str | None = Header(None) 
) -> dict[str, str]:
    """
    Internal authoring execution seam.
    Preserved for queue-style dispatch compatibility while local development uses
    BackgroundTasks. Enforces idempotency and delegates execution to AuthoringService.
    """
    logger.info(f"Received Cloud Task execution for job {payload.job_id} | Task: {x_cloudtasks_taskname}")

    job = db.query(AuthoringJob).filter(AuthoringJob.id == payload.job_id).first()
    if not job:
        logger.error("Job not found. Discarding task.")
        raise HTTPException(status_code=404, detail="Job not found")

    # Fast Idempotency Barrier: Tolerate retries without side effects
    if job.status in ["completed", "failed", "processing"]:
        logger.warning(f"IDEMPOTENCY TRIGGERED: Job {job.id} is already {job.status}. Bypassing execution.")
        return {"status": "bypassed", "reason": f"idempotency_barrier: {job.status}"}

    # Delegate full execution and state management to the AuthoringService
    await AuthoringService.run_job(job.id)

    return {"status": "success", "job_id": job.id}


# =====================================================================
# JOB STATUS AND RESULT ENDPOINTS
# =====================================================================

class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    assignment_id: str
    created_at: str
    updated_at: str
    error_trace: Optional[str] = None

class JobResultResponse(BaseModel):
    job_id: str
    assignment_id: str
    blueprint: dict
    canonical_output: Optional[Dict[str, Any]] = None  # Teacher preview payload; blueprint remains for internal compatibility.

@app.get("/api/authoring/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str, db: Session = Depends(get_db)) -> JobStatusResponse:
    """
    Public polling endpoint for the current AuthoringJob status.
    Includes error_trace only when the job has failed.
    """
    job = db.query(AuthoringJob).filter(AuthoringJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    error_trace = None
    if job.status == "failed" and job.task_payload:
        error_trace = job.task_payload.get("error_trace")

    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        assignment_id=job.assignment_id,
        created_at=job.created_at.isoformat() if job.created_at else "",
        updated_at=job.updated_at.isoformat() if job.updated_at else "",
        error_trace=error_trace
    )

@app.get("/api/authoring/jobs/{job_id}/result", response_model=JobResultResponse)
def get_job_result(job_id: str, db: Session = Depends(get_db)) -> JobResultResponse:
    """
    Fetch the persisted result for a completed AuthoringJob.
    Returns the internal blueprint plus canonical_output for the teacher preview.
    """
    job = db.query(AuthoringJob).filter(AuthoringJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Job not ready",
            headers={"X-Job-Status": job.status}
        )

    assignment = db.query(Assignment).filter(Assignment.id == job.assignment_id).first()
    if not assignment or not assignment.blueprint:
        raise HTTPException(
            status_code=409,
            detail="Job completed but blueprint not yet available"
        )

    return JobResultResponse(
        job_id=job.id,
        assignment_id=assignment.id,
        blueprint=assignment.blueprint,
        canonical_output=assignment.canonical_output,
    )


# =====================================================================
# SSE PROGRESS ENDPOINT
# =====================================================================

class JobProgressEvent(BaseModel):
    step: str
    progress: float  # 0.0 a 1.0
    message: str

# Mapping of internal graph nodes to teacher-facing progress messages.
NODE_PROGRESS = {
    "input_adapter": (0.02, "Preparando configuración..."),
    "case_architect": (0.08, "Diseñando arquitectura del caso..."),
    "case_writer": (0.18, "Escribiendo narrativa del caso..."),
    "case_questions": (0.18, "Generando preguntas de discusión..."),
    "schema_designer": (0.25, "Diseñando estructura de datos..."),
    "data_generator": (0.30, "Generando dataset sintético..."),
    "data_validator": (0.33, "Validando calidad del dataset..."),
    "eda_text_analyst": (0.40, "Analizando datos exploratoriamente..."),
    "eda_chart_generator": (0.48, "Generando gráficos del EDA..."),
    "eda_questions_generator": (0.55, "Creando preguntas del EDA..."),
    "notebook_generator": (0.55, "Generando notebook Python..."),
    "m3_content_generator": (0.62, "Generando auditoría de evidencia (M3)..."),
    "m3_questions_generator": (0.66, "Preguntas M3..."),
    "m3_chart_generator": (0.66, "Gráficos M3..."),
    "m4_content_generator": (0.72, "Generando proyección financiera (M4)..."),
    "m4_questions_generator": (0.76, "Preguntas M4..."),
    "m4_chart_generator": (0.76, "Gráficos M4..."),
    "m5_content_generator": (0.82, "Generando recomendación ejecutiva (M5)..."),
    "teaching_note_part1": (0.82, "Escribiendo Teaching Note (parte 1)..."),
    "m5_questions_generator": (0.90, "Preguntas de síntesis M5..."),
    "teaching_note_part2": (0.95, "Completando Teaching Note (parte 2)..."),
    "output_adapter_final": (0.99, "Finalizando caso..."),
}

@app.get("/api/authoring/jobs/{job_id}/progress", response_class=EventSourceResponse, response_model=None)
async def stream_job_progress(job_id: str) -> EventSourceResponse:
    """SSE endpoint with immediate queue push plus DB catch-up for late connections."""
    async def event_publisher() -> AsyncIterator[dict[str, str]]:
        queue = subscribe(job_id)
        try:
            # Catch-up path for clients that connect after the job has already advanced.
            db = SessionLocal()
            try:
                job = db.query(AuthoringJob).filter_by(id=job_id).first()
                if not job:
                    yield {"event": "error", "data": json.dumps({"detail": "Job no encontrado"})}
                    return
                if job.status == "completed":
                    assignment = db.query(Assignment).filter(Assignment.id == job.assignment_id).first()
                    result_data = assignment.canonical_output if assignment and assignment.canonical_output else {}
                    yield {"event": "result", "data": json.dumps({"canonical_output": result_data})}
                    return
                if job.status == "failed":
                    error_msg = job.task_payload.get("error_trace", "Error en generación") if job.task_payload else "Error en generación"
                    yield {"event": "error", "data": json.dumps({"detail": error_msg})}
                    return
                yield {"event": "metadata", "data": json.dumps({"status": job.status})}
                current_step = (job.task_payload or {}).get("current_step")
                if current_step:
                    yield {"event": "message", "data": json.dumps({"node": current_step})}
            finally:
                db.close()

            # Real-time queue drain until the job reaches a terminal state.
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=25.0)
                except asyncio.TimeoutError:
                    # Heartbeat safety net in case a terminal event was missed.
                    db = SessionLocal()
                    try:
                        job = db.query(AuthoringJob).filter_by(id=job_id).first()
                        if job and job.status == "completed":
                            assignment = db.query(Assignment).filter(Assignment.id == job.assignment_id).first()
                            result_data = assignment.canonical_output if assignment and assignment.canonical_output else {}
                            yield {"event": "result", "data": json.dumps({"canonical_output": result_data})}
                            return
                        if job and job.status == "failed":
                            error_msg = job.task_payload.get("error_trace", "Error en generación") if job.task_payload else "Error en generación"
                            yield {"event": "error", "data": json.dumps({"detail": error_msg})}
                            return
                    finally:
                        db.close()
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



# =====================================================================
# TEACHER FORM SUGGEST ENDPOINT
# =====================================================================
from case_generator.suggest_service import SuggestRequest, SuggestResponse, generate_suggestion

@app.post("/api/suggest", response_model=SuggestResponse)
async def suggest_context(req: SuggestRequest) -> SuggestResponse:
    try:
        return await generate_suggestion(req)
    except json.JSONDecodeError:
        logger.error("JSONDecodeError in suggest", exc_info=True)
        raise HTTPException(status_code=500, detail="Invalid JSON from LLM.")
    except Exception as e:
        logger.error(f"Error in suggest: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================================
# Frontend Static Files
# =====================================================================
def create_frontend_router(build_dir: str = "../frontend/dist") -> Any:
    build_path = pathlib.Path(__file__).parent.parent.parent / build_dir
    if not build_path.is_dir() or not (build_path / "index.html").is_file():
        from starlette.routing import Route
        async def dummy_frontend(request: Any) -> Response:
            return Response("Frontend not built.", media_type="text/plain", status_code=503)
        return Route("/{path:path}", endpoint=dummy_frontend)
    return StaticFiles(directory=build_path, html=True)

app.mount("/app", create_frontend_router(), name="frontend")



