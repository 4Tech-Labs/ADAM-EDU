from __future__ import annotations

import asyncio
import logging
import traceback
import uuid
from typing import Any, Literal, Mapping, cast

from case_generator.core.artifact_manager import ArtifactManager
from case_generator.core.storage import get_storage_provider
from case_generator.graph import graph
from case_generator.orchestration.frontend_output_adapter import adapter_legacy_to_canonical_output
from langchain_core.runnables import RunnableConfig
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
from shared.database import SessionLocal
from shared.models import Assignment, AuthoringJob
from shared.progress_bus import publish
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

        # --- DB MICRO-SESSION 1: transition the job into processing ---
        db = SessionLocal()
        try:
            job = db.query(AuthoringJob).filter(AuthoringJob.id == job_id).first()
            if job is None:
                logger.error("AuthoringService: Job %s not found in DB.", job_id)
                return

            if job.status in ["completed", "processing", "failed"]:
                logger.warning(
                    "AuthoringService: Job %s is already in terminal/processing state '%s'. Aborting.",
                    job_id,
                    job.status,
                )
                return

            assignment = db.query(Assignment).filter(Assignment.id == job.assignment_id).first()
            if assignment is None:
                logger.error("AuthoringService: Assignment %s not found for job %s.", job.assignment_id, job_id)
                job.status = "failed"
                payload_with_error = dict(job.task_payload or {})
                payload_with_error["error_trace"] = "Assignment not found for authoring job."
                job.task_payload = payload_with_error
                db.commit()
                publish(job_id, {"type": "failed", "error": payload_with_error["error_trace"]})
                return

            job.status = "processing"
            job.retry_count += 1
            assignment_id = assignment.id
            owner_id = assignment.teacher_id
            payload = dict(job.task_payload or {})
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

        # --- LANGGRAPH EXECUTION (no open DB session) ---
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
            }

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
                last_reported_step = "processing"
                stream_mode: Literal["values"] = "values"
                stream = cast(Any, graph).astream(state_input, config=run_config, stream_mode=stream_mode)

                async for event in stream:
                    final_state = dict(event)
                    current_agent = final_state.get("current_agent")

                    if current_agent and current_agent != last_reported_step:
                        try:
                            db_step = SessionLocal()
                            try:
                                job_step = db_step.query(AuthoringJob).filter(AuthoringJob.id == job_id).first()
                                if job_step is not None:
                                    payload_step = dict(job_step.task_payload or {})
                                    payload_step["current_step"] = current_agent
                                    job_step.task_payload = payload_step
                                    db_step.commit()
                                    last_reported_step = str(current_agent)
                            finally:
                                db_step.close()
                        except Exception as exc:
                            logger.error(
                                "AuthoringService: Error updating current_step '%s' for job %s: %s",
                                current_agent,
                                job_id,
                                exc,
                            )
                        publish(job_id, {"type": "step", "node": current_agent})

                return final_state

            graph_output = await asyncio.wait_for(_run_graph_stream(), timeout=900)
            logger.info("AuthoringService: LangGraph execution finished for Job %s.", job_id)
        except asyncio.TimeoutError:
            logger.error("AuthoringService: TIMEOUT — Job %s exceeded 900s", job_id)
            error_msg = (
                "Nuestros servidores de IA estan a maxima capacidad y el tiempo de espera se agoto. "
                "Por favor, reintenta en unos minutos."
            )
        except Exception:
            logger.error("AuthoringService: LangGraph raised exception for Job %s", job_id, exc_info=True)
            error_trace = traceback.format_exc()
            error_str = error_trace.lower()
            if "503" in error_str or "high demand" in error_str or "unavailable" in error_str:
                error_msg = (
                    "Nuestros servidores de IA estan experimentando un pico de trafico en este momento. "
                    "Por favor, reintenta en un par de minutos."
                )
            elif "429" in error_str or "quota" in error_str:
                error_msg = (
                    "Hemos alcanzado el limite de operaciones de IA permitidas por minuto. "
                    "Por favor, intenta generar el caso un poco mas tarde."
                )
            else:
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
                job.status = "failed"
                current_payload = dict(job.task_payload or {})
                current_payload["error_trace"] = error_msg
                job.task_payload = current_payload

                logger.error("AuthoringService: Job %s marked as FAILED. Cleaning up artifacts.", job_id)
                ArtifactManager.orphan_job_artifacts(db, job_id)
                db.commit()
                publish(job_id, {"type": "failed", "error": error_msg})
                return

            if graph_output is None:
                raise RuntimeError("LangGraph completed without returning a final state.")

            narrative_text = _extract_text_field(graph_output, "doc1_narrativa", NARRATIVE_ARTIFACT_LIMIT)
            if not narrative_text:
                raise ValueError("Authoring graph returned an empty doc1_narrativa; cannot publish blueprint.")

            eda_full_text = _extract_text_field(graph_output, "doc2_eda", EDA_ARTIFACT_LIMIT)
            eda_summary = _build_eda_summary(eda_full_text)

            storage_provider = get_storage_provider()
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
            job.status = "completed"

            ArtifactManager.publish_job_artifacts(db, job_id)
            db.commit()
            publish(job_id, {"type": "completed", "result": assignment.canonical_output or {}})
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
                if job is not None and job.status != "failed":
                    job.status = "failed"
                    current_payload = dict(job.task_payload or {})
                    current_payload["error_trace"] = traceback.format_exc()
                    job.task_payload = current_payload
                    ArtifactManager.orphan_job_artifacts(db, job_id)
                    db.commit()
                    publish(job_id, {"type": "failed", "error": current_payload["error_trace"]})
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
