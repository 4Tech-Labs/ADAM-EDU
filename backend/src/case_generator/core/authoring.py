from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from psycopg import Error as PsycopgError
from psycopg_pool import PoolClosed, PoolTimeout
import time
import traceback
import uuid
from typing import Any, Literal, Mapping, cast

from case_generator.core.artifact_manager import ArtifactManager
from case_generator.core.storage import get_storage_provider
from case_generator.graph import DurableCheckpointUnavailableError, RESUME_CACHE_STATE_KEY, get_graph
from case_generator.orchestration.frontend_output_adapter import adapter_legacy_to_canonical_output
from langchain_core.runnables import RunnableConfig
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.exc import TimeoutError as SATimeoutError
from shared.blueprint_schema import (
    ArtifactManifestProjection,
    AssignmentBlueprint,
    ConfigObject,
    DeterministicCheck,
    GradingContract,
    ModuleManifest,
    ModuleManifests,
    RoutingManifest,
    StudentArtifacts,
    ValidationContract,
)
from shared.database import SessionLocal, register_active_authoring_job, settings, unregister_active_authoring_job
from shared.models import (
    AUTHORING_JOB_RETRYABLE_STATUSES,
    AUTHORING_JOB_STATUS_COMPLETED,
    AUTHORING_JOB_STATUS_FAILED,
    AUTHORING_JOB_STATUS_FAILED_RESUMABLE,
    AUTHORING_JOB_STATUS_PROCESSING,
    Assignment,
    AuthoringJob,
)
from shared.sanitization import sanitize_untrusted_text

logger = logging.getLogger(__name__)

DEFAULT_TWIN_ROLE_SYSTEM_PROMPT = (
    "Eres el twin socratico del modulo de narrativa. "
    "Ayuda al estudiante a aclarar el problema central, identificar evidencia del caso "
    "y contrastar stakeholders sin resolverle la decision final."
)
SUPPORTED_CONTEXT_KEYS = [
    "student_artifacts.narrative_text",
    "student_artifacts.eda_summary",
]
NARRATIVE_ARTIFACT_LIMIT = 30000
EDA_ARTIFACT_LIMIT = 40000

# Keep this list synchronized with frontend PIPELINE_STEPS ids in
# frontend/src/features/teacher-authoring/AuthoringProgressTimeline.tsx.
CANONICAL_TIMELINE_STEP_IDS = (
    "case_architect",
    "case_writer",
    "eda_text_analyst",
    "m3_content_generator",
    "m4_content_generator",
    "m5_content_generator",
    "teaching_note_part1",
)
NARRATIVE_TIMELINE_STEP_IDS = (
    "case_architect",
    "case_writer",
    "m4_content_generator",
    "m5_content_generator",
    "teaching_note_part1",
)
TERMINAL_PROGRESS_STEPS = ("completed", "failed")
_FIRST_CANONICAL_STEP = CANONICAL_TIMELINE_STEP_IDS[0]

# Internal graph nodes are translated to stable timeline steps so the UI receives
# deterministic progress values even if the orchestration graph evolves.
_GRAPH_AGENT_TO_CANONICAL_STEP = {
    "case_architect": "case_architect",
    "case_writer": "case_writer",
    "case_questions": "case_writer",
    "doc3_generation": "case_writer",
    "data_generator": "eda_text_analyst",
    "data_validator": "eda_text_analyst",
    "eda_text_analyst": "eda_text_analyst",
    "eda_chart_generator": "eda_text_analyst",
    "m3_content_generator": "m3_content_generator",
    "m3_questions_generator": "m3_content_generator",
    "m3_notebook_generator": "m3_content_generator",
    "m4_content_generator": "m4_content_generator",
    "m4_chart_generator": "m4_content_generator",
    "m4_questions_generator": "m4_content_generator",
    "m5_content_generator": "m5_content_generator",
    "m5_questions_generator": "m5_content_generator",
    "teaching_note_part1": "teaching_note_part1",
    "teaching_note_part2": "teaching_note_part1",
    "processing": _FIRST_CANONICAL_STEP,
}

_PROGRESS_DEGRADATION_KEYS = (
    "progress_degraded",
    "progress_degraded_step",
    "progress_degraded_reason",
    "progress_degraded_retries",
    "progress_degraded_at",
    "progress_degraded_error",
)
_RESUME_PREFETCH_WARN_MS = 25.0

_RESUMABLE_FAILURE_CODES = {
    "bootstrap_timeout",
    "checkpoint_unavailable",
    "llm_timeout",
    "llm_provider_unavailable",
    "llm_rate_limited",
}

BOOTSTRAP_STATE_INITIALIZING = "initializing"
_BOOTSTRAP_STATE_KEYS = (
    "bootstrap_state",
    "bootstrap_started_at",
    "bootstrap_timeout_seconds",
)


class GraphBootstrapTimeoutError(RuntimeError):
    """Raised when the graph bootstrap exceeds the configured timeout."""

_TRANSIENT_TIMEOUT_MARKERS = (
    "timed out",
    "read timeout",
    "connect timeout",
    "readtimeout",
    "connecttimeout",
    "deadline exceeded",
)

_TRANSIENT_PROVIDER_UNAVAILABLE_MARKERS = (
    "503",
    "service unavailable",
    "temporarily unavailable",
    "high demand",
    "connection reset",
    "connection aborted",
    "network is unreachable",
)

_DURABLE_CHECKPOINT_ERROR_MESSAGE = (
    "No se pudo inicializar la persistencia durable del proceso de generacion. "
    "Por favor, reintenta cuando el servicio de checkpoints este disponible."
)
_CHECKPOINT_INFRA_ERROR_TYPES = (
    DBAPIError,
    OperationalError,
    SATimeoutError,
    PsycopgError,
    PoolClosed,
    PoolTimeout,
)


def _classify_failure_status(error_code: str | None) -> str:
    """Map known transient failures to failed_resumable and default to failed."""
    if error_code in _RESUMABLE_FAILURE_CODES:
        return AUTHORING_JOB_STATUS_FAILED_RESUMABLE
    return AUTHORING_JOB_STATUS_FAILED


def _iter_exception_chain(exc: BaseException) -> list[BaseException]:
    """Return the causal chain for an exception without revisiting cycles."""
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc

    while current is not None and id(current) not in seen:
        chain.append(current)
        seen.add(id(current))
        current = current.__cause__ or current.__context__

    return chain


def _is_durable_checkpoint_runtime_failure(exc: BaseException) -> bool:
    """Return True when a graph stream error comes from checkpoint infra."""
    return any(
        isinstance(candidate, _CHECKPOINT_INFRA_ERROR_TYPES)
        for candidate in _iter_exception_chain(exc)
    )


def _to_canonical_progress_step(raw_step: str | None) -> str | None:
    """Translate internal graph agent ids into the stable timeline step contract."""
    if raw_step is None:
        return None

    normalized = raw_step.strip()
    if not normalized:
        return None

    if normalized in TERMINAL_PROGRESS_STEPS:
        return normalized

    mapped = _GRAPH_AGENT_TO_CANONICAL_STEP.get(normalized)
    if mapped:
        return mapped

    if normalized in CANONICAL_TIMELINE_STEP_IDS:
        return normalized

    return None


def _timeline_steps_for_payload(payload: Mapping[str, Any] | None) -> tuple[str, ...]:
    case_type = payload.get("caseType", "harvard_only") if payload else "harvard_only"
    return NARRATIVE_TIMELINE_STEP_IDS if case_type == "harvard_only" else CANONICAL_TIMELINE_STEP_IDS


def derive_progress_percentage(
    payload: Mapping[str, Any] | None,
    *,
    current_step: str | None,
    status: str | None,
) -> int | None:
    """Match the frontend timeline percentage from the canonical persisted step."""
    if status == AUTHORING_JOB_STATUS_COMPLETED or current_step == "completed":
        return 100

    canonical_step = _to_canonical_progress_step(current_step)
    if canonical_step is None or canonical_step in TERMINAL_PROGRESS_STEPS:
        return None

    timeline_steps = _timeline_steps_for_payload(payload)
    try:
        step_index = timeline_steps.index(canonical_step)
    except ValueError:
        return None

    return round(((step_index + 1) / len(timeline_steps)) * 100)


def _clear_progress_degradation(payload: dict[str, Any]) -> None:
    for key in _PROGRESS_DEGRADATION_KEYS:
        payload.pop(key, None)


def _bootstrap_timeout_seconds() -> float:
    configured_timeout = settings.authoring_bootstrap_timeout_seconds
    if configured_timeout is not None and configured_timeout > 0:
        return float(configured_timeout)

    normalized_environment = settings.environment.strip().lower()
    return 120.0 if normalized_environment == "development" else 60.0


def _clear_bootstrap_state(payload: dict[str, Any]) -> None:
    for key in _BOOTSTRAP_STATE_KEYS:
        payload.pop(key, None)


def _mark_bootstrap_initializing(payload: dict[str, Any], *, timeout_seconds: float) -> None:
    payload["bootstrap_state"] = BOOTSTRAP_STATE_INITIALIZING
    payload["bootstrap_started_at"] = datetime.now(timezone.utc).isoformat()
    payload["bootstrap_timeout_seconds"] = round(timeout_seconds, 3)


def _remember_last_canonical_step(payload: dict[str, Any]) -> None:
    current_step = payload.get("current_step")
    if not isinstance(current_step, str):
        return

    canonical_step = _to_canonical_progress_step(current_step)
    if canonical_step is None or canonical_step in TERMINAL_PROGRESS_STEPS:
        return

    payload["last_known_step"] = canonical_step


def _processing_resume_step(payload: Mapping[str, Any] | None) -> str | None:
    if not payload:
        return None

    for key in ("current_step", "last_known_step"):
        raw_step = payload.get(key)
        if not isinstance(raw_step, str):
            continue

        canonical_step = _to_canonical_progress_step(raw_step)
        if canonical_step is None or canonical_step in TERMINAL_PROGRESS_STEPS:
            continue

        return canonical_step

    return None


def _persist_progress_degradation(
    *,
    job_id: str,
    canonical_step: str,
    max_attempts: int,
    error_detail: str,
) -> None:
    """Persist a durable degraded marker when intermediate progress writes exhaust retries."""
    db_degraded = SessionLocal()
    try:
        job_degraded = db_degraded.query(AuthoringJob).filter(AuthoringJob.id == job_id).first()
        if job_degraded is None:
            logger.error(
                "AuthoringService: Could not mark degraded progress state because job %s was not found.",
                job_id,
            )
            return

        payload = dict(job_degraded.task_payload or {})
        current_step = payload.get("current_step")
        canonical_current_step = (
            _to_canonical_progress_step(current_step)
            if isinstance(current_step, str)
            else None
        ) or _FIRST_CANONICAL_STEP

        payload = _next_progress_payload(
            payload,
            status="processing",
            current_step=canonical_current_step,
        )
        _clear_bootstrap_state(payload)
        payload["progress_degraded"] = True
        payload["progress_degraded_step"] = canonical_step
        payload["progress_degraded_reason"] = "intermediate_checkpoint_write_failed"
        payload["progress_degraded_retries"] = max_attempts
        payload["progress_degraded_at"] = datetime.now(timezone.utc).isoformat()
        payload["progress_degraded_error"] = error_detail[:500]
        job_degraded.task_payload = payload

        db_degraded.commit()
        logger.warning(
            "AuthoringService: Progress stream degraded for job %s after %s failed attempts at step '%s'.",
            job_id,
            max_attempts,
            canonical_step,
        )
    except Exception as exc:
        logger.error(
            "AuthoringService: Could not persist degraded progress state for job %s at step '%s': %s",
            job_id,
            canonical_step,
            exc,
        )
        db_degraded.rollback()
    finally:
        db_degraded.close()


async def _persist_intermediate_progress_step(
    *,
    job_id: str,
    canonical_step: str,
    max_attempts: int = 3,
    retry_base_delay_seconds: float = 0.2,
) -> bool:
    """Persist a canonical intermediate step with bounded retries and degraded fallback."""
    if canonical_step not in CANONICAL_TIMELINE_STEP_IDS:
        logger.warning(
            "AuthoringService: Skipping non-canonical progress step '%s' for job %s.",
            canonical_step,
            job_id,
        )
        return False

    last_error = "unknown_error"

    for attempt in range(1, max_attempts + 1):
        db_step = SessionLocal()
        try:
            job_step = db_step.query(AuthoringJob).filter(AuthoringJob.id == job_id).first()
            if job_step is None:
                logger.error(
                    "AuthoringService: Could not persist progress checkpoint because job %s was not found.",
                    job_id,
                )
                return False

            payload_step = _next_progress_payload(
                job_step.task_payload,
                status="processing",
                current_step=canonical_step,
            )
            _clear_bootstrap_state(payload_step)
            _clear_progress_degradation(payload_step)
            job_step.task_payload = payload_step
            db_step.commit()

            if attempt > 1:
                logger.warning(
                    "AuthoringService: Progress checkpoint write recovered for job %s at step '%s' (attempt %s/%s).",
                    job_id,
                    canonical_step,
                    attempt,
                    max_attempts,
                )
            return True
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "AuthoringService: Progress checkpoint write failed for job %s at step '%s' (attempt %s/%s): %s",
                job_id,
                canonical_step,
                attempt,
                max_attempts,
                exc,
            )
            db_step.rollback()
            if attempt < max_attempts and retry_base_delay_seconds > 0:
                await asyncio.sleep(retry_base_delay_seconds * (2 ** (attempt - 1)))
        finally:
            db_step.close()

    _persist_progress_degradation(
        job_id=job_id,
        canonical_step=canonical_step,
        max_attempts=max_attempts,
        error_detail=last_error,
    )
    return False


def _next_progress_payload(
    existing_payload: Mapping[str, Any] | None,
    *,
    status: str,
    current_step: str | None = None,
    error_code: str | None = None,
    error_trace: str | None = None,
) -> dict[str, Any]:
    """Build a monotonic progress payload persisted in authoring_jobs.task_payload."""
    payload = dict(existing_payload or {})

    previous_seq = payload.get("progress_seq")
    progress_seq = previous_seq if isinstance(previous_seq, int) else 0

    payload["progress_seq"] = progress_seq + 1
    payload["progress_ts"] = datetime.now(timezone.utc).isoformat()
    payload["progress_status"] = status

    if current_step is not None:
        payload["current_step"] = current_step
    if error_code is not None:
        payload["error_code"] = error_code
    if error_trace is not None:
        payload["error_trace"] = error_trace

    return payload


def _derive_output_depth(payload: Mapping[str, Any]) -> str | None:
    """Determine the graph output depth from the current intake payload."""
    case_type = payload.get("caseType", "harvard_only")
    student_profile = payload.get("studentProfile", "business")
    eda_depth = payload.get("edaDepth")
    include_python = payload.get("includePythonCode", False)

    if case_type == "harvard_only":
        return None
    if student_profile == "business":
        return "visual_plus_technical"
    if eda_depth == "charts_plus_code" or include_python is True:
        return "visual_plus_notebook"
    return "visual_plus_technical"


def _derive_routing_manifest(payload: Mapping[str, Any]) -> RoutingManifest:
    """Translate intake switches into the internal routing manifest stored in the blueprint."""
    case_type = payload.get("caseType", "harvard_only")
    eda_depth = payload.get("edaDepth")
    include_python = payload.get("includePythonCode", False)

    if case_type == "harvard_only":
        policy_type = "harvard_only"
        enabled_tabs = ["narrative"]
    elif eda_depth == "charts_only":
        policy_type = "charts_only"
        enabled_tabs = ["narrative", "eda"]
    elif eda_depth == "charts_plus_explanation":
        policy_type = "charts_plus_solution"
        enabled_tabs = ["narrative", "eda", "analysis"]
    elif eda_depth == "charts_plus_code" or include_python is True:
        policy_type = "charts_plus_code"
        enabled_tabs = ["narrative", "eda", "analysis", "notebook"]
    else:
        policy_type = "charts_plus_solution"
        enabled_tabs = ["narrative", "eda", "analysis"]

    return RoutingManifest(policy_type=policy_type, enabled_tabs=enabled_tabs)


def _extract_text_field(graph_output: Mapping[str, Any], key: str, max_chars: int) -> str:
    """Read and sanitize a text field from LangGraph output."""
    return sanitize_untrusted_text(graph_output.get(key), max_chars=max_chars)


def _is_useful_eda(eda_text: str) -> bool:
    """Ignore sentinel placeholders so only meaningful EDA text is summarized downstream."""
    normalized = eda_text.strip()
    return bool(normalized and normalized not in {"DATASET_UNAVAILABLE", "NO_EDA_AVAILABLE"})


def _build_eda_summary(eda_text: str) -> str | None:
    """Produce a deterministic, bounded EDA summary for the persisted blueprint."""
    if not _is_useful_eda(eda_text):
        return None
    return sanitize_untrusted_text(eda_text, max_chars=2000)


def _build_productive_blueprint(
    payload: Mapping[str, Any],
    narrative_text: str,
    eda_summary: str | None,
    artifact_ids: list[str],
) -> AssignmentBlueprint:
    """Assemble the internal AssignmentBlueprint persisted alongside canonical_output."""
    return AssignmentBlueprint(
        version="adam-v8.0",
        config_object=ConfigObject(
            language="es",
            difficulty=str(payload.get("nivel", "pregrado")),
            industry_context=sanitize_untrusted_text(payload.get("industria"), max_chars=255) or None,
            target_audience=sanitize_untrusted_text(payload.get("studentProfile"), max_chars=64) or None,
        ),
        routing_manifest=_derive_routing_manifest(payload),
        student_artifacts=StudentArtifacts(
            narrative_text=narrative_text,
            eda_summary=eda_summary,
            attached_datasets_manifest_ids=[],
        ),
        module_manifests=ModuleManifests(
            modules=[
                ModuleManifest(
                    module_id="doc1_narrativa",
                    twin_role_system_prompt=DEFAULT_TWIN_ROLE_SYSTEM_PROMPT,
                    isolated_memory=True,
                    allowed_context_keys=SUPPORTED_CONTEXT_KEYS.copy(),
                )
            ]
        ),
        grading_contract=GradingContract(
            deterministic_checks=[
                DeterministicCheck(
                    check_id="minimum_response_length",
                    requirement="Answer > 50 chars",
                    weight=0.3,
                ),
                DeterministicCheck(
                    check_id="references_case_evidence",
                    requirement="Mentions at least one stakeholder, exhibit, or case metric",
                    weight=0.2,
                ),
            ],
            qualitative_rubric={
                "problem_framing": {
                    "description": "Frames the core problem and tradeoff clearly.",
                    "max_score": 1.0,
                },
                "evidence_use": {
                    "description": "Uses case evidence from exhibits, stakeholders, or metrics.",
                    "max_score": 1.0,
                },
                "stakeholder_reasoning": {
                    "description": "Reasons through stakeholder incentives and consequences.",
                    "max_score": 1.0,
                },
            },
        ),
        validation_contract=ValidationContract(
            passing_threshold_global=0.6,
            required_modules_passed=1,
        ),
        artifact_manifest=ArtifactManifestProjection(artifact_ids=artifact_ids),
    )


class AuthoringService:
    """
    Coordinates LangGraph execution, artifact persistence, and progress events.
    Uses short-lived DB sessions so long LLM calls do not keep transactions open.
    """

    @classmethod
    async def run_job(cls, job_id: str) -> None:
        """
        Execute the full authoring pipeline asynchronously.
        Persists the internal blueprint plus canonical_output for the teacher preview.
        """
        logger.info("AuthoringService: Starting background execution for Job %s", job_id)

        assignment_id: str | None = None
        owner_id = ""
        payload: dict[str, Any] = {}
        error_code: str | None = None
        storage_provider = get_storage_provider()
        resume_cached_nodes: dict[str, dict[str, str]] = {}
        is_resume_retry = False

        # --- DB MICRO-SESSION 1: transition the job into processing ---
        # Winner-takes-lock CAS: only one concurrent retry may move status to processing.
        db = SessionLocal()
        try:
            existing_job = db.query(AuthoringJob).filter(AuthoringJob.id == job_id).first()
            if existing_job is None:
                logger.error("AuthoringService: Job %s not found in DB.", job_id)
                return

            is_resume_retry = existing_job.status == AUTHORING_JOB_STATUS_FAILED_RESUMABLE

            if existing_job.status in [
                AUTHORING_JOB_STATUS_COMPLETED,
                AUTHORING_JOB_STATUS_PROCESSING,
                AUTHORING_JOB_STATUS_FAILED,
            ]:
                logger.warning(
                    "AuthoringService: Job %s is already in terminal/processing state '%s'. Aborting.",
                    job_id,
                    existing_job.status,
                )
                return

            bootstrap_timeout_seconds = _bootstrap_timeout_seconds()
            processing_resume_step = _processing_resume_step(existing_job.task_payload)
            processing_payload = _next_progress_payload(
                existing_job.task_payload,
                status=AUTHORING_JOB_STATUS_PROCESSING,
                current_step=processing_resume_step,
            )
            if processing_resume_step is None:
                processing_payload.pop("current_step", None)
            processing_payload.pop("error_code", None)
            processing_payload.pop("error_trace", None)
            _mark_bootstrap_initializing(
                processing_payload,
                timeout_seconds=bootstrap_timeout_seconds,
            )
            lock_stmt = (
                update(AuthoringJob)
                .where(
                    AuthoringJob.id == job_id,
                    AuthoringJob.status.in_(AUTHORING_JOB_RETRYABLE_STATUSES),
                )
                .values(
                    status=AUTHORING_JOB_STATUS_PROCESSING,
                    retry_count=AuthoringJob.retry_count + 1,
                    task_payload=processing_payload,
                )
                .returning(AuthoringJob.assignment_id, AuthoringJob.task_payload)
            )
            locked_row = db.execute(lock_stmt).mappings().first()
            if locked_row is None:
                logger.info(
                    "AuthoringService: retry_lost_race for job %s; another worker already claimed processing.",
                    job_id,
                )
                db.rollback()
                return

            assignment_id = cast(str, locked_row["assignment_id"])
            payload = dict(locked_row["task_payload"] or {})

            assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
            if assignment is None:
                logger.error("AuthoringService: Assignment %s not found for job %s.", assignment_id, job_id)
                payload_with_error = _next_progress_payload(
                    payload,
                    status=AUTHORING_JOB_STATUS_FAILED,
                    current_step="failed",
                    error_code="assignment_missing",
                    error_trace="Assignment not found for authoring job.",
                )
                db.execute(
                    update(AuthoringJob)
                    .where(AuthoringJob.id == job_id)
                    .values(status=AUTHORING_JOB_STATUS_FAILED, task_payload=payload_with_error)
                )
                db.commit()
                return

            owner_id = assignment.teacher_id
            db.commit()
        except Exception as exc:
            logger.error("AuthoringService: Failure locking job %s: %s", job_id, exc)
            db.rollback()
            return
        finally:
            db.close()

        if assignment_id is None:
            logger.error("AuthoringService: Missing assignment_id for job %s after lock.", job_id)
            return

        if is_resume_retry:
            prefetch_started_at = time.perf_counter()
            prefetch_db = SessionLocal()
            try:
                resume_cached_nodes = await ArtifactManager.prefetch_resume_artifacts(
                    db=prefetch_db,
                    storage_provider=storage_provider,
                    assignment_id=assignment_id,
                )
            except Exception as exc:
                logger.warning(
                    "AuthoringService: Resume artifact prefetch failed for job %s: %s",
                    job_id,
                    exc,
                )
            finally:
                prefetch_db.close()

            prefetch_latency_ms = round((time.perf_counter() - prefetch_started_at) * 1000, 3)
            logger.info(
                "AuthoringService: Resume prefetch for job %s loaded %s node payload(s) in %s ms.",
                job_id,
                len(resume_cached_nodes),
                prefetch_latency_ms,
            )
            if prefetch_latency_ms > _RESUME_PREFETCH_WARN_MS:
                logger.warning(
                    "AuthoringService: Resume prefetch latency high for job %s: %s ms (threshold %s ms)",
                    job_id,
                    prefetch_latency_ms,
                    _RESUME_PREFETCH_WARN_MS,
                )

        # --- LANGGRAPH EXECUTION (no open DB session) ---
        # Retry/resume pipeline:
        #   failed_resumable job
        #     -> await get_graph()  [async lazy singleton, durable saver required]
        #     -> graph.astream(thread_id=job_id)
        #     -> checkpoint reload + explicit node skip/hydration
        #     -> completed | failed_resumable | failed
        graph_output: dict[str, Any] | None = None
        error_msg: str | None = None
        try:
            level_map = {
                "pregrado": "undergrad",
                "undergraduate": "undergrad",
                "posgrado": "grad",
                "graduate": "grad",
                "maestría": "grad",
                "maestria": "grad",
                "ejecutivo": "executive",
                "executive": "executive",
            }
            output_depth = _derive_output_depth(payload)
            scenario_description = payload.get("escenario", payload.get("scenarioDescription", ""))
            target_groups = payload.get("targetGroups", [])

            state_input: dict[str, Any] = {
                "asignatura": payload.get("asignatura", "Default Subject"),
                "nivel": payload.get("nivel", "pregrado"),
                "industria": payload.get("industria", "General"),
                "studentProfile": payload.get("studentProfile", "business"),
                "algoritmos": payload.get("algoritmos", []),
                "edaDepth": payload.get("edaDepth"),
                "includePythonCode": payload.get("includePythonCode", False),
                "topicUnit": payload.get("topicUnit", ""),
                "targetGroups": target_groups,
                "caseType": payload.get("caseType", "harvard_only"),
                "guidingQuestion": payload.get("pregunta_guia", payload.get("guidingQuestion", "")),
                "scenarioDescription": scenario_description,
                "syllabusModule": payload.get("modulo", payload.get("syllabusModule", "")),
                "output_depth": output_depth,
                # Legacy-compatible aliases still consumed by graph.py prompt builders.
                "modulos": target_groups,
                "horas": payload.get("horas", 4),
                "descripcion": scenario_description,
                "scope": "technical" if output_depth else "narrative",
                # Global graph context.
                "case_id": str(uuid.uuid4()),
                "course_level": level_map.get(str(payload.get("nivel", "posgrado")).lower(), "grad"),
                "output_language": "es",
                "is_docente_only": True,
                "max_investment_pct": 8,
                "urgency_frame": "48-96 horas",
                "protected_columns": ["target", "id", "date"],
                "industry_cagr_range": "5-8%",
                RESUME_CACHE_STATE_KEY: resume_cached_nodes,
            }

            # Inject hydrated artifacts into initial graph state so downstream nodes
            # keep context even when upstream generation is skipped.
            for node_payload in resume_cached_nodes.values():
                state_input.update(node_payload)

            register_active_authoring_job(job_id)
            try:
                bootstrap_started_at = time.perf_counter()
                try:
                    compiled_graph = await asyncio.wait_for(
                        get_graph(),
                        timeout=bootstrap_timeout_seconds,
                    )
                except asyncio.TimeoutError as exc:
                    raise GraphBootstrapTimeoutError(
                        f"Graph bootstrap exceeded {bootstrap_timeout_seconds} seconds"
                    ) from exc

                logger.info(
                    "AuthoringService: Graph bootstrap ready for Job %s",
                    job_id,
                    extra={
                        "bootstrap_latency_ms": round((time.perf_counter() - bootstrap_started_at) * 1000, 3),
                        "bootstrap_timeout_seconds": bootstrap_timeout_seconds,
                    },
                )

                run_config: RunnableConfig = {
                    "configurable": {
                        "thread_id": job_id,
                        "writer_model": "gemini-3-flash-preview",
                        "architect_model": "gemini-3-flash-preview",
                        "job_id": job_id,
                        "assignment_id": assignment_id,
                        "owner_id": owner_id,
                    }
                }

                logger.info(
                    "AuthoringService: Invoking LangGraph v8 for Job %s (case_id=%s)...",
                    job_id,
                    state_input["case_id"],
                )

                async def _run_graph_stream() -> dict[str, Any]:
                    final_state: dict[str, Any] = state_input.copy()
                    current_step = payload.get("current_step")
                    last_reported_step = (
                        _to_canonical_progress_step(current_step)
                        if isinstance(current_step, str)
                        else None
                    ) or _FIRST_CANONICAL_STEP
                    stream_mode: Literal["values"] = "values"
                    stream = cast(Any, compiled_graph).astream(
                        state_input,
                        config=run_config,
                        stream_mode=stream_mode,
                    )

                    async for event in stream:
                        final_state = dict(event)
                        current_agent = final_state.get("current_agent")
                        canonical_step = (
                            _to_canonical_progress_step(current_agent)
                            if isinstance(current_agent, str)
                            else None
                        )

                        if canonical_step and canonical_step != last_reported_step:
                            persisted = await _persist_intermediate_progress_step(
                                job_id=job_id,
                                canonical_step=canonical_step,
                            )
                            if persisted:
                                last_reported_step = canonical_step

                    return final_state

                graph_task = asyncio.create_task(_run_graph_stream(), name=f"authoring-job-{job_id}")
                graph_output = await asyncio.wait_for(graph_task, timeout=900)
                logger.info("AuthoringService: LangGraph execution finished for Job %s.", job_id)
            finally:
                unregister_active_authoring_job(job_id)
        except DurableCheckpointUnavailableError:
            logger.error(
                "AuthoringService: Durable checkpoint wiring unavailable for Job %s",
                job_id,
                exc_info=True,
            )
            error_code = "checkpoint_unavailable"
            error_msg = _DURABLE_CHECKPOINT_ERROR_MESSAGE
        except GraphBootstrapTimeoutError:
            logger.error(
                "AuthoringService: Graph bootstrap timeout for Job %s",
                job_id,
                exc_info=True,
            )
            error_code = "bootstrap_timeout"
            error_msg = (
                "La infraestructura de generacion tardo demasiado en inicializarse. "
                "Puedes reintentar sin perder el progreso ya completado."
            )
        except asyncio.TimeoutError:
            logger.error("AuthoringService: TIMEOUT — Job %s exceeded 900s", job_id)
            error_code = "llm_timeout"
            error_msg = (
                "Nuestros servidores de IA estan a maxima capacidad y el tiempo de espera se agoto. "
                "Por favor, reintenta en unos minutos."
            )
        except Exception as exc:
            if _is_durable_checkpoint_runtime_failure(exc):
                logger.error(
                    "AuthoringService: Durable checkpoint runtime failed for Job %s",
                    job_id,
                    exc_info=True,
                )
                error_code = "checkpoint_unavailable"
                error_msg = _DURABLE_CHECKPOINT_ERROR_MESSAGE
            else:
                # Secondary guard: catch DB/pool errors wrapped by LangGraph retry
                # machinery that escape the outer _is_durable_checkpoint_runtime_failure
                # check (e.g. RuntimeError -> __cause__ = PoolTimeout).
                if any(
                    isinstance(e, _CHECKPOINT_INFRA_ERROR_TYPES)
                    for e in _iter_exception_chain(exc)
                ):
                    logger.error(
                        "AuthoringService: Infra error in exception chain for Job %s",
                        job_id,
                        exc_info=True,
                    )
                    error_code = "checkpoint_unavailable"
                    error_msg = _DURABLE_CHECKPOINT_ERROR_MESSAGE
                else:
                    logger.error("AuthoringService: LangGraph raised exception for Job %s", job_id, exc_info=True)
                    error_trace = traceback.format_exc()
                    error_str = error_trace.lower()
                    if any(marker in error_str for marker in _TRANSIENT_TIMEOUT_MARKERS):
                        error_code = "llm_timeout"
                        error_msg = (
                            "Nuestros servidores de IA estan a maxima capacidad y el tiempo de espera se agoto. "
                            "Por favor, reintenta en unos minutos."
                        )
                    elif any(marker in error_str for marker in _TRANSIENT_PROVIDER_UNAVAILABLE_MARKERS):
                        error_code = "llm_provider_unavailable"
                        error_msg = (
                            "Nuestros servidores de IA estan experimentando un pico de trafico en este momento. "
                            "Por favor, reintenta en un par de minutos."
                        )
                    elif "429" in error_str or "quota" in error_str:
                        error_code = "llm_rate_limited"
                        error_msg = (
                            "Hemos alcanzado el limite de operaciones de IA permitidas por minuto. "
                            "Por favor, intenta generar el caso un poco mas tarde."
                        )
                    else:
                        error_code = "llm_unhandled_error"
                        error_msg = error_trace

        # --- MICRO-SESSION 2: Persist Results ---
        db = SessionLocal()
        try:
            job = db.query(AuthoringJob).filter(AuthoringJob.id == job_id).first()
            assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()

            if job is None or assignment is None:
                logger.error("AuthoringService: Missing persisted entities for finalization of job %s.", job_id)
                return

            if error_msg:
                failure_status = _classify_failure_status(error_code)
                job.status = failure_status
                existing_payload = dict(job.task_payload or {})
                _remember_last_canonical_step(existing_payload)
                current_payload = _next_progress_payload(
                    existing_payload,
                    status=failure_status,
                    current_step="failed",
                    error_code=error_code or "llm_failure",
                    error_trace=error_msg,
                )
                _clear_bootstrap_state(current_payload)
                job.task_payload = current_payload

                if failure_status == AUTHORING_JOB_STATUS_FAILED:
                    logger.error("AuthoringService: Job %s marked as FAILED. Cleaning up artifacts.", job_id)
                    ArtifactManager.orphan_job_artifacts(db, job_id)
                else:
                    logger.warning(
                        "AuthoringService: Job %s marked as FAILED_RESUMABLE after transient failure (%s).",
                        job_id,
                        error_code,
                    )
                db.commit()
                return

            if graph_output is None:
                raise RuntimeError("LangGraph completed without returning a final state.")

            narrative_text = _extract_text_field(graph_output, "doc1_narrativa", NARRATIVE_ARTIFACT_LIMIT)
            if not narrative_text:
                raise ValueError("Authoring graph returned an empty doc1_narrativa; cannot publish blueprint.")

            eda_full_text = _extract_text_field(graph_output, "doc2_eda", EDA_ARTIFACT_LIMIT)
            eda_summary = _build_eda_summary(eda_full_text)

            artifact_ids: list[str] = []
            artifact_ids.append(
                await ArtifactManager.save_artifact(
                    db=db,
                    storage_provider=storage_provider,
                    text_content=narrative_text,
                    assignment_id=assignment.id,
                    job_id=job_id,
                    owner_id=assignment.teacher_id,
                    artifact_type="narrative_text",
                    producer_node="case_writer",
                )
            )
            if eda_summary is not None and _is_useful_eda(eda_full_text):
                artifact_ids.append(
                    await ArtifactManager.save_artifact(
                        db=db,
                        storage_provider=storage_provider,
                        text_content=eda_full_text,
                        assignment_id=assignment.id,
                        job_id=job_id,
                        owner_id=assignment.teacher_id,
                        artifact_type="eda_report",
                        producer_node="eda_text_analyst",
                    )
                )

            blueprint = _build_productive_blueprint(
                payload=payload,
                narrative_text=narrative_text,
                eda_summary=eda_summary,
                artifact_ids=artifact_ids,
            )

            assignment.blueprint = blueprint.model_dump(exclude_none=True)

            canonical_result = adapter_legacy_to_canonical_output(graph_output)
            assignment.canonical_output = canonical_result.get("canonical_output", {})
            assignment.status = "published"
            job.status = AUTHORING_JOB_STATUS_COMPLETED
            completed_payload = _next_progress_payload(
                job.task_payload,
                status=AUTHORING_JOB_STATUS_COMPLETED,
                current_step="completed",
            )
            _clear_bootstrap_state(completed_payload)
            job.task_payload = completed_payload

            ArtifactManager.publish_job_artifacts(db, job_id)
            db.commit()
            logger.info("AuthoringService: Successfully promoted to V5 and completed Job %s", job_id)
        except Exception:
            logger.error(
                "AuthoringService: Failure updating final state for Job %s: %s",
                job_id,
                traceback.format_exc(),
            )
            db.rollback()
            db = SessionLocal()
            try:
                job = db.query(AuthoringJob).filter(AuthoringJob.id == job_id).first()
                if job is not None and job.status != AUTHORING_JOB_STATUS_FAILED:
                    job.status = AUTHORING_JOB_STATUS_FAILED
                    current_payload = _next_progress_payload(
                        job.task_payload,
                        status=AUTHORING_JOB_STATUS_FAILED,
                        current_step="failed",
                        error_code="finalization_error",
                        error_trace=traceback.format_exc(),
                    )
                    job.task_payload = current_payload
                    ArtifactManager.orphan_job_artifacts(db, job_id)
                    db.commit()
                    logger.error(
                        "AuthoringService: Job %s marked as FAILED after final-state exception.",
                        job_id,
                    )
            except Exception as inner_exc:
                logger.error("AuthoringService: Could not persist failure state for Job %s: %s", job_id, inner_exc)
                db.rollback()
            finally:
                db.close()
            return
        finally:
            db.close()
