"""
adam-v8.0 — Pipeline de generación de casos académicos con LangGraph.

Topología del grafo maestro:
  input_adapter → doc1_flow → output_adapter_intermediate → route_master
    → harvard_with_eda: eda_flow → m3_flow → m4_flow → synthesis_flow
    → harvard_only: m4_flow → synthesis_flow
  → output_adapter_final

Subgrafos:
  doc1_flow: case_architect → [case_writer ∥ case_questions] → doc1_complete
  eda_flow: schema_designer → data_generator → data_validator
            → eda_text_analyst → eda_chart_generator
            → eda_questions_generator → eda_phase2_sync
            (M2 NO genera notebook — único notebook del sistema es M3 para ml_ds)
    m3_flow: m3_content_generator → [m3_questions_generator ∥ (m3_notebook_generator → m3_notebook_executor)] → m3_sync
                     (m3_notebook_generator/executor: noop si output_depth != "visual_plus_notebook")
  m4_flow: m4_content → [m4_questions ∥ m4_charts] → m4_sync
  synthesis_flow: [m5_content ∥ teaching_note_part1]
                  → sync1 → m5_questions → teaching_note_part2 → sync2

Total nodos LLM por path:
  harvard_only (business): ~10 llamadas
  harvard_with_eda (ml_ds + notebook): ~19 llamadas

Modelos (tier por-nodo vía configuration.resolve_node_model + node_model_overrides;
  cada .invoke lleva tag node:<name> y CostCallbackHandler agrega tokens/USD por nodo):
  architect_model (Pro): case_architect (thinking medium — Fase 1), schema_designer
  m3: m3_content_generator (ml_ds → Pro, eval-gate pendiente para Flash),
      m3_notebook_generator (Flash — Fase 1 downgrade, protegido por gate de ejecución)
    m4/m5 (Pro chain): m4_content_generator (thinking medium — Fase 1),
                       m5_content_generator, m5_questions_generator
    writer_model (Flash): m3_content_generator (business), m3_notebook_generator,
                          demás nodos LLM y fallback operativo M4/M5
  chart_llm (Flash, 16K tokens): chart generators (M2, M3, M4)
  Cadenas de fallback (depende del nodo, no es global):
    - _get_writer_llm  / _get_chart_llm    : primary -> gemini-2.5-flash
    - _get_architect_llm                   : Pro -> Pro-medium -> gemini-3-flash-preview
        - _get_m4_llm / _get_m5_llm            : Pro-medium -> Pro-low -> writer_model -> gemini-2.5-flash
    - schema_designer (M2 inline)          : Pro-medium -> Pro-low -> gemini-3-flash-preview
    - m3_content_generator (ml_ds inline)  : Pro-medium -> Pro-low -> gemini-3-flash-preview
    - m3_notebook_generator                : Flash(writer) -> gemini-2.5-flash
  Python puro (0 tokens): data_generator, data_validator, barriers sync

Resiliencia (v9):
  - InMemoryRateLimiter: 10 req/s por instancia Cloud Run (burst 20)
  - .with_fallbacks: primary → gemini-2.5-flash automático en caída de API
  - Fallback graceful: todos los nodos LLM retornan sentinel en vez de raise
  - RetryPolicy: backoff exponencial (1s → 2s → 4s, max 30s, jitter ON)
    - Timeout global: 1900 segundos por job (authoring.GRAPH_EXECUTION_TIMEOUT_SECONDS)
  - AsyncPostgresSaver: checkpointer para resume-from-failure
    - get_graph(): singleton lazy por event loop para evitar reuse cruzado en tests/workers async
"""

import asyncio
import hashlib
import json
import logging
import os
import random
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

logger = logging.getLogger("adam.graph")
from pydantic import ValidationError

from dotenv import load_dotenv
from langchain_core.exceptions import OutputParserException
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver as LangGraphAsyncPostgresSaver
from langgraph.graph import StateGraph, START, END
from langgraph.types import RetryPolicy
from psycopg.errors import UndefinedTable

from case_generator.state import ADAMState
from case_generator.configuration import (
    Configuration,
    resolve_node_model,
    NODE_CASE_ARCHITECT,
    NODE_SCHEMA_DESIGNER,
    NODE_M3_CONTENT,
    NODE_M3_NOTEBOOK,
    NODE_M3_NOTEBOOK_ESCALATION,
    NODE_M4_CONTENT,
    NODE_M5_CONTENT,
    NODE_M5_QUESTIONS,
    M3_NOTEBOOK_MAX_ATTEMPTS,
)
from case_generator.prompts import (
    ARCHITECT_IMPACT_LENS_BLOCK,
    CASE_ARCHITECT_PROMPT,
    CASE_ARCHITECT_PROMPT_BY_FAMILY,
    M1_CLASSIFICATION_BUSINESS_TARGET_BLOCK,
    CASE_QUESTIONS_PROMPT,
    CASE_QUESTIONS_PROMPT_BY_FAMILY,
    CASE_WRITER_PROMPT,
    CASE_WRITER_PROMPT_BY_FAMILY,
    EDA_ANNOTATE_ONLY_PROMPT,
    EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION,
    EDA_CHART_GENERATOR_PROMPT,
    EDA_QUESTIONS_GENERATOR_PROMPT,
    EDA_QUESTIONS_PROMPT_BY_FAMILY,
    EDA_TEXT_ANALYST_PROMPT,
    EDA_TEXT_ANALYST_PROMPT_BY_FAMILY,
    build_cost_matrix_block,
    select_eda_text_blocks,
    CLASSIFICATION_NOTEBOOK_PROMPT_BY_VARIANT,
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST,
    CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY,
    ClassificationNotebookVariant,
    TOC_MARKDOWN_CELL_BY_VARIANT,
    M4_QUESTIONS_GENERATOR_PROMPT,
    M4_QUESTIONS_GENERATOR_PROMPT_NEUTRAL,
    M4_QUESTIONS_PROMPT_BY_FAMILY,
    M4_QUESTIONS_PROMPT_BY_FAMILY_NEUTRAL,
    M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION_NEUTRAL,
    M5_QUESTIONS_GENERATOR_PROMPT,
    M5_QUESTIONS_PROMPT_BY_FAMILY,
    # v8 M3 — prompts por perfil (aliases backward-compat también disponibles)
    M3_AUDIT_LR_BUSINESS_BLOCK,
    M3_AUDIT_PROMPT,
    M3_EXPERIMENT_PROMPT,
    M3_AUDIT_QUESTIONS_PROMPT,
    M3_EXPERIMENT_QUESTIONS_PROMPT,
    M3_NOTEBOOK_BASE_TEMPLATE,
    M3_CONTENT_PROMPT_BY_FAMILY,
    M3_CONTENT_PROMPT_CLASSIFICATION_BY_VARIANT,
    M3_CLASSIFICATION_QUESTIONS_BY_VARIANT,
    PROMPT_BY_FAMILY,
    M4_PROMPT_BY_FAMILY,
    M4_PROMPT_BY_FAMILY_NEUTRAL,
    M4_CONTENT_GENERATOR_PROMPT,
    M4_CONTENT_GENERATOR_PROMPT_NEUTRAL,
    M4_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT,
    M4_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT_NEUTRAL,
    M4_BUSINESS_PROMPT_CLASSIFICATION,
    M4_BUSINESS_PROMPT_CLASSIFICATION_NEUTRAL,
    M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION,
    M4_CHART_GENERATOR_PROMPT,
    M4_CHART_GENERATOR_PROMPT_LEGACY,
    M4_CHART_GENERATOR_PROMPT_NEUTRAL,
    M4_CHART_BUSINESS_PROMPT_CLASSIFICATION,
    M4_CHART_BUSINESS_PROMPT_CLASSIFICATION_LEGACY,
    M4_CHART_BUSINESS_PROMPT_CLASSIFICATION_NEUTRAL,
    M4_CHARTS_PROMPT_BY_FAMILY,
    M4_CHARTS_PROMPT_BY_FAMILY_LEGACY,
    M4_CHARTS_PROMPT_BY_FAMILY_NEUTRAL,
    M5_PROMPT_BY_FAMILY,
    M5_CONTENT_GENERATOR_PROMPT,
    M5_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT,
    M5_BUSINESS_PROMPT_CLASSIFICATION,
    M5_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION,
    TEACHING_NOTE_PART1_PROMPT,
    TEACHING_NOTE_PART1_PROMPT_LEGACY,
    TEACHING_NOTE_PART2_PROMPT,
    TEACHING_NOTE_PART2_PROMPT_LEGACY,
    build_module_guide_block,
    build_roster_allowlist,
    module_guide_roster_ids,
    SCHEMA_DESIGNER_PROMPT,
    SCHEMA_DESIGNER_PROMPT_BY_FAMILY,
)
from case_generator.suggest_service import (
    family_of,
    get_dispatch_meta,
    resolve_legacy_family,
)
from case_generator.impact_lens import (
    DEFAULT_IMPACT_LENS,
    IMPACT_LENS_KEYS,
    build_impact_lens_architect_hint,
    build_impact_lens_hint,
    build_impact_lens_m5_hint,
    normalize_impact_lens,
)
from case_generator.retention_tokens import (
    RETENTION_CHURN_TOKENS,
    is_retention_match,
)
from case_generator.narrative_grounding import (
    NARRATIVE_GROUNDING_WARNING,
    build_computed_metrics_block,
    contextualize_grounding_violations,
    detect_unselected_model_mentions,
    has_metric_anchors,
    log_raw_identifier_leak,
    validate_narrative_grounding,
)
from case_generator.m1_grounding import (
    detect_exhibit2_completeness_row,
    enforce_usd_currency,
    validate_exhibit2_event_rate,
    validate_narrative_exhibit_coherence,
    validate_question_option_coherence,
    validate_questions_exhibit_coherence,
)
from case_generator.m2_grounding import validate_eda_questions_coherence
from case_generator.m3_grounding import (
    allowed_sections_for,
    validate_m3_questions_coherence,
)
from case_generator.m5_grounding import validate_m5_questions_coherence
from case_generator.m6_grounding import log_out_of_roster_mentions
from case_generator.m4_grounding import (
    build_m4_chart_grounding_reprompt,
    drop_sensitivity_charts,
    log_chart_benchmark_fabrication,
    log_duplicate_deployment_sections,
    log_narrative_benchmark_fabrication,
    validate_m4_chart_grounding,
)
from case_generator.m3_notebook_execution import (
    M3NotebookExecutionError,
    _bounded_diagnostic,
    build_target_identity_warning,
    execute_m3_notebook,
    format_execution_failure_for_prompt,
    is_m3_quality_warning_blocking,
    scrub_notebook_for_safe_execution,
)
from case_generator.m3_notebook_repair import repair_locals_existence_guards
from case_generator.tools_and_schemas import (
    CaseArchitectOutput,
    EDAAnnotateOnlyOutput,
    EDAChartGeneratorOutput,
    GeneradorPreguntasM1Output,
    GeneradorPreguntasOutput,
    GeneradorPreguntasM5Output,
    EDAQuestionsOutput,
    DatasetSchema,
    TeachingNoteIntroOutput,
)
from case_generator.datagen.eda_charts_business import (
    generate_business_eda_charts,
)
from case_generator.datagen.eda_charts_classification import (
    generate_classification_eda_charts,
)
from case_generator.orchestration.frontend_adapter import adapter_canonical_to_legacy
from case_generator.orchestration.frontend_output_adapter import adapter_legacy_to_canonical_output
from shared.database import (
    clean_authoring_runtime,
    collect_langgraph_bootstrap_diagnostics,
    get_checkpoint_migrations_version,
    get_langgraph_checkpointer_async_pool,
    settings,
    snapshot_langgraph_pool_stats,
)
from shared.sanitization import sanitize_untrusted_payload

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

load_dotenv()

if os.getenv("GEMINI_API_KEY") is None:
    raise ValueError("GEMINI_API_KEY is not set")


class AsyncPostgresSaver(LangGraphAsyncPostgresSaver):
    """Skip LangGraph DDL when Alembic already aligned checkpoint schema."""

    async def setup(self) -> None:
        async with self._cursor() as cur:
            try:
                results = await cur.execute(
                    "SELECT v FROM checkpoint_migrations ORDER BY v DESC LIMIT 1"
                )
                row = await results.fetchone()
            except UndefinedTable:
                await cur.execute(self.MIGRATIONS[0])
                await cur.execute(
                    "INSERT INTO checkpoint_migrations (v) VALUES (%s) ON CONFLICT DO NOTHING",
                    (0,),
                )
                version = 0
            else:
                if row is None:
                    await cur.execute(
                        "INSERT INTO checkpoint_migrations (v) VALUES (%s) ON CONFLICT DO NOTHING",
                        (0,),
                    )
                    version = 0
                else:
                    version = row["v"]

            for v, migration in zip(
                range(version + 1, len(self.MIGRATIONS)),
                self.MIGRATIONS[version + 1 :],
                strict=False,
            ):
                await cur.execute(migration)
                await cur.execute(
                    "INSERT INTO checkpoint_migrations (v) VALUES (%s) ON CONFLICT DO NOTHING",
                    (v,),
                )

        if self.pipe:
            await self.pipe.sync()


# Rate limiter compartido por TODOS los LLMs de esta instancia de Cloud Run.
# 10 req/s es conservador — Gemini Pay-as-you-go soporta ~15-20 RPM/modelo.
# Con 5 instancias Cloud Run × 10 req/s = 50 req/s total.
# Ajustar según el tier de la API key.
_rate_limiter = InMemoryRateLimiter(
    requests_per_second=10,
    check_every_n_seconds=0.1,
    max_bucket_size=20,  # Burst de hasta 20 llamadas acumuladas
)

# ─── OpenRouter (proveedor alterno, OpenAI-compatible) ──────────────────────────
# Se activa SOLO cuando un nodo resuelve a un model id con "/" (p.ej. "minimax/minimax-m3")
# vía NODE_MODEL_OVERRIDES; reversible sin redeploy. El fallback cross-provider a Gemini vive
# en las cadenas .with_fallbacks de las factories (ver _build_llm).
_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _env_float(name: str, default: float) -> float:
    """Read a float env var, falling back to ``default`` on absence or a malformed value.

    Tolerant by design: a fat-fingered OpenRouter tuning env must NEVER crash module import —
    that would take down EVERY node (all of M1..M6), not just the OpenRouter path, breaking the
    inert-by-default guarantee.
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("[config] %s=%r no es float válido — usando default %s", name, raw, default)
        return default


def _env_int(name: str, default: int) -> int:
    """Read an int env var, falling back to ``default`` on absence or a malformed value (see _env_float)."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("[config] %s=%r no es int válido — usando default %s", name, raw, default)
        return default


# Rate limiter DEDICADO (no el de Gemini): los límites de OpenRouter son independientes de los
# de Gemini; compartir un bucket acoplaría ambos presupuestos y M5 podría starve a otros nodos
# Gemini. Process-local → el techo real es N_instancias × requests_per_second (igual que el de
# Gemini); para un burst que pueda exceder el límite de cuenta de OpenRouter, considerar un
# limiter distribuido o cap de instancias. Tunable por env.
_openrouter_rate_limiter = InMemoryRateLimiter(
    requests_per_second=_env_float("OPENROUTER_REQUESTS_PER_SECOND", 5.0),
    check_every_n_seconds=0.1,
    max_bucket_size=_env_int("OPENROUTER_MAX_BUCKET_SIZE", 10),
)

# minimax-m3 es un modelo de RAZONAMIENTO y sus reasoning tokens cuentan contra max_tokens. Sin
# cap pueden ahogar la salida visible (p.ej. la matriz de decisión de M5). El max_tokens total que
# enviamos = answer (_M5_MAX_OUTPUT_TOKENS, 32768) + este valor. En modo PRESUPUESTO (effort vacío)
# se manda como reasoning.max_tokens, así que answer y razonamiento están separados. En modo EFFORT
# este valor NO se manda como reasoning.max_tokens (excluyentes → 400); solo sube el max_tokens
# total, del cual OpenRouter toma una fracción para razonar (~80% "high") y deja el resto a la
# respuesta. Default 4000 → total 36768 (answer ~7.3k bajo "high", de sobra para M5 ~1-4k). Subirlo
# (p.ej. 16000 → total 48768) da más respuesta+razonamiento; verificado en vivo: 48768 + effort=high
# → finish_reason=stop, sin truncar, en M5 (minimax y glm). Para respuestas grandes bajo effort,
# sube este presupuesto.
_OPENROUTER_REASONING_MAX_TOKENS = _env_int("OPENROUTER_REASONING_MAX_TOKENS", 4000)
# Niveles de esfuerzo válidos en OpenRouter (mayor→menor). EXCLUYENTE con reasoning.max_tokens
# (OpenRouter da 400 si se envían ambos): con effort, OpenRouter asigna una FRACCIÓN del max_tokens
# total al razonamiento (~95% max/xhigh, ~80% high, ~50% medium, ~20% low, ~10% minimal, 0% none) y
# deja el resto para la respuesta — por eso el max_tokens total (= answer + presupuesto) debe ser
# holgado: con presupuesto pequeño y effort alto el ~20% de respuesta puede quedar corto.
_VALID_OPENROUTER_EFFORTS = frozenset({"max", "xhigh", "high", "medium", "low", "minimal", "none"})
# Nivel de esfuerzo de razonamiento. Vacío = usar el presupuesto de tokens de arriba. Un valor NO
# vacío pero inválido (typo) cae a presupuesto CON un warning (no se ignora en silencio).
_OPENROUTER_REASONING_EFFORT = os.getenv("OPENROUTER_REASONING_EFFORT", "").strip().lower()
# Timeout por request: acota una llamada colgada para que la cadena .with_fallbacks avance a
# Gemini mucho antes del deadline global del job (~1900s).
_OPENROUTER_TIMEOUT_SECONDS = _env_float("OPENROUTER_TIMEOUT_SECONDS", 150.0)
# Routing de proveedor (coma-separado): upstreams capaces de structured-output/tools para
# minimax-m3 (p.ej. "Together,Parasail,Morph"). Vacío = OpenRouter elige; require_parameters
# igual filtra a un proveedor capaz. VERIFICAR contra los endpoints vigentes de minimax-m3.
_OPENROUTER_PROVIDER_ORDER = [
    p.strip() for p in os.getenv("OPENROUTER_PROVIDER_ORDER", "").split(",") if p.strip()
]
# Política de datos del routing. Por DEFECTO NO se envía: muchos modelos (incl. minimax-m3) NO
# tienen NINGÚN proveedor con data_collection=deny, y enviar "deny" hace que OpenRouter no
# encuentre endpoint elegible → 404 en CADA llamada (cae todo a Gemini). Pon
# OPENROUTER_DATA_COLLECTION=deny (o "allow") solo si tu modelo/proveedores lo soportan; vacío =
# routing normal. data_collection NO es zero-retention (eso es ZDR a nivel de cuenta de OpenRouter).
_OPENROUTER_DATA_COLLECTION = os.getenv("OPENROUTER_DATA_COLLECTION", "").strip().lower()
# Filtra a proveedores que soporten los params enviados (necesario para que el structured-output de
# m5_questions aterrice en un upstream capaz: Together/Parasail/Morph). NO causa 404: sí hay
# proveedores elegibles. Pon OPENROUTER_REQUIRE_PARAMETERS=false para relajar el routing.
_OPENROUTER_REQUIRE_PARAMETERS = (
    os.getenv("OPENROUTER_REQUIRE_PARAMETERS", "true").strip().lower() != "false"
)

_M5_MODEL = "gemini-3.1-pro-preview"
_M5_MAX_OUTPUT_TOKENS = 32768


# ─── LLM Factory ────────────────────────────────────────


def _build_gemini(
    model: str,
    *,
    temperature: float,
    max_output_tokens: int,
    thinking_level: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    response_mime_type: str | None = None,
) -> ChatGoogleGenerativeAI:
    """Build one ChatGoogleGenerativeAI with the shared resilience boilerplate.

    Single source of truth for ``api_key``, the shared ``_rate_limiter`` and
    ``max_retries`` so the tier factories below stay thin and per-node model /
    thinking changes live in one place. Callers compose ``.with_fallbacks()``
    chains around the result — those chains are intentionally NOT built here, so
    the resilience net per node is preserved exactly.

    ``thinking_level``/``tools``/``response_mime_type`` are omitted when None so
    the model gets the SDK default (matches the prior per-factory behavior).
    """
    kwargs: dict[str, Any] = dict(
        model=model,
        temperature=temperature,
        max_retries=2,
        max_output_tokens=max_output_tokens,
        api_key=os.getenv("GEMINI_API_KEY"),
        rate_limiter=_rate_limiter,
    )
    if thinking_level is not None:
        kwargs["thinking_level"] = thinking_level
    if tools is not None:
        kwargs["model_kwargs"] = {"tools": tools}
    if response_mime_type is not None:
        kwargs["response_mime_type"] = response_mime_type
    return ChatGoogleGenerativeAI(**kwargs)


def _build_openrouter(
    model: str,
    *,
    temperature: float,
    max_output_tokens: int,
    thinking_level: str | None = None,  # Gemini-only → ignorado
    tools: list[dict[str, Any]] | None = None,  # Gemini code_execution → ignorado
    response_mime_type: str | None = None,  # → se usa .with_structured_output
) -> Any:
    """Build one ChatOpenAI pointed at OpenRouter (OpenAI-compatible).

    ESTRICTO: lanza si falta ``OPENROUTER_API_KEY`` o si ``langchain_openai`` no está instalado
    (import perezoso). El wrapper ``_build_llm`` captura esos fallos y degrada a Gemini, así que
    un nodo nunca queda sin cliente por una mala config del proveedor alterno.

    ``thinking_level``/``tools``/``response_mime_type`` son kwargs Gemini-only aceptados por
    paridad de firma con ``_build_gemini`` y se ignoran: minimax usa ``extra_body.reasoning`` para
    el razonamiento y ``.with_structured_output`` para JSON. ``max_output_tokens`` se mapea a
    ``max_tokens`` (nombre de ChatOpenAI) y se le suma el cap de reasoning para no truncar la salida.
    """
    from langchain_openai import ChatOpenAI  # lazy: dep ausente → ImportError captado por _build_llm

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY no está seteado pero un nodo se enrutó a OpenRouter")

    headers = {
        k: v
        for k, v in {
            "HTTP-Referer": os.getenv("OPENROUTER_HTTP_REFERER"),
            "X-Title": os.getenv("OPENROUTER_APP_TITLE"),
        }.items()
        if v
    }
    provider: dict[str, Any] = {"allow_fallbacks": True}
    if _OPENROUTER_REQUIRE_PARAMETERS:
        # solo upstreams que soportan los params enviados (tools/json) → garantiza structured-output
        provider["require_parameters"] = True
    if _OPENROUTER_DATA_COLLECTION in ("deny", "allow"):
        # OPT-IN (default = no enviar). "deny" restringe a proveedores zero-collection; si NINGUNO
        # del modelo lo cumple → 404. NO es zero-retention (eso es ZDR a nivel de cuenta).
        provider["data_collection"] = _OPENROUTER_DATA_COLLECTION
    if _OPENROUTER_PROVIDER_ORDER:
        provider["order"] = _OPENROUTER_PROVIDER_ORDER
    # reasoning.effort y reasoning.max_tokens son EXCLUYENTES (OpenRouter → 400 si ambos). Si hay un
    # nivel de esfuerzo configurado, se manda SOLO effort; si no, el presupuesto de tokens.
    reasoning_cfg: dict[str, Any]
    if _OPENROUTER_REASONING_EFFORT in _VALID_OPENROUTER_EFFORTS:
        reasoning_cfg = {"effort": _OPENROUTER_REASONING_EFFORT}
    else:
        if _OPENROUTER_REASONING_EFFORT:  # no vacío pero inválido → avisar, no ignorar en silencio
            logger.warning(
                "[config] OPENROUTER_REASONING_EFFORT=%r inválido (válidos: %s) — usando reasoning.max_tokens",
                _OPENROUTER_REASONING_EFFORT,
                ", ".join(sorted(_VALID_OPENROUTER_EFFORTS)),
            )
        reasoning_cfg = {"max_tokens": _OPENROUTER_REASONING_MAX_TOKENS}
    extra_body: dict[str, Any] = {
        # CRÍTICO: `max_tokens` va AQUÍ (en extra_body), NO como kwarg de ChatOpenAI. ChatOpenAI
        # serializa su `max_tokens=` como `max_completion_tokens` (campo nuevo de OpenAI), y con
        # `provider.require_parameters=true` OpenRouter exige un upstream que soporte ESE parámetro
        # — los proveedores de minimax-m3 solo listan `max_tokens` → ningún endpoint elegible → 404
        # ("No endpoints found that can handle the requested parameters"). Enviarlo por extra_body
        # lo serializa como `max_tokens` (soportado por todos) → 200. (Verificado contra la API.)
        # El total = answer + presupuesto de reasoning (que con effort actúa como headroom).
        "max_tokens": max_output_tokens + _OPENROUTER_REASONING_MAX_TOKENS,
        "provider": provider,
        "reasoning": reasoning_cfg,
        "usage": {"include": True},
    }
    return ChatOpenAI(
        model=model,
        base_url=_OPENROUTER_BASE_URL,
        api_key=api_key,
        temperature=temperature,
        # NO pasar max_tokens aquí: se serializaría como max_completion_tokens → 404 (ver extra_body).
        max_retries=2,
        timeout=_OPENROUTER_TIMEOUT_SECONDS,
        rate_limiter=_openrouter_rate_limiter,
        default_headers=headers or None,
        extra_body=extra_body,
    )


def _build_llm(
    model: str,
    *,
    gemini_fallback_model: str = "gemini-3-flash-preview",
    **kwargs: Any,
) -> Runnable:
    """Dispatch a model id to its provider builder, degrading to Gemini on any OpenRouter failure.

    Regla: un id con ``"/"`` (p.ej. ``"minimax/minimax-m3"``) → OpenRouter; cualquier otro →
    Gemini (incluye los ids Gemini reales y los sintéticos de tests como ``"pro-x"``).

    RESILIENCIA (clave para no romper el fallback): las tier factories construyen sus tiers de
    forma EAGER antes de ``.with_fallbacks``; si ``_build_openrouter`` lanzara (falta
    ``OPENROUTER_API_KEY``, ``langchain_openai`` no instalado, error de construcción) la factory
    entera reventaría ANTES de existir la cadena de fallbacks → Gemini inalcanzable. Por eso aquí
    degradamos a ``_build_gemini(gemini_fallback_model)`` en vez de propagar: una mala config del
    proveedor alterno cae limpio a Gemini (el fallback deseado) y el nodo nunca queda sin cliente.
    """
    if "/" in model:
        try:
            return _build_openrouter(model, **kwargs)
        except Exception as exc:  # noqa: BLE001 — degradar SIEMPRE a Gemini, nunca romper la factory
            logger.warning(
                "[_build_llm] OpenRouter no disponible para model=%s (%s) — degradando a Gemini %s",
                model,
                type(exc).__name__,
                gemini_fallback_model,
            )
            return _build_gemini(gemini_fallback_model, **kwargs)
    return _build_gemini(model, **kwargs)


def _is_transient_llm_error(exc: BaseException) -> bool:
    """Return True if an LLM error is transient (worth a graph-level retry).

    Reconoce los marcadores de Google/Gemini (string-match histórico) Y los de OpenAI/OpenRouter
    (``openai.*`` expone el código HTTP en ``.status_code``). 402 (sin créditos) NO es transitorio
    — debe degradar al fallback Gemini, no reintentar.
    """
    if any(code in str(exc) for code in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED")):
        return True
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status == 429 or 500 <= status < 600
    return False


def _get_writer_llm(
    model: str,
    temperature: float = 0.7,
    thinking_level: str = "low",
):
    """LLM estándar (Flash) para redacción y structured output.
    Fallback automático a gemini-2.5-flash si el primary falla.
    """
    primary = _build_gemini(
        model, temperature=temperature, thinking_level=thinking_level, max_output_tokens=8192
    )
    # Fallback: modelo anterior estable. Mismos prompts funcionan sin cambios.
    fallback = _build_gemini("gemini-2.5-flash", temperature=temperature, max_output_tokens=8192)
    return primary.with_fallbacks([fallback])


def _get_architect_llm(
    model: str,
    temperature: float = 0.2,
    thinking_level: str = "high",
):
    """LLM Pro con Code Execution para verificación numérica.

    Code Execution permite al modelo ejecutar Python para validar
    los cálculos financieros del Exhibit 1 (inversión ≤ 8% de revenue).
    Fallback automático a gemini-3-flash-preview si el primary falla.
    max_output_tokens=16384: thinking_level="medium" consume ~2-4K tokens de reasoning;
    CaseArchitectOutput (8 campos densos) requiere ~3500-5000 tokens de output JSON.
    """
    _code_exec: list[dict[str, Any]] = [{"code_execution": {}}]
    primary = _build_gemini(
        model, temperature=temperature, thinking_level=thinking_level,
        max_output_tokens=16384, tools=_code_exec,
    )
    # Cadena de fallbacks ordenada:
    #   1) Pro con thinking_level="medium": misma calidad de modelo, menos
    #      reasoning tokens. Cubre fallos transitorios (rate limit, 5xx puntual,
    #      parser error en una respuesta).
    #   2) Flash: red de seguridad final por si Pro está caído globalmente.
    pro_fallback_medium = _build_gemini(
        model, temperature=temperature, thinking_level="medium",
        max_output_tokens=16384, tools=_code_exec,
    )
    flash_fallback = _build_gemini(
        "gemini-3-flash-preview", temperature=temperature, max_output_tokens=16384
    )
    return primary.with_fallbacks([pro_fallback_medium, flash_fallback])


def _get_m4_llm(
    model: str = "gemini-3.1-pro-preview",
    fallback_model: str = "gemini-3-flash-preview",
    temperature: float = 0.5,
):
    """High-reasoning Pro chain for M4 narrative impact analysis.

    M4 has to translate notebook/model evidence into executive ROI, risk, and
    deployment language. Prefer Gemini Pro, but keep Configuration-driven
    fallback escape hatches for preview-model outages and rollouts. Do not reuse
    the architect helper because M4 should not receive Code Execution tools.
    """
    # Fase 1 cost cut: primary thinking "high"→"medium". M4 prose stays on Pro
    # (HIGH-risk terminal narrative), but the extra "high" reasoning tokens were
    # billed at Pro output rates for marginal quality; "medium" keeps the model.
    primary = _build_gemini(model, temperature=temperature, thinking_level="medium", max_output_tokens=24576)
    pro_fallback_low = _build_gemini(model, temperature=temperature, thinking_level="low", max_output_tokens=24576)
    writer_fallback = _build_gemini(fallback_model, temperature=temperature, max_output_tokens=24576)
    stable_fallback = _build_gemini("gemini-2.5-flash", temperature=temperature, max_output_tokens=24576)
    return primary.with_fallbacks([pro_fallback_low, writer_fallback, stable_fallback])


def _get_chart_llm(
    model: str,
    temperature: float = 0.3,
    thinking_level: str = "minimal",
):
    """LLM para chart generators — tokens de output ampliados para JSON pesado.

    Auditoría C-05: 8 charts Plotly ml_ds × ~1000–1500 tokens c/u = ~8000–12000 tokens.
    max_output_tokens=8192 (default de _get_writer_llm) trunca los últimos charts
    silenciosamente sin lanzar excepción — la respuesta JSON queda incompleta y
    EDAChartGeneratorOutput.parse() falla o descarta charts válidos.

    Fix: 16384 tokens de output garantizan margen para hasta 10 charts Plotly complejos.
    Fallback automático a gemini-2.5-flash si el primary falla.
    """
    primary = _build_gemini(
        model, temperature=temperature, thinking_level=thinking_level, max_output_tokens=16384
    )
    fallback = _build_gemini("gemini-2.5-flash", temperature=temperature, max_output_tokens=16384)
    return primary.with_fallbacks([fallback])


def _get_m5_llm(
    model: str = _M5_MODEL,
    fallback_model: str = "gemini-3-flash-preview",
    temperature: float = 0.5,
):
    """Dedicated Pro chain for all Module 5 generation nodes.

    M5 is the final synthesis surface: content must reconcile M1-M4 evidence,
    narrative grounding, and the decision matrix, while questions produce long
    board-level expected answers. Prefer Gemini Pro and first fall back to the
    same model with lower reasoning; then use configured writer/stable Flash
    fallbacks so operations can route around preview-model incidents.
    """
    _max = _M5_MAX_OUTPUT_TOKENS
    # Las dos tiers que llevan el `model` resuelto pasan por el dispatcher: un id con "/" corre en
    # OpenRouter (minimax), si no en Gemini. Un fallo de construcción OpenRouter degrada a
    # `fallback_model` (Gemini) DENTRO de `_build_llm`, así que esta factory nunca lanza por el
    # proveedor alterno. Las dos tiers finales son SIEMPRE Gemini (la red cross-provider del plan).
    primary = _build_llm(model, gemini_fallback_model=fallback_model, temperature=temperature, thinking_level="medium", max_output_tokens=_max)
    pro_fallback_low = _build_llm(model, gemini_fallback_model=fallback_model, temperature=temperature, thinking_level="low", max_output_tokens=_max)
    writer_fallback = _build_gemini(fallback_model, temperature=temperature, max_output_tokens=_max)
    stable_fallback = _build_gemini("gemini-2.5-flash", temperature=temperature, max_output_tokens=_max)
    return primary.with_fallbacks([pro_fallback_low, writer_fallback, stable_fallback])


# ─── Utilidades ─────────────────────────────────────────

def _compute_dataset_summary(dataset: list) -> tuple:
    """Calcula resumen estadístico del dataset (count/mean/min/max por columna numérica).

    Fix M-04: evita ~15 líneas de código duplicado en eda_text_analyst,
    eda_chart_generator y m3_chart_generator. Centralizar aquí simplifica
    futuros cambios (ej: añadir std/percentiles).

    Returns:
        summary_json (str): JSON con estadísticas por columna numérica.
        total_rows (int): número de filas en el dataset.
    """
    if not dataset:
        return "{}", 0
    numeric_cols: dict = {}
    for row in dataset:
        for k, v in row.items():
            if isinstance(v, (int, float)):
                numeric_cols.setdefault(k, []).append(v)
    summary = {}
    for col, vals in numeric_cols.items():
        summary[col] = {
            "count": len(vals),
            "mean": round(sum(vals) / len(vals), 2),
            "min": min(vals),
            "max": max(vals),
        }
    return json.dumps(summary, ensure_ascii=False), len(dataset)


def sanitize_markdown(text: str) -> str:
    """Escudo de formato: limpia markdown code blocks y normaliza tablas."""
    if not text:
        return ""
    # 1. Eliminar fence de apertura: ```markdown, ```python, ```py, ```text, ``` solo
    text = re.sub(r'^```[a-zA-Z]*\s*\n?', '', text, flags=re.IGNORECASE)
    # 2. Eliminar fence de cierre al final: ``` (con o sin newline/espacios)
    text = re.sub(r'\n?```\s*$', '', text)
    # 3. Normalizar separadores de tablas (prevenir más de 3 guiones que rompen el parser)
    text = re.sub(r'-{4,}', '---', text)
    text = text.strip()
    # 4. Backstop USD-only (#377): reetiqueta cualquier moneda no-USD pegada a una cifra
    #    (€/£/EUR/COP/MXN/R$/…) a USD. Punto DRY que cubre TODA la prosa downstream que pasa por
    #    aquí (narrativa M1 del writer, EDA M2, narrativa M4/M5). Byte-idéntico para texto ya en
    #    USD/$. Kill-switch CASE_USD_CURRENCY_ENFORCE. La FUENTE (campos del architect, structured
    #    output) NO pasa por aquí → se enfuerza explícitamente en `case_architect` (#377 PUNTO 1).
    if settings.case_usd_currency_enforce:
        text = enforce_usd_currency(text)
    return text


_EXHIBIT_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)


def normalize_exhibit_markdown(text: str) -> str:
    """Convert literal ``<br>`` row separators to real newlines in M1 Exhibit tables (#356).

    The architect emits ``CaseArchitectOutput`` as *structured output*, where multi-line
    markdown is frequently written with literal ``<br>`` as row separators and ZERO real
    newlines (a well-known LLM quirk for string fields). That breaks BOTH the frontend GFM
    table parser (it collapses to one line → renders raw) and the backend ``.splitlines()``
    anchor parser in ``m1_grounding``. This pure, deterministic relabel converts ``<br>`` /
    ``<br/>`` / ``<br />`` (any case, optional inner spaces) to ``\\n``. Scoped to the three
    ``doc1_anexo_*`` fields only — NOT the shared ``sanitize_markdown`` blast radius. A string
    without ``<br>`` is byte-identical.
    """
    if not text:
        return ""
    normalized = _EXHIBIT_BR_RE.sub("\n", text)
    if normalized == text:
        # No <br> present → return the original verbatim. Strictly additive: this helper
        # never touches an exhibit that already uses real newlines.
        return text
    # Only when a <br> was actually converted: collapse the 3+ newline runs a <br><br><br>…
    # heading gap can produce (matches the repo's sanitize_untrusted_text newline-collapse
    # convention). A single blank line between a heading and the table (\n\n) is the
    # GFM-correct shape and is preserved.
    return re.sub(r"\n{3,}", "\n\n", normalized)


def _extract_text(response) -> str:
    """Extrae texto limpio del response de Gemini 2.5 o 3.x.

    Gemini 2.5: response.content es str.
    Gemini 3.x: response.content es list[dict] con bloques tipo
    {"type": "text", "text": "..."} y opcionalmente {"type": "thinking", ...}.

    Esta función es agnóstica al modelo — funciona con ambos.
    Ref: https://github.com/langchain-ai/langchain/issues/35571
    """
    content = response.content

    # Fix M-10: guard para respuesta vacía o error de red enmascarado.
    # Gemini puede retornar content=None en timeouts o safety blocks.
    # Verificado contra Context7 docs (langchain-google): response.content puede ser None,
    # str (Gemini 2.5) o list[dict] (Gemini 3.x). Los tres casos deben manejarse
    # explícitamente; str(None) = "None" era el comportamiento silencioso previo.
    if content is None:
        return ""

    # Gemini 2.5: ya es string
    if isinstance(content, str):
        return content

    # Gemini 3.x: lista de bloques
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                # Solo extraer bloques de texto, ignorar thinking/reasoning
                if block.get("type") in ("text", None):
                    parts.append(block.get("text", ""))
            elif hasattr(block, "text"):
                # Objetos con atributo .text (variante del SDK)
                parts.append(block.text)
        return "".join(parts)

    # Fallback de seguridad
    return str(content)


# ─────────────────────────────────────────────────────────
# HELPER — _repair_truncated_json
# ─────────────────────────────────────────────────────────

def _repair_truncated_json(text: str) -> str | None:
    """Repara un JSON truncado cerrando las estructuras que quedaron abiertas.

    Usa un stack-parser char a char para rastrear {/[ abiertos y strings sin cerrar.
    Retorna la cadena reparada, o None si el JSON ya estaba completo (sin truncación).

    Ejemplo:
      '{"columns": [{"name": "period", "type": "str"'
      → '{"columns": [{"name": "period", "type": "str"}]}'
    """
    stack: list[str] = []
    in_string = False
    escape_next = False

    for char in text:
        if escape_next:
            escape_next = False
            continue
        if char == '\\' and in_string:
            escape_next = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char in ('{', '['):
            stack.append(char)
        elif char in ('}', ']'):
            if stack:
                stack.pop()

    if not stack and not in_string:
        # JSON gramaticalmente completo — no hay nada que reparar
        return None

    repaired = text

    # Si el truncamiento ocurrió dentro de un string, cerrarlo
    if in_string:
        repaired += '"'

    # Eliminar trailing comma o fragmento incompleto antes de cerrar
    repaired = re.sub(r',\s*$', '', repaired.rstrip())

    # Cerrar estructuras abiertas en orden LIFO
    closing = {'{': '}', '[': ']'}
    repaired += ''.join(closing[c] for c in reversed(stack))

    return repaired


# ─────────────────────────────────────────────────────────
# HELPER — _extract_json_from_llm_response
# ─────────────────────────────────────────────────────────

def _extract_json_from_llm_response(raw: str) -> dict | None:
    """Extrae el primer objeto JSON válido de una respuesta LLM.

    Estrategias (en orden):
    1. Strip markdown fences (```json ... ```) y luego json.loads del contenido.
    2. json.loads del raw completo (ya limpio o sin fences).
    3. Regex para extraer substring entre primer '{' y último '}', luego json.loads.
    4. raw_decode desde cada '{' — valida presencia de 'columns' para confirmar
       que es el schema del dataset y no un objeto de error del modelo.
    5. Reparación de truncamiento: _repair_truncated_json + json.loads.
       Cubre el caso donde el modelo se queda sin tokens antes de cerrar el objeto.
    Retorna None si todas fallan, dejando al caller registrar el error y continuar.
    """
    if not raw or not raw.strip():
        return None

    _decoder = json.JSONDecoder()

    # Estrategia 1: extraer bloque ```json ... ```
    fence_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw)
    candidate = fence_match.group(1) if fence_match else raw

    # Estrategia 2: json.loads directo sobre el candidato
    try:
        result = json.loads(candidate)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Estrategia 3: recortar entre primer '{' y último '}'
    start = candidate.find('{')
    end = candidate.rfind('}')
    if start != -1 and end != -1 and end > start:
        try:
            result = json.loads(candidate[start:end + 1])
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # Estrategia 4: raw_decode desde cada '{' (más tolerante a texto extra al final)
    for m in re.finditer(r'\{', raw):
        try:
            result, _ = _decoder.raw_decode(raw, m.start())
            if isinstance(result, dict) and "columns" in result:
                return result
        except (json.JSONDecodeError, ValueError):
            continue

    # Estrategia 5: reparación de JSON truncado por límite de tokens del modelo.
    # Solo acepta el resultado si tiene los campos Required de DatasetSchema
    # (n_rows, constraints) y un mínimo de columnas semánticamente útiles.
    # Un schema con <4 columnas o sin constraints/n_rows fallaría Pydantic igualmente.
    repaired = _repair_truncated_json(candidate)
    if repaired:
        try:
            result = json.loads(repaired)
            if isinstance(result, dict):
                _MIN_COLUMNS = 4
                cols_ok = len(result.get("columns", [])) >= _MIN_COLUMNS
                fields_ok = "n_rows" in result and "constraints" in result
                if cols_ok and fields_ok:
                    logger.warning(
                        "[_extract_json_from_llm_response] JSON truncado reparado "
                        "(%d chars originales → %d chars reparados, %d columnas). "
                        "Si esto ocurre frecuentemente, aumentar max_output_tokens.",
                        len(candidate), len(repaired), len(result.get("columns", [])),
                    )
                    return result
                else:
                    logger.warning(
                        "[_extract_json_from_llm_response] JSON reparado rechazado — "
                        "truncamiento severo: columnas=%d (min=%d), n_rows=%s, constraints=%s.",
                        len(result.get("columns", [])), _MIN_COLUMNS,
                        "ok" if "n_rows" in result else "FALTA",
                        "ok" if "constraints" in result else "FALTA",
                    )
        except json.JSONDecodeError:
            pass

    return None


# ─────────────────────────────────────────────────────────
# HELPER — _build_base_context (v8)
# ─────────────────────────────────────────────────────────

def _build_base_context(state: ADAMState) -> dict:
    """Contexto base que TODOS los nodos heredan. Evita KeyError en prompts v8.

    Contiene las 17 variables globales que todos los prompts esperan.
    Cada nodo hace context = _build_base_context(state) y luego
    context.update({...campos específicos del nodo...}).
    """
    profile = state.get("studentProfile", "business")
    course = state.get("course_level", "grad")
    case_id = state.get("case_id", "no-id")

    logger.debug(
        "[_build_base_context] case_id=%s profile=%s has_m2=%s has_m3=%s has_m4=%s",
        case_id, profile,
        bool(state.get("doc2_eda")),
        bool(state.get("m3_content")),
        bool(state.get("m4_content")),
    )

    # Extrae nombre de empresa del título con fallback robusto
    titulo = state.get("titulo", "La empresa del caso")
    if "—" in titulo:
        nombre_empresa = titulo.split("—")[0].strip()
    elif " - " in titulo:
        nombre_empresa = titulo.split(" - ")[0].strip()
    elif "–" in titulo:  # en-dash
        nombre_empresa = titulo.split("–")[0].strip()
    else:
        nombre_empresa = titulo[:50]

    # Fix M-09: guard final — nombre_empresa nunca debe ser vacío.
    # Un título vacío o sin delimitadores producía nombre_empresa=""
    # y luego preguntas M4 con "métrica de " sin empresa.
    if not nombre_empresa or not nombre_empresa.strip():
        nombre_empresa = "la empresa del caso"

    # Extrae hipótesis del dilema
    dilema = state.get("dilema_brief", "")
    dilema_hypotheses = dilema[:500] if dilema else "No hay hipótesis disponibles del M1."

    # Extrae riesgo principal de M3 o M4 para M5 Questions (push-back P2).
    # Cubre dos formatos de M3:
    #   - audit  (business):  heading ## / ### / #### con número de sección o título semántico
    #   - experiment (ml_ds): campo inline **5. Principal Sesgo o Confusión:** dentro de sección de algoritmo
    _RISK_PATTERNS = [
        # Audit format — heading numbered sections (3.3, 4.4, etc.)
        r'#{2,4}\s*(?:3\.3|4\.4)[^\n]*\n(.*?)(?=#{2,4}|\Z)',
        # Audit format — heading semántico: "Riesgos de Interpretación / Implementación"
        r'#{2,4}\s*[Rr]iesgo[s]?\s+de\s+[Ii]nterp[^\n]*\n(.*?)(?=#{2,4}|\Z)',
        r'#{2,4}\s*[Rr]iesgo[s]?\s+de\s+[Ii]mpl[^\n]*\n(.*?)(?=#{2,4}|\Z)',
        r'#{2,4}\s*[Pp]unto[s]?\s+[Cc]iego[^\n]*\n(.*?)(?=#{2,4}|\Z)',
        r'#{2,4}\s*[Ss]upuesto[s]?\s+[Ff]r[^\n]*\n(.*?)(?=#{2,4}|\Z)',
        r'#{2,4}\s*[Ii]mpl[^\n]*[Rr]iesgo[^\n]*\n(.*?)(?=#{2,4}|\Z)',
        # Experiment format (ml_ds) — inline bold field inside algorithm section:
        # **5. Principal Sesgo o Confusión:** texto  OR  **Principal Sesgo:** texto
        r'\*\*\s*\d+[\.\):\s]+[Pp]rincipal\s+[Ss]esgo[^*\n]*\*\*[:\s]*(.*?)(?=\n\*\*\d|\n#{2,4}|\Z)',
        r'\*\*[Pp]rincipal\s+[Ss]esgo[^*\n]*\*\*[:\s]*(.*?)(?=\n\*\*\d|\n#{2,4}|\Z)',
        # Experiment format — "Sesgo o Confusión" / "Sesgo de Confusión" variants
        r'\*\*[^*\n]*[Ss]esgo[^*\n]*[Cc]onfusi[^*\n]*\*\*[:\s]*(.*?)(?=\n\*\*\d|\n#{2,4}|\Z)',
        # Experiment format — numbered field "5. ..." OR "**Limitación Principal:**"
        r'\*\*[^*\n]*[Ll]imitaci[oó]n[^*\n]*[Pp]rincipal[^*\n]*\*\*[:\s]*(.*?)(?=\n\*\*\d|\n#{2,4}|\Z)',
        # Experiment format — "**Overfitting / Data Drift / Degradación:**"
        r'\*\*[^*\n]*(?:[Oo]verfitting|[Dd]ata\s+[Dd]rift|[Dd]egradaci)[^*\n]*\*\*[:\s]*(.*?)(?=\n\*\*\d|\n#{2,4}|\Z)',
    ]

    _RISK_KEYWORDS = re.compile(
        r'riesgo|sesgo|drift|limitaci|confusi|bias|degrad|sobreaj|overfitting|'
        r'fragilidad|punto\s+ciego|supuesto|advertencia|precauci',
        re.IGNORECASE
    )

    def _extract_main_risk(content: str) -> str | None:
        for _pat in _RISK_PATTERNS:
            _m = re.search(_pat, content, re.DOTALL | re.IGNORECASE)
            if _m:
                text = _m.group(1).strip()
                # Strip any leading markdown from captured text
                text = re.sub(r'^#+\s*', '', text).strip()
                text = text[:200]
                if len(text) > 30:
                    return text
        # Fallback semántico: buscar párrafo que contenga palabras clave de riesgo.
        # Excluir párrafos que empiezan con # (headings) o son títulos de algoritmos.
        paras = [
            p.strip() for p in content.split('\n\n')
            if len(p.strip()) > 60 and not p.strip().startswith('#')
        ]
        # Preferir párrafos con palabras clave de riesgo
        risk_paras = [p for p in paras if _RISK_KEYWORDS.search(p)]
        if risk_paras:
            return risk_paras[-1][:200]
        # Último párrafo sustantivo sin heading
        return paras[-1][:200] if paras else None

    m3 = state.get("m3_content", "")
    m4 = state.get("m4_content", "")
    main_risk = None
    if m3 and "[M3_NOT_EXECUTED]" not in m3:
        main_risk = _extract_main_risk(m3)
    if not main_risk and m4 and "[M4_GENERATION_ERROR]" not in m4:
        main_risk = _extract_main_risk(m4)
    if not main_risk:
        main_risk = "Revisar supuestos del modelo antes de escalar la implementación"

    # Marco temporal según nivel del curso
    if course == "executive":
        impl_time = "las próximas 4 semanas"
    elif course == "grad":
        impl_time = "los próximos 100 días"
    else:
        impl_time = "el próximo semestre"

    grounding = state.get("ai_grounding_context", {})
    grounding_generation_hints: dict[str, Any] = {}
    grounding_instructional_scope: dict[str, Any] = {}
    grounding_pedagogical_intent: dict[str, Any] = {}
    grounding_course_identity: dict[str, Any] = {}
    if isinstance(grounding, dict):
        grounding_generation_hints = cast(dict[str, Any], grounding.get("generation_hints", {}))
        grounding_instructional_scope = cast(dict[str, Any], grounding.get("instructional_scope", {}))
        grounding_pedagogical_intent = cast(dict[str, Any], grounding.get("pedagogical_intent", {}))
        grounding_course_identity = cast(dict[str, Any], grounding.get("course_identity", {}))

    algoritmos = list(state.get("algoritmos", []))
    for preferred in grounding_generation_hints.get("preferred_techniques", []):
        if isinstance(preferred, str) and preferred and preferred not in algoritmos:
            algoritmos.append(preferred)
    profile_for_focus, primary_family = _resolve_generation_focus(
        state,
        default_unresolved_ml_ds_to_classification=True,
    )

    return {
        "student_profile": profile_for_focus,
        "primary_family": primary_family or "desconocida",
        "pregunta_eje": state.get("pregunta_eje") or "",
        "output_language": state.get("output_language", "es"),
        "case_id": case_id,
        "course_level": course,
        "max_investment_pct": state.get("max_investment_pct", 8),
        "urgency_frame": state.get("urgency_frame", "48-96 horas"),
        "protected_columns": json.dumps(
            state.get("protected_columns", ["target", "id", "date"])
        ),
        "main_risk_from_m3_m4": main_risk,
        "is_docente_only": state.get("is_docente_only", True),
        "implementation_timeframe": impl_time,
        "industria": state.get("industria", ""),
        "industry_cagr_range": state.get("industry_cagr_range", "5-8%"),
        "nombre_empresa": nombre_empresa,
        "dilema_hypotheses": dilema_hypotheses,
        "output_depth": state.get("output_depth", ""),
        "algoritmos": json.dumps(algoritmos, ensure_ascii=False),
        "titulo": state.get("titulo", ""),
        "grounding_modules": json.dumps(grounding_instructional_scope.get("modules", []), ensure_ascii=False),
        "grounding_objectives": json.dumps(
            grounding_pedagogical_intent.get("specific_objectives", []),
            ensure_ascii=False,
        ),
        "grounding_generation_hints": json.dumps(grounding_generation_hints, ensure_ascii=False),
        "grounding_course_identity": json.dumps(grounding_course_identity, ensure_ascii=False),
    }


# #305 Gate 1b — Condiciona POR PERFIL la "regla 7" y la prosa de `dataset_schema_required`
# en el texto ENSAMBLADO para business+clasificación. La base (compartida) permite `null`/
# continuo, legítimo para ml_ds y para business en otras familias; aquí se NEUTRALIZA esa
# permisión SOLO para business+clasificación, de modo que el prompt ya no se contradiga con
# `M1_CLASSIFICATION_BUSINESS_TARGET_BLOCK`. La sustitución corre ANTES de `.format()` (el
# template aún tiene `{student_profile}` sin formatear) y los reemplazos NO introducen llaves
# nuevas. Si la base deriva y un `old` deja de encontrarse, el `.replace` es no-op y el guard
# test (permisivo ABSENT / restrictivo PRESENT) lo detecta en CI — nunca falla un job en runtime.
_BUSINESS_CLF_PERMISSIVE_SUBSTITUTIONS: tuple[tuple[str, str], ...] = (
    (
        '**Obligatorio cuando {student_profile}="ml_ds"**. Para "business" puedes\n'
        "emitir `null` (el pipeline mantiene el comportamiento heurístico previo).",
        '**Obligatorio** (también para "business" en clasificación). En clasificación el '
        "contrato de target es OBLIGATORIO y binario — NO `null`, NO continuo "
        "(ver el bloque de target binario de dominio más abajo).",
    ),
    (
        '7. Para "business" perfil puedes emitir `null` o un contrato simple con un único\n'
        "   target gerencial (ej: `revenue`, `margin_pct`).",
        '7. Para "business" en clasificación NO emitas `null` ni un target continuo '
        "(`revenue`, `margin_pct`): el target es OBLIGATORIO y binario de dominio "
        "(ver el bloque de target binario de dominio más abajo).",
    ),
)


def _assemble_architect_prompt(context: dict, *, lens_on: bool = False) -> str:
    """Selecciona el prompt M1 por familia y lo formatea con el contexto.

    ``lens_on`` (Issue #437 Fase 2) appends the brace-free ``ARCHITECT_IMPACT_LENS_BLOCK``
    (value_model emission + lens-aware option dimension). Default ``False`` so the existing SHA
    snapshot / differential tests keep asserting the byte-identical base+anchor assembly; the
    production caller passes ``settings.impact_lens_architect``.

    Punto único de ensamblado del prompt del architect. El gate por perfil (#301) vive AQUÍ,
    de modo que el prompt ensamblado para ml_ds queda byte-idéntico (el snapshot de Item 4 /
    Riesgo #1 lo vigila)::

        family/profile
          ├─ ml_ds + clasificación ──────► base+anchor, SIN cirugía  → byte-idéntico
          ├─ business + clasificación ───► base+anchor
          │       + cirugía: neutraliza regla 7 / prosa permisiva (#305 Gate 1b)
          │       + M1_CLASSIFICATION_BUSINESS_TARGET_BLOCK (PR2b)
          └─ business/otros + otra fam ──► base, SIN cirugía  (null/continuo legítimo)
    """
    family = str(context.get("primary_family") or "")
    profile = str(context.get("student_profile") or "")
    template = CASE_ARCHITECT_PROMPT_BY_FAMILY.get(family, CASE_ARCHITECT_PROMPT)
    # business + clasificación: exige un target binario de dominio. Primero NEUTRALIZA la
    # permisión `null`/continuo en el texto (Gate 1b) y luego añade el bloque obligatorio
    # (PR2b). Gate por perfil → ml_ds queda byte-idéntico. El bloque no tiene placeholders.
    if profile == "business" and family == "clasificacion":
        for old, new in _BUSINESS_CLF_PERMISSIVE_SUBSTITUTIONS:
            template = template.replace(old, new)
        template = template + M1_CLASSIFICATION_BUSINESS_TARGET_BLOCK
    # Issue #437 (ADR 0003, Fase 2) — append the Impact Lens block when enabled (value_model
    # emission + lens-aware option dimension; Exhibit 1 stays a USD P&L per DD3). Purely additive +
    # brace-free → lens_on=False is byte-identical to pre-#437 (the existing SHA still matches that
    # path); lens_on=True has its own frozen hash. Default False so callers/tests that omit it (incl.
    # the existing SHA snapshot) keep the byte-identical assembly.
    if lens_on:
        template = template + ARCHITECT_IMPACT_LENS_BLOCK
    return template.format(**context)


# ─────────────────────────────────────────────────────────
# NODO 1 — CASE ARCHITECT (Pro con Code Execution)
# ─────────────────────────────────────────────────────────
def case_architect(state: ADAMState, config: RunnableConfig) -> dict:
    """Diseña los cimientos del caso: empresa, dilema, exhibits e instrucciones."""
    cfg = Configuration.from_runnable_config(config)
    # Fase 1 cost cut: thinking "high"→"medium". case_architect stays on Pro
    # (Code Execution + downstream dependency), but trims Pro-rate reasoning tokens.
    llm = _get_architect_llm(
        resolve_node_model(cfg, NODE_CASE_ARCHITECT, cfg.architect_model),
        temperature=0.3,
        thinking_level="medium",
    )

    context = _build_base_context(state)
    context.update({
        "teacher_input": sanitize_untrusted_payload({
            "asignatura": state.get("asignatura", ""),
            "modulos": state.get("modulos", []),
            "nivel": state.get("nivel", "pregrado"),
            "perfil_estudiante": context.get("student_profile", "business"),
            "horas": state.get("horas", 4),
            "industria": state.get("industria", ""),
            "descripcion_escenario": state.get("descripcion", ""),
            "pregunta_guia_directiva": state.get("guidingQuestion", ""),
            "grounding_course_identity": context.get("grounding_course_identity", ""),
            "grounding_modules": context.get("grounding_modules", ""),
            "grounding_objectives": context.get("grounding_objectives", ""),
            "grounding_generation_hints": context.get("grounding_generation_hints", ""),
        }, per_field_limit=800, total_limit=2500),
    })

    # Issue #437 Fase 2 — append the Impact Lens block (value_model emission + lens-aware option
    # dimension) when enabled. lens_on=False is byte-identical to pre-#437 (DD5).
    prompt = _assemble_architect_prompt(context, lens_on=settings.impact_lens_architect)
    # Issue #437 Fase 3 — when the teacher set an explicit OVERRIDE, append a brace-free runtime hint
    # that CONSTRAINS the (otherwise domain-inferred) Fase-2 lens block to the override, so M1 frames
    # options + emits value_model by the SAME lens M4/M5/M6 take via the resolver (DD1 cross-module
    # coherence). Fires ONLY on a valid override → no override = byte-identical to Fase 2 (financial AND
    # non-financial-industry). Appended in the NODE (not in the frozen ARCHITECT_IMPACT_LENS_BLOCK) so
    # the architect SHA snapshots are untouched; the prompt is already formatted, so no second .format.
    _lens_override = state.get("impact_lens_override")
    if settings.impact_lens_architect and _lens_override in IMPACT_LENS_KEYS:
        prompt = prompt + build_impact_lens_architect_hint(_lens_override)

    try:
        result, profile_resolved, family_resolved, pregunta_eje = (
            _invoke_case_architect_with_contract(
                llm=llm,
                prompt=prompt,
                state=state,
            )
        )

        print(
            f"[case_architect] titulo='{result.titulo}', industria='{result.industria}', "
            f"profile={len(result.company_profile)} chars, "
            f"dilema={len(result.dilema_brief)} chars"
        )

        # Issue #225 — persiste contrato dataset↔dilema (None-safe).
        contract_dict = (
            result.dataset_schema_required.model_dump()
            if result.dataset_schema_required is not None
            else None
        )

        # Issue #228 — endurecemos el contrato emitido por el LLM con dos
        # validaciones deterministas:
        #   (a) coherencia semántica título↔target → warning si hay mismatch.
        #   (b) inferencia de leakage por naming → marca features obvias
        #       (retention_*, churn_*, nps, ...) cuando el target NO es de
        #       la familia retención. Cero tokens, idempotente.
        coherence_warnings = _validate_target_semantic_coherence(
            result.titulo,
            (contract_dict or {}).get("target_column") if contract_dict else None,
        )
        contract_dict = _infer_leakage_risk_from_naming(contract_dict)

        # Issue #301 PR2b (A1/A4) — convierte la detección de #228 en ACCIÓN para
        # business+clasificación: null/continuo/rol no-clasificación → classification_target
        # int binario. El spine downstream construye la columna; el nombre de dominio es
        # LLM-primario (lo empuja el bloque del prompt). Esta normalización solo corrige la
        # FORMA; el mismatch título↔target (nombre válido pero desalineado) lo maneja el
        # bloque Gate 2 de más abajo (#305), no esta función.
        contract_dict, target_enforced = _normalize_business_classification_target(
            contract_dict, profile=profile_resolved, family=family_resolved
        )
        # Issue #350 — sibling ml_ds+clasificación: coacciona un classification_target no-int
        # (str/multiclase) o de rol no-clasificación a int binario ANTES de persistir el contrato,
        # para que la cadena de schema (binario-only) no degrade en silencio (post-#348). No-op
        # para business / otras familias. Kill-switch MLDS_BINARY_TARGET_COERCE (default true).
        contract_dict, _ = _normalize_mlds_classification_target(
            contract_dict, profile=profile_resolved, family=family_resolved,
            enabled=settings.mlds_binary_target_coerce,
        )

        # Issue #301 #305 Gate 2 — enforcement de #228 por mismatch título↔target.
        # Si la forma NO se tuvo que normalizar (target ya era un classification_target
        # válido) pero su NOMBRE está semánticamente desalineado del título, reprompt UNA
        # vez para que el LLM lo renombre. Se acepta cualquier nombre de clasificación
        # válido sin re-juzgarlo con la heurística (a prueba de falsos positivos); el
        # re-_normalize garantiza la forma binaria pase lo que pase. Nunca falla el job.
        if _should_reprompt_on_target_mismatch(
            target_enforced=target_enforced,
            profile=profile_resolved,
            family=family_resolved,
            warnings=coherence_warnings,
        ):
            contract_dict, mismatch_note = _reprompt_business_target_on_mismatch(
                llm=llm, prompt=prompt, contract=contract_dict, title=result.titulo
            )
            contract_dict = _infer_leakage_risk_from_naming(contract_dict)
            contract_dict, _ = _normalize_business_classification_target(
                contract_dict, profile=profile_resolved, family=family_resolved
            )
            if mismatch_note:
                coherence_warnings = list(coherence_warnings) + [mismatch_note]

        # Issue #238/#242 — valida matriz de costos con la misma resolución de
        # familia que usan los dispatchers downstream.
        contract_dict, cost_warnings = _validate_business_cost_matrix(
            contract_dict, family_resolved, result.titulo
        )
        coherence_warnings = list(coherence_warnings) + cost_warnings

        # Issue F1 — valida la tasa de evento (fuente única M1↔M2) con la misma
        # resolución de perfil/familia. Gateada a ml_ds + clasificación binaria.
        contract_dict, rate_warnings = _validate_target_event_rate(
            contract_dict, family_resolved, result.titulo, profile_resolved
        )
        coherence_warnings = list(coherence_warnings) + rate_warnings
        if target_enforced:
            coherence_warnings.append(
                "target business+clasificación normalizado a classification_target binario "
                "(#301): revisar que el nombre refleje el evento del dilema."
            )

        # Issue #372 — verifica que Exhibit 2 imprima la fila de tasa de ocurrencia del
        # evento con el MISMO número que `target_event_rate` (acople F1). Reprompt-once-
        # then-DEGRADE targeted al anexo; gateado a ml_ds+clf, best-effort, nunca lanza. La
        # fila de completitud es warning-only. No toca el prompt → SHA256 intacto; no-op
        # byte-idéntico para business y otras familias.
        anexo_operativo_final = _invoke_m1_exhibit2_coherence(
            llm=llm,
            state=state,
            anexo_operativo=result.anexo_operativo,
            contract=contract_dict,
        )

        # Issue #437 Fase 2 — persist the architect's value_model (prompt-side only; NOT canonical
        # nor student-facing). It is the D-A hybrid REFINEMENT carrier: _resolve_impact_lens prefers
        # value_model["lens"] over the intake lens. Gated by the kill-switch (None when off → the
        # intake lens stands → byte-identical M4 behavior). We DELIBERATELY do NOT write
        # state["impact_lens"] here: on a resumed job state_input re-injects the intake lens and the
        # last-write-wins channel would clobber any refinement back to intake (the architect is
        # skip-short-circuited and never re-emits it). value_model is NOT in state_input, so the
        # durable checkpoint value SURVIVES resume — making it the resume-robust refinement source.
        value_model_dict = (
            result.value_model.model_dump()
            if (result.value_model is not None and settings.impact_lens_architect)
            else None
        )

        return {
            "current_agent": "case_architect",
            "value_model": value_model_dict,
            "titulo": result.titulo,
            "industria": result.industria,
            # Issue #377 — relabel any non-USD currency to USD at the source (structured-output
            # fields bypass sanitize_markdown). Best-effort, magnitude-preserving, kill-switch
            # gated; byte-identical when the field is already USD-only. anexo_operativo uses the
            # POST-#372 value (anexo_operativo_final) so the F1 rate row is already settled.
            "company_profile": _enforce_usd_currency_field(result.company_profile),
            "dilema_brief": _enforce_usd_currency_field(result.dilema_brief),
            "pregunta_eje": (
                _enforce_usd_currency_field(pregunta_eje) if pregunta_eje else pregunta_eje
            ),
            "doc1_instrucciones": _enforce_usd_currency_field(result.instrucciones_estudiante),
            # #356 — normalize <br> row separators → real newlines BEFORE the USD relabel,
            # so both the frontend GFM parser and the backend .splitlines() anchor parser see
            # a real multi-line table (the architect structured output bypasses sanitize_markdown).
            "doc1_anexo_financiero": _enforce_usd_currency_field(
                _normalize_exhibit_field(result.anexo_financiero)
            ),
            "doc1_anexo_operativo": _enforce_usd_currency_field(
                _normalize_exhibit_field(anexo_operativo_final)
            ),
            "doc1_anexo_stakeholders": _enforce_usd_currency_field(
                _normalize_exhibit_field(result.anexo_stakeholders)
            ),
            # downstream nodes leen state["dataset_schema_required"] y degradan
            # gracefully al comportamiento previo si es None.
            "dataset_schema_required": contract_dict,
            # Issue #228 — semilla de data_gap_warnings con detección de
            # mismatch título↔target. schema_designer concatenará sus propios
            # warnings (missing/leakage) preservando esta semilla.
            "data_gap_warnings": coherence_warnings,
        }
    except RuntimeError:
        raise
    except Exception as e:
        logger.error("[case_architect] ERROR: %s", e, exc_info=True)
        return {
            "current_agent": "case_architect",
            "titulo": "Error en generación — reintentar",
            "industria": state.get("industria", "general"),
            "company_profile": "Error en generación",
            "dilema_brief": "Error en generación",
            "doc1_instrucciones": "",
            "doc1_anexo_financiero": "",
            "doc1_anexo_operativo": "",
            "doc1_anexo_stakeholders": "",
        }


# ─────────────────────────────────────────────────────────
# Issue #360 — M1 Exhibit coherence (ml_ds + clasificacion)
# Reprompt-once-then-DEGRADE; best-effort; never raises. Opposite of M4/M5,
# which hard-fail: M1 MUST complete the job. No new canonical/state key.
# ─────────────────────────────────────────────────────────
_M1_WRITER_EXHIBIT_REPROMPT_HEADER = (
    "\n\n# CORRECCIÓN OBLIGATORIA DE COHERENCIA CON EXHIBITS\n"
    "Tu salida anterior citó cifras de negocio marcadas con (Exhibit N) que NO "
    "coinciden con la tabla de ese anexo. Reescribe la narrativa COMPLETA usando "
    "ÚNICAMENTE cifras que aparezcan textualmente en los Exhibits citados; NUNCA "
    "aproximes ni redondees. Incoherencias detectadas:\n"
)
_M1_QUESTIONS_EXHIBIT_REPROMPT_HEADER = (
    "\n\n# CORRECCIÓN OBLIGATORIA DE COHERENCIA CON EXHIBITS\n"
    "Algunas preguntas citan cifras (campo exhibit_ref) que NO coinciden con la tabla "
    "de ese anexo. Regenera EXACTAMENTE 3 preguntas con el mismo schema, usando sólo "
    "cifras que aparezcan textualmente en el Exhibit referido; NUNCA aproximes ni "
    "redondees. Incoherencias detectadas:\n"
)
_M1_QUESTIONS_OPTION_REPROMPT_HEADER = (
    "\n\n# CORRECCIÓN OBLIGATORIA DE COHERENCIA DE OPCIONES\n"
    "Algunas preguntas recomiendan en `solucion_esperada` una opción estratégica que NO "
    "existe en el caso, o que el propio enunciado de esa pregunta no presenta al estudiante. "
    "El caso define un conjunto cerrado de opciones (A, B, C). Regenera EXACTAMENTE 3 "
    "preguntas con el mismo schema: el enunciado de cada pregunta de decisión DEBE presentar "
    "las opciones (A/B/C) entre las que el estudiante elige, y `solucion_esperada` SOLO puede "
    "recomendar una de las opciones presentadas en su enunciado, nombrándola por su letra. "
    "NUNCA recomiendes una opción inexistente ni ausente del enunciado. Incoherencias "
    "detectadas:\n"
)
_M4_QUESTIONS_OPTION_REPROMPT_HEADER = (
    "\n\n# CORRECCIÓN OBLIGATORIA DE COHERENCIA DE OPCIONES (Módulo 4)\n"
    "Algunas preguntas recomiendan en `solucion_esperada` una opción estratégica que NO "
    "existe en el caso, o que el propio enunciado de esa pregunta no presenta al estudiante. "
    "El caso define un conjunto cerrado de opciones (A, B, C). Regenera EXACTAMENTE 3 "
    "preguntas con el MISMO schema y los MISMOS `numero` (1, 2, 3): el enunciado de cada "
    "pregunta de decisión DEBE presentar las opciones (A/B/C) entre las que el estudiante "
    "elige, y `solucion_esperada` SOLO puede recomendar una de las opciones presentadas en "
    "su enunciado, nombrándola por su letra. NUNCA recomiendes una opción inexistente ni "
    "ausente del enunciado. Incoherencias detectadas:\n"
)


def _build_m1_exhibit_anexos(state: ADAMState) -> dict[str, str]:
    """Raw (untruncated) Exhibit tables from state for M1 coherence checks (#360).

    Reads ``doc1_anexo_*`` directly — NOT the ``sanitize_untrusted_payload`` copy the
    prompt receives, whose per-field truncation could cut table rows and cause a false
    negative.
    """
    return {
        "financiero": str(state.get("doc1_anexo_financiero") or ""),
        "operativo": str(state.get("doc1_anexo_operativo") or ""),
        "stakeholders": str(state.get("doc1_anexo_stakeholders") or ""),
    }


def _extract_business_cost_matrix(state: ADAMState) -> dict | None:
    """Return the normalized ``business_cost_matrix`` sub-dict, or ``None`` (Issue #361).

    Reads ``state["dataset_schema_required"]["business_cost_matrix"]`` — the dict already
    validated + normalized by ``_validate_business_cost_matrix`` inside ``case_architect``
    (which runs before the ``case_writer ∥ case_questions`` fan-out). The same source M3
    consumes via the contract block. ``None`` whenever the contract or the matrix is absent
    (business profile, or ml_ds+clasificación with an absent/invalid matrix the validator
    nulified) — the P3 block degrades to a qualitative trade-off in that case.
    """
    contract = state.get("dataset_schema_required")
    if not isinstance(contract, dict):
        return None
    matrix = contract.get("business_cost_matrix")
    return matrix if isinstance(matrix, dict) else None


def _invoke_m1_writer_with_exhibit_coherence(
    *, llm: Any, prompt: str, state: ADAMState, narrativa_raw: str
) -> str:
    """Validate + reprompt-once-then-DEGRADE the M1 narrative (Issue #360).

    Gated to ml_ds + clasificacion (byte-identical no-op otherwise). Best-effort: any
    internal error keeps the best narrative and the job continues. Never raises.
    """
    if not _is_ml_ds_classification(state):
        return narrativa_raw
    try:
        anexos = _build_m1_exhibit_anexos(state)
        violations = validate_narrative_exhibit_coherence(narrativa_raw, anexos)
        if not violations:
            return narrativa_raw
        bullet_list = "\n".join(f"- {violation}" for violation in violations)
        print(
            f"[case_writer] Incoherencias Exhibit M1 detectadas: {violations}. "
            "Reprompt explícito (1/1)."
        )
        reprompt = prompt + _M1_WRITER_EXHIBIT_REPROMPT_HEADER + bullet_list
        corrected = sanitize_markdown(_extract_text(llm.invoke(reprompt)))
        violations_2 = validate_narrative_exhibit_coherence(corrected, anexos)
        if not violations_2:
            print("[case_writer] Reprompt coherencia Exhibit M1 OK")
            return corrected
        logger.warning(
            "[case_writer] coherencia Exhibit M1 degradada tras reprompt",
            extra={
                "node": "case_writer",
                "violations": violations_2,
                "case_id": state.get("case_id"),
            },
        )
        # DEGRADE: keep whichever pass violates least.
        return corrected if len(violations_2) < len(violations) else narrativa_raw
    except Exception as exc:  # best-effort — a validator bug must never fail M1
        logger.warning(
            "[case_writer] validador coherencia Exhibit M1 falló (best-effort): %s",
            exc,
            extra={"node": "case_writer", "case_id": state.get("case_id")},
        )
        return narrativa_raw


def _apply_m1_questions_exhibit_coherence(
    *, llm: Any, prompt: str, state: ADAMState, preguntas_dict: list[dict]
) -> list[dict]:
    """Validate + reprompt-once-then-DEGRADE the M1 questions (Issue #360).

    Gated to ml_ds + clasificacion. The reprompt re-invokes structured output, which may
    raise ``ValidationError`` / ``OutputParserException`` / ``ValueError``; any failure or
    a second violation degrades to the pass-1 questions. Never raises (in particular never
    propagates ``RuntimeError``), so the job always completes.
    """
    if not _is_ml_ds_classification(state):
        return preguntas_dict
    try:
        anexos = _build_m1_exhibit_anexos(state)
        violations = validate_questions_exhibit_coherence(preguntas_dict, anexos)
        if not violations:
            return preguntas_dict
        bullet_list = "\n".join(f"- {violation}" for violation in violations)
        print(
            f"[case_questions] Incoherencias Exhibit M1 detectadas: {violations}. "
            "Reprompt explícito (1/1)."
        )
        reprompt = prompt + _M1_QUESTIONS_EXHIBIT_REPROMPT_HEADER + bullet_list
        try:
            resultado: GeneradorPreguntasM1Output = llm.with_structured_output(
                GeneradorPreguntasM1Output
            ).invoke(reprompt)
            corrected = [p.model_dump() for p in resultado.preguntas]
        except (ValidationError, OutputParserException, ValueError) as exc:
            logger.warning(
                "[case_questions] reprompt coherencia Exhibit M1 inválido — degrada a pass-1: %s",
                exc,
                extra={"node": "case_questions", "case_id": state.get("case_id")},
            )
            return preguntas_dict
        violations_2 = validate_questions_exhibit_coherence(corrected, anexos)
        if not violations_2:
            print("[case_questions] Reprompt coherencia Exhibit M1 OK")
            return corrected
        logger.warning(
            "[case_questions] coherencia Exhibit M1 degradada tras reprompt",
            extra={
                "node": "case_questions",
                "violations": violations_2,
                "case_id": state.get("case_id"),
            },
        )
        return preguntas_dict
    except Exception as exc:  # best-effort — never fail M1
        logger.warning(
            "[case_questions] validador coherencia Exhibit M1 falló (best-effort): %s",
            exc,
            extra={"node": "case_questions", "case_id": state.get("case_id")},
        )
        return preguntas_dict


def _apply_m1_questions_option_coherence(
    *, llm: Any, prompt: str, state: ADAMState, preguntas_dict: list[dict]
) -> list[dict]:
    """Validate + reprompt-once-then-DEGRADE the M1 question option coherence.

    Internal coherence: a ``solucion_esperada`` must only recommend a strategic option that
    exists in the case (A/B/C, derived from ``dilema_brief``) and that its own ``enunciado``
    presents. Gated to the classification family for BOTH profiles (business AND ml_ds) and
    behind the ``m1_option_coherence`` kill-switch; a byte-identical no-op otherwise. The
    reprompt re-invokes structured output (may raise ``ValidationError`` /
    ``OutputParserException`` / ``ValueError``); any failure or a residual violation degrades
    to the pass-1 questions. Best-effort: never raises (in particular never propagates
    ``RuntimeError``), so the job always completes. Runs AFTER the Exhibit-coherence pass.
    """
    if not settings.m1_option_coherence or not _is_classification_family(state):
        return preguntas_dict
    try:
        dilema_brief = str(state.get("dilema_brief") or "")
        violations = validate_question_option_coherence(preguntas_dict, dilema_brief)
        if not violations:
            return preguntas_dict
        bullet_list = "\n".join(f"- {violation}" for violation in violations)
        print(
            f"[case_questions] Incoherencias de opciones M1 detectadas: {violations}. "
            "Reprompt explícito (1/1)."
        )
        reprompt = prompt + _M1_QUESTIONS_OPTION_REPROMPT_HEADER + bullet_list
        try:
            resultado: GeneradorPreguntasM1Output = llm.with_structured_output(
                GeneradorPreguntasM1Output
            ).invoke(reprompt)
            corrected = [p.model_dump() for p in resultado.preguntas]
        except (ValidationError, OutputParserException, ValueError) as exc:
            logger.warning(
                "[case_questions] reprompt coherencia de opciones inválido — degrada a pass-1: %s",
                exc,
                extra={"node": "case_questions", "case_id": state.get("case_id")},
            )
            return preguntas_dict
        violations_2 = validate_question_option_coherence(corrected, dilema_brief)
        if not violations_2:
            print("[case_questions] Reprompt coherencia de opciones M1 OK")
            return corrected
        logger.warning(
            "[case_questions] coherencia de opciones M1 degradada tras reprompt",
            extra={
                "node": "case_questions",
                "violations": violations_2,
                "case_id": state.get("case_id"),
            },
        )
        return preguntas_dict
    except Exception as exc:  # best-effort — never fail M1
        logger.warning(
            "[case_questions] validador coherencia de opciones M1 falló (best-effort): %s",
            exc,
            extra={"node": "case_questions", "case_id": state.get("case_id")},
        )
        return preguntas_dict


# ─────────────────────────────────────────────────────────
# M4 (Impacto) question option coherence — reuses the M1 validator with the FLOOR
# universe {A,B,C} (M4 has no dilema_brief). See m1_grounding.validate_question_option_coherence.
# ─────────────────────────────────────────────────────────
_M4_VIOLATION_CODES = (
    ("OPTION_NONEXISTENT", "option_nonexistent"),
    ("OPTION_NOT_PRESENTED", "option_not_presented"),
)


def _m4_violation_types(violations: list[str]) -> list[str]:
    """Enumerated short codes for structured logging — never the raw message (no PII)."""
    codes: list[str] = []
    for violation in violations:
        for prefix, code in _M4_VIOLATION_CODES:
            if violation.startswith(prefix) and code not in codes:
                codes.append(code)
    return codes


def _apply_m4_questions_option_coherence(
    *, llm: Any, prompt: str, state: ADAMState, preguntas_dict: list[dict]
) -> list[dict]:
    """Validate + reprompt-once-then-DEGRADE the M4 (Impacto) question option coherence.

    Reuses the M1 option validator with the FLOOR universe (M4 has no ``dilema_brief``): a
    ``solucion_esperada`` may only recommend an option the case defines (A/B/C) and that its
    own ``enunciado`` presents. Gated to the classification family for BOTH profiles
    (business + ml_ds) behind the ``m4_question_coherence`` kill-switch; a byte-identical
    no-op otherwise. On a violation it reprompts ONCE (one Flash call); the corrected set is
    accepted ONLY if it preserves the question count AND the ``numero`` sequence (the grading
    key ``M4-Q{numero}`` in shared.student_reads/teacher_reads) AND is now coherent —
    otherwise it degrades to the pass-1 questions. ``GeneradorPreguntasOutput`` (unlike M1's
    schema) does NOT enforce count/numbering, so the identity guard is load-bearing.
    Best-effort: ANY throw (including a reprompt ``RuntimeError``) degrades to pass-1. Never
    raises, so the job always completes.

    Known coverage limit (same trade-off as M1, zero false positives): only A/B/C LETTER
    options are checked. Options named as models/prose ("desplegar Random Forest") or an
    enunciado that names a single option are not flagged; the M4 questions prompt boundary
    nudges the LLM to the letter form so the validator covers the reported defect.
    """
    log_extra = {"node": "m4_questions_generator", "case_id": state.get("case_id")}
    try:
        if not settings.m4_question_coherence or not _is_classification_family(state):
            return preguntas_dict
        violations = validate_question_option_coherence(preguntas_dict, "")
        if not violations:
            return preguntas_dict
        logger.info(
            "[m4_questions] reprompt de coherencia de opciones M4 disparado",
            extra={
                **log_extra,
                "violation_count": len(violations),
                "violation_types": _m4_violation_types(violations),
            },
        )
        bullet_list = "\n".join(f"- {violation}" for violation in violations)
        reprompt = prompt + _M4_QUESTIONS_OPTION_REPROMPT_HEADER + bullet_list
        try:
            resultado: GeneradorPreguntasOutput = llm.with_structured_output(
                GeneradorPreguntasOutput
            ).invoke(reprompt)
            corrected = [p.model_dump() for p in resultado.preguntas]
        except (ValidationError, OutputParserException, ValueError) as exc:
            logger.warning(
                "[m4_questions] reprompt coherencia de opciones M4 inválido — degrada a pass-1: %s",
                exc,
                extra=log_extra,
            )
            return preguntas_dict
        # Identity guard: a reprompt that drops/adds/renumbers a question would corrupt the
        # ``M4-Q{numero}`` grading key (shared.student_reads) — reject it, keep pass-1.
        if [q.get("numero") for q in corrected] != [q.get("numero") for q in preguntas_dict]:
            logger.warning(
                "[m4_questions] reprompt M4 alteró conteo/numero — degrada a pass-1",
                extra=log_extra,
            )
            return preguntas_dict
        residual = validate_question_option_coherence(corrected, "")
        if not residual:
            logger.info(
                "[m4_questions] coherencia de opciones M4 corregida por reprompt",
                extra={**log_extra, "degraded": False},
            )
            return corrected
        logger.warning(
            "[m4_questions] coherencia de opciones M4 degradada tras reprompt",
            extra={**log_extra, "violation_types": _m4_violation_types(residual), "degraded": True},
        )
        return preguntas_dict
    except Exception as exc:  # best-effort — a coherence pass must never fail the job
        logger.warning(
            "[m4_questions] validador coherencia de opciones M4 falló (best-effort): %s",
            exc,
            extra=log_extra,
        )
        return preguntas_dict


# ─────────────────────────────────────────────────────────
# Issue #372 — Exhibit 2 mandatory-row coherence (ml_ds + clasificacion)
# Runs INSIDE case_architect (the owner of anexo_operativo + target_event_rate), unlike
# #360 which runs in the writer/questions fan-out. Only the architect can fix a missing
# row. Reprompt-once-then-DEGRADE; best-effort; never raises. The PRIMARY trigger is the
# deterministic F1 coupling; the completeness row is heuristic → warning-only (never
# reprompts). No prompt-constant edit → _MLDS_ARCHITECT_PROMPT_SHA256 stays frozen.
# ─────────────────────────────────────────────────────────
# A corrected anexo shorter than this fraction of the original is treated as a gutted
# rewrite (rate row added at the cost of dropping operational rows) and rejected, so the
# writer/questions never read a thinner Exhibit 2 than the architect produced.
_M1_EXHIBIT2_MIN_REPROMPT_RATIO = 0.6


def _m1_exhibit2_reprompt(anexo_operativo: str, rate_pct: float) -> str:
    """Focused, self-contained reprompt to rewrite the COMPLETE Exhibit 2 anexo (#372).

    Asks for the full anexo (heading + every row), changing only what's needed to print the
    rate row, so the corrected text replaces ``doc1_anexo_operativo`` at comparable length
    (the length-floor guard at the call site rejects a gutted rewrite). Carries the EXACT
    required number (``rate_pct``) so the correction is deterministic, not a vague "you are
    incoherent". Concatenated at runtime (never ``.format`` — the anexo may carry ``{}``) and
    is a runtime string, so it never touches the frozen architect prompt.
    """
    return (
        "\n\n# CORRECCIÓN OBLIGATORIA DE EXHIBIT 2 (Operativo)\n"
        "El Exhibit 2 (Operativo) que generaste NO imprime la fila obligatoria de calidad "
        "de datos «Tasa de ocurrencia del evento objetivo» con el número correcto. Reescribe "
        "el Exhibit 2 (Operativo) COMPLETO — su encabezado y TODAS sus filas — corrigiendo "
        "ÚNICAMENTE lo necesario para que incluya una fila de calidad de datos cuya tasa de "
        f"ocurrencia del evento sea EXACTAMENTE {rate_pct:.1f} % (debe coincidir con la "
        "prevalencia del dataset). Conserva la fila de completitud de campos críticos y toda "
        "otra fila operativa existente. Devuelve SOLO el markdown del Exhibit 2 (Operativo) "
        "(encabezado + tabla), sin otros Exhibits ni texto adicional.\n\n"
        "Exhibit 2 actual:\n"
        f"{anexo_operativo}\n"
    )


def _invoke_m1_exhibit2_coherence(
    *, llm: Any, state: ADAMState, anexo_operativo: str, contract: dict | None
) -> str:
    """Validate + reprompt-once-then-DEGRADE the Exhibit 2 rate row (Issue #372).

    Gated to ml_ds + clasificacion (byte-identical no-op otherwise). PRIMARY check is the
    deterministic F1 coupling: a miss triggers ONE targeted text reprompt that rewrites the
    full Exhibit 2 with the exact number; the rewrite is accepted only if it now prints the
    rate AND preserves the anexo's bulk, otherwise the original is kept. The completeness row
    is a SECONDARY heuristic that only logs a warning — it NEVER drives the reprompt.
    Best-effort: any internal error keeps the original anexo and the job continues. Never raises.
    """
    if not _is_ml_ds_classification(state):
        return anexo_operativo
    try:
        rate = contract.get("target_event_rate") if isinstance(contract, dict) else None

        # SECONDARY heuristic — warning-only, never reprompt (D2).
        completeness_violations = detect_exhibit2_completeness_row(anexo_operativo)
        if completeness_violations:
            logger.warning(
                "[case_architect] Exhibit 2 sin fila de completitud reconocible "
                "(heurística, warning-only)",
                extra={
                    "node": "case_architect",
                    "violations": completeness_violations,
                    "case_id": state.get("case_id"),
                },
            )

        # PRIMARY deterministic F1 coupling — reprompt-worthy.
        violations = validate_exhibit2_event_rate(anexo_operativo, rate)
        if not violations:
            return anexo_operativo
        if not isinstance(rate, (int, float)) or isinstance(rate, bool):
            return anexo_operativo  # unreachable when violations≠[]; satisfies typing
        rate_pct = float(rate) * 100.0
        print(
            f"[case_architect] Exhibit 2 no imprime la tasa F1 ({rate_pct:.1f} %): "
            f"{violations}. Reprompt targeted (1/1)."
        )
        corrected = sanitize_markdown(
            _extract_text(llm.invoke(_m1_exhibit2_reprompt(anexo_operativo, rate_pct)))
        )
        # Accept ONLY a rewrite that (a) now prints the rate AND (b) preserves the anexo's
        # bulk. A gutted rewrite that satisfies the rate by dropping operational rows is
        # rejected — we keep the original (richer, only rate-incoherent) anexo instead of
        # shipping a thinner one downstream. F1 presence is binary, so there is no
        # "partially better" pass to salvage.
        corrected_ok = (
            bool(corrected)
            and not validate_exhibit2_event_rate(corrected, rate)
            and len(corrected) >= int(len(anexo_operativo) * _M1_EXHIBIT2_MIN_REPROMPT_RATIO)
        )
        if corrected_ok:
            print("[case_architect] Reprompt coherencia Exhibit 2 F1 OK")
            return corrected
        logger.warning(
            "[case_architect] coherencia Exhibit 2 F1 no corregida tras reprompt — "
            "se conserva el anexo original",
            extra={
                "node": "case_architect",
                "violations": violations,
                "case_id": state.get("case_id"),
            },
        )
        return anexo_operativo
    except Exception as exc:  # best-effort — a validator bug must never fail M1
        logger.warning(
            "[case_architect] validador coherencia Exhibit 2 F1 falló (best-effort): %s",
            exc,
            extra={"node": "case_architect", "case_id": state.get("case_id")},
        )
        return anexo_operativo


# ─────────────────────────────────────────────────────────
# Issue #377 — USD-only currency backstop at the architect SOURCE
# The architect emits structured output (CaseArchitectOutput) that BYPASSES sanitize_markdown
# (where the same backstop runs for downstream prose, #377 PUNTO 2). So the source free-text
# fields — the highest money-density surfaces (Exhibits + dilema) — must be relabeled to USD
# explicitly here. Pure deterministic relabel; magnitudes preserved; kill-switch gated; never
# raises (enforce_usd_currency is best-effort). Profile-agnostic. No prompt edit → SHA256 frozen.
# ─────────────────────────────────────────────────────────
def _enforce_usd_currency_field(text: str) -> str:
    """Relabel non-USD currency → USD in one architect free-text field (kill-switch gated)."""
    if not settings.case_usd_currency_enforce:
        return text
    return enforce_usd_currency(text)


def _normalize_exhibit_field(text: str) -> str:
    """Normalize ``<br>`` → real newlines in one M1 exhibit field (kill-switch gated, #356)."""
    if not settings.m1_exhibit_normalize:
        return text
    return normalize_exhibit_markdown(text)


# ─────────────────────────────────────────────────────────
# NODO 2a — CASE WRITER (Flash, paralelo con 2b)
# ─────────────────────────────────────────────────────────
def case_writer(state: ADAMState, config: RunnableConfig) -> dict:
    """Redacta la narrativa larga del caso (2,500-3,000 palabras)."""
    cfg = Configuration.from_runnable_config(config)
    # Fix A-04: narrativa de 3000 palabras ≈ 4000-4500 tokens output.
    # _get_writer_llm tiene max_output_tokens=8192 — suficiente en la mayoría de
    # modelos Flash, pero con thinking_level="low" algunos tokens se consumen en
    # el bloque de thinking interno, dejando margen ajustado.
    # 12288 garantiza que incluso con Exhibits extensos (>1500 chars c/u) el modelo
    # complete la narrativa sin truncamiento silencioso.
    primary = ChatGoogleGenerativeAI(
        model=cfg.writer_model,
        temperature=0.7,
        thinking_level="low",
        max_output_tokens=12288,
        max_retries=2,
        api_key=os.getenv("GEMINI_API_KEY"),
        rate_limiter=_rate_limiter,
    )
    # Fallback: gemini-2.5-flash con mismos tokens para narrativa extensa.
    fallback = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=0.7,
        max_output_tokens=12288,
        max_retries=2,
        api_key=os.getenv("GEMINI_API_KEY"),
        rate_limiter=_rate_limiter,
    )
    llm = primary.with_fallbacks([fallback])

    context = _build_base_context(state)
    context.update({
        "architect_output": sanitize_untrusted_payload({
            "titulo": state.get("titulo", ""),
            "company_profile": state.get("company_profile", ""),
            "dilema_brief": state.get("dilema_brief", ""),
            "instrucciones_estudiante": state.get("doc1_instrucciones", ""),
            "anexo_financiero": state.get("doc1_anexo_financiero", ""),
            "anexo_operativo": state.get("doc1_anexo_operativo", ""),
            "anexo_stakeholders": state.get("doc1_anexo_stakeholders", ""),
            "asignatura": state.get("asignatura", ""),
            "nivel": state.get("nivel", "pregrado"),
        }, per_field_limit=2000, total_limit=8000),
    })

    prompt = CASE_WRITER_PROMPT_BY_FAMILY.get(
        context["primary_family"], CASE_WRITER_PROMPT
    ).format(**context)

    try:
        # Invocación directa de texto crudo (sin JSON schema)
        # Esto permite que el modelo use todos sus tokens para escribir Markdown libremente
        response = llm.invoke(prompt)
        narrativa_raw = sanitize_markdown(_extract_text(response))
        narrativa_raw = _invoke_m1_writer_with_exhibit_coherence(
            llm=llm, prompt=prompt, state=state, narrativa_raw=narrativa_raw
        )
        print(f"[case_writer] narrativa={len(narrativa_raw)} chars")
        # No escribe current_agent — nodo paralelo (evita race condition)
        return {"doc1_narrativa": narrativa_raw}
    except Exception as e:
        logger.error("[case_writer] ERROR: %s", e, exc_info=True)
        return {"doc1_narrativa": ""}


# ─────────────────────────────────────────────────────────
# NODO 2b — CASE QUESTIONS (Flash, paralelo con 2a)
# ─────────────────────────────────────────────────────────
def case_questions(state: ADAMState, config: RunnableConfig) -> dict:
    """Genera las 3 preguntas de discusión M1 del caso."""
    cfg = Configuration.from_runnable_config(config)
    # Fix M-07: 0.5 en vez de 0.7 — preguntas estructuradas Bloom L4-L6
    # requieren consistencia pedagógica, no creatividad narrativa.
    llm = _get_writer_llm(cfg.writer_model, temperature=0.5, thinking_level="low")

    context = _build_base_context(state)
    context.update({
        "architect_output": sanitize_untrusted_payload({
            "titulo": state.get("titulo", ""),
            "company_profile": state.get("company_profile", ""),
            "dilema_brief": state.get("dilema_brief", ""),
            "anexo_financiero": state.get("doc1_anexo_financiero", ""),
            "anexo_operativo": state.get("doc1_anexo_operativo", ""),
            "anexo_stakeholders": state.get("doc1_anexo_stakeholders", ""),
            "asignatura": state.get("asignatura", ""),
            "nivel": state.get("nivel", "pregrado"),
        }, per_field_limit=2000, total_limit=8000),
        # Issue #361 — ground P3's asymmetric-cost trade-off in the SAME shared source M3
        # uses (business_cost_matrix), curated into business language. Always present (gate
        # is `is None` inside the builder, not by profile), so the classification prompt's
        # `{cost_matrix_block}` never KeyErrors and non-clf prompts simply ignore the key.
        "cost_matrix_block": build_cost_matrix_block(
            _extract_business_cost_matrix(state)
        ),
    })

    prompt = CASE_QUESTIONS_PROMPT_BY_FAMILY.get(
        context["primary_family"], CASE_QUESTIONS_PROMPT
    ).format(**context)

    try:
        resultado: GeneradorPreguntasM1Output = llm.with_structured_output(
            GeneradorPreguntasM1Output
        ).invoke(prompt)
        
        preguntas_dict = [p.model_dump() for p in resultado.preguntas]
        print(f"[case_questions] {len(preguntas_dict)} preguntas generadas")
    except RuntimeError:
        raise
    except (ValidationError, OutputParserException, ValueError) as e:
        logger.warning("[case_questions] OUTPUT INVÁLIDO (reintentando/fallando): %s", e)
        raise
    except Exception as e:
        logger.error("[case_questions] ERROR tras reintentos: %s", e, exc_info=True)
        return {"doc1_preguntas": []}  # Degradación graceful — pipeline continúa sin preguntas M1

    # Issue #360 — best-effort Exhibit coherence (outside the try above so the existing
    # `except RuntimeError: raise` is untouched; this helper never raises).
    preguntas_dict = _apply_m1_questions_exhibit_coherence(
        llm=llm, prompt=prompt, state=state, preguntas_dict=preguntas_dict
    )
    # Option coherence (clasificación, both profiles) — best-effort, runs after the Exhibit
    # pass; the solución must only recommend options the case defines and the enunciado presents.
    preguntas_dict = _apply_m1_questions_option_coherence(
        llm=llm, prompt=prompt, state=state, preguntas_dict=preguntas_dict
    )
    # No escribe current_agent — nodo paralelo (evita race condition)
    return {
        "doc1_preguntas": preguntas_dict,
    }


# ─────────────────────────────────────────────────────────
# NODO — DOC1 COMPLETE (sync barrier para fan-in)
# ─────────────────────────────────────────────────────────
def doc1_complete(state: ADAMState) -> dict:
    """Punto de sincronización después del fan-out de Documento 1."""
    narrativa_len = len(state.get("doc1_narrativa", ""))
    
    preguntas_val = state.get("doc1_preguntas", [])
    preguntas_len = len(preguntas_val) if isinstance(preguntas_val, list) else len(str(preguntas_val))
    
    print(
        f"[doc1_complete] Fan-in OK — "
        f"narrativa={narrativa_len} chars, preguntas={preguntas_len} items/chars"
    )
    return {}


# ─────────────────────────────────────────────────────────
# NODO 3 — EDA TEXT ANALYST (Flash)
# ─────────────────────────────────────────────────────────
def eda_text_analyst(state: ADAMState, config: RunnableConfig) -> dict:
    """Genera el reporte EDA en Markdown (Documento 2 — parte texto)."""
    narrativa = state.get("doc1_narrativa", "")
    if not narrativa or len(narrativa.strip()) < 50:
        logger.warning("[eda_text_analyst] narrativa vacía o muy corta")
        return {
            "doc2_eda": (
                "## Reporte EDA\n\n"
                "*No disponible: el caso base no fue generado correctamente. "
                "Intenta generar el caso nuevamente.*"
            ),
            "current_agent": "eda_text_analyst",
        }

    try:
        cfg = Configuration.from_runnable_config(config)
        # Fix M-08: "medium" — análisis estadístico del dataset requiere razonamiento
        # (correlaciones, outliers, tendencias). "low" producía análisis superficiales.
        llm = _get_writer_llm(cfg.writer_model, temperature=0.4, thinking_level="medium")

        dataset = state.get("doc7_dataset", [])
        if dataset:
            dataset_str = json.dumps(dataset[:30], ensure_ascii=False)
            dataset_instruction = "DATASET_AVAILABLE: usa los datos provistos en el campo Dataset."
            # Fix M-04: usar helper compartido en vez de código inline duplicado
            dataset_summary, dataset_total_rows = _compute_dataset_summary(dataset)
        else:
            dataset_str = "[]"
            dataset_instruction = (
                "DATASET_UNAVAILABLE: basa el análisis en los Exhibits 1 y 2 del M1. "
                "Advierte al lector que el análisis es de contexto, no de datos primarios."
            )
            dataset_summary, dataset_total_rows = "{}", 0

        context = _build_base_context(state)
        context.update({
            # Fix M-02: 6000 chars ≈ 1500 tokens — incluye opciones A/B/C
            # que están al final de la narrativa. Con 2000 el analista EDA
            # no veía el dilema completo y perdía coherencia con M1.
            "case_context": narrativa[:6000],
            "dataset_str": dataset_str,
            "dataset_instruction": dataset_instruction,
            "dataset_summary": dataset_summary,
            "dataset_total_rows": dataset_total_rows,
            "financial_exhibit": state.get("doc1_anexo_financiero", ""),
            "operational_exhibit": state.get("doc1_anexo_operativo", ""),
            # Issue #225 — brechas dilema↔dataset detectadas por validador.
            # Si está vacío, el bloque indica al LLM que el dataset cubre el
            # contrato y no debe inventar advertencias metodológicas.
            "data_gap_warnings_block": _format_data_gap_warnings_block(
                state.get("data_gap_warnings") or [],
                empty_message="(sin brechas detectadas — el dataset cubre el contrato dilema↔datos)",
            ),
        })
        # P1 (auditoría business+clasificacion) — secciones de balance/distribución/
        # señales gated por perfil: business recibe lenguaje gerencial sin jerga DS y
        # sin "churn" cableado; ml_ds conserva el rigor técnico verbatim (AUC-ROC,
        # matriz de confusión, leakage guard). Espejo del patrón {lr_business_block}
        # de M3. Solo afecta al prompt de clasificación (las demás familias ignoran
        # estas claves extra en su .format()).
        # Issue #383 — el nombre real del target (ml_ds+clf: el dataset ya renombró
        # `categoria` al nombre del contrato). business / no-clf → "categoria" (cuerpo
        # byte-idéntico). Se inyecta al cuerpo Y se pre-sustituye en los bloques ml_ds
        # (que son placeholder-free → un {..} dentro no se re-expande en el único .format).
        target_column_name = _resolve_eda_target_name(state)
        context["target_column_name"] = target_column_name
        context.update(
            select_eda_text_blocks(state.get("studentProfile", "business"), target_column_name)
        )

        prompt = EDA_TEXT_ANALYST_PROMPT_BY_FAMILY.get(
            context.get("primary_family", ""), EDA_TEXT_ANALYST_PROMPT
        ).format(**context)

        # 🚀 LA SOLUCIÓN: Invocación directa sin JSON schema
        response = llm.invoke(prompt)
        eda_report_raw = sanitize_markdown(_extract_text(response))

        print(f"[eda_text_analyst] reporte={len(eda_report_raw)} chars")

        return {
            "doc2_eda": eda_report_raw,
            "current_agent": "eda_text_analyst",
        }

    except Exception as e:
        logger.error("[eda_text_analyst] ERROR tras reintentos: %s", e, exc_info=True)
        return {"doc2_eda": "DATASET_UNAVAILABLE", "current_agent": "eda_text_analyst"}  # Sentinel — downstream usa fallback


# ─────────────────────────────────────────────────────────
# HELPER — _identify_target_variable y _calculate_eda_regressions
# ─────────────────────────────────────────────────────────

def _identify_target_variable(state: ADAMState, df: 'pd.DataFrame') -> str:
    """Extrae dinámicamente el nombre de la variable objetivo."""
    # 1. Desde metadata explícita
    metadata = state.get("dataset_metadata", {})
    if metadata and "target_variable" in metadata and metadata["target_variable"] in df.columns:
        return metadata["target_variable"]
    
    # 2. Desde el schema_designer (buscando 'objetivo' o 'target' en la descripción)
    schema = state.get("dataset_schema", {})
    columns = schema.get("columns", [])
    for col in columns:
        desc = col.get("description", "").lower()
        if "objetivo" in desc or "target" in desc:
            name = col.get("name")
            if name and name in df.columns:
                return name
    
    # 3. Heurística básica: nombres comunes
    common_targets = ["churn", "target", "conversion", "adopcion", "margin_ebitda", "riesgo", "risk", "revenue"]
    for col in df.columns:
        col_lower = col.lower()
        if any(t in col_lower for t in common_targets):
            return col
    
    # 4. Fallback: última columna numérica
    numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
    if numeric_cols:
        return numeric_cols[-1]
        
    return ""

def _calculate_eda_regressions(state: ADAMState, dataset: list[dict]) -> dict:
    """Calcula métricas precalculadas para el EDA Chart Generator.

    Siempre computa correlation_matrix cuando hay datos suficientes. cohort_matrix
    (artefacto de retención) SOLO se computa en casos de retención — Issue #326:
    business con target de retención (mismo predicado que la selección determinista,
    eda_charts_business.py); nunca para ml_ds (su panel determinista no renderiza
    cohort heatmap). Las regresiones lineales (target_vs_X) son opcionales y se
    omiten sin early-return cuando target_col no está disponible.

    Fix v8.2: el early-return previo en "target_col not found" dejaba
    precalculated_metrics = {} y el LLM no tenía matriz para heatmaps.
    """
    try:
        if not dataset:
            return {}

        import pandas as pd
        import numpy as np
        from scipy.stats import linregress

        df = pd.DataFrame(dataset)
        results: dict = {}

        # ── 1. Correlation matrix (siempre, independiente del target) ─────────
        # Issue #294: una columna numérica de varianza cero (constante) tiene
        # correlación INDEFINIDA (no 0). Incluirla hacía que Series.corr (np.corrcoef,
        # usado más abajo contra el target) dividiera por std=0 y emitiera un
        # RuntimeWarning, y que el heatmap mostrara una "0 correlación" engañosa.
        # Calculamos las columnas constantes UNA vez y reutilizamos el set para la
        # matriz y para las regresiones. fillna(0) queda solo como red de seguridad
        # (json.dumps rechaza NaN nativo).
        numeric_all = df.select_dtypes(include=["number"])
        constant_cols = {
            c for c in numeric_all.columns if numeric_all[c].nunique(dropna=True) <= 1
        }
        numeric_df = numeric_all.drop(columns=list(constant_cols))
        if len(numeric_df.columns) >= 2:
            corr_matrix = numeric_df.corr().round(2).fillna(0)
            results["correlation_matrix"] = {
                "x": list(corr_matrix.columns),
                "y": list(corr_matrix.columns),
                "z": corr_matrix.values.tolist(),
            }

        # ── 2. Cohort matrix (SOLO en casos de RETENCIÓN — Issue #326) ────────
        # El heatmap de cohortes es un artefacto de retención. Antes se computaba
        # para CUALQUIER dataset con retention_m* (≥2) + period, dejando un
        # artefacto fantasma en casos NO-retención. Lo gateamos con el MISMO
        # predicado que la selección determinista business (is_retention_match,
        # eda_charts_business.py:473), así computar ⟺ seleccionar: nunca queda un
        # fantasma ni se suprime un heatmap legítimo de #322.
        #
        #   business + target de retención → cohort COMPUTADO  (preserva #322)
        #   business + target NO-retención → cohort AUSENTE     (builder→box; LLM-JSON→CASO B)
        #   ml_ds (cualquier tema)         → cohort AUSENTE     (el panel determinista
        #                                                        ml_ds no renderiza cohort heatmap)
        target_col = _identify_target_variable(state, df)
        profile = state.get("studentProfile", "business")
        is_retention_case = profile != "ml_ds" and is_retention_match(target_col)

        retention_cols = sorted(
            [c for c in df.columns if c.startswith("retention_m")],
            key=lambda x: int(x.split("_m")[1])
        )
        if is_retention_case and len(retention_cols) >= 2 and "period" in df.columns:
            # Limita a las primeras MAX_COHORT_ROWS cohortes: legibles, todas
            # históricas (empiezan en 2023-01 → sin fechas futuras) y las más
            # observadas a M12. Sin recorte, las 80-120 filas del dataset business
            # vuelven ilegible el heatmap y apilan las etiquetas de texto por celda
            # en bandas verticales solapadas.
            MAX_COHORT_ROWS = 12
            cohort_df = df.head(MAX_COHORT_ROWS)
            # None en lugar de 0/NaN → Plotly los deja transparentes en el heatmap
            # (fillna(0) pintaría los huecos con el color más oscuro de la escala)
            cohort_rounded = cohort_df[retention_cols].round(4)
            cohort_z = [
                [None if pd.isna(v) else float(v) for v in row]
                for row in cohort_rounded.values.tolist()
            ]
            results["cohort_matrix"] = {
                "x": [c.replace("retention_", "").upper() for c in retention_cols],
                "y": cohort_df["period"].tolist(),
                "z": cohort_z,
            }

        # ── 3. Regresiones lineales (opcional — requiere target_col) ──────────
        # target_col ya se identificó arriba (gate de cohort) — se reutiliza aquí.
        if not target_col or target_col not in df.columns:
            # No target → skip regressions, but still return matrices above
            return results

        if not pd.api.types.is_numeric_dtype(df[target_col]):
            unique_vals = df[target_col].dropna().unique()
            if len(unique_vals) == 2:
                df[target_col] = df[target_col].map({unique_vals[0]: 0, unique_vals[1]: 1})
            else:
                return results  # non-numeric target with >2 categories → skip regressions

        # Issue #294: un target constante haría que toda corr(feature, target) divida
        # por std=0 (np.corrcoef). Sin regresiones útiles → devolvemos las matrices ya
        # calculadas. (El fallback de _identify_target_variable es la última columna
        # numérica, que podría ser justamente la constante.)
        if target_col in constant_cols:
            return results

        numeric_cols = [
            c
            for c in df.select_dtypes(include=[np.number]).columns
            if c not in constant_cols  # Issue #294: no correlacionar columnas constantes
        ]
        if target_col in numeric_cols:
            numeric_cols.remove(target_col)

        if not numeric_cols:
            return results

        correlations = {}
        for col in numeric_cols:
            corr = df[col].corr(df[target_col])
            if pd.notna(corr) and not np.isinf(corr):
                correlations[col] = abs(corr)

        top_features = sorted(correlations.items(), key=lambda x: x[1], reverse=True)[:3]

        for feature, _ in top_features:
            valid_data = df[[feature, target_col]].replace([np.inf, -np.inf], np.nan).dropna()
            if len(valid_data) < 2:
                continue

            x = valid_data[feature]
            y = valid_data[target_col]

            res = linregress(x, y)
            x_min, x_max = float(x.min()), float(x.max())
            y_min = res.intercept + res.slope * x_min
            y_max = res.intercept + res.slope * x_max

            results[f"target_vs_{feature}"] = {
                "x": [round(x_min, 4), round(x_max, 4)],
                "y": [round(y_min, 4), round(y_max, 4)],
                "r2": round(float(res.rvalue ** 2), 4),
                "pearson": round(float(res.rvalue), 4),
            }

        return results
    except Exception as e:
        logger.error("[_calculate_eda_regressions] Error math engine: %s", e)
        return {}


# ─────────────────────────────────────────────────────────
# HELPER — Heatmap matrix injection (proactive)
# ─────────────────────────────────────────────────────────

def _inject_heatmap_matrices(
    charts: list[dict],
    precalculated_metrics: dict,
) -> list[dict]:
    """Inyecta proactivamente las matrices precalculadas en cada trace de tipo heatmap.

    Siempre sobreescribe x/y/z — el LLM no genera datos numéricos para heatmaps,
    solo proporciona la estructura del chart y opcionalmente x (nombres de columnas)
    como hint para sub-matrix slicing en correlation heatmaps.

    Heurística de selección de matriz (colorscale):
    - YlOrRd / YlGnBu / sequential → cohort_matrix (retention rates 0-1)
    - RdBu / diverging / desconocido → correlation_matrix (Pearson -1..1)

    Sub-matrix slicing (solo para correlation, no cohort):
    - Si el LLM proporciona x con nombres de columnas válidos → extrae sub-bloque
    - Si los nombres son inválidos → fallback a matriz completa + log de advertencia
    - Para cohort: y=períodos (no columnas), no se aplica slicing en ningún eje
    """
    corr = precalculated_metrics.get("correlation_matrix")
    cohort = precalculated_metrics.get("cohort_matrix")

    for chart in charts:
        for trace in chart.get("traces", []):
            if str(trace.get("type", "")).lower() != "heatmap":
                continue

            cs = str(trace.get("colorscale", "")).lower()
            is_cohort_hint = any(k in cs for k in ("ylorrd", "ylord", "ylgnbu", "sequential"))
            matrix = (cohort if is_cohort_hint else None) or corr or cohort

            if not matrix:
                logger.warning(
                    "[_inject_heatmap_matrices] No matrix available for chart '%s' — skipping",
                    chart.get("id", "?"),
                )
                continue

            # Defaults: full matrix
            injected_x = matrix["x"]
            injected_y = matrix["y"]
            injected_z = matrix["z"]

            # Sub-matrix slicing solo para correlation (is_cohort_hint=False):
            # - Cohort: y=períodos, no columnas → slicing rompería el eje temporal
            # - all(col in matrix["x"]) verifica que el LLM no escribió nombres mal
            x_hint = trace.get("x")
            if (
                not is_cohort_hint
                and isinstance(x_hint, list)
                and len(x_hint) >= 2
            ):
                if all(col in matrix["x"] for col in x_hint):
                    indices = [matrix["x"].index(col) for col in x_hint]
                    injected_x = x_hint
                    injected_y = x_hint
                    injected_z = [[matrix["z"][i][j] for j in indices] for i in indices]
                else:
                    # Nombres inválidos → fallback a matriz completa + log para ajuste de prompt
                    invalid_cols = [col for col in x_hint if col not in matrix["x"]]
                    logger.warning(
                        "[_inject_heatmap_matrices] chart '%s': x_hint contiene columnas "
                        "no encontradas en la matriz — usando matriz completa. "
                        "Columnas inválidas: %s",
                        chart.get("id", "?"), invalid_cols,
                    )

            trace["x"] = injected_x
            trace["y"] = injected_y
            trace["z"] = injected_z
            matrix_name = "cohort_matrix" if (is_cohort_hint and cohort) else "correlation_matrix"
            logger.info(
                "[eda_chart_generator] Matrix injected for heatmap '%s' using %s (%d×%d)",
                chart.get("id", "?"),
                matrix_name,
                len(injected_z),
                len(injected_z[0]) if injected_z else 0,
            )

    return charts


# ─────────────────────────────────────────────────────────
# NODO 4 — EDA CHART GENERATOR (Flash, structured output)
# ─────────────────────────────────────────────────────────
# Issue #237 — helpers para el path Python-determinista (clasificación ml_ds)
def _clamp(text: str, max_chars: int) -> str:
    if not isinstance(text, str):
        return ""
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


def _annotate_validate_emit(
    charts: list[dict],
    state: ADAMState,
    config: RunnableConfig,
    annotate_prompt: str,
    *,
    deterministic_text_ids: frozenset[str] = frozenset(),
) -> dict | None:
    """Cola compartida de los paths EDA Python-deterministas (clasif + business).

    Pide al LLM SOLO `description`/`notes` (annotate-only), fusiona con los charts
    ya construidos en Python (sin tocar números), valida contra
    ``EDAChartGeneratorOutput`` y devuelve el update del nodo, o ``None`` si nada
    validó. El boundary del LLM nunca tumba el panel: si la anotación falla, se
    sirven los charts sin texto LLM (preservando los `notes` del builder, p. ej.
    el aviso anti-overclaim del chart de drivers).

    ``deterministic_text_ids`` son los charts cuyo `description`/`notes` los escribe
    el builder de forma determinista (p. ej. `missingness_heatmap`): se EXCLUYEN de
    la petición al LLM y se descartan de sus anotaciones, de modo que el texto del
    builder se conserva (el merge ya prefiere el texto del builder cuando el id no
    está en `ann_by_id`). Default vacío → no-op byte-idéntico (path business).
    """
    # Cap defensivo: el contrato son ≤5 charts.
    if len(charts) > 5:
        charts = charts[:5]

    try:
        cfg = Configuration.from_runnable_config(config)
        llm = _get_chart_llm(cfg.writer_model, temperature=0.3, thinking_level="minimal")
        charts_context = [
            {
                "id": c.get("id", ""),
                "title": c.get("title", ""),
                "subtitle": c.get("subtitle", ""),
                "chart_type": c.get("chart_type", ""),
            }
            for c in charts
            if c.get("id", "") not in deterministic_text_ids
        ]
        prompt = annotate_prompt.format(
            charts_context_json=json.dumps(charts_context, ensure_ascii=False),
            case_id=state.get("case_id", "") or state.get("titulo", ""),
            student_profile=state.get("studentProfile", "business"),
            output_language=state.get("output_language", "es"),
        )
        ann_result: EDAAnnotateOnlyOutput = llm.with_structured_output(
            EDAAnnotateOnlyOutput
        ).invoke(prompt)
        ann_by_id: dict[str, tuple[str, str]] = {}
        for ann in (ann_result.annotations or []):
            if not ann.id:
                continue
            ann_by_id[ann.id] = (
                _clamp(ann.description or "", 500),
                _clamp(ann.notes or "", 300),
            )
    except Exception as ann_err:  # noqa: BLE001
        # Boundary: errores del LLM nunca tumban el panel.
        logger.warning(
            "[eda_chart_generator/py] annotate-only LLM falló (%s) — sirviendo charts sin anotaciones",
            ann_err,
        )
        ann_by_id = {}

    # Charts con texto determinista: descartar cualquier anotación LLM (incl. una
    # que un modelo díscolo devuelva sin habérsela pedido) para preservar el texto
    # honesto del builder en el merge de abajo.
    for _det_id in deterministic_text_ids:
        ann_by_id.pop(_det_id, None)

    # Merge defensivo: solo description/notes; preservamos data_source y los
    # `notes` factuales del builder (p. ej. el caveat anti-overclaim). El caveat va
    # ÍNTEGRO y primero; la nota pedagógica del LLM se presupuesta al espacio restante
    # y se clampa con elipsis (no se corta a media palabra). Total ≤ 300 chars.
    for c in charts:
        cid = c.get("id", "")
        desc, llm_notes = ann_by_id.get(cid, ("", ""))
        c["description"] = desc or c.get("description", "") or ""
        builder_notes = (c.get("notes", "") or "").strip()
        sep = " " if builder_notes and llm_notes else ""
        budget = max(0, 300 - len(builder_notes) - len(sep))
        llm_tail = _clamp(llm_notes, budget) if budget else ""
        c["notes"] = (builder_notes + sep + llm_tail).strip()
        c["data_source"] = "python_builder"

    # Validamos contra el schema (descartamos charts que rompan el contrato).
    validated: list[dict] = []
    for c in charts:
        try:
            spec = EDAChartGeneratorOutput.model_validate({"charts": [c]})
            validated.append(spec.charts[0].model_dump())
        except Exception as ve:  # noqa: BLE001
            logger.warning(
                "[eda_chart_generator/py] chart %s falló validación: %s — se omite",
                c.get("id"), ve,
            )

    if not validated:
        return None

    logger.info(
        "[eda_chart_generator/py] panel Python-determinista emitido: %d/%d charts",
        len(validated), len(charts),
    )
    return {
        "doc2_eda_charts": validated,
        "current_agent": "eda_chart_generator",
    }


def _eda_classification_python_path(
    state: ADAMState, config: RunnableConfig, contract: dict | None
) -> dict | None:
    """Issue #237 — construye los charts EDA de clasificación (ml_ds) en Python y
    pide al LLM solo `description`/`notes`. Devuelve el update del nodo o ``None``
    si el path Python no aplica (deja que el caller use el LLM-JSON).
    """
    try:
        import pandas as pd  # noqa: PLC0415 — local para no penalizar imports globales

        dataset = state.get("doc7_dataset") or []
        if not dataset:
            logger.warning(
                "[eda_chart_generator/py] doc7_dataset vacío — fallback a path LLM"
            )
            return None
        df = pd.DataFrame(dataset)
        target_col = _identify_target_variable(state, df)
        if not target_col:
            logger.warning(
                "[eda_chart_generator/py] target no identificable — fallback a path LLM"
            )
            return None

        # Kill-switch `m2_missingness_honest_text` (default true): el builder escribe
        # texto determinista y honesto para `missingness_heatmap` (que el LLM no debe
        # pisar). Off → texto vacío + el LLM lo anota (comportamiento previo).
        honest_text = settings.m2_missingness_honest_text
        # Kill-switch `m2_mi_exclude_index` (default true): filtra del chart de MI las
        # columnas que inflan la métrica por alta cardinalidad discreta (period/IDs/texto).
        # Off → todas las columnas salvo el target (comportamiento legacy byte-idéntico).
        exclude_index = settings.m2_mi_exclude_index
        charts = generate_classification_eda_charts(
            df, target_col, contract, honest_text=honest_text, exclude_index=exclude_index
        )
        if not charts:
            logger.warning(
                "[eda_chart_generator/py] builder devolvió 0 charts — fallback a path LLM"
            )
            return None

        # El id está acoplado al builder (`_build_missingness_heatmap`); el test E2E
        # de coherencia de texto lo bloquea contra un rename silencioso.
        deterministic_text_ids = (
            frozenset({"missingness_heatmap"}) if honest_text else frozenset()
        )
        return _annotate_validate_emit(
            charts,
            state,
            config,
            EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION,
            deterministic_text_ids=deterministic_text_ids,
        )
    except Exception as e:  # noqa: BLE001
        logger.error(
            "[eda_chart_generator/py] ERROR no recuperable: %s — fallback a path LLM",
            e, exc_info=True,
        )
        return None


def _eda_business_python_path(
    state: ADAMState, config: RunnableConfig, contract: dict | None
) -> dict | None:
    """Path Python-determinista del perfil business (mirror del de clasificación).

    Construye el panel honesto de 3 charts (`generate_business_eda_charts`) y pide
    al LLM solo `description`/`notes`. Consume `precalculated_metrics`
    (`_calculate_eda_regressions`) para la matriz de cohortes y las correlaciones.

    Devuelve el update del nodo o ``None`` en fallo. A diferencia del path ml_ds,
    el caller NO hace fallback al LLM-JSON (Issue 5A): ``None`` → panel vacío, para
    no reintroducir nunca los charts LLM de baja calidad que este cambio retira.
    """
    try:
        import pandas as pd  # noqa: PLC0415 — local para no penalizar imports globales

        dataset = state.get("doc7_dataset") or []
        if not dataset:
            logger.warning(
                "[eda_chart_generator/business] doc7_dataset vacío — panel vacío (sin fallback LLM)"
            )
            return None
        df = pd.DataFrame(dataset)
        # target_col puede quedar vacío: el chart financiero y el de cohortes no lo
        # necesitan; el de drivers degrada a placeholder con aviso.
        target_col = _identify_target_variable(state, df)
        precalculated = _calculate_eda_regressions(state, dataset)

        charts = generate_business_eda_charts(df, target_col, precalculated, contract)
        if not charts:
            logger.warning(
                "[eda_chart_generator/business] builder devolvió 0 charts — panel vacío (sin fallback LLM)"
            )
            return None

        return _annotate_validate_emit(charts, state, config, EDA_ANNOTATE_ONLY_PROMPT)
    except Exception as e:  # noqa: BLE001
        logger.error(
            "[eda_chart_generator/business] ERROR no recuperable: %s — panel vacío (sin fallback LLM)",
            e, exc_info=True,
        )
        return None


def eda_chart_generator(state: ADAMState, config: RunnableConfig) -> dict:
    """Extrae los charts del reporte EDA (Documento 2 — parte charts).

    Dispatch de generación (charts deterministas Python vs. LLM-JSON legacy):

        familia clasificacion + perfil ml_ds   → _eda_classification_python_path
                                                  (Issue #237; 3 charts; LLM solo anota)
                                                  fallback → LLM-JSON si el path Python falla
        familia clasificacion + perfil business → _eda_business_python_path
                                                  (3 charts honestos; LLM solo anota)
                                                  SIN fallback LLM (Issue 5A): falla → panel vacío
        cualquier otra combinación              → path LLM-JSON (EDA_CHART_GENERATOR_PROMPT)

    Los paths Python construyen TODOS los números en pandas y el LLM solo escribe
    `description`/`notes` — eso elimina las correlaciones sobre-afirmadas y los
    doble-ejes engañosos del path LLM-JSON. El path LLM-JSON queda solo para
    business+otras-familias y ml_ds+otras-familias (y como fallback de ml_ds+clasif).
    """
    eda_report = state.get("doc2_eda", "")
    if not eda_report or "No disponible" in eda_report:
        print("[eda_chart_generator] Skipping: no hay reporte EDA válido")
        return {"doc2_eda_charts": [], "current_agent": "eda_chart_generator"}

    # ── Dispatch a paths Python-deterministas (clasificacion) ────────────
    profile = state.get("studentProfile", "business")
    task_payload_obj = state.get("task_payload") or {}
    algoritmos_disp: list[str] = []
    if isinstance(task_payload_obj, dict):
        algoritmos_disp = list(task_payload_obj.get("algoritmos") or [])
    if not algoritmos_disp:
        algoritmos_disp = list(state.get("algoritmos") or [])
    primary_family, _legacy_warn = _resolve_primary_family(algoritmos_disp)
    if primary_family == "clasificacion":
        contract = state.get("dataset_schema_required")
        if profile == "ml_ds":
            py_update = _eda_classification_python_path(state, config, contract)
            if py_update is not None:
                return py_update
            # else: fall through to legacy LLM-JSON path (warning already logged).
        elif profile == "business":
            # Issue 5A: el builder business NUNCA cae al LLM-JSON (el path que
            # producía los charts malos). Falla → panel vacío degradado.
            py_update = _eda_business_python_path(state, config, contract)
            if py_update is not None:
                return py_update
            logger.warning(
                "[eda_chart_generator] business builder no produjo charts — panel vacío (sin fallback LLM)"
            )
            return {"doc2_eda_charts": [], "current_agent": "eda_chart_generator"}

    try:
        cfg = Configuration.from_runnable_config(config)
        # Fix C-05: _get_chart_llm (16384 tokens) para JSON pesado de múltiples charts
        llm = _get_chart_llm(cfg.writer_model, temperature=0.3, thinking_level="minimal")

        dataset = state.get("doc7_dataset", [])
        # Fix M-04: usar helper compartido
        dataset_summary, dataset_total_rows = _compute_dataset_summary(dataset)

        precalculated_metrics = _calculate_eda_regressions(state, dataset)
        
        context = _build_base_context(state)
        context.update({
            "dataset_json": json.dumps(dataset[:50], ensure_ascii=False),
            "precalculated_metrics": json.dumps(precalculated_metrics, ensure_ascii=False),
            "eda_report": eda_report,
            "dataset_summary": dataset_summary,
            "dataset_total_rows": dataset_total_rows,
        })

        prompt = EDA_CHART_GENERATOR_PROMPT.format(**context)

        result: EDAChartGeneratorOutput = llm.with_structured_output(
            EDAChartGeneratorOutput
        ).invoke(prompt)

        # v8: Plotly — validar que cada chart tiene id, chart_type y traces
        charts_raw = result.charts or []
        charts_valid = []
        for chart in charts_raw:
            try:
                if chart.id and chart.chart_type and chart.traces:
                    dumped = chart.model_dump()
                    # Issue #237 — telemetría: marcar el path LLM-JSON
                    # explicitamente para distinguirlo de python_builder.
                    if not dumped.get("data_source"):
                        dumped["data_source"] = "llm_json"
                    charts_valid.append(dumped)
            except Exception:
                continue

        # v8.1: Repair heatmap z matrices the LLM generated incompletely.
        # precalculated_metrics is already in scope (computed at line 793).
        charts_valid = _inject_heatmap_matrices(charts_valid, precalculated_metrics)

        print(
            f"[eda_chart_generator] charts: {len(charts_valid)}/{len(charts_raw)}, "
            f"ids: {[c.get('id') for c in charts_valid]}"
        )

        # Defensa: truncar a máximo 3 charts (el prompt exige exactamente 3)
        if len(charts_valid) > 3:
            logger.warning(
                "[eda_chart_generator] LLM generó %d charts, truncando a 3",
                len(charts_valid)
            )
            charts_valid = charts_valid[:3]

        return {"doc2_eda_charts": charts_valid, "current_agent": "eda_chart_generator"}

    except OutputParserException as ope:
        logger.error("[eda_chart_generator] OutputParserException tras reintentos: %s", ope, exc_info=True)
        return {"doc2_eda_charts": [], "current_agent": "eda_chart_generator"}  # Degradación graceful — EDA sin gráficos
    except Exception as e:
        logger.error("[eda_chart_generator] ERROR tras reintentos: %s", e, exc_info=True)
        return {"doc2_eda_charts": [], "current_agent": "eda_chart_generator"}  # Degradación graceful — EDA sin gráficos


# ─────────────────────────────────────────────────────────
# NODO 5 — EDA QUESTIONS GENERATOR (Flash, contexto optimizado)
# ─────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────
# M2 EDA question coherence (clasificación, business + ml_ds)
# Deterministic sibling of the M1 option-coherence guard (#412). Runs INSIDE
# `eda_questions_generator`. Reprompt-once-then-DEGRADE; best-effort; never raises.
# Zero LLM cost on the happy path (deterministic validation); one Flash reprompt only
# on a violation. See m2_grounding.py for the pure validator.
# ─────────────────────────────────────────────────────────
_M2_VIOLATION_CODES = (
    ("CHART_REF_NONEXISTENT", "chart_ref"),
    ("EVENT_RATE_INCOHERENT", "rate_internal"),
    ("EVENT_RATE_VS_CONTRACT", "rate_contract"),
)


def _m2_violation_types(violations: list[str]) -> list[str]:
    """Enumerated short codes for structured logging — never the raw message (no PII)."""
    codes: list[str] = []
    for violation in violations:
        for prefix, code in _M2_VIOLATION_CODES:
            if violation.startswith(prefix) and code not in codes:
                codes.append(code)
    return codes


def _build_m2_coherence_reprompt(
    chart_ids: set[str], rate_pct: float | None, violations: list[str]
) -> str:
    """Focused reprompt (CONCATENATED, never ``.format`` — prose may carry ``{}``).

    Carries the CONCRETE fix (valid chart ids + the real event rate) so the model
    corrects the specific figures, and demands the SAME 2 questions with the SAME
    ``numero`` (1 and 2) so the downstream ``M2-Q{numero}`` answer/grading key is preserved.
    """
    bullet_list = "\n".join(f"- {violation}" for violation in violations)
    valid_charts = ", ".join(sorted(chart_ids)) if chart_ids else "ninguna"
    rate_line = (
        f"La tasa real del evento del dataset es {rate_pct:g}% — cítala textualmente.\n"
        if rate_pct is not None
        else ""
    )
    return (
        "\n\n# CORRECCIÓN OBLIGATORIA DE COHERENCIA (Módulo 2)\n"
        "Algunas preguntas citan una gráfica inexistente o una tasa del evento en "
        "`solucion_esperada` que NO coincide con su propio `enunciado` ni con el dataset. "
        "Regenera EXACTAMENTE 2 preguntas con el MISMO schema y los MISMOS `numero` (1 y 2): "
        "cada `chart_ref` debe ser uno de los ids válidos del manifest (o null), y toda cifra "
        "de la tasa del evento en `solucion_esperada` debe ser EXACTAMENTE la de su enunciado.\n"
        f"Gráficas válidas (ids): {valid_charts}.\n"
        f"{rate_line}"
        "Incoherencias detectadas:\n" + bullet_list
    )


def _apply_eda_questions_coherence(
    *,
    llm: Any,
    prompt: str,
    state: ADAMState,
    preguntas_dict: list[dict],
    chart_ids: set[str],
) -> list[dict]:
    """Validate + reprompt-once-then-DEGRADE the M2 EDA question coherence.

    Gated to the classification family for BOTH profiles (business + ml_ds) behind the
    ``m2_question_coherence`` kill-switch; a byte-identical no-op otherwise. On a violation
    it reprompts ONCE (one Flash call) with the concrete fix; the corrected set is accepted
    ONLY if it preserves the question count AND the ``numero`` sequence (the answer/grading
    key ``M2-Q{numero}``) AND is now coherent — otherwise it degrades to the pass-1 questions.
    Best-effort: ANY throw (including a reprompt ``RuntimeError``, which the node would
    otherwise re-raise and fail the job) degrades to pass-1. Never raises.
    """
    log_extra = {"node": "eda_questions_generator", "case_id": state.get("case_id")}
    try:
        if not settings.m2_question_coherence or not _is_classification_family(state):
            return preguntas_dict
        contract = state.get("dataset_schema_required")
        raw_rate = contract.get("target_event_rate") if isinstance(contract, dict) else None
        rate: float | None = (
            float(raw_rate)
            if isinstance(raw_rate, (int, float)) and not isinstance(raw_rate, bool)
            else None
        )
        violations = validate_eda_questions_coherence(preguntas_dict, chart_ids, rate)
        if not violations:
            return preguntas_dict
        logger.info(
            "[eda_questions] reprompt de coherencia M2 disparado",
            extra={
                **log_extra,
                "violation_count": len(violations),
                "violation_types": _m2_violation_types(violations),
            },
        )
        rate_pct = rate * 100.0 if rate is not None and 0.0 < rate <= 1.0 else None
        reprompt = prompt + _build_m2_coherence_reprompt(chart_ids, rate_pct, violations)
        try:
            resultado: EDAQuestionsOutput = llm.with_structured_output(
                EDAQuestionsOutput
            ).invoke(reprompt)
            corrected = [p.model_dump() for p in resultado.preguntas]
        except (ValidationError, OutputParserException, ValueError) as exc:
            logger.warning(
                "[eda_questions] reprompt de coherencia M2 inválido — degrada a pass-1: %s",
                exc,
                extra=log_extra,
            )
            return preguntas_dict
        # Identity guard: a reprompt that drops/adds/renumbers a question would corrupt the
        # ``M2-Q{numero}`` answer/grading key (shared.teacher_reads) — reject it, keep pass-1.
        if [q.get("numero") for q in corrected] != [q.get("numero") for q in preguntas_dict]:
            logger.warning(
                "[eda_questions] reprompt M2 alteró conteo/numero — degrada a pass-1",
                extra=log_extra,
            )
            return preguntas_dict
        residual = validate_eda_questions_coherence(corrected, chart_ids, rate)
        if not residual:
            logger.info(
                "[eda_questions] coherencia M2 corregida por reprompt",
                extra={**log_extra, "degraded": False},
            )
            return corrected
        logger.warning(
            "[eda_questions] coherencia M2 degradada tras reprompt",
            extra={
                **log_extra,
                "violation_types": _m2_violation_types(residual),
                "degraded": True,
            },
        )
        return preguntas_dict
    except Exception as exc:  # best-effort — a coherence pass must never fail the job
        logger.warning(
            "[eda_questions] validador de coherencia M2 falló (best-effort): %s",
            exc,
            extra=log_extra,
        )
        return preguntas_dict


def eda_questions_generator(state: ADAMState, config: RunnableConfig) -> dict:
    """Genera EXACTAMENTE 2 preguntas socráticas EDA (Sesgo + Correlación vs Causalidad).

    v9 M2-Redesign: usa EDAQuestionsOutput (modelo aislado) en vez de GeneradorPreguntasOutput.
    Contexto optimizado: solo recibe doc2_eda y doc2_eda_charts.
    """
    try:
        cfg = Configuration.from_runnable_config(config)
        # Fix M-07: 0.5 — preguntas socráticas EDA requieren rigor analítico, no creatividad.
        llm = _get_writer_llm(cfg.writer_model, temperature=0.5, thinking_level="low")

        charts = state.get("doc2_eda_charts", [])
        chart_manifest = json.dumps(
            [
                {"id": c.get("id", f"chart_{i}"), "title": c.get("title", "")}
                for i, c in enumerate(charts)
            ],
            ensure_ascii=False,
        )

        context = _build_base_context(state)
        context.update({
            "eda_context": state.get("doc2_eda", "")[:3000],
            "chart_manifest": chart_manifest,
        })

        prompt = EDA_QUESTIONS_PROMPT_BY_FAMILY.get(
            context.get("primary_family", ""), EDA_QUESTIONS_GENERATOR_PROMPT
        ).format(**context)

        # v9 M2-Redesign: EDAQuestionsOutput con EDASocraticQuestion (solucion_esperada = objeto)
        resultado: EDAQuestionsOutput = llm.with_structured_output(
            EDAQuestionsOutput
        ).invoke(prompt)

        preguntas_eda_dict = [p.model_dump() for p in resultado.preguntas]
        print(f"[eda_questions_generator] {len(preguntas_eda_dict)} preguntas socráticas generadas")

        # M2 coherence: chart_ref must exist + the event rate in each solución must match
        # its enunciado (and the real prevalence for ml_ds). `chart_ids` MUST use the SAME
        # `c.get("id", f"chart_{i}")` fallback as the manifest the LLM saw (line above), or a
        # valid ref to an id-less chart would false-positive. Best-effort, never raises.
        chart_ids = {str(c.get("id", f"chart_{i}")) for i, c in enumerate(charts)}
        preguntas_eda_dict = _apply_eda_questions_coherence(
            llm=llm,
            prompt=prompt,
            state=state,
            preguntas_dict=preguntas_eda_dict,
            chart_ids=chart_ids,
        )

        return {
            "doc2_preguntas_eda": preguntas_eda_dict,
            "current_agent": "doc3_generation",
        }

    except RuntimeError:
        raise
    except Exception as e:
        logger.error("[eda_questions_generator] ERROR tras reintentos: %s", e, exc_info=True)
        return {"doc2_preguntas_eda": [], "current_agent": "doc3_generation"}  # Degradación graceful — sin preguntas EDA



# ─────────────────────────────────────────────────────────
# HELPER — _parse_dataset_rows (multi-estrategia)
# ─────────────────────────────────────────────────────────

def _parse_dataset_rows(raw: str) -> list:
    """Extrae filas del dataset desde la respuesta del LLM con 4 estrategias en cascada.

    Issue 6.4: el parser original buscaba clave "rows" pero el prompt define "data".
    Estrategia 4 (nueva): recupera filas parciales de JSON truncado buscando objetos
    dentro del array "data", incluso si el array no está cerrado.

    Estrategia 1: bloque ```json — busca {"data": [...]} o {"rows": [...]}
    Estrategia 2: objeto JSON raw (sin Markdown) — usa JSONDecoder.raw_decode
    Estrategia 3: array JSON standalone — primer array de dicts encontrado
    Estrategia 4: recuperación parcial — extrae objetos completos del array "data" truncado
    """
    if not raw:
        return []

    decoder = json.JSONDecoder()

    # Estrategia 1 — bloque ```json (con o sin cierre)
    m = re.search(r'```json\s*([\s\S]*?)(?:\s*```|$)', raw)
    if m:
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, list):
                return obj
            rows = obj.get("data") or obj.get("rows") or []
            if rows:
                return rows
        except (json.JSONDecodeError, AttributeError):
            pass

    # Estrategia 2 — objeto JSON raw: busca todos los { y prueba parse completo
    for match in re.finditer(r'\{', raw):
        start = match.start()
        try:
            obj, _ = decoder.raw_decode(raw, start)
            if isinstance(obj, dict):
                rows = obj.get("data") or obj.get("rows") or []
                if rows and isinstance(rows, list) and isinstance(rows[0], dict):
                    return rows
        except (json.JSONDecodeError, ValueError, IndexError):
            continue

    # Estrategia 3 — array JSON standalone: busca todos los [ y prueba parse
    for match in re.finditer(r'\[', raw):
        start = match.start()
        try:
            arr, _ = decoder.raw_decode(raw, start)
            if isinstance(arr, list) and len(arr) > 1 and isinstance(arr[0], dict):
                # Descartar arrays de schema tipo "columns" (tienen "name"/"type" como keys)
                first_keys = set(arr[0].keys())
                if first_keys <= {"name", "type", "description"}:
                    continue
                return arr
        except (json.JSONDecodeError, ValueError):
            continue

    # Estrategia 4 — recuperación parcial de JSON truncado
    # Busca el array "data" y extrae todos los objetos completos aunque el array esté cortado
    data_match = re.search(r'"data"\s*:\s*\[', raw)
    if data_match:
        tail = raw[data_match.end():]
        partial_rows: list = []
        for obj_match in re.finditer(r'\{', tail):
            try:
                obj, _ = decoder.raw_decode(tail, obj_match.start())
                if isinstance(obj, dict) and len(obj) >= 2:
                    # Descartar objetos schema (solo tienen "name"/"type"/"description")
                    if set(obj.keys()) <= {"name", "type", "description"}:
                        continue
                    partial_rows.append(obj)
            except (json.JSONDecodeError, ValueError):
                continue
        if partial_rows:
            print(f"[_parse_dataset_rows] Estrategia 4: {len(partial_rows)} filas parciales recuperadas")
            return partial_rows

    return []



# ═════════════════════════════════════════════════════════
# DATASET PIPELINE v8 — 3 NODOS (reemplaza dataset_generator)
# schema_designer → data_serializer → data_validator
# ═════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────
# HELPER — _validate_dataset (Python puro, sin LLM)
# ─────────────────────────────────────────────────────────

def _validate_and_correct_dataset(
    rows: list,
    constraints: dict,
    context_label: str = "",
) -> tuple:
    """Valida Y CORRIGE el dataset contra constraints matemáticos. CERO tokens LLM.

    Correcciones aplicadas (Python puro, deterministas):
    - Filas nulas: eliminadas
    - Revenue: escala proporcional para que la suma cuadre con Exhibit 1 ±5%
    - Costs: misma lógica si tienen constraint
    - EBITDA: recalculado como Revenue − Costs si ambas columnas existen
    - margin_pct: recalculado como (Revenue − Costs) / Revenue × 100

    Retorna (is_valid, errors, corrected_rows).
    """
    label = f"[_validate_and_correct] {context_label}" if context_label else "[_validate_and_correct]"
    errors: list = []

    if not rows:
        errors.append("Dataset vacío — 0 filas")
        return False, errors, []

    # Trabajar sobre copias para no mutar el state
    corrected_rows = [row.copy() for row in rows]

    revenue_col = constraints.get("revenue_column", "revenue")
    tolerance = constraints.get("tolerance_pct", 0.05)

    # ── Corrección 1: eliminar filas completamente nulas ──────────────
    before = len(corrected_rows)
    corrected_rows = [r for r in corrected_rows if not all(v is None for v in r.values())]
    removed = before - len(corrected_rows)
    if removed:
        print(f"  [corrector] Eliminadas {removed} filas completamente nulas")

    if not corrected_rows:
        errors.append("Dataset vacío tras eliminar filas nulas")
        return False, errors, []

    # ── Corrección 2: escalar revenue al total esperado ───────────────
    expected_revenue = constraints.get("revenue_annual_total")
    has_revenue_col = revenue_col in corrected_rows[0]

    if expected_revenue and has_revenue_col:
        actual_revenue = sum(
            float(row[revenue_col])
            for row in corrected_rows
            if row.get(revenue_col) is not None
        )
        if actual_revenue > 0:
            deviation = abs(actual_revenue - expected_revenue) / expected_revenue
            if deviation > tolerance:
                scale = expected_revenue / actual_revenue
                for row in corrected_rows:
                    if row.get(revenue_col) is not None:
                        row[revenue_col] = round(float(row[revenue_col]) * scale, 2)
                print(
                    f"  [corrector] Revenue escalado: {actual_revenue:,.0f} -> "
                    f"{expected_revenue:,.0f} (factor {scale:.4f})"
                )
            else:
                print(f"  [corrector] Revenue OK: {actual_revenue:,.0f} aprox {expected_revenue:,.0f}")
        else:
            errors.append("Revenue total es 0 — no se puede escalar")

    # ── Corrección 3: escalar costs si hay constraint ─────────────────
    expected_costs = constraints.get("cost_annual_total")
    if expected_costs:
        cost_col = "costs"
        actual_costs = sum(float(row.get(cost_col, 0) or 0) for row in corrected_rows)
        if actual_costs > 0:
            deviation = abs(actual_costs - expected_costs) / expected_costs
            if deviation > tolerance:
                scale = expected_costs / actual_costs
                for row in corrected_rows:
                    if row.get(cost_col) is not None:
                        row[cost_col] = round(float(row[cost_col]) * scale, 2)
                print(f"  [corrector] Costs escalado (factor {scale:.4f})")

    # ── Corrección 4: recalcular EBITDA = Revenue − Costs ─────────────
    # Fix M-14: SOLO si el valor NO es None — preservar nulls intencionales del ml_ds.
    # En ml_ds algunas filas tienen ebitda=null intencionalmente (datos faltantes realistas).
    if has_revenue_col and "ebitda" in corrected_rows[0] and "costs" in corrected_rows[0]:
        recalc_count = 0
        for row in corrected_rows:
            if row.get("ebitda") is not None:
                rev = float(row.get(revenue_col, 0) or 0)
                cost = float(row.get("costs", 0) or 0)
                row["ebitda"] = round(rev - cost, 2)
                recalc_count += 1
        print(f"  [corrector] EBITDA recalculado (solo no-null) en {recalc_count}/{len(corrected_rows)} filas")

    # ── Corrección 5: recalcular margin_pct ───────────────────────────
    # Fix M-14: SOLO si el valor NO es None — preservar nulls intencionales.
    if has_revenue_col and "margin_pct" in corrected_rows[0] and "costs" in corrected_rows[0]:
        recalc_count = 0
        for row in corrected_rows:
            if row.get("margin_pct") is not None:
                rev = float(row.get(revenue_col, 0) or 0)
                cost = float(row.get("costs", 0) or 0)
                row["margin_pct"] = round(((rev - cost) / rev) * 100, 2) if rev > 0 else 0.0
                recalc_count += 1
        print(f"  [corrector] margin_pct recalculado (solo no-null) en {recalc_count}/{len(corrected_rows)} filas")

    # ── Validación post-corrección ────────────────────────────────────
    n_expected = constraints.get("n_rows_expected", 0)
    if n_expected and len(corrected_rows) < n_expected:
        errors.append(f"Filas insuficientes: {len(corrected_rows)} de {n_expected}")

    # Verificar que el escalado fue efectivo
    if expected_revenue and has_revenue_col and not any("Revenue total es 0" in e for e in errors):
        final_rev = sum(
            float(row[revenue_col]) for row in corrected_rows if row.get(revenue_col) is not None
        )
        final_dev = abs(final_rev - expected_revenue) / expected_revenue
        if final_dev > tolerance:
            errors.append(
                f"Revenue post-corrección: {final_rev:,.0f} vs {expected_revenue:,.0f} "
                f"(desviacion {final_dev:.1%})"
            )

    is_valid = len(errors) == 0
    if is_valid:
        print(f"{label} OK — {len(corrected_rows)} filas validas y corregidas")
    else:
        for e in errors:
            print(f"{label} FAIL: {e}")

    return is_valid, errors, corrected_rows


# Entity-level SEGMENTATION feature columns for the ml_ds + clustering fallback schema
# (Issue #452). Customer-level RFM + behavioural axes (NOT a financial time-series panel), so
# K-Means clusters interpretable segments. `_enforce_mlds_clustering_structure` injects the
# latent blob structure over these; the financial Exhibit 1 stays a separate M1 narrative.
_CLUSTERING_SEGMENTATION_COLUMNS: tuple[dict, ...] = (
    {"name": "recency_days",      "type": "int",   "description": "Días desde la última actividad de la entidad",         "range_min": 1,    "range_max": 365,  "nullable": False, "trend": None, "dependency": None},
    {"name": "frequency_count",   "type": "int",   "description": "Número de interacciones/compras en el período",        "range_min": 1,    "range_max": 60,   "nullable": False, "trend": None, "dependency": None},
    {"name": "monetary_value",    "type": "float", "description": "Valor monetario acumulado de la entidad (USD)",        "range_min": 50.0, "range_max": 5000.0,"nullable": False, "trend": None, "dependency": None},
    {"name": "tenure_months",     "type": "int",   "description": "Antigüedad de la relación en meses",                   "range_min": 1,    "range_max": 72,   "nullable": False, "trend": None, "dependency": None},
    {"name": "engagement_score",  "type": "float", "description": "Score de engagement de la entidad (0-1)",             "range_min": 0.0,  "range_max": 1.0,  "nullable": False, "trend": None, "dependency": None},
    {"name": "support_intensity", "type": "float", "description": "Intensidad de uso de soporte (interacciones/mes)",     "range_min": 0.0,  "range_max": 10.0, "nullable": False, "trend": None, "dependency": None},
)


def _build_clustering_fallback_schema(max_rows: int) -> dict:
    """Entity-level segmentation fallback schema for ml_ds + clustering (Issue #452).

    ``period`` is kept as a row id (str → excluded from the numeric K-Means fit); the rest are
    interpretable segmentation features that `_enforce_mlds_clustering_structure` blobs. No
    revenue/costs/margin/ebitda → the financial scaling + ebitda/margin recompute + outlier
    target selection in `_generate_dataset_from_schema`/`data_validator` all no-op cleanly.
    """
    columns: list[dict] = [
        {"name": "period", "type": "str", "description": "Identificador de entidad/registro",
         "range_min": None, "range_max": None, "nullable": False, "trend": None, "dependency": None},
    ]
    columns.extend(dict(c) for c in _CLUSTERING_SEGMENTATION_COLUMNS)
    return {
        "columns": columns,
        "n_rows": max_rows,
        "time_granularity": "monthly",
        "constraints": {"tolerance_pct": 0.05},
        "reasoning_summary": "Fallback schema clustering — features de segmentación (Issue #452)",
    }


# ─────────────────────────────────────────────────────────
# HELPER — _build_fallback_schema (sin LLM, regex sobre Exhibit 1)
# ─────────────────────────────────────────────────────────

def _build_fallback_schema(
    state: ADAMState,
    max_rows: int,
    profile: str,
    primary_family: str = "clasificacion",
    *,
    clustering_structure_enabled: bool = True,
) -> dict:
    """Schema mínimo si schema_designer falla. Extrae revenue con regex del Exhibit 1.

    ``primary_family`` gates the ml_ds column extension: only "clasificacion" gets the
    18-column binary-target schema; all other ml_ds families receive the 12-column
    generic baseline (cols 1–10 + customer_ltv + engagement_score) so their M3
    notebooks do not receive a classification-specific target.

    Issue #452 — for ``ml_ds + clustering`` (with the kill-switch on) it returns a dedicated
    entity-level SEGMENTATION schema (``period`` + interpretable segmentation features, no
    churn/retention/financial time-series panel) instead, so K-Means clusters interpretable
    behavioural axes; ``_enforce_mlds_clustering_structure`` then injects the latent blobs.
    """
    if (
        clustering_structure_enabled
        and profile == "ml_ds"
        and primary_family == "clustering"
    ):
        return _build_clustering_fallback_schema(max_rows)

    financial_text = state.get("doc1_anexo_financiero", "")

    revenue_match = re.search(r'[\$€]?\s*([\d,]+(?:\.\d+)?)\s*[Mm]', financial_text)
    revenue_estimate = (
        float(revenue_match.group(1).replace(",", "")) * 1_000_000
        if revenue_match
        else 10_000_000
    )

    # Calibrar rangos por fila (no por año) para que el revenue scaler no aplaste
    # el margen. Con rangos anuales y n_rows=200 el scaler reducía revenue a 1/16
    # de su valor, pero costs permanecían sin escalar → margin de -1200%.
    per_row_rev = revenue_estimate / max_rows

    base_columns = [
        {"name": "period",        "type": "str",   "description": "Período temporal",    "range_min": None, "range_max": None,              "nullable": False, "trend": None, "dependency": None},
        {"name": "revenue",       "type": "float", "description": "Ingresos del período", "range_min": round(per_row_rev * 0.85, 2), "range_max": round(per_row_rev * 1.15, 2), "nullable": False, "trend": "up", "dependency": None},
        {"name": "costs",         "type": "float", "description": "Costos del período",   "range_min": round(per_row_rev * 0.60, 2), "range_max": round(per_row_rev * 0.88, 2), "nullable": False, "trend": "up", "dependency": None},
        {"name": "margin_pct",    "type": "float", "description": "Margen operativo %",   "range_min": 10.0, "range_max": 35.0, "nullable": False, "trend": None, "dependency": None},
        {"name": "churn_rate",    "type": "float", "description": "Tasa de churn mensual","range_min": 0.02, "range_max": 0.15, "nullable": False, "trend": None, "dependency": {"depends_on": "revenue", "relationship": "inverse", "noise_factor": 0.1}},
        {"name": "nps",           "type": "int",   "description": "Net Promoter Score",   "range_min": 20,   "range_max": 75,   "nullable": False, "trend": None, "dependency": None},
        {"name": "retention_m1",  "type": "float", "description": "Retención cohorte mes 1",  "range_min": 0.65, "range_max": 0.95, "nullable": False, "trend": None, "dependency": None},
        {"name": "retention_m3",  "type": "float", "description": "Retención cohorte mes 3",  "range_min": 0.50, "range_max": 0.80, "nullable": False, "trend": None, "dependency": {"depends_on": "retention_m1", "relationship": "linear", "noise_factor": 0.05}},
        {"name": "retention_m6",  "type": "float", "description": "Retención cohorte mes 6",  "range_min": 0.35, "range_max": 0.65, "nullable": False, "trend": None, "dependency": {"depends_on": "retention_m3", "relationship": "linear", "noise_factor": 0.05}},
        {"name": "retention_m12", "type": "float", "description": "Retención cohorte mes 12", "range_min": 0.20, "range_max": 0.50, "nullable": False, "trend": None, "dependency": {"depends_on": "retention_m6", "relationship": "linear", "noise_factor": 0.05}},
    ]

    if profile == "ml_ds" and primary_family == "clasificacion":
        # Columns 11–18 for clasificacion: binary churn target with signal.
        # customer_ltv / engagement_score keep nullable=True (5% null ratio);
        # cols 13–18 are fixed classification features; categoria is the binary
        # target (int 0/1) correlated with churn_rate via linear dependency so
        # LR/RF achieve AUC-ROC ≥ 0.70 instead of learning noise from a str target.
        base_columns.extend([
            {"name": "customer_ltv",            "type": "float", "description": "Customer lifetime value estimado",                  "range_min": 500,  "range_max": 5000, "nullable": True,  "trend": "up", "dependency": None},
            {"name": "engagement_score",        "type": "float", "description": "Score de engagement del usuario (0-1)",             "range_min": 0.1,  "range_max": 0.95, "nullable": True,  "trend": None, "dependency": None},
            {"name": "days_since_last_login",   "type": "int",   "description": "Días desde el último login del usuario",            "range_min": 1,    "range_max": 180,  "nullable": False, "trend": None, "dependency": {"depends_on": "engagement_score", "relationship": "inverse", "noise_factor": 0.2}},
            {"name": "support_tickets_count",   "type": "int",   "description": "Número de tickets de soporte abiertos",            "range_min": 0,    "range_max": 10,   "nullable": False, "trend": None, "dependency": {"depends_on": "nps",              "relationship": "inverse", "noise_factor": 0.2}},
            {"name": "plan_tier",               "type": "int",   "description": "Nivel del plan contratado (1=básico, 2=estándar, 3=premium)", "range_min": 1, "range_max": 3, "nullable": False, "trend": None, "dependency": None},
            {"name": "payment_failures",        "type": "int",   "description": "Número de fallos de pago en los últimos 3 meses",   "range_min": 0,    "range_max": 5,    "nullable": False, "trend": None, "dependency": {"depends_on": "churn_rate",       "relationship": "linear",  "noise_factor": 0.3}},
            {"name": "monthly_usage_pct",       "type": "float", "description": "Porcentaje de uso mensual del producto (0-1)",      "range_min": 0.0,  "range_max": 1.0,  "nullable": False, "trend": None, "dependency": {"depends_on": "engagement_score", "relationship": "linear",  "noise_factor": 0.1}},
            {"name": "categoria",               "type": "int",   "description": "Etiqueta binaria de clasificación: 0=activo, 1=en riesgo de churn", "range_min": 0, "range_max": 1, "nullable": False, "trend": None, "dependency": {"depends_on": "churn_rate", "relationship": "linear", "noise_factor": 0.30}},
        ])
    elif profile == "ml_ds":
        # Generic ml_ds baseline (cols 11–12) for non-clasificacion families
        # (regresion, clustering, serie_temporal, or unresolved primary_family).
        # No classification target here — M3 prompts for those families derive
        # their target from the base columns (e.g. revenue for regresion).
        base_columns.extend([
            {"name": "customer_ltv",     "type": "float", "description": "Customer lifetime value estimado",         "range_min": 500, "range_max": 5000, "nullable": True,  "trend": "up", "dependency": None},
            {"name": "engagement_score", "type": "float", "description": "Score de engagement del usuario (0-1)",     "range_min": 0.1, "range_max": 0.95, "nullable": True,  "trend": None, "dependency": None},
        ])

    return {
        "columns": base_columns,
        "n_rows": max_rows,
        "time_granularity": "monthly",
        "constraints": {
            "revenue_annual_total": revenue_estimate,
            "tolerance_pct": 0.05,
            "revenue_column": "revenue",
        },
        "reasoning_summary": "Fallback schema — schema_designer falló",
    }


# ─────────────────────────────────────────────────────────
# HELPER — _normalize_ml_ds_columns (safety-net post-validación Pydantic)
# ─────────────────────────────────────────────────────────

def _normalize_ml_ds_columns(schema_result: dict, profile: str) -> dict:
    """Renombra columnas ml_ds legacy que no hacen match con los alias del notebook.

    Se ejecuta DESPUÉS de la validación Pydantic del output del LLM, capturando casos
    en que el LLM ignora el prompt actualizado y sigue emitiendo los nombres viejos.
    Solo actúa sobre profile == 'ml_ds'. Nunca agrega ni elimina columnas (14 se preservan).
    """
    if profile != "ml_ds":
        return schema_result

    RENAME_MAP = {
        "support_tickets":      ("ticket_text", "str"),
        "feature_adoption_pct": ("categoria",   "str"),
    }

    columns = schema_result.get("columns", [])
    seen_names: set = set()
    for col in columns:
        col_name = col.get("name", "")
        if col_name in RENAME_MAP:
            new_name, new_type = RENAME_MAP[col_name]
            if new_name in seen_names:
                new_name = new_name + "_2"
                logger.warning("[_normalize_ml_ds_columns] nombre duplicado — usando '%s'", new_name)
            logger.info(
                "[_normalize_ml_ds_columns] '%s' (%s) → '%s' (%s)",
                col_name, col.get("type"), new_name, new_type,
            )
            col["name"] = new_name
            col["type"] = new_type
            col["range_min"] = None
            col["range_max"] = None
            col["trend"] = None
            col["dependency"] = None
        elif col_name.endswith("_tickets") and col.get("type") == "int":
            # catch-all: cualquier contador *_tickets con tipo int es inseguro para NLP
            new_name = "ticket_text" if "ticket_text" not in seen_names else "ticket_text_2"
            logger.info(
                "[_normalize_ml_ds_columns] catch-all: '%s' (int) → '%s' (str)", col_name, new_name
            )
            col["name"] = new_name
            col["type"] = "str"
            col["range_min"] = None
            col["range_max"] = None
            col["trend"] = None
            col["dependency"] = None
        seen_names.add(col.get("name", ""))

    schema_result["columns"] = columns
    return schema_result


# ─────────────────────────────────────────────────────────
# Issue #225 — Dataset Schema Required Contract: validator + augmenter
# Funciones Python puras (cero tokens LLM, deterministas, sin I/O).
# Mantienen el contrato dilema↔dataset alineado entre case_architect,
# schema_designer, data_validator y m3_notebook_generator.
# ─────────────────────────────────────────────────────────

# Tipos válidos según ColumnDefinition.type — mantener sincronizado.
# "date" alineado con ColumnDefinition.type (Issue #225 review follow-up).
_CONTRACT_TYPE_TO_SCHEMA_TYPE = {
    "int": "int",
    "float": "float",
    "str": "str",
    "date": "date",
}


# ─────────────────────────────────────────────────────────
# Issue #228 — Coherencia semántica título↔target + inferencia de leakage
# Determinista, cero tokens LLM. Cubre las dos brechas observadas en la
# revisión empírica de PR #227 (caso "LogiTech — retención" con target
# `delay_flag` y features `retention_m*` no marcadas como leakage).
# ─────────────────────────────────────────────────────────

# Diccionario título→tokens esperados en target_column.name/role.
# Cada clave es un keyword (sin acentos) que puede aparecer en el título;
# el valor es la lista de tokens (snake_case) que el target debería contener
# para considerarse coherente. Mantener corto y de alta precisión: si el
# título no matchea ninguna clave, NO emitimos warning (silent OK).
# Retention-family rows are sourced from RETENTION_CHURN_TOKENS (the single vocab) so
# the lists cannot drift again (#301 PR2b). Keys with an extra domain token compose it.
_TITLE_TO_TARGET_TOKENS: dict[str, tuple[str, ...]] = {
    "retencion": RETENTION_CHURN_TOKENS,
    "retención": RETENTION_CHURN_TOKENS,
    "churn": RETENTION_CHURN_TOKENS,
    "abandono": RETENTION_CHURN_TOKENS,
    "cancelacion": RETENTION_CHURN_TOKENS + ("cancel",),
    "cancelación": RETENTION_CHURN_TOKENS + ("cancel",),
    "fidelizacion": RETENTION_CHURN_TOKENS,
    "fidelización": RETENTION_CHURN_TOKENS,
    "retraso": ("delay", "late", "lateness", "delivery_time"),
    "demora": ("delay", "late", "lateness", "delivery_time"),
    "fraude": ("fraud", "fraudulent", "anomaly"),
    "fraud": ("fraud", "fraudulent", "anomaly"),
    "default": ("default", "delinquency", "credit_loss"),
    "morosidad": ("default", "delinquency", "overdue"),
    "ventas": ("sales", "revenue", "demand", "units_sold"),
    "demanda": ("demand", "sales", "units_sold", "forecast"),
    "ingresos": ("revenue", "sales", "income"),
    "rotacion": RETENTION_CHURN_TOKENS + ("turnover",),
    "rotación": RETENTION_CHURN_TOKENS + ("turnover",),
    "produccion": ("output", "production", "throughput"),
    "producción": ("output", "production", "throughput"),
    "calidad": ("defect", "quality", "reject"),
    "defectos": ("defect", "reject", "quality"),
    "satisfaccion": ("satisfaction", "nps", "csat"),
    "satisfacción": ("satisfaction", "nps", "csat"),
}

# Patrones de naming que marcan leakage cuando el target NO es la propia familia
# de retención/churn. Aplicado por _infer_leakage_risk_from_naming.
_LEAKAGE_NAMING_PATTERN = re.compile(
    r"(?i)("
    r"^retention_|^churn_|^churn$|^retention$|"
    r"^nps$|^csat$|customer_ltv|^ltv$|"
    r"^complaint|^complaints?_|cancellation_|cancellations?$|"
    r"_post_event|_after_event|_post_churn"
    r")"
)

# Targets de retención/churn (por nombre) se identifican vía `_is_retention_target_name`,
# que envuelve `retention_tokens.is_retention_match` (vocab único + denylist de gobernanza).
# Se usa para no inferir leakage por naming cuando el propio objetivo pertenece a esa
# familia (las retention_* features podrían ser lags válidos de auditoría temporal).

# Token único del warning de mismatch título↔target. Lo EMITE
# `_validate_target_semantic_coherence` y lo CONSUME `_should_reprompt_on_target_mismatch`
# (#305 Gate 2). Constante compartida para que productor y consumidor no se acoplen por un
# string literal duplicado.
_TARGET_SEMANTIC_MISMATCH_TOKEN = "target_semantic_mismatch"


def _validate_target_semantic_coherence(
    case_title: str | None, target_spec: dict | None
) -> list[str]:
    """Detecta desalineamiento entre título del caso y target_column.

    Devuelve list[str] de warnings (vacía si no hay mismatch o no aplica).
    Cero LLM, cero red, idempotente. Falsos positivos minimizados: solo
    emite cuando el título contiene un keyword conocido y el target no
    matchea NINGUNO de los tokens esperados.
    """
    if not case_title or not target_spec:
        return []
    target_name = (target_spec.get("name") or "").lower().strip()
    target_role = (target_spec.get("role") or "").lower().strip()
    if not target_name:
        return []

    title_lower = case_title.lower()
    matched_keys: list[str] = []
    expected_tokens: set[str] = set()
    for kw, tokens in _TITLE_TO_TARGET_TOKENS.items():
        if kw in title_lower:
            matched_keys.append(kw)
            expected_tokens.update(tokens)

    if not expected_tokens:
        # Título sin keyword conocido — no juzgamos coherencia (silent OK).
        return []

    haystack = f"{target_name} {target_role}"
    if any(tok in haystack for tok in expected_tokens):
        return []

    expected_str = ", ".join(sorted(expected_tokens))
    matched_str = ", ".join(sorted(set(matched_keys)))
    return [
        f"{_TARGET_SEMANTIC_MISMATCH_TOKEN}: el título sugiere [{matched_str}] "
        f"(tokens esperados: {expected_str}) pero target_column.name='{target_name}' "
        f"(role={target_role or 'n/a'}). Revisa que el dataset y el dilema "
        f"resuelvan la misma pregunta de negocio."
    ]


def _infer_leakage_risk_from_naming(contract: dict | None) -> dict | None:
    """Marca features con `is_leakage_risk=True` cuando su nombre matchea
    patrones de naming (retention_*, churn_*, nps, customer_ltv, complaint_*,
    cancellation_*, *_post_event) Y el target NO pertenece a la familia de
    retención/churn (en cuyo caso esas features podrían ser lags válidos).

    No muta el dict de entrada. Idempotente: features ya marcadas se respetan.
    Devuelve el contrato (posiblemente con flags adicionales) o None.
    """
    if not contract:
        return contract

    target = contract.get("target_column") or {}
    target_name = (target.get("name") or "").lower()
    target_role = (target.get("role") or "").lower()

    if _is_retention_target_name(target_name, target_role):
        # No inferimos leakage: retention_m* podría ser un lag válido del propio target.
        return contract

    new_contract = dict(contract)
    new_features: list[dict] = []
    inferred_count = 0
    for feat in contract.get("feature_columns") or []:
        fname = (feat.get("name") or "").strip()
        if not fname:
            new_features.append(feat)
            continue
        if feat.get("is_leakage_risk"):
            new_features.append(feat)
            continue
        if _LEAKAGE_NAMING_PATTERN.search(fname):
            updated = dict(feat)
            updated["is_leakage_risk"] = True
            # Marca interna no destinada a docente: queda en el dict del
            # contrato pero no se propaga a ColumnDefinition.description
            # (downstream solo lee `description`). Útil para auditoría/logging.
            updated["leakage_inferred_by"] = "naming_pattern"
            new_features.append(updated)
            inferred_count += 1
        else:
            new_features.append(feat)

    if inferred_count == 0:
        return contract

    new_contract["feature_columns"] = new_features
    logger.warning(
        "[contract.leakage_inference] %d feature(s) auto-marcadas como leakage "
        "por naming (target='%s', role='%s')",
        inferred_count, target_name, target_role,
    )
    return new_contract


# Roles que ya nombran un evento de clasificación (preservamos el nombre de dominio que
# el LLM eligió; solo corregimos el rol/dtype). regression/forecasting NO están aquí: sus
# nombres suelen ser métricas continuas (margin_pct, churn_rate) → caen a target_event_flag.
_CLASSIFICATION_ADJACENT_ROLES: frozenset[str] = frozenset({
    "classification_target", "anomaly_target", "ranking_target",
})


def _normalize_business_classification_target(
    contract: dict | None, *, profile: str, family: str | None
) -> tuple[dict | None, bool]:
    """Endurece SOLO la FORMA del target para business+clasificación (#301 PR2b, A1/A4).

    Convierte la detección de #228 en ACCIÓN: ``null`` / target continuo / rol no-clasificación
    → ``classification_target`` ``int`` binario. El spine downstream construye la columna
    (no se duplica aquí). El NOMBRE de dominio es LLM-primario — lo empuja el bloque del prompt
    business; aquí se PRESERVA si vino con un rol de clasificación-adyacente, y solo se cae a
    ``target_event_flag`` como último recurso (sin slugging del título — 3B descartado).

    Árbol de decisión (business+clasificación)::

        target = contract.target_column
        ¿binario de dominio ya? (role==classification_target ∧ dtype==int ∧ name)
            ├─ sí → (contract, False)          # passthrough — NO reescribe por mismatch (A4)
            └─ no → reescribe forma:
                      role→classification_target, dtype→int
                      name→ se conserva si (name ∧ role ∈ clasificación-adyacente)
                            si no → "target_event_flag"   (último recurso)
                      (contract', True)

    NO muta el dict de entrada. Fuera del gate (ml_ds / business no-clasificación) devuelve
    ``(contract, False)`` intacto.
    """
    if profile != "business" or family != "clasificacion":
        return contract, False

    src = contract or {}
    target = src.get("target_column") or {}
    name = (target.get("name") or "").strip()
    role = (target.get("role") or "").strip().lower()
    dtype = (target.get("dtype") or "").strip().lower()

    if name and role == "classification_target" and dtype == "int":
        return contract, False  # ya es un classification_target binario — passthrough

    keep_name = bool(name) and role in _CLASSIFICATION_ADJACENT_ROLES
    new_name = name if keep_name else "target_event_flag"

    new_target = dict(target)
    new_target.update({
        "name": new_name,
        "role": "classification_target",
        "dtype": "int",
    })
    if not (new_target.get("description") or "").strip():
        new_target["description"] = "Variable objetivo binaria del caso (0/1)"

    new_contract = dict(src)
    new_contract["target_column"] = new_target
    return new_contract, True


def _normalize_mlds_classification_target(
    contract: dict | None, *, profile: str, family: str | None, enabled: bool = True
) -> tuple[dict | None, bool]:
    """Endurece la FORMA del target para ml_ds + clasificación a binario (Issue #350).

    SIBLING de ``_normalize_business_classification_target`` — NO generalizar esa función
    (``test_normalize_noop_for_ml_ds`` exige que siga siendo identidad para ml_ds). El ancla M1
    ml_ds es ahora binario-only, pero el prompt es PROBABILÍSTICO: un LLM puede emitir igual un
    ``classification_target`` ``dtype="str"`` (multiclase) o un rol no-clasificación. Toda la
    cadena downstream es binario-only y, post-#348 (notebook contract-first), un target no-int
    DEGRADA EN SILENCIO (``_align``/``_enforce_mlds`` hacen early-return en ``dtype!="int"``, el
    augmenter inyecta una columna ``str``/``int[0,100]`` y el notebook hace
    ``skipped_non_binary_target`` → job COMPLETA sin modelo, sin flag ``m3NotebookDegraded``). Este
    normalizador determinista cierra ese hueco en el ORIGEN: coacciona cualquier target que no sea
    ya un ``classification_target`` binario a ``role=classification_target`` + ``dtype=int``,
    ANTES de persistir el contrato (``case_architect`` lo escribe en ``dataset_schema_required``),
    de modo que ``_align``/``_augment``/``_enforce_mlds`` lo vean ya binario.

    Coacciona AMBOS ``role`` Y ``dtype`` (no solo dtype): las 3 puertas downstream exigen
    ``role=="classification_target"`` AND ``dtype=="int"``; un ``anomaly_target`` con ``dtype=int``
    pasaría un chequeo dtype-only, conservaría su rol y DEGRADARÍA igual vía
    ``_augment._default_column`` → ``int[0,100]``. Preserva el NOMBRE de dominio para roles de
    clasificación adyacentes (``_CLASSIFICATION_ADJACENT_ROLES``); si no, cae a ``target_event_flag``
    (mismo árbol que el sibling business). Determinista, 0 tokens, copy-on-write (no muta el dict de
    entrada → determinismo del seed + thread-safety). Kill-switch ``MLDS_BINARY_TARGET_COERCE``.

    Fuera del gate (kill-switch off / business / no-clasificación) devuelve ``(contract, False)``
    intacto. Passthrough byte-idéntico (mismo objeto) cuando el target ya es binario válido
    (cubre churn y todo caso binario normal).
    """
    if not enabled or profile != "ml_ds":
        return contract, False
    # ml_ds: None family → "clasificacion" (espeja `_align`/`_enforce_mlds`/`_effective_family`):
    # un job ml_ds con algoritmos vacíos (family None) igual construye el template clf downstream,
    # así que el contrato debe normalizarse para ese cohorte también.
    if (family or "clasificacion") != "clasificacion":
        return contract, False

    src = contract or {}
    target = src.get("target_column") or {}
    name = (target.get("name") or "").strip()
    role = (target.get("role") or "").strip().lower()
    dtype = (target.get("dtype") or "").strip().lower()

    if name and role == "classification_target" and dtype == "int":
        return contract, False  # ya es un classification_target binario — passthrough

    keep_name = bool(name) and role in _CLASSIFICATION_ADJACENT_ROLES
    new_target = dict(target)
    new_target.update({
        "name": name if keep_name else "target_event_flag",
        "role": "classification_target",
        "dtype": "int",
    })
    if not (new_target.get("description") or "").strip():
        new_target["description"] = "Variable objetivo binaria del caso (0/1)"

    new_contract = dict(src)
    new_contract["target_column"] = new_target
    # Observabilidad LOG-ONLY (precedente #336): no teacher-facing, no persistido.
    logger.warning(
        "[case_architect] ml_ds classification target coerced to binary int (#350)",
        extra={
            "node": "case_architect", "original_role": role, "original_dtype": dtype,
            "coerced_name": new_target["name"], "reason": "mlds_binary_target_coerced",
        },
    )
    return new_contract, True


def _should_reprompt_on_target_mismatch(
    *, target_enforced: bool, profile: str, family: str | None, warnings: list[str]
) -> bool:
    """#305 Gate 2 — gate the mismatch reprompt. True only when the shape was NOT
    normalized (``target_enforced`` is False → the target is already a valid binary
    classification target) for business+clasificación AND a ``target_semantic_mismatch``
    warning is present (valid shape, wrong NAME). Extracted from ``case_architect`` so the
    exact condition is unit-testable in isolation."""
    if target_enforced or profile != "business" or family != "clasificacion":
        return False
    return any(w.startswith(_TARGET_SEMANTIC_MISMATCH_TOKEN) for w in warnings)


def _reprompt_business_target_on_mismatch(
    *, llm: Any, prompt: str, contract: dict | None, title: str | None
) -> tuple[dict | None, str | None]:
    """#305 Gate 2 — reprompt-once enforcement for a title↔target NAME mismatch.

    Precondition (checked by the caller): business+clasificación, a
    ``target_semantic_mismatch`` warning is present, and the target is a *valid* binary
    classification target whose NAME is semantically misaligned with the título. The shape
    is fine; only the LLM can rename it to the domain event (deterministic title-slugging
    was rejected — 3B). So we reprompt ONCE and let the caller re-run
    ``_normalize_business_classification_target`` to guarantee the binary shape regardless::

        reprompt ONCE (wrapped — any exception is swallowed)
          ├─ usable classification target returned ─► swap it in (NOT re-judged by the
          │                                            heuristic → false-positive-safe)
          ├─ null / unusable target returned ───────► keep original (still valid) + note
          └─ LLM call raises ───────────────────────► keep original (still valid) + note

    Returns ``(contract, note)``. NEVER raises — a mismatch was only a warning before, so
    enforcement must not regress reliability by failing the job.
    """
    correction = (
        prompt
        + "\n\n# CORRECCIÓN OBLIGATORIA DE COHERENCIA TÍTULO↔TARGET (#228/#301)\n"
        + f'El título del caso es: "{title}". Tu `dataset_schema_required.target_column.name` '
        + "anterior NO refleja el evento central de ese título. Reescribe la respuesta "
        + "COMPLETA respetando el schema, manteniendo `role`=`classification_target` y "
        + "`dtype`=`int` binario, pero renombrando `target_column.name` (snake_case inglés) "
        + "para que nombre el EVENTO binario del título (p. ej. incumplimiento→`late_partner_flag`, "
        + "fraude→`fraud_flag`, mora→`default_60d`, abandono→`churn_flag`). No menciones Python, "
        + "notebooks, AUC ni hiperparámetros."
    )
    try:
        structured_llm = llm.with_structured_output(CaseArchitectOutput)
        result: CaseArchitectOutput = structured_llm.invoke(correction)
    except Exception as e:  # noqa: BLE001 — best-effort; never fail the job on a reprompt
        logger.warning("[case_architect] reprompt #305 Gate2 falló: %s", e)
        return contract, (
            "target_semantic_mismatch no corregido (reprompt falló): se conserva el target "
            "original válido; revisar coherencia título↔target."
        )

    new_contract = (
        result.dataset_schema_required.model_dump()
        if result.dataset_schema_required is not None
        else None
    )
    if not new_contract or not ((new_contract.get("target_column") or {}).get("name") or "").strip():
        return contract, (
            "reprompt no produjo un target de clasificación usable: se conserva el target "
            "original válido; revisar coherencia título↔target."
        )
    return new_contract, (
        "target_column reemplazado por la respuesta del reprompt (#305 Gate 2): se solicitó "
        "alinear el nombre con el evento del título; aceptado sin re-juzgar."
    )


def _validate_business_cost_matrix(
    contract: dict | None, family: str | None, case_title: str | None
) -> tuple[dict | None, list[str]]:
    """Valida y sanitiza ``business_cost_matrix`` del contrato (Issue #238).

    Política de degradación (case_architect-style):
      * Si ``family is None`` (no se pudo resolver el algoritmo via
        ``family_of`` ni ``resolve_legacy_family``) y el campo viene poblado
        → se preserva intacto + warning ``unknown_family``. Razón: el
        dispatcher M3 hace fallback a ``clasificacion`` cuando no resuelve
        familia, así que nulificar aquí perdería una matriz que M3 sí va a
        usar. La asimetría no se compromete por un nombre de algoritmo
        no canónico.
      * Si el LLM emitió un dict inválido (negativo, no finito, fields faltantes)
        → ``ValidationError`` capturado, structured ``logger.warning`` con
        ``case_title`` + ``raw_values`` + ``e.errors()`` para trazabilidad,
        + warning sanitizado en español apto para ``data_gap_warnings`` (sin
        repetir el título crudo en el string del prompt), + ``business_cost_matrix``
        nulificado en el dict devuelto.
      * Si la familia es ``clasificacion`` y el campo viene None → warning
        estructurado + sanitizado (M3 caerá en el fallback fp=1, fn=5).
      * Si la familia es una NO-clasificación conocida y el campo viene
        poblado → warning + nulificado (M3 de otras familias no usa cost
        matrix).
      * Si todo OK → se devuelve un contrato con la matriz **normalizada**
        (currency upper, tipos float emitidos por Pydantic). El contrato
        original nunca se muta in-place.

    El contrato de entrada NO se muta in-place: se devuelve un nuevo dict
    cuando hay cualquier cambio efectivo (nulificación o normalización).
    Devuelve ``(contract_or_copy, warnings)``.

    El logger NUNCA loguea el dict raw completo del contrato (puede contener
    metadatos pedagógicos largos); siempre acota ``raw_values`` a las 3 keys
    esperadas (``fp_cost``, ``fn_cost``, ``currency``) para evitar leakear
    shape inesperada del LLM al log estructurado.
    """
    # Late import para evitar ciclo: tools_and_schemas <- graph en tests.
    from case_generator.tools_and_schemas import BusinessCostMatrix
    from pydantic import ValidationError

    warnings: list[str] = []
    if contract is None:
        return contract, warnings

    raw_value = contract.get("business_cost_matrix")
    family_norm = (family or "").strip().lower()
    is_classification = family_norm == "clasificacion"
    is_unknown_family = family_norm == ""

    # Helper para acotar el log estructurado a las 3 keys conocidas, evitando
    # leakear keys inesperadas del LLM.
    def _safe_subset(value: object) -> dict:
        if not isinstance(value, dict):
            return {"_raw_type": type(value).__name__}
        return {k: value.get(k) for k in ("fp_cost", "fn_cost", "currency")}

    # Caso 1 — campo ausente para clasificacion.
    if raw_value is None:
        if is_classification:
            logger.warning(
                "[case_architect.cost_matrix] missing for classification case "
                "(case_title=%r, family=%r)",
                case_title or "<sin titulo>", family,
            )
            warnings.append(
                "business_cost_matrix_missing: el caso es de clasificación pero "
                "case_architect no emitió matriz de costos (fp_cost/fn_cost). "
                "El notebook M3 usará fallback fp=1, fn=5 (sin asimetría real)."
            )
        return contract, warnings

    # Caso 1b — familia desconocida (no resoluble) con matriz poblada:
    # NO nulificar. El dispatcher M3 cae a clasificación por defecto, así
    # que descartar aquí perdería datos válidos. Solo emitimos warning.
    if is_unknown_family:
        logger.warning(
            "[case_architect.cost_matrix] cost matrix emitted but family could "
            "not be resolved (case_title=%r, family=%r, raw_values=%r) \u2014 "
            "preservando matriz (M3 har\u00e1 fallback a clasificacion)",
            case_title or "<sin titulo>", family, _safe_subset(raw_value),
        )
        warnings.append(
            "business_cost_matrix_unknown_family: no se pudo resolver la familia "
            "del algoritmo principal. La matriz de costos se preserva porque el "
            "notebook M3 hará fallback a clasificación."
        )
        # Continúa al Caso 3/4 para validar e (idealmente) normalizar la matriz.

    # Caso 2 — campo poblado para una familia conocida que no es clasificación.
    elif not is_classification:
        logger.warning(
            "[case_architect.cost_matrix] cost matrix emitted for non-classification "
            "family (case_title=%r, family=%r, raw_values=%r) \u2014 nulificando",
            case_title or "<sin titulo>", family, _safe_subset(raw_value),
        )
        warnings.append(
            "business_cost_matrix_wrong_family: case_architect emitió matriz de "
            "costos para una familia que no es clasificación. Se descarta "
            "(M3 no la usa fuera de clasificación)."
        )
        new_contract = dict(contract)
        new_contract["business_cost_matrix"] = None
        return new_contract, warnings

    # Caso 3 — campo poblado para clasificacion (o familia desconocida que
    # cae al fallback de M3): validamos con Pydantic.
    try:
        validated = BusinessCostMatrix.model_validate(raw_value)
    except ValidationError as e:
        # Structured log con todos los detalles para trazabilidad en producción.
        # raw_values se acota a las 3 keys esperadas para evitar PII inesperada.
        logger.warning(
            "[case_architect.cost_matrix] ValidationError (case_title=%r, "
            "raw_values=%r, errors=%r) \u2014 nulificando",
            case_title or "<sin titulo>", _safe_subset(raw_value), e.errors(),
        )
        # Warning sanitizado para data_gap_warnings (no repite el título crudo
        # ni los errors de Pydantic; basta para que el docente entienda que el
        # M3 cayó al fallback).
        warnings.append(
            "business_cost_matrix_invalid: case_architect emitió valores no "
            "válidos en la matriz de costos (revisa logs estructurados para "
            "fp_cost/fn_cost/currency exactos). El notebook M3 usará fallback "
            "fp=1, fn=5."
        )
        new_contract = dict(contract)
        new_contract["business_cost_matrix"] = None
        return new_contract, warnings

    # Caso 4 — válido. Persistimos la versión normalizada (currency upper).
    new_contract = dict(contract)
    new_contract["business_cost_matrix"] = validated.model_dump()
    return new_contract, warnings


def _validate_target_event_rate(
    contract: dict | None,
    family: str | None,
    case_title: str | None,
    profile: str | None,
) -> tuple[dict | None, list[str]]:
    """Valida y sanitiza ``target_event_rate`` del contrato (Issue F1).

    Fuente única de verdad de la prevalencia del evento: el architect la emite, Exhibit 2 la
    imprime, y el generador determinista calibra la columna target a ella. Best-effort
    (case_architect-style), NUNCA lanza ni muta el dict in-place:
      * Gate = ml_ds + clasificación + target binario (``role==classification_target`` y
        ``dtype==int``). Fuera del gate y poblado → warning + nulificado (no aplica a
        business/multiclase/otras familias).
      * Dentro del gate y ausente → warning estructurado (el generador cae al umbral ~0.50 y
        Exhibit 2 quedará incoherente — señal accionable para operadores).
      * Dentro del gate, presente pero fuera de [_MIN, _MAX] o no finito → warning + nulificado.
      * OK → contrato con el rate como ``float``.
    Devuelve ``(contract_or_copy, warnings)``.
    """
    from case_generator.tools_and_schemas import (
        _MAX_TARGET_EVENT_RATE,
        _MIN_TARGET_EVENT_RATE,
    )

    warnings: list[str] = []
    if contract is None:
        return contract, warnings

    raw_value = contract.get("target_event_rate")
    family_norm = (family or "").strip().lower()
    profile_norm = (profile or "").strip().lower()
    target = contract.get("target_column") or {}
    is_binary_clf = (
        profile_norm == "ml_ds"
        and family_norm == "clasificacion"
        and isinstance(target, dict)
        and target.get("role") == "classification_target"
        and target.get("dtype") == "int"
    )

    # Fuera del gate: si viene poblado, nulificar (no aplica).
    if not is_binary_clf:
        if raw_value is not None:
            logger.warning(
                "[case_architect.target_event_rate] emitido fuera del gate ml_ds+clf binario "
                "(profile=%r, family=%r, case_title=%r) — nulificado",
                profile, family, case_title or "<sin titulo>",
            )
            new_contract = dict(contract)
            new_contract["target_event_rate"] = None
            warnings.append(
                "target_event_rate_wrong_scope: target_event_rate solo aplica a ml_ds + "
                "clasificación binaria; se ignoró para este caso."
            )
            return new_contract, warnings
        return contract, warnings

    # Dentro del gate, ausente.
    if raw_value is None:
        logger.warning(
            "[case_architect.target_event_rate] missing for ml_ds binary classification "
            "(case_title=%r) — el generador usará ~0.50 y Exhibit 2 quedará incoherente",
            case_title or "<sin titulo>",
        )
        warnings.append(
            "target_event_rate_missing: caso ml_ds de clasificación sin tasa de evento; "
            "el dataset usará prevalencia ~0.50 que puede no coincidir con Exhibit 2."
        )
        return contract, warnings

    # Dentro del gate, presente — bounds + finitud (la comparación excluye NaN/inf sin `math`).
    valid = (
        isinstance(raw_value, (int, float))
        and not isinstance(raw_value, bool)
        and _MIN_TARGET_EVENT_RATE <= float(raw_value) <= _MAX_TARGET_EVENT_RATE
    )
    if not valid:
        logger.warning(
            "[case_architect.target_event_rate] inválido (%r) fuera de [%.2f, %.2f] o no finito "
            "(case_title=%r) — nulificado",
            raw_value, _MIN_TARGET_EVENT_RATE, _MAX_TARGET_EVENT_RATE,
            case_title or "<sin titulo>",
        )
        new_contract = dict(contract)
        new_contract["target_event_rate"] = None
        warnings.append(
            "target_event_rate_invalid: tasa de evento fuera del rango plausible [1%, 50%]; "
            "se ignoró (el dataset usará prevalencia ~0.50)."
        )
        return new_contract, warnings

    # OK — normaliza a float si vino como int.
    if not isinstance(raw_value, float):
        new_contract = dict(contract)
        new_contract["target_event_rate"] = float(raw_value)
        return new_contract, warnings
    return contract, warnings


def _format_dataset_contract_block(contract: dict | None) -> str:
    """Renderiza el contrato como bloque legible para inyectar en SCHEMA_DESIGNER_PROMPT.

    Devuelve un string vacío informativo cuando no hay contrato — el prompt
    explica al LLM que en ese caso aplica las reglas heurísticas legacy.
    """
    if not contract:
        return "(sin contrato — aplica las reglas heurísticas de columnas obligatorias por perfil)"
    try:
        return json.dumps(contract, ensure_ascii=False, indent=2)
    except (TypeError, ValueError) as exc:
        # Defensivo: si el contrato persistido no es JSON-serializable, no rompemos
        # el grafo — degradamos al modo legacy con una advertencia visible.
        logger.warning("[contract] no serializable, modo legacy: %s", exc)
        return "(contrato corrupto — aplica las reglas heurísticas)"


def _format_data_gap_warnings_block(
    warnings: list[str] | tuple[str, ...] | None,
    *,
    empty_message: str,
) -> str:
    if not warnings:
        return empty_message
    return "\n".join(f"- {warning}" for warning in warnings)


def _validate_schema_against_contract(
    schema: dict, contract: dict | None
) -> tuple[list[str], list[str]]:
    """Compara columns del schema_designer contra el contrato del case_architect.

    Returns:
        (missing_required, leakage_warnings)
        - missing_required: nombres de target/feature del contrato ausentes en columns.
        - leakage_warnings: notas en español listas para inyectar en M2 EDA.

    No muta el schema. La inyección de columnas faltantes la hace
    `_augment_schema_with_contract`. Esta función es para reporting/observabilidad.
    """
    if not contract:
        return [], []

    schema_columns = {c.get("name", "") for c in schema.get("columns", [])}
    missing: list[str] = []

    target = contract.get("target_column") or {}
    target_name = (target.get("name") or "").strip()
    if target_name and target_name not in schema_columns:
        missing.append(
            f"target '{target_name}' (rol={target.get('role')}, dtype={target.get('dtype')}) "
            "no fue producido por schema_designer"
        )

    for feat in contract.get("feature_columns") or []:
        fname = (feat.get("name") or "").strip()
        if fname and fname not in schema_columns:
            missing.append(
                f"feature '{fname}' (dtype={feat.get('dtype')}) no fue producido por schema_designer"
            )

    leakage: list[str] = []
    for feat in contract.get("feature_columns") or []:
        fname = (feat.get("name") or "").strip()
        if not fname:
            continue
        offset = feat.get("temporal_offset_months")
        if feat.get("is_leakage_risk") or (isinstance(offset, int) and offset > 0):
            leakage.append(
                f"feature '{fname}' marcada con riesgo de leakage "
                f"(temporal_offset_months={offset}, is_leakage_risk={bool(feat.get('is_leakage_risk'))}). "
                "El notebook M3 debe excluirla del entrenamiento o tratarla como variable de auditoría."
            )

    return missing, leakage


def _augment_schema_with_contract(schema: dict, contract: dict | None) -> dict:
    """Inyecta de forma determinista las columnas del contrato ausentes en el schema.

    Cero tokens LLM. Idempotente. No muta el dict de entrada.
    Estrategia conservadora:
      - Si el contrato declara una columna que el schema NO tiene, se añade al final
        de `columns` con rangos por defecto seguros según dtype.
      - NUNCA renombra ni elimina columnas existentes — preserva el output del LLM.
      - NUNCA toca constraints (revenue_annual_total, etc.).
    """
    if not contract:
        return schema

    new_schema = dict(schema)
    columns = list(new_schema.get("columns", []))
    existing_names = {c.get("name", "") for c in columns}

    def _default_column(name: str, dtype: str, description: str, nullable: bool = False) -> dict:
        col_type = _CONTRACT_TYPE_TO_SCHEMA_TYPE.get(dtype, "float")
        col: dict = {
            "name": name,
            "type": col_type,
            "description": description or f"Columna inyectada por contrato ({name})",
            "range_min": None,
            "range_max": None,
            "nullable": nullable,
            "trend": None,
            "dependency": None,
        }
        if col_type == "float":
            col["range_min"] = 0.0
            col["range_max"] = 1.0
        elif col_type == "int":
            col["range_min"] = 0
            col["range_max"] = 100
        # "date" y "str" mantienen range_min/range_max=None (regla de
        # SCHEMA_DESIGNER_PROMPT para columnas no numéricas).
        return col

    target = contract.get("target_column") or {}
    target_name = (target.get("name") or "").strip()
    if target_name and target_name not in existing_names:
        if (
            target.get("role") == "classification_target"
            and target.get("dtype") == "int"
            and target_name.isidentifier()
        ):
            # Endurecimiento R2: un classification_target BINARIO (dtype int) inyectado DEBE ser
            # {0,1} con señal, NO un int [0,100] random — el notebook lo resuelve contract-first
            # (#348) y un target no-binario degrada el modeling entero. Lo inyectamos como
            # `categoria`: int [0,1] dependiente de un driver numérico existente. Un target
            # multiclase (dtype str) cae al `_default_column` (str categórico), sin tocar.
            # El guard `.isidentifier()` espeja `_safe_contract_target_name`/`_align`: un nombre
            # no-identificador NO debe producir una binaria inyectada (el notebook caería al
            # alias `categoria`, dejando esta binaria como duplicado con leakage).
            driver = _pick_numeric_driver(columns, exclude=target_name)
            columns.append({
                "name": target_name,
                "type": "int",
                "description": target.get(
                    "description", "Variable objetivo binaria declarada por contrato"
                ),
                "range_min": 0,
                "range_max": 1,
                "nullable": False,
                "trend": None,
                "dependency": (
                    {"depends_on": driver, "relationship": "linear", "noise_factor": 0.30}
                    if driver else None
                ),
            })
        else:
            columns.append(_default_column(
                name=target_name,
                dtype=target.get("dtype", "float"),
                description=target.get("description", "Variable objetivo declarada por contrato"),
            ))
        existing_names.add(target_name)
        logger.warning(
            "[contract.augment] target '%s' faltante — inyectado con defaults seguros",
            target_name,
        )

    for feat in contract.get("feature_columns") or []:
        fname = (feat.get("name") or "").strip()
        if not fname or fname in existing_names:
            continue
        columns.append(_default_column(
            name=fname,
            dtype=feat.get("dtype", "float"),
            description=feat.get("description", "Feature declarada por contrato"),
            nullable=False,
        ))
        existing_names.add(fname)
        logger.warning(
            "[contract.augment] feature '%s' faltante — inyectada con defaults seguros",
            fname,
        )

    new_schema["columns"] = columns
    return new_schema


def _pick_numeric_driver(columns: list[dict], *, exclude: str = "") -> str | None:
    """Elige una columna numérica existente como driver de un target binario inyectado.

    Prefiere ``churn_rate`` (el driver canónico del template ml_ds de clasificación); si no
    está, la primera columna ``int``/``float`` con rango declarado distinta del propio target.
    Devuelve ``None`` si no hay ninguna (→ el target se genera independiente, igual binario).
    """
    names = {c.get("name") for c in columns}
    if "churn_rate" in names and exclude != "churn_rate":
        return "churn_rate"
    for c in columns:
        if (
            c.get("name") != exclude
            and c.get("type") in ("int", "float")
            and c.get("range_min") is not None
            and c.get("range_max") is not None
        ):
            return c.get("name")
    return None


def _align_ml_ds_classification_target(
    schema_result: dict,
    contract: dict | None,
    *,
    profile: str,
    primary_family: str | None,
) -> dict:
    """Reconcilia la identidad del target binario para ml_ds + clasificación (R2).

    El architect nombra el target con un nombre de dominio (``churn_flag``) en el contrato,
    pero el schema fijo M2 construye la binaria como ``categoria``. Si divergen, el notebook
    (contract-first, #348) entrena el nombre del contrato: o el augmenter lo inyecta como
    ``int [0,100]`` random (no binario → degrada el modeling) o coexiste con ``categoria`` (otra
    binaria del MISMO driver → feature con leakage). Este normalizador garantiza UNA sola
    binaria, con el nombre del contrato, derivada del driver:

      1. renombra la binaria fija (``categoria``) al nombre del contrato si éste aún no es columna;
      2. elimina cualquier binaria duplicada derivada del MISMO driver que el target (anti-leakage).

    Determinista, 0 tokens, no muta el dict de entrada. NO toca business, otras familias, ni el
    caso sin un ``classification_target`` de contrato con nombre válido (→ ``categoria`` se
    preserva). Debe correr ANTES de ``_augment_schema_with_contract`` para que el augmenter vea
    el target ya presente y no inyecte la columna ``[0,100]``.
    """
    if profile != "ml_ds":
        return schema_result
    # ml_ds: None family → "clasificacion" (espeja `_effective_family` de schema_designer,
    # graph.py ~3494). Sin esto, un job ml_ds con algoritmos vacíos (primary_family=None)
    # construye el template `categoria` pero NO se reconcilia aquí → el augmenter inyecta un
    # duplicado del mismo driver (el leakage que esta función previene).
    if (primary_family or "clasificacion") != "clasificacion":
        return schema_result
    contract_target = _safe_contract_target_name(contract)
    if not contract_target:
        return schema_result
    tgt = (contract or {}).get("target_column") or {}
    # Solo reconciliamos un target BINARIO (dtype int). Un classification_target multiclase
    # (dtype str) NO debe heredar la binaria `categoria` — se deja intacto.
    if tgt.get("role") != "classification_target" or tgt.get("dtype") != "int":
        return schema_result

    columns = [dict(c) for c in schema_result.get("columns", [])]
    binary_targets = [
        c for c in columns
        if _is_declared_binary_int(c) and isinstance(c.get("dependency"), dict)
    ]
    if not binary_targets:
        return schema_result  # nada que reconciliar; el augmenter endurecido es la red.

    # Elige la binaria objetivo de forma orden-robusta (no asumas binary_targets[0]): la que ya
    # lleva el nombre del contrato → la canónica `categoria` → la primera.
    target_col = (
        next((c for c in binary_targets if c.get("name") == contract_target), None)
        or next((c for c in binary_targets if c.get("name") == "categoria"), None)
        or binary_targets[0]
    )
    if target_col.get("name") != contract_target:
        # Renombra la binaria al nombre del contrato — SOLO si ese nombre no colisiona con otra
        # columna existente (evitar dos columnas homónimas → corrupción del df al ensamblar).
        if contract_target in {c.get("name") for c in columns}:
            logger.warning(
                "[_align_ml_ds_classification_target] nombre de contrato '%s' ya existe como "
                "columna no-objetivo — se omite el rename para no duplicar nombre.",
                contract_target,
            )
            return schema_result
        old_name = target_col.get("name")
        target_col["name"] = contract_target
        logger.info(
            "[_align_ml_ds_classification_target] target binario '%s' → '%s' (nombre del contrato)",
            old_name, contract_target,
        )
    keep_name = target_col.get("name")
    keep_driver = (target_col.get("dependency") or {}).get("depends_on")
    # anti-leakage: descarta otras binarias {0,1} derivadas del MISMO driver que el target.
    new_columns = [
        c for c in columns
        if not (
            c.get("name") != keep_name
            and _is_declared_binary_int(c)
            and isinstance(c.get("dependency"), dict)
            and c["dependency"].get("depends_on") == keep_driver
        )
    ]
    if len(new_columns) != len(columns):
        logger.info(
            "[_align_ml_ds_classification_target] binaria duplicada del driver '%s' eliminada "
            "(anti-leakage) — target único: '%s'", keep_driver, keep_name,
        )
    new_schema = dict(schema_result)
    new_schema["columns"] = new_columns
    return new_schema


# ─────────────────────────────────────────────────────────
# HELPER — Spine determinista business + clasificación (Issue #301)
# ─────────────────────────────────────────────────────────
#
#   business + clasificacion ?
#     ├─ contrato con target_column.role == "classification_target"
#     │     → target binario de dominio + driver de dominio + features del contrato
#     │       (set financiero mínimo; churn/retention SOLO si el dilema es de retención)
#     ├─ sin contrato / target continuo
#     │     → síntesis determinista: target_event_flag {0,1} + 1 driver + aviso honesto
#     └─ dilema de retención → conserva el template churn/SaaS  (NO-REGRESIÓN)
#
# 0 tokens LLM, business-only. NO toca ml_ds (usa prompts por familia + `categoria`).

# Columnas del template churn/SaaS que SOLO pertenecen a un dilema de retención.
# En un caso business+clasificación NO-retención se eliminan para que el dataset
# hable del dominio del caso (logística, fraude, crédito…) en vez de churn.
_CHURN_TEMPLATE_COLUMNS: frozenset[str] = frozenset({
    "churn_rate", "nps", "retention_m1", "retention_m3", "retention_m6", "retention_m12",
})

# Columnas SaaS no-churn del template fijo ml_ds de clasificación (cols 11–17 del contrato de
# 18 columnas en M2_clasificacion/dataset.py y de `_build_fallback_schema`). NO son churn por
# nombre, pero pertenecen al mismo escenario SaaS: dos de ellas (`payment_failures`→churn_rate,
# `support_tickets_count`→nps) quedarían HUÉRFANAS si solo se quitan las 6 `_CHURN_TEMPLATE_COLUMNS`
# (→ ruido vía `_generate_dataset_from_schema`). El sibling ml_ds de-churn (Issue #382) las elimina
# JUNTO con el bloque churn en un caso NO-retención, EXCEPTO las declaradas por el contrato del caso.
_MLDS_SAAS_TEMPLATE_COLUMNS: frozenset[str] = frozenset({
    "customer_ltv", "engagement_score", "days_since_last_login", "support_tickets_count",
    "plan_tier", "payment_failures", "monthly_usage_pct",
})


def _is_retention_target_name(name: str, role: str = "") -> bool:
    """True si el target pertenece a la familia retención/churn (por nombre o rol).

    Delega el match de nombre en `retention_tokens.is_retention_match` (vocab único +
    denylist de gobernanza: `data_retention_days`/`employee_loyalty_index` NO son churn,
    `customer_abandon_flag` SÍ). Conserva la rama de rol `forecasting_target`.
    """
    if is_retention_match(name):
        return True
    n = (name or "").lower()
    return (role or "").strip().lower() == "forecasting_target" and "retention" in n


def _select_driver_feature(
    contract: dict | None, *, target_name: str | None = None
) -> tuple[str, dict | None]:
    """Elige la feature de dominio que el target binario usará como driver (#298 absorbido).

    Regla (7A): primera ``feature_columns`` con ``is_leakage_risk=False`` y dtype numérico
    (un driver de leakage haría que el modelo 'haga trampa'). Si no hay ninguna usable,
    sintetiza un driver numérico neutro para que exista UNA señal real GENERADA en los
    datos (no afirmada en prosa). El chart conserva el aviso 'sin driver fuerte' si la
    señal resultante igual es débil. ``target_name`` (si se pasa) se excluye para que el
    target nunca dependa de sí mismo (contrato malformado que lista el target como feature).

    Devuelve ``(driver_name, synth_column_or_None)``.
    """
    for feat in (contract or {}).get("feature_columns") or []:
        if feat.get("is_leakage_risk"):
            continue
        fname = (feat.get("name") or "").strip()
        if target_name and fname == target_name:
            continue  # L-6: el target no puede ser su propio driver
        if feat.get("dtype") in ("int", "float") and fname:
            return fname, None
    synth = {
        "name": "domain_driver_score",
        "type": "float",
        "description": "Driver de dominio sintetizado correlado con el objetivo del caso",
        "range_min": 0.0,
        "range_max": 1.0,
        "nullable": False,
        "trend": None,
        "dependency": None,
    }
    return "domain_driver_score", synth


def _binary_target_column(
    name: str, *, depends_on: str, description: str, min_signal_strength: float = 0.15
) -> dict:
    """Construye una columna target binaria {0,1} con señal correlada a ``depends_on``.

    Mismo patrón estructural que la columna ``categoria`` de ml_ds (int, range[0,1],
    dependency lineal), extraído para no duplicar la definición (6A). ``noise_factor``
    se deriva de ``min_signal_strength``: a mayor señal requerida, menor ruido (mayor
    correlación). La ``description`` incluye 'objetivo' para que
    ``_identify_target_variable`` la capture aun sin metadata (belt-and-suspenders).
    """
    noise_factor = max(0.08, min(0.30, 0.30 - float(min_signal_strength)))
    return {
        "name": name,
        "type": "int",
        "description": f"Variable objetivo binaria del caso (0/1): {description}".strip(),
        "range_min": 0,
        "range_max": 1,
        "nullable": False,
        "trend": None,
        # Issue #301 PR2a — marca el target de dominio resuelto por el spine. El guard
        # anti-degeneración (_ensure_both_classes) honra ESTA bandera en vez de asumir que
        # cualquier binaria {0,1} dependiente es el target (rompía con varias binarias).
        "is_domain_target": True,
        "dependency": {
            "depends_on": depends_on,
            "relationship": "linear",
            "noise_factor": round(noise_factor, 3),
        },
    }


def _enforce_business_classification_schema(
    schema: dict, contract: dict | None, *, profile: str, primary_family: str | None
) -> tuple[dict, list[str], str | None]:
    """Garantiza un dataset coherente con el dilema para business + clasificación (#301).

    Determinista, 0 tokens LLM, business-only (gate ``profile == "business"`` +
    ``primary_family == "clasificacion"``). NO toca el dict de entrada ni ml_ds.
    Devuelve ``(schema, notes, target_name)``: ``notes`` alimenta ``data_gap_warnings`` y
    ``target_name`` es el nombre del target binario garantizado (``None`` fuera del gate) —
    schema_designer lo propaga al contrato para que la selección downstream lo elija
    (Issue #301 H-1).
    """
    notes: list[str] = []
    if profile != "business" or primary_family != "clasificacion":
        return schema, notes, None

    contract = contract or {}
    target_spec = contract.get("target_column") or {}
    role = (target_spec.get("role") or "").strip().lower()
    cname = (target_spec.get("name") or "").strip()
    cdesc = (target_spec.get("description") or "").strip()
    cdtype = (target_spec.get("dtype") or "").strip().lower()

    if role == "classification_target" and cname:
        target_name = cname
        if cdtype and cdtype != "int":
            # L-5 — el dtype declarado se coerciona a binario {0,1}; avisar al docente.
            notes.append(
                f"target '{cname}' declarado dtype='{cdtype}' coercido a binario {{0,1}} (int) "
                "para clasificación business."
            )
    else:
        # 3A — síntesis determinista honesta cuando no hay contrato de clasificación.
        target_name = "target_event_flag"
        notes.append(
            "target sintetizado sin contrato de dominio (business+clasificación): se generó "
            "un objetivo binario y un driver para mantener la coherencia M1↔M2; revisar que "
            "refleje el dilema del caso."
        )

    is_retention = _is_retention_target_name(target_name, role)
    min_signal = float(contract.get("min_signal_strength") or 0.15)
    driver_name, synth_driver = _select_driver_feature(contract, target_name=target_name)

    new_schema = dict(schema)
    columns = [dict(c) for c in new_schema.get("columns", [])]

    # 1. En dilemas NO-retención, eliminar el template churn/SaaS (deja financiero mínimo).
    if not is_retention:
        columns = [c for c in columns if c.get("name") not in _CHURN_TEMPLATE_COLUMNS]

    existing = {c.get("name", "") for c in columns}

    # 2. Asegurar el driver (synth solo si no hay feature numérica usable en el contrato).
    if synth_driver is not None and driver_name not in existing:
        columns.append(synth_driver)
        existing.add(driver_name)

    # 3. Construir/forzar el target binario (override aunque exista, p. ej. tras augment,
    #    que lo habría inyectado con range[0,100] en vez de {0,1}).
    binary_target = _binary_target_column(
        target_name,
        depends_on=driver_name,
        description=cdesc or "evento objetivo del dilema",
        min_signal_strength=min_signal,
    )
    if target_name in existing:
        columns = [binary_target if c.get("name") == target_name else c for c in columns]
    else:
        columns.append(binary_target)
        existing.add(target_name)

    # 4. Cobertura de domain_features_required (8A): añade una columna por categoría no
    #    cubierta (L-2: match EXACTO de nombre — `in` por substring saltaba una categoría
    #    'rate' por ser substring de 'churn_rate' y la dejaba sin cubrir).
    for cat in contract.get("domain_features_required") or []:
        cat_name = str(cat).strip()
        if not cat_name or cat_name in existing:
            continue
        columns.append({
            "name": cat_name,
            "type": "float",
            "description": f"Feature de dominio requerida por el contrato ({cat_name})",
            "range_min": 0.0,
            "range_max": 1.0,
            "nullable": False,
            "trend": None,
            "dependency": None,
        })
        existing.add(cat_name)

    new_schema["columns"] = columns
    return new_schema, notes, target_name


def _enforce_mlds_classification_schema(
    schema: dict,
    contract: dict | None,
    *,
    profile: str,
    primary_family: str | None,
    enabled: bool = True,
) -> dict:
    """De-churna la SEÑAL del target para ml_ds + clasificación NO-retención (Issue #382).

    SIBLING determinista de ``_enforce_business_classification_schema`` — NO generalizar esa
    función (``test_enforce_noop_for_ml_ds`` exige que siga siendo identidad para ml_ds). Corre
    DESPUÉS de ``_align`` + ``_augment`` + el spine business en ``schema_designer``, sobre el
    schema ya ensamblado. 0 tokens LLM, PURO copy-on-write (no muta el dict de entrada) →
    determinismo del seed (``_generate_dataset_from_schema``) + thread-safety bajo jobs
    concurrentes.

    Para un target binario de DOMINIO (no churn/retención) re-apunta su señal a un driver de
    dominio y elimina el template churn/SaaS, de modo que un caso de fraude/mora/aprobación
    aprenda del dominio y no de ``churn_rate``. El camino churn/retención salta el sibling
    completo → schema BYTE-IDÉNTICO (gate ``_is_retention_target_name``). Reusa los helpers del
    spine #301 (``_select_driver_feature``, ``_CHURN_TEMPLATE_COLUMNS``); no reescribe el
    mecanismo de señal — solo cambia de qué columna DERIVA el target.

    Gate (fuera de él → mismo objeto, byte-idéntico):
      ``enabled`` (kill-switch ``MLDS_DECHURN_SIGNAL``) AND ``profile=="ml_ds"`` AND
      ``(primary_family or "clasificacion")=="clasificacion"`` AND el target del contrato es
      binario (``role==classification_target`` y ``dtype=="int"``) AND
      ``NOT _is_retention_target_name(target_name)``.
    """
    if not enabled or profile != "ml_ds":
        return schema
    # ml_ds: None family → "clasificacion" (espeja `_align`/`_effective_family`); NO el
    # early-return business (`primary_family != "clasificacion"`), que mataría un job ml_ds con
    # algoritmos vacíos (primary_family=None) que igual construye el template `categoria`.
    if (primary_family or "clasificacion") != "clasificacion":
        return schema
    tgt = (contract or {}).get("target_column") or {}
    if tgt.get("role") != "classification_target" or tgt.get("dtype") != "int":
        return schema
    contract_target = _safe_contract_target_name(contract)
    if not contract_target:
        return schema
    # LÍNEA ROJA: churn/retención conserva el template intacto (byte-idéntico).
    if _is_retention_target_name(contract_target):
        return schema

    columns = [dict(c) for c in schema.get("columns", [])]
    binary_targets = [
        c for c in columns
        if _is_declared_binary_int(c) and isinstance(c.get("dependency"), dict)
    ]
    if not binary_targets:
        return schema  # sin binaria objetivo que de-churnar (el augmenter endurecido es la red).

    # Resuelve la binaria objetivo orden-robusta (igual que `_align`): la que ya lleva el nombre
    # del contrato → la canónica `categoria` → la primera.
    target_col = (
        next((c for c in binary_targets if c.get("name") == contract_target), None)
        or next((c for c in binary_targets if c.get("name") == "categoria"), None)
        or binary_targets[0]
    )
    # Guard de colisión: si `_align` saltó el rename (el nombre del contrato YA existe como una
    # columna NO-objetivo, graph.py ~3355-3361), el notebook contract-first entrenaría ESA
    # columna, no la binaria. Re-apuntar `categoria` a ciegas ampliaría la incoherencia. NO-OP +
    # warning observable (defecto pre-existente de `_align`, fuera del alcance de #382).
    if (
        target_col.get("name") != contract_target
        and contract_target in {c.get("name") for c in columns}
    ):
        logger.warning(
            "[_enforce_mlds_classification_schema] colisión de nombre: target del contrato '%s' "
            "existe como columna no-objetivo; se omite el de-churn (defecto pre-existente de "
            "_align). Binaria objetivo resuelta: '%s'.",
            contract_target, target_col.get("name"),
            extra={
                "node": "schema_designer", "target_name": contract_target,
                "resolved_binary": target_col.get("name"), "reason": "name_collision",
            },
        )
        return schema

    keep_name = target_col.get("name")
    driver_name, synth_driver = _select_driver_feature(contract, target_name=keep_name)

    # NUNCA elimines una columna declarada por el contrato (aunque su nombre coincida con el
    # template), ni el target ni el driver.
    contract_features = {
        (f.get("name") or "").strip()
        for f in (contract or {}).get("feature_columns") or []
    }
    protected = contract_features | {keep_name, driver_name}
    strip_set = (_CHURN_TEMPLATE_COLUMNS | _MLDS_SAAS_TEMPLATE_COLUMNS) - protected
    stripped = [c.get("name") for c in columns if c.get("name") in strip_set]
    columns = [c for c in columns if c.get("name") not in strip_set]

    # Defensa en profundidad (RT1): tras el strip el driver DEBE existir como columna, o el target
    # re-apuntado quedaría huérfano (padre ausente → `_generate_independent_values` → AUC ~0.5). En
    # el pipeline cableado `_augment_schema_with_contract` ya inyectó las features del contrato ANTES
    # de este nodo, pero el sibling NO debe depender de ese orden: si el driver elegido (nombre de
    # feature del contrato) no quedó presente, garantiza un driver de dominio sintetizado y reapunta.
    present = {c.get("name") for c in columns}
    if driver_name not in present:
        if synth_driver is None:
            synth_driver = {
                "name": "domain_driver_score",
                "type": "float",
                "description": "Driver de dominio sintetizado correlado con el objetivo del caso",
                "range_min": 0.0,
                "range_max": 1.0,
                "nullable": False,
                "trend": None,
                "dependency": None,
            }
        driver_name = synth_driver["name"]
        if driver_name not in present:
            columns.append(synth_driver)

    # Re-apunta la señal del target al driver de dominio + márcalo (anti-degeneración no-rate:
    # el `is_domain_target` activa `_ensure_both_classes` ampliado a ml_ds). noise_factor con la
    # MISMA fórmula que `_binary_target_column` (#301) para señal consistente.
    min_signal = float((contract or {}).get("min_signal_strength") or 0.15)
    noise_factor = round(max(0.08, min(0.30, 0.30 - min_signal)), 3)
    for c in columns:
        if c.get("name") == keep_name:
            c["dependency"] = {
                "depends_on": driver_name,
                "relationship": "linear",
                "noise_factor": noise_factor,
            }
            c["is_domain_target"] = True

    # Reparación de dependencias colgantes: cualquier columna restante cuyo padre fue eliminado
    # por el strip genera independiente (evita huérfanos → ruido con warning de runtime). El
    # target queda a salvo: su nuevo `depends_on` es `driver_name`, que está protegido.
    remaining = {c.get("name") for c in columns}
    for c in columns:
        dep = c.get("dependency")
        if isinstance(dep, dict) and dep.get("depends_on") not in remaining:
            c["dependency"] = None

    # Observabilidad LOG-ONLY (no teacher-facing; precedente #336). Best-effort por estar dentro
    # de un nodo best-effort; un fallo de logging nunca debe propagarse.
    logger.warning(
        "[_enforce_mlds_classification_schema] de-churn ml_ds+clf: target '%s' ← driver de "
        "dominio '%s'; columnas removidas: %s",
        keep_name, driver_name, stripped,
        extra={
            "node": "schema_designer", "family": "clasificacion", "target_name": keep_name,
            "driver_chosen": driver_name, "columns_stripped": stripped, "is_retention": False,
        },
    )

    new_schema = dict(schema)
    new_schema["columns"] = columns
    return new_schema


def _contract_with_enforced_target(contract: dict | None, target_name: str | None) -> dict | None:
    """Reescribe ``target_column`` del contrato al target binario que el spine garantizó.

    Issue #301 H-1: ``_build_metadata``/``_identify_target_variable`` eligen el target vía
    ``contract.target_column.name``. Cuando el architect emitió un target CONTINUO
    (p. ej. ``margin_pct``, role regresión) o ninguno, el spine sintetiza un binario, pero
    el contrato seguía nombrando la columna continua → la selección downstream graficaba el
    target equivocado (el síntoma de #301 desplazado). Propagar el target binario al
    contrato cierra el bucle de forma determinista. Devuelve ``None`` si no aplica.
    """
    if not target_name:
        return None
    updated = dict(contract or {})
    tcol = dict(updated.get("target_column") or {})
    prev_desc = (tcol.get("description") or "").strip()
    tcol.update({"name": target_name, "role": "classification_target", "dtype": "int"})
    if not prev_desc:
        tcol["description"] = "Variable objetivo binaria del caso (0/1)"
    updated["target_column"] = tcol
    return updated


# ─────────────────────────────────────────────────────────
# NODO 1 — SCHEMA DESIGNER (Pro, thinking activo, output pequeño)
# ─────────────────────────────────────────────────────────

def schema_designer(state: ADAMState, config: RunnableConfig) -> dict:
    """NODO 1 del pipeline de dataset. Diseña schema y constraints.
    Modelo Pro vía Configuration (overridable por-nodo), thinking_level="medium".
    Dos candidatos con .with_fallbacks() para resiliencia ante 503.
    Responsabilidad ÚNICA: diseñar. NO genera filas.
    """
    cfg = Configuration.from_runnable_config(config)
    profile = state.get("studentProfile", "business")

    # Resolve primary family BEFORE max_rows — both max_rows and the fallback schema
    # branch by family. _detect_algorithm_families is kept for the prompt vocabulary
    # string; _resolve_primary_family is the authoritative single-family resolver.
    algoritmos_raw = state.get("algoritmos", [])
    familias_detectadas = _detect_algorithm_families(algoritmos_raw) if algoritmos_raw else []
    ml_required_families = (
        ", ".join(familias_detectadas) if familias_detectadas else "clasificacion"
    )
    primary_family, _legacy_warn_schema = _resolve_primary_family(algoritmos_raw)

    # Effective family drives max_rows, prompt dispatch, and fallback schema branch.
    #
    # ml_ds: use the resolved family when available; fall back to "clasificacion" to
    # mirror _prepare_m3_notebook_generation_context() (line ~4323), which makes the
    # same explicit fallback so M3 and schema_designer always agree on the family.
    # Without this alignment a None-family ml_ds job emits a non-classification schema
    # (no 'categoria', 200 rows, generic prompt) while M3 generates a classification
    # notebook — silent AUC collapse.
    #
    # business: always "" → generic schema prompt, regardless of primary_family.
    # The classification and future family-specific prompts contain ml_ds-only sections
    # (18-col contract, GridSearchCV row counts) that should never reach business cases.
    # The generic prompt seeds the financial base; for business+clasificacion the
    # deterministic spine `_enforce_business_classification_schema` (Issue #301) then
    # OWNS the target/feature columns (binary domain target + driver), replacing the
    # rigid churn template when the dilemma is not about retention. `primary_family`
    # (the resolved family, not "") gates that spine.
    _effective_family = (primary_family or "clasificacion") if profile == "ml_ds" else ""

    # ml_ds+clasificacion: 600 filas (Issue #240 cascade: 600 ≤ 2000 → full GridSearchCV).
    # ml_ds+otras familias: 200 filas — el GridSearchCV size cascade es exclusivo del
    # notebook de clasificacion; regresion/clustering no necesitan 600 filas.
    # business: 100 (midpoint de 80-120; el LLM elige n_rows estrictamente entre 80-120).
    _is_clasificacion_ml = profile == "ml_ds" and _effective_family == "clasificacion"
    max_rows = 600 if _is_clasificacion_ml else (200 if profile == "ml_ds" else 100)

    _schema_prompt = SCHEMA_DESIGNER_PROMPT_BY_FAMILY.get(
        _effective_family, SCHEMA_DESIGNER_PROMPT
    )
    # Issue #452 kill-switch — when MLDS_CLUSTERING_STRUCTURE is off, the clustering case reverts
    # to the generic schema prompt (and the generic ml_ds fallback) byte-identically.
    if _effective_family == "clustering" and not settings.mlds_clustering_structure:
        _schema_prompt = SCHEMA_DESIGNER_PROMPT

    context = _build_base_context(state)
    context.update({
        "titulo": state.get("titulo", ""),
        "financial_data": state.get("doc1_anexo_financiero", ""),
        "operational_data": state.get("doc1_anexo_operativo", ""),
        "max_rows": max_rows,
        "ml_required_families": ml_required_families,
        # Issue #225 — inyecta contrato dilema↔dataset emitido por case_architect.
        # Si es None (perfil business legado o architect no lo emitió), el bloque
        # contiene un mensaje que activa las reglas heurísticas en el LLM.
        "dataset_contract_block": _format_dataset_contract_block(
            state.get("dataset_schema_required")
        ),
    })
    prompt = _schema_prompt.format(**context)

    # Cadena de fallback resiliente alineada con el patrón del case_architect (M1):
    #   1) Pro thinking_level="medium" — primario (mantiene thinking; subir a "high"
    #      arriesga truncar el JSON estructurado de 14 columnas por consumo de
    #      reasoning interno).
    #   2) Pro thinking_level="low"    — fallback transitorio sin degradar de modelo.
    #   3) Flash                       — red de seguridad final ante incidente global
    #      del Pro (sin response_mime_type estructurado, parser tolerante downstream).
    # max_output_tokens=24576 da margen extra para el JSON (~5-6k tokens) sobre el
    # reasoning de "medium" (~3-8k), reduciendo riesgo de truncamiento.
    _common_kwargs = dict(
        model=resolve_node_model(cfg, NODE_SCHEMA_DESIGNER, cfg.architect_model),
        temperature=0.2,
        max_retries=2,
        max_output_tokens=24576,
        api_key=os.getenv("GEMINI_API_KEY"),
        rate_limiter=_rate_limiter,
        response_mime_type="application/json",
    )
    primary = ChatGoogleGenerativeAI(thinking_level="medium", **_common_kwargs)
    pro_low_fallback = ChatGoogleGenerativeAI(thinking_level="low", **_common_kwargs)
    flash_fallback = ChatGoogleGenerativeAI(
        model="gemini-3-flash-preview",
        temperature=0.2,
        max_retries=2,
        max_output_tokens=24576,
        api_key=os.getenv("GEMINI_API_KEY"),
        rate_limiter=_rate_limiter,
    )
    candidates = [primary.with_fallbacks([pro_low_fallback, flash_fallback])]

    for i, llm in enumerate(candidates):
        # Solo 1 candidato compuesto; el fallback chain (Pro-medium → Pro-low → Flash)
        # se resuelve internamente vía .with_fallbacks().
        model_label = "pro-medium-chain" if i == 0 else f"candidate-{i}"
        try:
            response = llm.invoke(prompt)
            raw = _extract_text(response)
            if not raw or not raw.strip():
                print(f"[schema_designer] {model_label}: respuesta vacía, probando siguiente")
                continue

            schema_dict = _extract_json_from_llm_response(raw)

            if not schema_dict:
                snippet = raw[:200].replace('\n', ' ')
                logger.warning(
                    "[schema_designer] %s: no se pudo extraer JSON válido. "
                    "Primeros 200 chars del raw: %s", model_label, snippet
                )
                continue

            validated = DatasetSchema(**schema_dict)
            schema_result = validated.model_dump()
            schema_result = _normalize_ml_ds_columns(schema_result, profile)

            # Fix C-06: Guard de revenue — si el LLM escribe el valor en millones
            # (ej: 150) en vez de absoluto (150_000_000), el scaler downstream
            # produce valores astronómicamente erróneos sin detección.
            # Heurística: revenue < 100K en un caso empresarial es casi siempre un error
            # de unidades (millones, miles de millones, etc.).
            rev = schema_result.get("constraints", {}).get("revenue_annual_total", 0)
            if rev and 0 < rev < 100_000:
                logger.warning(
                    "[schema_designer] revenue_annual_total=%s sospechosamente bajo "
                    "(probablemente en millones) — aplicando ×1,000,000. "
                    "Si el caso es una micro-empresa, ajustar threshold.", rev
                )
                schema_result.setdefault("constraints", {})["revenue_annual_total"] = rev * 1_000_000

            print(
                f"[schema_designer] OK ({model_label}) — {len(validated.columns)} columnas, "
                f"{validated.n_rows} filas, granularidad={validated.time_granularity}"
            )
            # Issue #225 — Aplica contrato del case_architect:
            #   1) augmenter Python puro: añade columnas faltantes con defaults seguros
            #      (idempotente, cero tokens, evita un retry LLM costoso).
            #   2) validator: registra residuales (vacío post-augment) + leakage flags
            #      como data_gap_warnings que M2 EDA y M3 notebook leerán.
            contract = state.get("dataset_schema_required")
            # R2 — reconcilia la identidad del target binario ANTES del augment (ml_ds+clf),
            # para que el augmenter no inyecte un target [0,100] random y no quede una binaria
            # duplicada con leakage. No-op fuera del gate.
            schema_result = _align_ml_ds_classification_target(
                schema_result, contract, profile=profile, primary_family=primary_family
            )
            schema_result = _augment_schema_with_contract(schema_result, contract)
            # Issue #301 — spine determinista business+clasificación: garantiza un target
            # binario de dominio + driver (no el template fijo de churn). Business-only;
            # no toca ml_ds. Corre tras el augment para sobrescribir el target int genérico.
            schema_result, biz_notes, biz_target = _enforce_business_classification_schema(
                schema_result, contract, profile=profile, primary_family=primary_family
            )
            # Issue #382 — sibling determinista ml_ds+clasificación: de-churna la SEÑAL del target
            # (re-apunta a un driver de DOMINIO + elimina el template churn/SaaS) en casos
            # NO-retención. Corre tras el spine business; no-op byte-idéntico para churn/retención,
            # business y otras familias. Kill-switch MLDS_DECHURN_SIGNAL (default true).
            schema_result = _enforce_mlds_classification_schema(
                schema_result, contract, profile=profile, primary_family=primary_family,
                enabled=settings.mlds_dechurn_signal,
            )
            missing, leakage = _validate_schema_against_contract(schema_result, contract)
            # Issue #228 — preserva semillas de data_gap_warnings emitidas por
            # case_architect (ej: target_semantic_mismatch). LangGraph reemplaza
            # el canal en cada return, así que merge explícito.
            warnings_payload: list[str] = list(state.get("data_gap_warnings") or [])
            if missing:
                warnings_payload.extend(missing)
            if leakage:
                warnings_payload.extend(leakage)
            if biz_notes:
                warnings_payload.extend(biz_notes)
            node_out: dict[str, Any] = {
                "dataset_schema": schema_result,
                "data_gap_warnings": warnings_payload,
            }
            # Issue #301 H-1 — si el spine sintetizó/forzó el target binario, propágalo al
            # contrato para que _build_metadata/_identify_target_variable lo elijan (y no un
            # target de contrato continuo). Solo cuando realmente cambia algo.
            updated_contract = _contract_with_enforced_target(contract, biz_target)
            if updated_contract is not None and updated_contract != (contract or {}):
                node_out["dataset_schema_required"] = updated_contract
            return node_out
        except (ValidationError, Exception) as e:
            logger.error("[schema_designer] %s ERROR: %s", model_label, e, exc_info=True)

    print("[schema_designer] todos los intentos fallaron — usando fallback schema")
    fallback_schema = _build_fallback_schema(
        state, max_rows, profile, primary_family=_effective_family,
        clustering_structure_enabled=settings.mlds_clustering_structure,
    )
    # Issue #225 — incluso en fallback respetamos el contrato del architect.
    contract = state.get("dataset_schema_required")
    # R2 — misma reconciliación de identidad del target que en el camino feliz.
    fallback_schema = _align_ml_ds_classification_target(
        fallback_schema, contract, profile=profile, primary_family=primary_family
    )
    fallback_schema = _augment_schema_with_contract(fallback_schema, contract)
    # Issue #301 — el spine determinista también aplica en fallback (red de seguridad).
    fallback_schema, biz_notes, biz_target = _enforce_business_classification_schema(
        fallback_schema, contract, profile=profile, primary_family=primary_family
    )
    # Issue #382 — mismo de-churn ml_ds+clf que en el camino feliz (red de seguridad aguas
    # abajo del fallback; NO se toca `_build_fallback_schema`).
    fallback_schema = _enforce_mlds_classification_schema(
        fallback_schema, contract, profile=profile, primary_family=primary_family,
        enabled=settings.mlds_dechurn_signal,
    )
    missing, leakage = _validate_schema_against_contract(fallback_schema, contract)
    # Issue #228 — preserva warnings sembrados por case_architect.
    warnings_payload = list(state.get("data_gap_warnings") or [])
    if missing:
        warnings_payload.extend(missing)
    if leakage:
        warnings_payload.extend(leakage)
    if biz_notes:
        warnings_payload.extend(biz_notes)
    node_out = {
        "dataset_schema": fallback_schema,
        "data_gap_warnings": warnings_payload,
    }
    # Issue #301 H-1 — propaga el target binario garantizado al contrato (ver call-site happy).
    updated_contract = _contract_with_enforced_target(contract, biz_target)
    if updated_contract is not None and updated_contract != (contract or {}):
        node_out["dataset_schema_required"] = updated_contract
    return node_out


# ─────────────────────────────────────────────────────────
# HELPER — _generate_time_periods
# ─────────────────────────────────────────────────────────

def _generate_time_periods(n_rows: int, granularity: str) -> list:
    """Genera etiquetas de período temporal."""
    if granularity == "monthly":
        periods = []
        start_year = 2023
        for i in range(n_rows):
            year = start_year + (i // 12)
            month = (i % 12) + 1
            periods.append(f"{year}-{month:02d}")
        return periods
    elif granularity == "quarterly":
        periods = []
        start_year = 2023
        for i in range(n_rows):
            year = start_year + (i // 4)
            quarter = (i % 4) + 1
            periods.append(f"{year}-Q{quarter}")
        return periods
    elif granularity == "annual":
        return [str(2020 + i) for i in range(n_rows)]
    elif granularity == "daily":
        start = datetime(2024, 1, 1)
        return [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n_rows)]
    else:
        return [f"P{i+1}" for i in range(n_rows)]


# ─────────────────────────────────────────────────────────
# HELPER — _generate_independent_values
# ─────────────────────────────────────────────────────────

def _generate_independent_values(
    col: dict,
    low: float,
    high: float,
    n_rows: int,
    rng: "np.random.Generator",
) -> "np.ndarray":
    """Genera valores para una columna sin dependencias externas.

    Respeta range_min/max, trend y semántica del nombre de la columna.
    Los datos son sintéticos pero coherentes con el caso (case-consistent):
    - Negativas semánticas (churn, error, defect): distribución sesgada al extremo bajo
    - Positivas semánticas (nps, satisfaction, retention): distribución sesgada al alto
    - Neutrales: distribución centrada en la media del rango
    Usado como fallback cuando una dependencia no puede resolverse (padre no numérico
    o padre no encontrado) para nunca crashear ni generar datos puramente aleatorios.
    """
    import numpy as np

    name_lower = col.get("name", "").lower()
    trend = col.get("trend")

    if trend == "up":
        base = np.linspace(low, high, n_rows)
    elif trend == "down":
        base = np.linspace(high, low, n_rows)
    else:
        if any(kw in name_lower for kw in ("churn", "error", "defect", "complaint", "bug", "incident")):
            center = low + (high - low) * 0.25
        elif any(kw in name_lower for kw in ("nps", "satisfaction", "adoption", "retention", "engagement")):
            center = low + (high - low) * 0.70
        else:
            center = (low + high) / 2
        base = np.full(n_rows, center)

    return np.clip(base + rng.normal(0, (high - low) * 0.10, n_rows), low, high)


# Fracción mínima de clase minoritaria que inyecta el guard cuando un target binario
# degenera a una sola clase (Issue #301). 15% deja una clase aprendible por LR sin
# sobre-balancear (no es un balanceador, es una red de seguridad anti-degeneración).
_BINARY_MIN_MINORITY_FRACTION = 0.15


def _ensure_both_classes(values: "np.ndarray") -> "np.ndarray":
    """Garantiza que una serie continua en [0,1] redondee a AMBAS clases {0,1}.

        round(values) tiene 2 clases ?  ── sí ──►  passthrough (sin tocar la señal)
                       └─ no (degenerado) ──►  voltea las k filas más cercanas a 0.5
                                               hacia la clase ausente (mínimo daño)

    Determinista (orden estable por distancia a 0.5). Red de seguridad business-only
    (Issue #301): un target de una sola clase deja corr indefinida y una LR sin sentido,
    y se enviaría SILENCIOSAMENTE. Opera sobre los valores continuos PRE-redondeo para
    elegir las filas más ambiguas. Si tras forzar el balance la señal queda débil, el
    chart conserva el aviso 'sin driver fuerte' (honestidad #296/#298).
    """
    import numpy as np

    if values.size == 0:
        return values
    rounded = np.rint(values)
    if np.unique(rounded).size >= 2:
        return values
    only_class = float(rounded.flat[0])
    k = max(1, int(round(_BINARY_MIN_MINORITY_FRACTION * values.size)))
    order = np.argsort(np.abs(values - 0.5), kind="stable")
    flip_idx = order[:k]
    out = values.astype(float).copy()
    # 0.4 redondea a 0; 0.6 redondea a 1 → introduce la clase ausente con mínimo desvío.
    out[flip_idx] = 0.4 if only_class == 1.0 else 0.6
    return out


def _is_declared_binary_int(col: dict) -> bool:
    """Una columna declarada como binaria {0,1} (int, rango [0,1]) — target o feature.

    Predicado único (Issue #301 PR2a): lo comparten el guard N-7 del outlier (no inyectar
    atípicos en una binaria) y el recompute financiero (no pisar un target binario nombrado
    ``margin_pct``/``ebitda``). Una sola fuente de verdad evita que las dos reglas deriven.
    """
    return (
        col.get("type") == "int"
        and col.get("range_min") == 0
        and col.get("range_max") == 1
    )


# ─────────────────────────────────────────────────────────
# HELPER — _generate_dataset_from_schema (Python puro, 0 tokens LLM)
# ─────────────────────────────────────────────────────────

def _is_mlds_event_target(col: dict, target_col_name: str | None) -> bool:
    """¿Es ``col`` el target binario ml_ds a calibrar (Issue F1)?

    El target del contrato (ya reconciliado a una binaria por ``_align_ml_ds_classification_target``)
    o ``categoria`` como fallback alias-first cuando no hay nombre de contrato — espejo de la
    resolución contract-first del notebook (#348). Solo binarias {0,1} int.
    """
    if not _is_declared_binary_int(col):
        return False
    name = col.get("name")
    if target_col_name:
        return name == target_col_name
    return name == "categoria"


def _generate_dataset_from_schema(
    schema: dict,
    profile: str = "business",
    *,
    target_event_rate: float | None = None,
    target_col_name: str | None = None,
) -> list:
    """
    Genera filas de datos a partir del schema producido por schema_designer.
    Vectorizado con numpy. Cero tokens LLM. Determinista con seed derivado del schema.
    Soporta trend (up/down/stable) y dependency (linear/inverse) por columna.

    ``profile`` ("business" | "ml_ds") solo afecta el target de la inyección de
    outliers (Fix B-05): en business se excluyen las columnas de coherencia
    financiera para no romper el panel M2. ml_ds conserva su comportamiento.
    """
    import numpy as np

    columns = schema.get("columns", [])
    n_rows = schema.get("n_rows", 100)
    granularity = schema.get("time_granularity", "monthly")
    constraints = schema.get("constraints", {})

    # Seed determinista: mismo schema → mismo dataset siempre.
    # hashlib (no el builtin hash()) porque hash() de un str está aleatorizado por
    # proceso (PYTHONHASHSEED), lo que rompía la reproducibilidad entre corridas.
    # RNG local (no global) para evitar race conditions con usuarios concurrentes.
    case_seed = (
        int(hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest(), 16)
        % (2**31)
    )
    rng = np.random.default_rng(case_seed)       # numpy — thread-safe (instancia local)
    rng_std = random.Random(case_seed)            # stdlib — thread-safe (instancia local)

    # ── Columna temporal ──
    periods = _generate_time_periods(n_rows, granularity)

    # ── Separar columnas: period | str | independientes | dependientes ──
    period_col_names = {c["name"] for c in columns if c["name"] == "period" or c["type"] == "date"}
    str_cols = [c for c in columns if c["type"] == "str" and c["name"] not in period_col_names]
    num_cols = [c for c in columns if c["type"] in ("int", "float") and c["name"] not in period_col_names]
    independent_cols = [c for c in num_cols if not c.get("dependency")]
    dependent_cols   = [c for c in num_cols if c.get("dependency")]

    df_data: dict[str, list[Any]] = {}

    # ── Period ──
    df_data["period"] = periods[:n_rows]

    # ── String columns ──
    NLP_NAME_KWS = ("ticket", "comentario", "texto", "descripcion", "mensaje", "queja")
    for col in str_cols:
        vals: list[str | None]
        nullable = col.get("nullable", False)
        col_name_lower = col.get("name", "").lower()
        if any(kw in col_name_lower for kw in NLP_NAME_KWS):
            motivos = [
                "demora en entrega", "producto defectuoso", "cobro incorrecto",
                "problema de acceso", "mal servicio", "solicitud de reembolso",
                "error en facturación", "soporte técnico", "consulta general",
                "inconformidad con producto",
            ]
            urgencias = ["urgente", "normal", "bajo impacto"]
            vals = [
                f"ticket_{i+1:03d}: {rng_std.choice(motivos)} - cliente reporta {rng_std.choice(urgencias)}"
                for i in range(n_rows)
            ]
        else:
            vals = [f"cat_{rng_std.randint(1, 5)}" for _ in range(n_rows)]
        if nullable:
            vals = [None if rng_std.random() < 0.05 else v for v in vals]
        df_data[col["name"]] = vals

    # ── Independientes (con tendencias) ──
    for col in independent_cols:
        name = col["name"]
        col_type = col["type"]
        nullable = col.get("nullable", False)
        low  = float(col["range_min"]) if col.get("range_min") is not None else 0.0
        high = float(col["range_max"]) if col.get("range_max") is not None else low * 2 + 100
        if low >= high:
            high = low + 1.0

        values = _generate_independent_values(col, low, high, n_rows, rng)

        if nullable:
            null_mask = rng.random(n_rows) < 0.05
        else:
            null_mask = np.zeros(n_rows, dtype=bool)

        if col_type == "float":
            result = [None if null_mask[i] else round(float(values[i]), 2) for i in range(n_rows)]
        else:
            result = [None if null_mask[i] else int(round(float(values[i]))) for i in range(n_rows)]
        df_data[name] = result

    # ── Dependientes (correlaciones inyectadas) ──
    for col in dependent_cols:
        name = col["name"]
        col_type = col["type"]
        nullable = col.get("nullable", False)
        dep = col.get("dependency", {})
        parent_name = dep.get("depends_on", "")
        low  = float(col["range_min"]) if col.get("range_min") is not None else 0.0
        high = float(col["range_max"]) if col.get("range_max") is not None else low * 2 + 100
        if low >= high:
            high = low + 1.0

        if parent_name in df_data:
            # Guard: el padre debe ser numérico para aplicar la correlación matemática
            parent_col_def = next((c for c in columns if c["name"] == parent_name), None)
            if parent_col_def and parent_col_def.get("type") not in ("int", "float"):
                logger.warning(
                    "[_generate_dataset_from_schema] columna '%s': padre '%s' es tipo '%s' "
                    "(debe ser int/float) — dependencia ignorada, generando como independiente.",
                    name, parent_name, parent_col_def.get("type"),
                )
                values = _generate_independent_values(col, low, high, n_rows, rng)
            else:
                parent_raw = df_data[parent_name]
                parent_arr = np.array(
                    [float(v) if v is not None else 0.0 for v in parent_raw], dtype=float
                )
                p_min, p_max = parent_arr.min(), parent_arr.max()
                parent_norm = (parent_arr - p_min) / (p_max - p_min + 1e-9)

                if dep.get("relationship") == "inverse":
                    parent_norm = 1.0 - parent_norm

                target_range = high - low
                base = low + parent_norm * target_range
                noise_factor = float(dep.get("noise_factor", 0.1))
                noise = rng.normal(0, target_range * noise_factor, n_rows)
                values = np.clip(base + noise, low, high)
        else:
            # Padre declarado en dependency pero no encontrado en df_data
            logger.warning(
                "[_generate_dataset_from_schema] columna '%s': padre '%s' no encontrado "
                "— dependencia ignorada, generando como independiente.",
                name, parent_name,
            )
            values = _generate_independent_values(col, low, high, n_rows, rng)

        if nullable:
            null_mask = rng.random(n_rows) < 0.05
        else:
            null_mask = np.zeros(n_rows, dtype=bool)

        if col_type == "float":
            result = [None if null_mask[i] else round(float(values[i]), 2) for i in range(n_rows)]
        elif (
            profile == "ml_ds"
            # isinstance (no solo `is not None`): defensa-en-profundidad sobre un valor de
            # origen LLM, por si un rate malformado (str/bool/None) llegara sin pasar por
            # `_validate_target_event_rate` — cae al camino round normal en vez de crashear.
            and isinstance(target_event_rate, (int, float))
            and not isinstance(target_event_rate, bool)
            and _is_mlds_event_target(col, target_col_name)
        ):
            # Issue F1 — calibra la prevalencia del target binario ml_ds al `target_event_rate`
            # anunciado en Exhibit 2 (fuente única M1↔M2). Umbral top-k por argsort sobre los
            # `values` (= clip(base+noise), que ya codifican la señal driver→target): preserva
            # el ORDEN (señal/AUC intacta) y fija la prevalencia EXACTA a la tasa. `k` con
            # piso/techo garantiza ambas clases. Mutuamente excluyente con el balance business.
            scores = np.asarray(values, dtype=float)
            n = scores.size
            k = max(1, min(n - 1, int(round(float(target_event_rate) * n))))
            order = np.argsort(scores, kind="stable")  # ascendente, determinista con seed fijo
            labels = np.zeros(n, dtype=int)
            labels[order[n - k:]] = 1  # top-k scores → positivos → exactamente k=round(rate·n)
            result = [None if null_mask[i] else int(labels[i]) for i in range(n_rows)]
        else:
            # Issue #301 — guard anti-degeneración del target binario de dominio.
            # SOLO el target que el spine etiquetó con ``is_domain_target`` se balancea;
            # las demás binarias {0,1} (features no-target emitidas por el LLM, p. ej.
            # compliance_flag/late_flag) se dejan EXACTAMENTE como se generaron — no se
            # voltean filas sintéticas no anunciadas (PR2a). Garantizar ambas clases en el
            # target evita una LR sin sentido por una sola clase.
            # Issue #382 — ampliado a ml_ds: el sibling `_enforce_mlds_classification_schema`
            # marca `is_domain_target=True` en el target ml_ds de-churnado. Cuando
            # `target_event_rate` está presente la calibración top-k de arriba ya garantiza ambas
            # clases (este else no corre); este guard cubre el caso SIN rate (architect lo omitió,
            # graph.py ~3054-3064) para que un target de-churnado no degenere a una sola clase
            # silenciosamente. Byte-idéntico para churn: `categoria` no lleva `is_domain_target`.
            if (
                profile in ("business", "ml_ds")
                and low == 0.0
                and high == 1.0
                and col.get("is_domain_target")
            ):
                values = _ensure_both_classes(np.asarray(values, dtype=float))
            result = [None if null_mask[i] else int(round(float(values[i]))) for i in range(n_rows)]
        df_data[name] = result

    # ── Ensamblar filas ──
    col_order = [c["name"] for c in columns]
    rows = [{col: df_data.get(col, [None]*n_rows)[i] for col in col_order} for i in range(n_rows)]

    # ── Escalar revenue al total del Exhibit (CRÍTICO para coherencia financiera) ──
    revenue_col = constraints.get("revenue_column", "revenue")
    expected_revenue = constraints.get("revenue_annual_total")
    if expected_revenue and any(revenue_col in row for row in rows):
        actual = sum(float(row.get(revenue_col, 0) or 0) for row in rows)
        if actual > 0:
            scale = expected_revenue / actual
            for row in rows:
                if row.get(revenue_col) is not None:
                    row[revenue_col] = round(float(row[revenue_col]) * scale, 2)

    # ── Escalar costs si hay constraint ──
    expected_costs = constraints.get("cost_annual_total")
    if expected_costs:
        cost_col = next(
            (c["name"] for c in columns if "cost" in c["name"].lower()),
            "costs"
        )
        actual_costs = sum(float(row.get(cost_col, 0) or 0) for row in rows)
        if actual_costs > 0:
            scale = expected_costs / actual_costs
            for row in rows:
                if row.get(cost_col) is not None:
                    row[cost_col] = round(float(row[cost_col]) * scale, 2)

    # ── Recalcular campos derivados después del scaling ──
    cost_col_name = next(
        (c["name"] for c in columns if "cost" in c["name"].lower()),
        None
    )
    # Issue #301 PR2a — si el case_architect nombró un classification_target literal
    # ``margin_pct``/``ebitda``, el spine lo marcó binario int [0,1] (correcto). NO lo
    # recalcules a continuo: ello degradaba el 3er chart M2 a box. Simetría con el guard
    # N-7. Se resuelve UNA vez desde el spec (no por fila); business-gated → ml_ds intacto.
    binary_int_names = {
        c["name"] for c in columns
        if profile == "business" and _is_declared_binary_int(c)
    }
    for row in rows:
        rev  = float(row.get(revenue_col, 0) or 0)
        cost = float(row.get(cost_col_name, 0) or 0) if cost_col_name else 0
        if "ebitda" in row and "ebitda" not in binary_int_names:
            row["ebitda"] = round(rev - cost, 2)
        if "margin_pct" in row and "margin_pct" not in binary_int_names:
            row["margin_pct"] = round(((rev - cost) / rev * 100), 2) if rev > 0 else 0.0

    # ── Enforcement retenciones: m1 >= m3 >= m6 >= m12 por fila ──
    retention_col_names = sorted(
        [c["name"] for c in columns if c["name"].startswith("retention_m")],
        key=lambda x: int(x.split("_m")[1])
    )
    if retention_col_names:
        for i in range(1, len(retention_col_names)):
            prev = retention_col_names[i - 1]
            curr = retention_col_names[i]
            for row in rows:
                pv = row.get(prev)
                cv = row.get(curr)
                if pv is not None and cv is not None:
                    # Mes posterior nunca mayor que el anterior (retención decae)
                    max_allowed = round(float(pv) * rng_std.uniform(0.70, 0.95), 4)
                    row[curr] = round(min(float(cv), max_allowed), 4)

    # ── Fix B-05: Inyectar outliers para ejercicios EDA (n_rows >= 50) ──
    # Business: EXCLUIMOS las columnas de coherencia financiera
    # (revenue/cost/margin/ebitda) del target del outlier. El panel M2 business
    # grafica margen e ingresos indexados; un ×3.5 sobre `costs` distorsionaría esa
    # lectura. Así el outlier cae en una métrica de comportamiento (p. ej. churn),
    # más relevante para un caso de deserción. ml_ds conserva su comportamiento.
    _financial_tokens = ("revenue", "cost", "margin", "ebitda")
    numeric_non_revenue = [
        c for c in columns
        if c["type"] in ("float", "int")
        and c["name"] != revenue_col
        and not c["name"].startswith("period")
        and not c["name"].startswith("retention_")
        and not (
            profile == "business"
            and any(tok in c["name"].lower() for tok in _financial_tokens)
        )
        # N-7 (Issue #301): nunca inyectes el outlier en el target binario {0,1} — un ×3.5
        # capado lo convertiría en float 0.0/1.0 (dtype mixto en una columna de clasificación).
        # Se excluye toda columna int declarada en [0,1]. Issue #382 — ampliado a ml_ds (consistente
        # con `_ensure_both_classes`): el target de-churnado es un binario {0,1} real. Sin cambio de
        # comportamiento hoy (el target nunca es `numeric_non_revenue[0]`), es defensa-en-profundidad.
        and not (profile in ("business", "ml_ds") and _is_declared_binary_int(c))
    ]
    if numeric_non_revenue and n_rows >= 50:
        target_col_def = numeric_non_revenue[0]
        target_col = target_col_def["name"]
        col_range_max = target_col_def.get("range_max")
        outlier_indices = rng_std.sample(range(n_rows), min(3, n_rows))
        for idx in outlier_indices:
            if rows[idx].get(target_col) is not None:
                original = float(rows[idx][target_col])
                outlier_val = original * 3.5
                if col_range_max is not None and float(col_range_max) > 0:
                    # business: el atípico respeta el range_max declarado en vez de
                    # 2× (evita p. ej. churn 0.30 cuando el schema declaró [0.02,0.15],
                    # que además debilitaba la correlación nps↔churn que el panel
                    # presenta como driver real). ml_ds conserva el cap ×2 histórico.
                    cap_mult = 1.0 if profile == "business" else 2.0
                    outlier_val = min(outlier_val, float(col_range_max) * cap_mult)
                rows[idx][target_col] = round(outlier_val, 2)

    print(f"[_generate_dataset_from_schema] {len(rows)} filas generadas, {len(columns)} columnas")
    return rows


# ─────────────────────────────────────────────────────────
# HELPER — _enforce_mlds_clustering_structure (Issue #452)
# ─────────────────────────────────────────────────────────

# Within-blob standard deviation as a fraction of each feature's [range_min, range_max] span.
# Calibrated so StandardScaler + KMeans over the blobbed segmentation features lands the
# silhouette in the healthy band ~[0.45, 0.70] (neither trivial nor degenerate) and the
# adjusted Rand index vs. the latent blob label stays ≥ 0.6. Tuned against the deterministic
# golden oracle (tests/test_issue452_clustering_structure.py); do NOT change without re-running it.
_CLUSTERING_BLOB_SPREAD_FRAC = 0.135
# K (number of latent segments) is chosen deterministically per case from this set.
_CLUSTERING_K_CHOICES: tuple[int, ...] = (3, 4)


def _clustering_scalable_feature_columns(schema: dict) -> list[dict]:
    """Numeric, scalable feature columns a K-Means fit would use (Issue #452).

    Excludes the temporal/index column (``period``/date) — it is a row id the notebook drops
    from the fit. Everything else of type int/float is a segmentation feature that should carry
    the latent cluster structure.
    """
    feats: list[dict] = []
    for col in schema.get("columns", []):
        if col.get("type") not in ("int", "float"):
            continue
        name = str(col.get("name", ""))
        if name == "period" or name.startswith("period") or col.get("type") == "date":
            continue
        feats.append(col)
    return feats


def _enforce_mlds_clustering_structure(
    rows: list,
    schema: dict,
    *,
    profile: str,
    primary_family: str | None,
    enabled: bool = True,
    return_labels: bool = False,
):
    """Inyecta estructura de clusters REAL en el dataset ml_ds + clustering (Issue #452).

    El generador determinista produce columnas UNIMODALES (una sola moda por columna), así que
    K-Means parte una nube convexa en cuñas arbitrarias y la premisa pedagógica ("descubrir
    segmentos latentes") queda hueca. Este helper reescribe las features numéricas escalables
    como una **mezcla de K∈{3,4} blobs gaussianos separables**, de modo que K-Means descubre
    segmentos genuinos e interpretables.

    Es PURO copy-on-write (no muta el dict/lista de entrada → determinismo del seed +
    thread-safety bajo jobs concurrentes), preserva el conteo y el ORDEN de filas (los blobs
    quedan row-aligned a través de ``data_validator``), y conserva nulls intencionales y los
    rangos ``range_min``/``range_max`` declarados.

    Gate (fuera de él → la MISMA lista de entrada, byte-idéntica): ``enabled`` (kill-switch
    ``MLDS_CLUSTERING_STRUCTURE``) AND ``profile == "ml_ds"`` AND ``primary_family == "clustering"``
    (ESTRICTO — NO ``primary_family or "clustering"``: un job ml_ds con algoritmos vacíos/no
    mapeables resuelve ``primary_family=None`` y el resto del pipeline lo trata como CLASIFICACIÓN
    [``_effective_family = primary_family or "clasificacion"``], así que coaccionar ``None →
    clustering`` aquí blobearía el target binario ``categoria`` de ese cohorte). business /
    clasificación / regresión / serie_temporal / ml_ds-sin-algoritmos nunca entran.

    La etiqueta latente del blob es SOLO de generación: no se persiste en ``doc7_dataset`` (no se
    filtra al fit de K-Means). Con ``return_labels=True`` se devuelve aparte ``(rows, labels)``
    para que el oráculo golden mida el ARI contra la estructura inyectada (no es teacher/student
    facing).
    """
    if not enabled or profile != "ml_ds" or primary_family != "clustering":
        return (rows, None) if return_labels else rows
    if not isinstance(rows, list) or not rows:
        return (rows, None) if return_labels else rows
    feats = _clustering_scalable_feature_columns(schema)
    if len(feats) < 2:
        # Sin al menos 2 features escalables no hay espacio donde formar blobs separables.
        return (rows, None) if return_labels else rows

    import numpy as np

    n = len(rows)
    # Seed determinista derivado del schema (mismo patrón que `_generate_dataset_from_schema`),
    # desplazado para no correlacionar con el stream del generador. RNG LOCAL (thread-safe).
    base_seed = (
        int(hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest(), 16) % (2**31)
    )
    rng = np.random.default_rng(base_seed + 452)

    k = _CLUSTERING_K_CHOICES[base_seed % len(_CLUSTERING_K_CHOICES)]
    k = max(2, min(k, n - 1))

    # Asignación de blobs balanceada y determinista (round-robin barajado).
    labels = np.array([i % k for i in range(n)], dtype=int)
    rng.shuffle(labels)

    new_rows = [dict(r) for r in rows]
    for col in feats:
        name = col["name"]
        low = float(col["range_min"]) if col.get("range_min") is not None else 0.0
        high = float(col["range_max"]) if col.get("range_max") is not None else low + 1.0
        if low >= high:
            high = low + 1.0
        span = high - low
        # Centros por-blob = niveles EQUI-ESPACIADOS en el interior del rango normalizado,
        # BARAJADOS por feature. Como cada blob recibe un nivel distinto (permutación biyectiva),
        # cualquier par de blobs difiere en TODA feature por ≥ el gap mínimo → separación fuerte y
        # consistente (a diferencia de centros uniformes-aleatorios, que pueden caer juntos); la
        # permutación por-feature evita que los blobs queden colineales (separación isotrópica).
        centers = rng.permutation(np.linspace(0.18, 0.82, k))
        vals_norm = np.clip(
            centers[labels] + rng.normal(0.0, _CLUSTERING_BLOB_SPREAD_FRAC, n), 0.0, 1.0
        )
        vals = low + vals_norm * span
        is_int = col.get("type") == "int"
        for i, r in enumerate(new_rows):
            if r.get(name) is None:  # preserva nulls intencionales
                continue
            v = float(vals[i])
            r[name] = int(round(v)) if is_int else round(v, 4)

    if return_labels:
        return new_rows, labels.tolist()
    return new_rows


# ─────────────────────────────────────────────────────────
# NODO 2 — DATA GENERATOR (Python puro, 0 tokens LLM)
# ─────────────────────────────────────────────────────────

def data_generator(state: ADAMState, config: RunnableConfig) -> dict:  # noqa: ARG001
    """NODO 2: Genera filas del dataset usando Python puro.
    NO USA LLM. Cero tokens. Instantáneo. Siempre exactamente n_rows filas.
    Lee el schema del Nodo 1 (schema_designer) y genera datos con random + aritmética.
    """
    try:
        schema = state.get("dataset_schema", {})

        if not schema:
            logger.error("[data_generator] ERROR: no hay dataset_schema")
            return {"doc7_dataset": [], "dataset_constraints": {}}

        # Clamp n_rows según perfil: business → 80-120, ml_ds → sin límite (200 default).
        profile = state.get("studentProfile", "business")
        if profile == "business":
            schema["n_rows"] = max(80, min(120, schema.get("n_rows", 100)))

        # Issue F1 — pasa la tasa de evento + nombre del target (fuente única M1↔M2) para que
        # el generador calibre la prevalencia del target binario ml_ds. Como kwargs (no en
        # `schema`) el seed no cambia → datasets sin rate / business byte-idénticos.
        contract = state.get("dataset_schema_required")
        target_event_rate = (
            contract.get("target_event_rate") if isinstance(contract, dict) else None
        )
        target_col_name = _safe_contract_target_name(contract) or None
        rows = _generate_dataset_from_schema(
            schema,
            profile=profile,
            target_event_rate=target_event_rate,
            target_col_name=target_col_name,
        )
        # Issue #452 — inyecta estructura de clusters real para ml_ds + clustering (determinista,
        # gateado por kill-switch). No-op byte-idéntico para business/clasificación/regresión/
        # serie_temporal. Corre DESPUÉS del generador (sobrescribe las features → neutraliza el
        # outlier ×3.5 que cayó en la 1ª feature) y ANTES de `data_validator` (que solo corrige
        # revenue/costs/ebitda/margin/retención → no toca estas features de segmentación).
        _clustering_family, _ = _resolve_primary_family(_extract_state_algoritmos(state))
        rows = _enforce_mlds_clustering_structure(
            rows,
            schema,
            profile=profile,
            primary_family=_clustering_family,
            enabled=settings.mlds_clustering_structure,
        )
        constraints = schema.get("constraints", {})
        constraints_with_count = {**constraints, "n_rows_expected": schema.get("n_rows", 100)}

        print(f"[data_generator] {len(rows)} filas generadas — Python puro, 0 tokens LLM")
        return {
            "doc7_dataset": rows,
            "dataset_constraints": constraints_with_count,
            "current_agent": "data_generator",
        }

    except Exception as e:
        logger.error("[data_generator] ERROR: %s", e, exc_info=True)
        return {"doc7_dataset": [], "dataset_constraints": {}, "current_agent": "data_generator"}


# ─────────────────────────────────────────────────────────
# NODO 3 — DATA VALIDATOR (Python puro, CERO tokens LLM)
# ─────────────────────────────────────────────────────────

def data_validator(state: ADAMState, config: RunnableConfig) -> dict:  # noqa: ARG001
    """NODO 3 del pipeline de dataset. Valida Y CORRIGE filas contra constraints.
    CERO tokens LLM — validación y corrección determinista en Python puro.

    Correcciones aplicadas antes de decidir:
    - Revenue escalado al total esperado (Exhibit 1)
    - Costs escalados si hay constraint
    - EBITDA y margin_pct recalculados

    Retry solo si hay filas insuficientes (truncamiento del serializer).
    Los errores de revenue/costs se corrigen en Python — no necesitan retry.
    """
    rows = state.get("doc7_dataset", [])
    constraints = state.get("dataset_constraints", {})
    retry_count = state.get("dataset_retry_count", 0)
    schema = state.get("dataset_schema", {})
    MAX_RETRIES = 2
    # Fix C-03: Con data_generator Python puro (post v8), el retry es prácticamente
    # innecesario — Python no falla por truncamiento de tokens ni respuestas LLM.
    # Se conserva como red de seguridad para edge cases matemáticos:
    # ej. schema con range_min > range_max que causa ValueError en random.gauss,
    # o constraints que producen 0 filas válidas tras corrección.
    # El router _route_dataset_validation solo activa retry si hay "insuficientes" en errors.

    is_valid, errors, corrected_rows = _validate_and_correct_dataset(
        rows=rows,
        constraints=constraints,
        context_label=f"intento {retry_count + 1}/{MAX_RETRIES + 1}",
    )

    # Construir dataset_metadata para downstream (eda_text_analyst, eda_chart_generator)
    def _build_metadata(r: list) -> dict:
        columns = schema.get("columns", [])
        # Issue #225 — Prioridad para target_variable:
        #   1) Contrato del case_architect (fuente canónica del dilema).
        #   2) Heurística por descripción/nombre (legacy, casos sin contrato).
        #   3) Fallback a revenue_column.
        contract = state.get("dataset_schema_required") or {}
        contract_target = (
            (contract.get("target_column") or {}).get("name")
            if isinstance(contract, dict)
            else None
        )
        target_var = contract_target or next(
            (col["name"] for col in columns
             if "target" in col.get("description", "").lower()
             or "churn" in col["name"].lower()
             or "target" in col["name"].lower()),
            constraints.get("revenue_column", "revenue"),
        )
        return {
            "case_id": state.get("case_id", ""),
            "rows": len(r),
            "columns": len(r[0]) if r else 0,
            "time_granularity": schema.get("time_granularity", "monthly"),
            "target_variable": target_var,
            "protected_columns": [
                col["name"] for col in columns if not col.get("nullable", False)
            ][:5],
        }

    # Si la validación pasa (post-corrección), aceptar y retornar filas corregidas
    if is_valid:
        return {
            "doc7_dataset": corrected_rows,
            "dataset_metadata": _build_metadata(corrected_rows),
            "dataset_valid": True,
            "dataset_retry_count": 0,
            "dataset_errors": [],
            "current_agent": "data_validator",
        }

    # Retry SOLO si hay filas insuficientes (truncamiento del serializer)
    # Revenue/costs ya fueron corregidos — retry no ayudaría
    has_row_shortage = any("insuficientes" in e for e in errors)

    if has_row_shortage and retry_count < MAX_RETRIES:
        print(f"[data_validator] RETRY {retry_count + 1}/{MAX_RETRIES} — filas insuficientes")
        return {
            "dataset_valid": False,
            "dataset_retry_count": retry_count + 1,
            "dataset_errors": errors,
            "doc7_dataset": [],   # Limpia para forzar regeneración
            "current_agent": "data_validator",
        }

    # Retries agotados o solo errores no-row-shortage: aceptar filas corregidas.
    # Fix A-02: preservar el mejor resultado parcial disponible — mejor tener
    # N filas con errores residuales que 0 filas. El EDA downstream opera
    # correctamente con datos imperfectos pero no con un dataset vacío.
    if corrected_rows:
        logger.warning(
            "[data_validator] Aceptado con %d errores residuales — %d filas "
            "(mejor resultado disponible tras %d intento/s)",
            len(errors), len(corrected_rows), retry_count + 1,
        )
        return {
            "doc7_dataset": corrected_rows,
            "dataset_metadata": _build_metadata(corrected_rows),
            "dataset_valid": len(errors) == 0,
            "dataset_retry_count": 0,
            "dataset_errors": errors,
            "current_agent": "data_validator",
        }

    # Sin filas — pipeline continúa con dataset vacío
    logger.warning("[data_validator] sin filas válidas tras correcciones — %s", errors)
    return {
        "dataset_valid": False,
        "dataset_retry_count": 0,
        "dataset_errors": errors,
        "current_agent": "data_validator",
    }


# ─────────────────────────────────────────────────────────
# ROUTER — _route_dataset_validation
# ─────────────────────────────────────────────────────────

def _route_dataset_validation(state: ADAMState) -> str:
    """Decide si regenerar datos o continuar al EDA."""
    is_valid = state.get("dataset_valid", False)
    retry_count = state.get("dataset_retry_count", 0)
    if not is_valid and retry_count > 0:
        return "data_generator"   # Regenerar (instantáneo, Python puro)
    return "eda_text_analyst"     # Continuar al EDA


# NOTA: notebook_generator de M2 fue eliminado en v8-M3-refactor.
# M2 NO genera notebook. El único notebook del sistema es m3_notebook_generator (ml_ds).
# NOTEBOOK_BASE_TEMPLATE y NOTEBOOK_SOCRATIC_PROMPT (M2) también fueron eliminados de los imports.


# ─────────────────────────────────────────────────────────
# TEACHING NOTE (M6) — Guía del Docente por módulo
# Kill-switch TEACHING_NOTE_MODULE_GUIDE (default true):
#   ON  → guía concisa de 3 secciones; §2 "Recorrido por Módulo" lo ENSAMBLA Python
#         (build_module_guide_block) → módulos correctos por construcción; el LLM solo
#         escribe la sinopsis, el público, 3 objetivos y una frase de anclaje por módulo.
#   OFF → _legacy_teaching_note_part1/part2: cuerpos verbatim previos, byte-idéntico.
# ─────────────────────────────────────────────────────────
def _legacy_teaching_note_part1(state: ADAMState, config: RunnableConfig) -> dict:
    """Kill-switch OFF: comportamiento previo byte-idéntico (§1 Sinopsis, §2 Bloom, §3 Pauta)."""
    try:
        cfg = Configuration.from_runnable_config(config)
        llm = _get_writer_llm(cfg.writer_model, temperature=0.6, thinking_level="medium")

        context = _build_base_context(state)
        context.update({
            # ~6000 chars ≈ ~1500 tokens. Narrativa completa ~15000 chars → 40% de contexto.
            "case_context": state.get("doc1_narrativa", "")[:6000],
            # ~4000 chars ≈ ~1000 tokens. EDA completo ~10000 chars → 40%.
            "eda_section": state.get("doc2_eda", "")[:4000] if state.get("doc2_eda") else "",
        })
        response = llm.invoke(TEACHING_NOTE_PART1_PROMPT_LEGACY.format(**context))
        part1 = sanitize_markdown(_extract_text(response))
        print(f"[teaching_note_part1] {len(part1)} chars")
        return {"doc3_teaching_note_part1": part1, "current_agent": "teaching_note_part1"}
    except Exception as e:
        logger.error("[teaching_note_part1] ERROR: %s", e, exc_info=True)
        return {"doc3_teaching_note_part1": "⚠️ Error generando Teaching Note (parte 1)."}


def _legacy_teaching_note_part2(state: ADAMState, config: RunnableConfig) -> dict:
    """Kill-switch OFF: comportamiento previo byte-idéntico (§4 Análisis del Caso)."""
    try:
        cfg = Configuration.from_runnable_config(config)
        llm = _get_writer_llm(cfg.writer_model, temperature=0.6, thinking_level="medium")

        # Extraer sinopsis de part1 como contexto de coherencia narrativa.
        part1 = state.get("doc3_teaching_note_part1", "")
        synopsis = (
            part1.split("#### 2.")[0].strip()
            if "#### 2." in part1
            else part1[:500]
        )

        # Consolidar preguntas de todos los módulos como referencia para el análisis.
        all_questions: list[dict[str, Any]] = []
        for key in ["doc1_preguntas", "doc2_preguntas_eda", "m3_questions", "m4_questions"]:
            qs = cast(list[dict[str, Any]], state.get(key, []))
            if qs:
                all_questions.extend(qs)

        m5_questions = cast(list[dict[str, Any]], state.get("m5_questions", []))
        m5_questions_data = json.dumps(m5_questions, ensure_ascii=False) if m5_questions else "[]"

        context = _build_base_context(state)
        context.update({
            "teaching_note_part1_synopsis": synopsis,
            "question_full_data": json.dumps(all_questions[:16], ensure_ascii=False),
            "m5_questions_data": m5_questions_data,
        })
        response = llm.invoke(TEACHING_NOTE_PART2_PROMPT_LEGACY.format(**context))
        part2 = sanitize_markdown(_extract_text(response))
        print(f"[teaching_note_part2] {len(part2)} chars, m5_qs={'yes' if m5_questions else 'no'}")
        return {"doc3_teaching_note_part2": part2, "current_agent": "teaching_note_part2"}
    except Exception as e:
        logger.error("[teaching_note_part2] ERROR: %s", e, exc_info=True)
        return {"doc3_teaching_note_part2": "⚠️ Error generando Teaching Note (parte 2).", "current_agent": "teaching_note_part2"}


def _m6_render_section1(resultado: TeachingNoteIntroOutput) -> str:
    """Render §1 "Resumen para el Docente" from the structured intro output."""
    lines = ["## Resumen para el Docente", ""]
    sinopsis = (resultado.resumen_markdown or "").strip()
    lines.append(sinopsis if sinopsis else "_Sinopsis no disponible._")
    publico = (resultado.publico_objetivo or "").strip()
    if publico:
        lines.extend(["", f"**Público objetivo:** {publico}"])
    objetivos = [o.strip() for o in (resultado.objetivos or []) if o and o.strip()]
    if objetivos:
        lines.extend(["", "**Objetivos de aprendizaje:**"])
        lines.extend(f"- {o}" for o in objetivos)
    return "\n".join(lines).rstrip()


def _m6_fallback_section1(state: ADAMState) -> str:
    """Degrade §1 from the narrative when the structured intro call fails (never raises)."""
    narrativa = (state.get("doc1_narrativa") or "").strip()
    words = narrativa.split()
    sinopsis = " ".join(words[:90]) + ("…" if len(words) > 90 else "") if words else ""
    lines = ["## Resumen para el Docente", ""]
    lines.append(sinopsis if sinopsis else "_Sinopsis no disponible._")
    return "\n".join(lines)


def teaching_note_part1(state: ADAMState, config: RunnableConfig) -> dict:
    """M6 §1 Resumen + §2 Recorrido por Módulo (Python-owned roster + LLM anchors).

    Corre en fan-out paralelo de synthesis_flow (no necesita m5_content). El bloque
    determinista §2 se construye SIEMPRE (incluso si la llamada estructurada falla), por lo
    que un fallo del LLM degrada a esqueleto + §1 de respaldo en vez de perder la guía.
    """
    if not settings.teaching_note_module_guide:
        return _legacy_teaching_note_part1(state, config)

    try:
        is_business = state.get("studentProfile") == "business"
        case_type = state.get("caseType", "harvard_only")
        context = _build_base_context(state)
        family = context.get("primary_family")
        # Estado REALIZADO: el notebook M3 (generator family-agnóstico) sí se emitió y no está
        # degradado. Espeja lo que el estudiante realmente recibe (no la mera intención).
        notebook_present = bool(state.get("m3_notebook_code")) and not bool(
            state.get("m3_notebook_degraded")
        )
        roster_ids = module_guide_roster_ids(is_business, case_type)
        # Issue #437 Fase 3 — resolve the Impact Lens ONCE (DD1: the SAME _resolve_impact_lens M1/M4/M5
        # consume) so the M4 synopsis value noun matches the case's value frame. None when the lens
        # kill-switch is off → byte-identical OFF path; financial_roi is byte-identical regardless.
        _m6_lens = _resolve_impact_lens(state) if settings.impact_lens else None

        # §2 esqueleto (sin anclajes) — baseline que SIEMPRE existe.
        section2 = build_module_guide_block(
            is_business=is_business,
            case_type=case_type,
            family=family,
            notebook_present=notebook_present,
            anchors=None,
            lens=_m6_lens,
        )
        section1 = _m6_fallback_section1(state)

        try:
            cfg = Configuration.from_runnable_config(config)
            llm = _get_writer_llm(cfg.writer_model, temperature=0.6, thinking_level="medium")
            context.update({
                "case_context": state.get("doc1_narrativa", "")[:6000],
                "eda_section": state.get("doc2_eda", "")[:4000] if state.get("doc2_eda") else "",
                "modulos_disponibles": build_roster_allowlist(is_business, case_type),
            })
            resultado: TeachingNoteIntroOutput = llm.with_structured_output(
                TeachingNoteIntroOutput
            ).invoke(TEACHING_NOTE_PART1_PROMPT.format(**context))
            # Intersecta los anclajes con el roster real (ids desconocidos se descartan).
            anchors = {
                a.modulo_id.strip().lower(): a.frase
                for a in (resultado.anclajes or [])
                if a.modulo_id and a.modulo_id.strip().lower() in roster_ids and a.frase
            }
            section1 = _m6_render_section1(resultado)
            section2 = build_module_guide_block(
                is_business=is_business,
                case_type=case_type,
                family=family,
                notebook_present=notebook_present,
                anchors=anchors,
                lens=_m6_lens,
            )
        except Exception as e:
            logger.warning(
                "[teaching_note_part1] intro estructurada falló — esqueleto + §1 de respaldo: %s",
                e,
            )

        note = sanitize_markdown(f"{section1}\n\n{section2}")
        log_out_of_roster_mentions(
            note, roster_ids, case_id=state.get("case_id", "unknown"), node="teaching_note_part1"
        )
        print(f"[teaching_note_part1] {len(note)} chars (module guide)")
        return {"doc3_teaching_note_part1": note, "current_agent": "teaching_note_part1"}
    except Exception as e:
        logger.error("[teaching_note_part1] ERROR: %s", e, exc_info=True)
        # Centinela `[..._ERROR]` para que el resume RECALCULE (no congele la nota degradada).
        return {
            "doc3_teaching_note_part1": "[TEACHING_NOTE_PART1_ERROR] ⚠️ Error generando Teaching Note (parte 1).",
            "current_agent": "teaching_note_part1",
        }


def teaching_note_part2(state: ADAMState, config: RunnableConfig) -> dict:
    """M6 §3 "Plan de Clase y Dónde se Traban" (corre post sync1; tiene preguntas + M5)."""
    if not settings.teaching_note_module_guide:
        return _legacy_teaching_note_part2(state, config)

    try:
        cfg = Configuration.from_runnable_config(config)
        llm = _get_writer_llm(cfg.writer_model, temperature=0.6, thinking_level="medium")

        # Consolidar preguntas de todos los módulos como referencia para "dónde se traban".
        all_questions: list[dict[str, Any]] = []
        for key in ["doc1_preguntas", "doc2_preguntas_eda", "m3_questions", "m4_questions"]:
            qs = cast(list[dict[str, Any]], state.get(key, []))
            if qs:
                all_questions.extend(qs)

        m5_questions = cast(list[dict[str, Any]], state.get("m5_questions", []))
        m5_questions_data = json.dumps(m5_questions, ensure_ascii=False) if m5_questions else "[]"

        is_business = state.get("studentProfile") == "business"
        case_type = state.get("caseType", "harvard_only")
        roster_ids = module_guide_roster_ids(is_business, case_type)

        context = _build_base_context(state)
        context.update({
            "question_full_data": json.dumps(all_questions[:16], ensure_ascii=False),
            "m5_questions_data": m5_questions_data,
            "modulos_disponibles": build_roster_allowlist(is_business, case_type),
        })
        response = llm.invoke(TEACHING_NOTE_PART2_PROMPT.format(**context))
        part2 = sanitize_markdown(_extract_text(response))
        log_out_of_roster_mentions(
            part2, roster_ids, case_id=state.get("case_id", "unknown"), node="teaching_note_part2"
        )
        print(f"[teaching_note_part2] {len(part2)} chars, m5_qs={'yes' if m5_questions else 'no'}")
        return {"doc3_teaching_note_part2": part2, "current_agent": "teaching_note_part2"}
    except Exception as e:
        logger.error("[teaching_note_part2] ERROR: %s", e, exc_info=True)
        return {
            "doc3_teaching_note_part2": "[TEACHING_NOTE_PART2_ERROR] ⚠️ Error generando Teaching Note (parte 2).",
            "current_agent": "teaching_note_part2",
        }



# ─────────────────────────────────────────────────────────
# v7 — NODO: M4 QUESTIONS GENERATOR (Módulo Impacto)
# ─────────────────────────────────────────────────────────
def m4_questions_generator(state: ADAMState, config: RunnableConfig) -> dict:
    """Genera 3 preguntas del Módulo de Impacto (M4).
    v8: corre secuencialmente DESPUÉS de m4_content_generator en m4_flow.
    """
    try:
        cfg = Configuration.from_runnable_config(config)
        llm = _get_writer_llm(cfg.writer_model, temperature=0.5, thinking_level="low")

        context = _build_base_context(state)
        context.update({
            "m4_content": state.get("m4_content", ""),
            "anexo_financiero": state.get("doc1_anexo_financiero", ""),
            "algorithm_mode": _extract_state_algorithm_mode(state) or "single",
            "computed_metrics_block": build_computed_metrics_block(state.get("m3_metrics_summary")),
        })

        # Issue #437 (ADR 0003, Fase 1) — NEUTRAL questions set + «MARCO DE VALOR» hint when
        # settings.impact_lens is on (default); else the FINANCIAL set (byte-identical off-path).
        _lens_on = settings.impact_lens
        prompt = _resolve_family_prompt(
            state,
            M4_QUESTIONS_PROMPT_BY_FAMILY_NEUTRAL if _lens_on else M4_QUESTIONS_PROMPT_BY_FAMILY,
            M4_QUESTIONS_GENERATOR_PROMPT_NEUTRAL if _lens_on else M4_QUESTIONS_GENERATOR_PROMPT,
        )
        # Issue #329 — business+clasificación: alinea las preguntas con el arco LR (#306/#319).
        # No-op para ml_ds y para business no-clasificación (mismo gate que el contenido).
        prompt = _maybe_business_classification_prompt(
            state,
            prompt,
            M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION_NEUTRAL
            if _lens_on else M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION,
        )
        if _lens_on:
            prompt = prompt + build_impact_lens_hint(_resolve_impact_lens(state))
        # Render once; the coherence reprompt below reuses this verbatim so it re-grounds on
        # the SAME text the model first saw (mirrors the M1/M2 single-render pattern).
        rendered_prompt = prompt.format(**context)
        resultado: GeneradorPreguntasOutput = llm.with_structured_output(
            GeneradorPreguntasOutput
        ).invoke(rendered_prompt)

        preguntas = [p.model_dump() for p in resultado.preguntas]
        print(f"[m4_questions_generator] {len(preguntas)} preguntas")
        # Option coherence (clasificación, both profiles) — best-effort, reprompt-once-then-
        # degrade. The wrapper concatenates onto the rendered prompt (never re-.format, cifras `{}`).
        preguntas = _apply_m4_questions_option_coherence(
            llm=llm, prompt=rendered_prompt, state=state, preguntas_dict=preguntas
        )
        return {"m4_questions": preguntas, "current_agent": "m4_questions_generator"}
    except Exception as e:
        logger.error("[m4_questions_generator] ERROR: %s", e, exc_info=True)
        return {"m4_questions": [], "current_agent": "m4_questions_generator"}


# ─────────────────────────────────────────────────────────
# M5 memorándum coherence (sibling of M1 #412 / M2 #414 / M3 #415)
# ─────────────────────────────────────────────────────────

_M5_VIOLATION_CODES = (
    ("MODELO_NO_SELECCIONADO", "unselected_model"),
    ("METRICA_NO_ANCLADA", "unanchored_metric"),
    ("OPTION_NONEXISTENT", "option_nonexistent"),
)


def _m5_violation_types(violations: list[str]) -> list[str]:
    """Enumerated short codes for structured logging — never the raw message (no PII)."""
    codes: list[str] = []
    for violation in violations:
        for prefix, code in _M5_VIOLATION_CODES:
            if violation.startswith(prefix) and code not in codes:
                codes.append(code)
    return codes


def _build_m5_coherence_reprompt(
    violations: list[str],
    *,
    variant: str | None,
    metrics_block: str,
    numeros: list[Any],
) -> str:
    """Focused reprompt (CONCATENATED, never ``.format`` — the formatted prompt and the
    memorándum both carry ``{}`` from the JSON schema). Carries the concrete fix (the forbidden
    model when single-model, the verified-metrics rule, the option universe) and demands the SAME
    single memorándum with ``numero == 1`` so the downstream ``M5-Q{numero}`` grading key holds.
    """
    bullet_list = "\n".join(f"- {violation}" for violation in violations)
    forbidden_line = ""
    if variant == CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY:
        forbidden_line = "NO menciones Random Forest (el modelo seleccionado es Logistic Regression).\n"
    elif variant == CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY:
        forbidden_line = "NO menciones Logistic Regression (el modelo seleccionado es Random Forest).\n"
    metrics_line = ""
    if has_metric_anchors(metrics_block):
        metrics_line = (
            "Cita SOLO métricas del modelo (AUC/F1/precision/recall) que figuren en las métricas "
            "verificadas del M3; no inventes valores.\n"
        )
    numeros_str = ", ".join(str(numero) for numero in numeros)
    return (
        "\n\n# CORRECCIÓN OBLIGATORIA DE COHERENCIA (Módulo 5)\n"
        "El memorándum nombra un modelo no seleccionado, cita una métrica no verificada o "
        "recomienda una opción inexistente en el caso. "
        f"Regenera EXACTAMENTE {len(numeros)} consigna(s) con el MISMO schema y el MISMO "
        f"`numero` ({numeros_str}). La opción recomendada debe ser una de las opciones reales "
        "del caso (A/B/C).\n"
        f"{forbidden_line}"
        f"{metrics_line}"
        "Incoherencias detectadas:\n" + bullet_list
    )


def _apply_m5_questions_coherence(
    *,
    llm: Any,
    prompt: str,
    state: ADAMState,
    preguntas_dict: list[dict],
    variant: str | None,
    metrics_block: str,
    dilema_brief: str,
) -> list[dict]:
    """Validate + reprompt-once-then-DEGRADE the M5 memorándum coherence.

    Gated to the classification family for BOTH profiles (business + ml_ds) via
    ``_is_classification_family`` (the SAME gate M1/M2/M3 use) behind the
    ``m5_question_coherence`` kill-switch; a byte-identical no-op otherwise. On a violation it
    reprompts ONCE with the concrete fix; the corrected memo is accepted ONLY if it preserves the
    question count AND the ``numero`` sequence (the ``M5-Q{numero}`` grading key) AND is now
    coherent — otherwise it degrades to the pass-1 memo. Best-effort: ANY throw (including a
    reprompt ``RuntimeError``, which the node would otherwise re-raise via ``except RuntimeError:
    raise`` and FAIL the job) degrades to pass-1. Never raises.

    ``prompt`` is the ALREADY-formatted string; the reprompt is built by CONCATENATION (never
    re-``.format``). ``variant`` is the RESOLVED notebook variant (never ``algorithm_mode``);
    ``metrics_block`` / ``dilema_brief`` feed the three checks. ``state`` is read ONLY for the gate
    and ``case_id`` logging.
    """
    log_extra = {"node": "m5_questions_generator", "case_id": state.get("case_id")}
    try:
        if not settings.m5_question_coherence or not _is_classification_family(state):
            return preguntas_dict
        violations = validate_m5_questions_coherence(
            preguntas_dict,
            variant=variant,
            metrics_block=metrics_block,
            dilema_brief=dilema_brief,
        )
        if not violations:
            return preguntas_dict
        numeros = [q.get("numero") for q in preguntas_dict]
        logger.info(
            "[m5_questions] reprompt de coherencia M5 disparado",
            extra={
                **log_extra,
                "violation_count": len(violations),
                "violation_types": _m5_violation_types(violations),
            },
        )
        reprompt = prompt + _build_m5_coherence_reprompt(
            violations, variant=variant, metrics_block=metrics_block, numeros=numeros
        )
        try:
            resultado: GeneradorPreguntasM5Output = llm.with_structured_output(
                GeneradorPreguntasM5Output
            ).invoke(reprompt)
            corrected = [p.model_dump() for p in resultado.preguntas]
        except (ValidationError, OutputParserException, ValueError) as exc:
            logger.warning(
                "[m5_questions] reprompt de coherencia M5 inválido — degrada a pass-1: %s",
                exc,
                extra=log_extra,
            )
            return preguntas_dict
        # Identity guard: a reprompt that drops/adds/renumbers the memo would corrupt the
        # `M5-Q{numero}` grading key — reject it. `GeneradorPreguntasM5Output` already bounds this
        # to exactly 1 question with numero==1, so this is belt-and-suspenders (list equality =
        # count + order + values).
        if [q.get("numero") for q in corrected] != numeros:
            logger.warning(
                "[m5_questions] reprompt M5 alteró conteo/numero — degrada a pass-1",
                extra=log_extra,
            )
            return preguntas_dict
        residual = validate_m5_questions_coherence(
            corrected, variant=variant, metrics_block=metrics_block, dilema_brief=dilema_brief
        )
        if not residual:
            logger.info(
                "[m5_questions] coherencia M5 corregida por reprompt",
                extra={**log_extra, "degraded": False},
            )
            return corrected
        logger.warning(
            "[m5_questions] coherencia M5 degradada tras reprompt",
            extra={
                **log_extra,
                "violation_types": _m5_violation_types(residual),
                "degraded": True,
            },
        )
        return preguntas_dict
    except Exception as exc:  # best-effort — a coherence pass must never fail the job
        logger.warning(
            "[m5_questions] validador de coherencia M5 falló (best-effort): %s",
            exc,
            extra=log_extra,
        )
        return preguntas_dict


# ─────────────────────────────────────────────────────────
# v7 — NODO: M5 QUESTIONS GENERATOR (Módulo Recomendación)
# ─────────────────────────────────────────────────────────
def m5_questions_generator(state: ADAMState, config: RunnableConfig) -> dict:
    """Genera la consigna única de memorándum final del Módulo 5.

    v9: usa GeneradorPreguntasM5Output (PreguntaM5) — solucion_esperada sin límite
    de 60 palabras, en formato memorándum modelo, para calificación comparativa por IA.
    doc1_preguntas_complejas se pasa como historial de referencia (no como fuente):
    el LLM lo usa para no repetir temas ya evaluados en M1.
    Corre DESPUÉS de synthesis_phase1_sync — necesita m5_content del state.
    """
    try:
        cfg = Configuration.from_runnable_config(config)
        # temperature=0.5: balance entre creatividad en enunciados y consistencia estructural
        # Usa Gemini Pro medium + fallback Pro low: M5 es evaluación final integrativa.
        m5_model = resolve_node_model(cfg, NODE_M5_QUESTIONS, cfg.architect_model)
        logger.info("[m5_questions_generator] llm model=%s", m5_model)
        llm = _get_m5_llm(m5_model, cfg.writer_model, temperature=0.5)

        # Filtrar preguntas complejas de M1 (bloom Level 2/3) como historial de referencia.
        # Prioridad: synthesis → evaluation → analysis. Máx 3 para no saturar el contexto.
        all_q = state.get("doc1_preguntas", [])
        complex_q = [q for q in all_q
                     if q.get("bloom_level") in ("analysis", "evaluation", "synthesis")]
        complex_q.sort(
            key=lambda q: {
                "synthesis": 0,
                "evaluation": 1,
                "analysis": 2,
            }.get(str(q.get("bloom_level", "")), 3)
        )
        # Fallback histórico: si no hay bloom_level, usar las últimas 3 disponibles.
        # Payloads nuevos de M1 tienen 3 preguntas balanceadas; el filtro anterior
        # debe capturar las preguntas complejas por bloom_level cuando el campo existe.
        if not complex_q and all_q:
            complex_q = all_q[-3:]

        context = _build_base_context(state)
        profile, family = _resolve_generation_focus(
            state, default_unresolved_ml_ds_to_classification=True
        )
        # `resolved_variant` is None for every cohort EXCEPT ml_ds+clf (set below); the M5
        # coherence wrapper passes it to the unselected-model guard (no-op when None), so
        # business / ml_ds-non-clf never enter Check A. This is the RESOLVED notebook variant
        # (lr_only/rf_only/lr_rf_contrast), NEVER `algorithm_mode` — passing the mode would
        # silently disable the guard.
        resolved_variant: str | None = None
        if profile == "ml_ds" and family == "clasificacion":
            _algoritmos_raw = _extract_state_algoritmos(state)
            _algorithm_mode = _extract_state_algorithm_mode(state)
            _variant, _q_variant_warning = _resolve_classification_notebook_variant(
                algorithm_mode=_algorithm_mode,
                algoritmos=_algoritmos_raw,
            )
            if _q_variant_warning:
                logger.warning(
                    "[m5_questions_generator] question variant fallback — "
                    "variant=%s algoritmos=%r reason: %s",
                    _variant,
                    _algoritmos_raw,
                    _q_variant_warning,
                )
            resolved_variant = _variant
        prompt_text = _resolve_family_prompt(
            state, M5_QUESTIONS_PROMPT_BY_FAMILY, M5_QUESTIONS_GENERATOR_PROMPT
        )
        # Issue #329 — business+clasificación: alinea el memorándum con el arco LR (#306/#319).
        # No-op para ml_ds y para business no-clasificación (mismo gate que el contenido).
        prompt_text = _maybe_business_classification_prompt(
            state, prompt_text, M5_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION
        )
        computed_metrics_block = (
            build_computed_metrics_block(state.get("m3_metrics_summary"))
            if family == "clasificacion"
            else ""
        )
        context.update({
            "m5_content": state.get("m5_content", ""),
            "doc1_preguntas_complejas": json.dumps(complex_q[:3], ensure_ascii=False),
            # main_risk_from_m3_m4 e implementation_timeframe vienen de _build_base_context
            "algorithm_mode": _extract_state_algorithm_mode(state) or "single",
            "computed_metrics_block": computed_metrics_block,
        })

        # Capture the formatted prompt so the coherence wrapper can CONCATENATE its correction
        # suffix onto it (never a second `.format()` — JSON schema + memorándum braces).
        formatted = prompt_text.format(**context)
        resultado: GeneradorPreguntasM5Output = llm.with_structured_output(
            GeneradorPreguntasM5Output
        ).invoke(formatted)

        preguntas = [p.model_dump() for p in resultado.preguntas]
        preguntas = _apply_m5_questions_coherence(
            llm=llm,
            prompt=formatted,
            state=state,
            preguntas_dict=preguntas,
            variant=resolved_variant,
            metrics_block=computed_metrics_block,
            dilema_brief=str(state.get("dilema_brief") or ""),
        )
        print(f"[m5_questions_generator] {len(preguntas)} memorándum final")
        return {"m5_questions": preguntas, "current_agent": "m5_questions_generator"}
    except RuntimeError:
        raise
    except (ValidationError, OutputParserException, ValueError) as e:
        logger.warning("[m5_questions_generator] OUTPUT INVÁLIDO (reintentando/fallando): %s", e)
        raise
    except Exception as e:
        err_msg = str(e)
        # Re-raise errores transitorios → LangGraph RetryPolicy dispara con backoff
        # (max 3 intentos: 1s → 2s → 4s con jitter — ver standard_retry línea ~2805).
        # Sin este re-raise, el RetryPolicy nunca se activa porque el nodo "retorna" en lugar de "lanzar".
        if _is_transient_llm_error(e):
            logger.warning("[m5_questions_generator] ERROR TRANSITORIO (reintentando): %s", err_msg)
            raise
        if getattr(e, "status_code", None) == 402:
            logger.warning("[m5_questions_generator] OpenRouter SIN CRÉDITOS (402) — degradado a Gemini falló; recargar saldo")
        logger.error("[m5_questions_generator] ERROR: %s", e, exc_info=True)
        return {"m5_questions": [], "current_agent": "m5_questions_generator"}


# ─────────────────────────────────────────────────────────
# FASE 4 — NODOS NUEVOS v8
# ─────────────────────────────────────────────────────────

# ══════════════════════════════════════════════════════════════════════════════
# ALGORITHM FAMILY DETECTION — Issue #233
# Single source of truth lives in suggest_service.ALGORITHM_CATALOG. The legacy
# graph-local ALGORITHM_REGISTRY (9 keys with `_tabular` suffixes) was deleted
# so we cannot drift from the catalog the teacher form actually exposes.
# ══════════════════════════════════════════════════════════════════════════════


def _detect_algorithm_families(algoritmos: list[str]) -> list[str]:
    """Return the canonical 4-family keys for a list of algorithms.

    Resolution order per algorithm:
      1. ``family_of(name)``     — exact catalog match (Issue #233 catalog).
      2. ``resolve_legacy_family(name)`` — substring fallback for historical
         jobs (XGBoost, Ridge, Prophet pre-rename, NLP/recomendación, ...).
      3. ``"unsupported"``       — surfaces as a notebook warning.

    Issue #230 contract: ``len(algoritmos) ∈ {1, 2}`` — the teacher form picks
    exactly 1 (single mode) or 2 (contrast mode) algorithms. In contrast mode
    the family-coherence rule guarantees both share the same family, so the
    returned list is always length 1 (or ["unsupported"] if neither resolves).
    """
    detected: list[str] = []
    for algo in algoritmos:
        family = family_of(algo)
        if family is None:
            legacy = resolve_legacy_family(algo)
            family = legacy[0] if legacy else "unsupported"
        if family not in detected:
            detected.append(family)
    return detected


def _resolve_primary_family(
    algoritmos: list[str],
) -> tuple[str | None, str | None]:
    """Resolve the first algorithm to a canonical 4-family key.

    Issue #237 — DRY helper extracted from ``m3_notebook_generator`` so the
    EDA chart generator can apply the exact same dispatch chain without
    duplicating the resolution loop. Returns ``(family, legacy_warning)``:

      * ``family`` is one of ``{"clasificacion","regresion","clustering",
        "serie_temporal"}`` or ``None`` when neither the canonical catalog
        nor the legacy substring map can place the first algorithm.
      * ``legacy_warning`` is non-empty only when the legacy fallback fired
        and produced a teacher-facing message.

    Callers decide what to do with ``None`` (M3 falls back to
    ``"clasificacion"`` with a warning; EDA falls through to the
    profile-based LLM path).
    """
    for algo in algoritmos:
        family = family_of(algo)
        if family is not None:
            return family, None
    for algo in algoritmos:
        legacy = resolve_legacy_family(algo)
        if legacy is not None:
            return legacy[0], legacy[1]
    return None, None


def _extract_state_algoritmos(state: ADAMState) -> list[str]:
    """Read algorithm picks from canonical state, with task_payload fallback."""
    raw_algoritmos = state.get("algoritmos") or []
    if not raw_algoritmos:
        task_payload = state.get("task_payload") or {}
        if isinstance(task_payload, dict):
            raw_algoritmos = task_payload.get("algoritmos") or []
    if not isinstance(raw_algoritmos, list):
        return []
    return [str(algorithm) for algorithm in raw_algoritmos if str(algorithm).strip()]


def _extract_state_algorithm_mode(state: ADAMState) -> str | None:
    """Read the teacher algorithm mode from graph state, with payload fallback."""
    raw_mode = state.get("algorithm_mode")
    if raw_mode is None:
        task_payload = state.get("task_payload") or {}
        if isinstance(task_payload, dict):
            raw_mode = task_payload.get("algorithm_mode")
    mode = str(raw_mode or "").strip().lower()
    return mode if mode in {"single", "contrast"} else None


def _normalize_algorithm_pick(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _safe_contract_target_name(schema_required: object) -> str:
    """Resolve the contract target name for safe injection into the executed
    ``dummy_baseline`` cell (#348).

    The name is LLM-generated (``schema_designer``) and is only *described* as
    snake_case in the schema Field — there is NO upstream validator — yet #353
    injects it as a Python string literal (``_contract_target = "<name>"``) into
    the notebook that the executor runs. To keep that LLM→executable-code
    boundary airtight, ONLY a valid Python identifier is allowed through;
    anything carrying quotes, spaces, operators or newlines (the code-injection
    vectors) falls back to ``""`` so the cell uses the safe alias-first path.
    Mirrors the ``.isidentifier()`` guard in ``m3_notebook_repair``. The
    executor's AST scrub remains the defense-in-depth backstop.
    """
    if not isinstance(schema_required, dict):
        return ""
    spec = schema_required.get("target_column")
    if not isinstance(spec, dict):
        return ""
    name = (spec.get("name") or "").strip()
    return name if name.isidentifier() else ""


def _resolve_eda_target_name(state: ADAMState) -> str:
    """Resolve the target column name the M2 EDA narrative must cite (Issue #383).

    For ml_ds + clasificacion, ``_align_ml_ds_classification_target`` renames the fixed
    ``categoria`` binary to the contract domain name (e.g. ``fraud_flag``) in
    ``schema_designer`` — BEFORE this node runs. The classification EDA prompt must cite
    that real name instead of the hardcoded literal ``categoria`` (the follow-up that
    #346 / #382 deferred).

    Returns the literal ``"categoria"`` for everything outside ml_ds+clasificacion
    (business — including business+clf, which still gets the classification prompt — and
    the regresion/clustering/serie_temporal families), so the shared prompt body renders
    byte-identically for those cases.

    Gate uses ``default_unresolved_ml_ds_to_classification=True`` to mirror BOTH the prompt
    selection (``_build_base_context``) and the data layer (``_align`` treats an ml_ds job
    with unresolved/empty algoritmos as clasificacion); otherwise that cohort would render
    the classification prompt + a renamed dataset column while still narrating "categoria".

    The contract name is the intended target, but ``_align`` skips its rename on a name
    collision (leaving the dataset column as ``categoria``). To guarantee the narrated name
    matches the column the LLM actually sees, the contract name is verified against the real
    dataset columns; the prompt's own "si no existe, reporta la columna más cercana" line is
    the final safety net.
    """
    if not _is_ml_ds_classification(
        state, default_unresolved_ml_ds_to_classification=True
    ):
        return "categoria"
    contract_name = _safe_contract_target_name(state.get("dataset_schema_required"))
    if not contract_name:
        return "categoria"
    dataset = state.get("doc7_dataset") or []
    sample = next((row for row in dataset[:5] if isinstance(row, dict)), None)
    if sample is not None:
        if contract_name in sample:
            return contract_name          # rename applied (happy path)
        if "categoria" in sample:
            return "categoria"            # rename skipped (collision) → match the data
    return contract_name                  # no dataset sample → trust the contract name


def _resolve_classification_notebook_variant(
    *,
    algorithm_mode: str | None,
    algoritmos: list[str],
) -> tuple[ClassificationNotebookVariant, str | None]:
    """Resolve LR-only, RF-only, or LR/RF contrast for classification notebooks.

    Intake now prevents malformed current jobs, but historical rows and resumed
    checkpoints may lack ``algorithm_mode``. Those legacy cases infer from the
    concrete algorithm list and fall back to contrast with a warning so old jobs
    preserve the previous broad classification behavior.
    """
    normalized = {_normalize_algorithm_pick(algo) for algo in algoritmos}
    has_lr = bool({"logisticregression", "lr"} & normalized)
    has_rf = bool({"randomforest", "rf"} & normalized)

    if algorithm_mode == "single":
        if has_lr and not has_rf:
            return CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY, None
        if has_rf and not has_lr:
            return CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY, None
        return (
            CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST,
            "Modo single de clasificación no coincidió exactamente con Logistic Regression "
            f"o Random Forest (algoritmos={algoritmos!r}); se usó variante contraste legacy.",
        )

    if algorithm_mode == "contrast" and has_lr and has_rf:
        return CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST, None

    if algorithm_mode is None:
        if has_lr and not has_rf:
            return CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY, None
        if has_rf and not has_lr:
            return CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY, None
        if has_lr and has_rf:
            return CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST, None

    return (
        CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST,
        "No se pudo resolver una variante específica de notebook de clasificación "
        f"(algorithm_mode={algorithm_mode!r}, algoritmos={algoritmos!r}); "
        "se usó variante contraste legacy.",
    )


def _resolve_generation_focus(
    state: ADAMState,
    *,
    default_unresolved_ml_ds_to_classification: bool = False,
) -> tuple[str, str | None]:
    """Return normalized ``(student_profile, primary_family)`` for graph gates."""
    profile = str(state.get("studentProfile", "business") or "business").strip().lower()
    if profile not in {"business", "ml_ds"}:
        profile = "business"
    family, _legacy_warning = _resolve_primary_family(_extract_state_algoritmos(state))
    if (
        family is None
        and default_unresolved_ml_ds_to_classification
        and profile == "ml_ds"
    ):
        family = "clasificacion"
    return profile, family


def _resolve_impact_lens(state: ADAMState) -> str:
    """Return the case's resolved Impact Lens (value frame for M4) — Issue #437.

    DD1 single source of truth. Precedence (D-A hybrid):
      0. ``state["impact_lens_override"]`` — the OPTIONAL teacher override (Fase 3), HIGHEST priority.
         Validated by MEMBERSHIP in ``IMPACT_LENS_KEYS`` (NOT ``normalize_impact_lens``): an invalid/
         absent value FALLS THROUGH rather than coercing to the default, so a garbage value from a
         cached client / direct API call can never forge a ``financial_roi`` override that would beat
         the architect's ``value_model``. Intake-only (re-injected by ``state_input`` every attempt) ⇒
         resume-stable; no node writes it (no last-write-wins clobber).
      1. ``state["value_model"]["lens"]`` — the architect's more-informed refinement (Fase 2). It
         is WRITTEN only when the architect lens block is enabled (``impact_lens_architect`` at
         case_architect time), so on the normal flow its presence encodes the kill-switch. (Edge:
         if the switch is flipped OFF and a job that already persisted value_model is RESUMED,
         case_architect is skip-short-circuited and never clears it, so the refined lens still
         wins — benign, since a persisted refinement beats the intake default and it never raises.)
         It is **resume-robust**: ``value_model`` is NOT re-injected by ``state_input`` on resume,
         so the durable checkpoint value survives — unlike ``impact_lens``, which ``state_input``
         re-injects with the intake value on every attempt (last-write-wins), clobbering any
         refinement back to intake on a resumed job.
      2. ``state["impact_lens"]`` — the intake-resolved lens (Fase 1, from the constrained industry
         label; never re-derived from the architect's free-noun ``industria``).
      3. ``DEFAULT_IMPACT_LENS``.

    Total + safe: any missing/legacy/unknown value coerces to the default; never raises. Every M1/M4/
    M5/M6 consumer READS this (never re-derives), so all consume the SAME lens even on a resumed job.
    """
    override = state.get("impact_lens_override")
    if override in IMPACT_LENS_KEYS:
        return override
    vm = state.get("value_model")
    if isinstance(vm, dict):
        vm_lens = vm.get("lens")
        if vm_lens in IMPACT_LENS_KEYS:
            return normalize_impact_lens(vm_lens)
    return normalize_impact_lens(state.get("impact_lens", DEFAULT_IMPACT_LENS))


def _maybe_business_classification_prompt(
    state: ADAMState, default_prompt: str, business_clasif_prompt: str
) -> str:
    """Swap to the business+classification LR prompt variant; else keep ``default_prompt``.

    Issue #306 — shared gate for M4/M5 (DRY): only business + family==clasificacion gets the
    LR-business block (mirrors the M3 gate of ``M3_AUDIT_LR_BUSINESS_BLOCK``). ml_ds and
    business non-classification keep their original prompt untouched. The variant is purely
    additive (base + block), so ``.format(**context)`` is unaffected — no new placeholder.
    """
    profile, family = _resolve_generation_focus(state)
    if profile == "business" and family == "clasificacion":
        return business_clasif_prompt
    return default_prompt


def _is_ml_ds_classification(
    state: ADAMState,
    *,
    default_unresolved_ml_ds_to_classification: bool = False,
) -> bool:
    profile, family = _resolve_generation_focus(
        state,
        default_unresolved_ml_ds_to_classification=default_unresolved_ml_ds_to_classification,
    )
    return profile == "ml_ds" and family == "clasificacion"


def _is_classification_family(state: ADAMState) -> bool:
    """True for ANY profile (business OR ml_ds) when the resolved family is clasificación.

    Mirrors the family resolution `_build_base_context` uses for ``primary_family``
    (``default_unresolved_ml_ds_to_classification=True``), so this fires exactly when the
    classification M1 questions prompt was selected — covering BOTH ``business+clf`` and
    ``ml_ds+clf``. (Contrast with `_is_ml_ds_classification`, which is ml_ds-only.)
    """
    _profile, family = _resolve_generation_focus(
        state, default_unresolved_ml_ds_to_classification=True
    )
    return family == "clasificacion"


def _sanitize_pregunta_eje(
    pregunta_eje: str | None,
    *,
    profile: str,
    family: str | None,
) -> str | None:
    if profile != "ml_ds" or family != "clasificacion":
        return None
    if pregunta_eje is None:
        return None
    normalized = " ".join(str(pregunta_eje).split())
    return normalized or None


def _issue242_contract_required(state: ADAMState) -> bool:
    return _is_ml_ds_classification(
        state,
        default_unresolved_ml_ds_to_classification=True,
    )


def _invoke_case_architect_with_contract(
    *,
    llm: Any,
    prompt: str,
    state: ADAMState,
) -> tuple[CaseArchitectOutput, str, str | None, str | None]:
    profile, family = _resolve_generation_focus(
        state,
        default_unresolved_ml_ds_to_classification=True,
    )
    structured_llm = llm.with_structured_output(CaseArchitectOutput)
    result: CaseArchitectOutput = structured_llm.invoke(prompt)
    pregunta_eje = _sanitize_pregunta_eje(
        result.pregunta_eje,
        profile=profile,
        family=family,
    )

    if not _issue242_contract_required(state) or pregunta_eje:
        return result, profile, family, pregunta_eje

    logger.warning(
        "[case_architect] pregunta_eje ausente para ml_ds+clasificacion; reprompt 1/1",
        extra={"case_id": state.get("case_id")},
    )
    reprompt = (
        prompt
        + "\n\n# CORRECCIÓN OBLIGATORIA DE PREGUNTA EJE (Issue #242)\n"
        + "Tu salida anterior omitió `pregunta_eje`. Reescribe la respuesta "
        + "COMPLETA respetando el schema y emitiendo `pregunta_eje` como una "
        + "pregunta directiva gerencial concreta para ml_ds + clasificación. "
        + "No menciones Python, notebooks, AUC, F1 ni hiperparámetros."
    )
    result = structured_llm.invoke(reprompt)
    pregunta_eje = _sanitize_pregunta_eje(
        result.pregunta_eje,
        profile=profile,
        family=family,
    )
    if not pregunta_eje:
        raise RuntimeError(
            "case_architect no emitió pregunta_eje para ml_ds+clasificacion "
            "tras un reprompt. Job marcado como fallido para evitar un caso "
            "sin eje pedagógico M1-M5."
        )
    return result, profile, family, pregunta_eje


# Narrative grounding provenance (Issue #336):
#   m3_content (pre-executor): m3_metrics_summary is ALWAYS None here because the
#       executor runs AFTER m3_content_generator → reason="missing" → log.info, and
#       NO state warning is persisted (A2). This is benign/expected design narrative,
#       not a failure. The "anchorless" branch is unreachable for M3.
#   m4/m5 (post-executor): metrics may be legitimately missing/anchorless → log.warning
#       + persist NARRATIVE_GROUNDING_WARNING (the genuine, actionable failure signal).
def _prepare_classification_narrative_grounding(
    state: ADAMState,
    family: str | None,
    node_name: str,
) -> tuple[str, bool, dict[str, str]]:
    if family != "clasificacion":
        return "", False, {}

    metrics_summary = state.get("m3_metrics_summary")
    metrics_block = build_computed_metrics_block(metrics_summary)
    if metrics_summary is None or not has_metric_anchors(metrics_block):
        reason = "missing" if metrics_summary is None else "anchorless"
        if node_name == "m3_content_generator":
            # Pre-execution by graph order (Issue #336): m3_metrics_summary is
            # structurally None at M3-content time. Expected by design, not a failure
            # → INFO, and DO NOT persist the state warning. The non-empty
            # narrative_grounding_warning is reserved for the genuine M4/M5 failure
            # signal below so the two origins stay distinguishable in state and log.
            logger.info(
                "[narrative_grounding] m3_content pre-ejecucion: m3_metrics_summary "
                "ausente por diseno (grounding deshabilitado, sin warning de estado)",
                extra={
                    "case_id": state.get("case_id"),
                    "node": node_name,
                    "family": family,
                    "reason": reason,
                },
            )
            return metrics_block, False, {}
        logger.warning(
            "[narrative_grounding] m3_metrics_summary ausente o sin anclas numericas",
            extra={
                "case_id": state.get("case_id"),
                "node": node_name,
                "family": family,
                "reason": reason,
            },
        )
        return metrics_block, False, {
            "narrative_grounding_warning": NARRATIVE_GROUNDING_WARNING
        }
    return metrics_block, True, {}


def _resolve_family_prompt(
    state: ADAMState,
    prompt_by_family: dict[str, str],
    default_prompt: str,
) -> str:
    """Return the family-specific prompt for non-narrative M4 nodes (questions, charts).

    Mirrors the family-resolution logic used by ``_select_narrative_prompt`` but
    without narrative grounding: no metrics block, no reprompt loop.  The caller
    is responsible for injecting ``algorithm_mode`` and ``computed_metrics_block``
    into the context dict separately.

    Family dispatch is ONLY applied for ``ml_ds`` profiles — non-ml_ds profiles
    (e.g. ``business``) always receive ``default_prompt``.  This mirrors
    ``_select_narrative_prompt``'s gating logic exactly.
    """
    effective_family: str | None = None  # stays None for non-ml_ds → returns default
    profile, resolved_family = _resolve_generation_focus(state)
    if profile == "ml_ds":
        effective_family = resolved_family
        if effective_family is None:
            effective_family = "clasificacion"
            logger.warning(
                "[m4_dispatch] family unresolved for ml_ds; defaulting to clasificacion",
                extra={"case_id": state.get("case_id"), "algoritmos": _extract_state_algoritmos(state)},
            )
    return prompt_by_family.get(effective_family or "", default_prompt)


def _select_narrative_prompt(
    state: ADAMState,
    node_name: str,
    prompt_by_family: dict[str, str],
    default_prompt: str,
) -> tuple[str, str, bool, dict[str, str]]:
    family: str | None = None
    profile, resolved_family = _resolve_generation_focus(state)
    if profile == "ml_ds":
        family = resolved_family
        # Mirror the m3_notebook_generator dispatcher: when neither the canonical
        # catalog nor the legacy resolver places the first algorithm, fall back to
        # 'clasificacion' so M3-content/M4/M5 narratives keep grounding on for
        # ml_ds jobs with legacy/unknown algos instead of silently degrading to
        # the default prompt with no validation.
        if family is None:
            family = "clasificacion"
            logger.warning(
                "[narrative_grounding] family unresolved; defaulting to clasificacion",
                extra={
                    "case_id": state.get("case_id"),
                    "node": node_name,
                    "algoritmos": _extract_state_algoritmos(state),
                },
            )
    metrics_block, grounding_enabled, grounding_update = (
        _prepare_classification_narrative_grounding(state, family, node_name)
    )
    return (
        prompt_by_family.get(family or "", default_prompt),
        metrics_block,
        grounding_enabled,
        grounding_update,
    )


def _invoke_narrative_with_grounding(
    *,
    node_name: str,
    llm: Any,
    prompt: str,
    metrics_block: str,
    grounding_enabled: bool,
    variant: str | None = None,
) -> str:
    response = llm.invoke(prompt)
    prose = sanitize_markdown(_extract_text(response))
    # Issue #337 — the model-leak guard runs BEFORE the grounding gate: with
    # grounding disabled (missing/anchorless m3_metrics_summary) the prompt is the
    # only defense, so gating the leak check behind grounding would make it dead
    # code exactly when it is needed. ``detect_unselected_model_mentions`` is a
    # no-op ([]) for contrast / None / non-classification → byte-identical there.
    leak_violations = detect_unselected_model_mentions(prose, variant)
    grounding_violations = (
        validate_narrative_grounding(prose, metrics_block) if grounding_enabled else []
    )
    violations = grounding_violations + leak_violations
    if not violations:
        return prose

    contextualized_violations = (
        contextualize_grounding_violations(prose, grounding_violations) + leak_violations
    )
    bullet_list = "\n".join(f"- {violation}" for violation in contextualized_violations)
    print(
        f"[{node_name}] Violaciones narrative grounding detectadas: "
        f"{violations}. Reprompt explícito (1/1)."
    )
    reprompt = (
        prompt
        + "\n\n# CORRECCIÓN OBLIGATORIA DE GROUNDING NARRATIVO\n"
        + "Tu salida anterior violó el contrato de grounding. Reescribe la "
        + "salida COMPLETA sin citas externas y corrigiendo las métricas "
        + "de rendimiento o interpretabilidad del modelo no ancladas al "
        + "bloque de métricas incluido arriba. Violaciones detectadas:\n"
        + bullet_list
    )
    if leak_violations:
        reprompt += (
            "\n\n# RECORDATORIO — MODELO NO SELECCIONADO\n"
            "Esta narrativa es de un solo modelo: NO nombres el modelo no "
            "seleccionado (ver violaciones 'MODELO_NO_SELECCIONADO' arriba)."
        )
    response2 = llm.invoke(reprompt)
    prose = sanitize_markdown(_extract_text(response2))
    leak_violations2 = detect_unselected_model_mentions(prose, variant)
    grounding_violations2 = (
        validate_narrative_grounding(prose, metrics_block) if grounding_enabled else []
    )
    violations2 = grounding_violations2 + leak_violations2
    if violations2:
        contextualized_violations2 = (
            contextualize_grounding_violations(prose, grounding_violations2)
            + leak_violations2
        )
        logger.error(
            "[%s] Reprompt narrative grounding falló — violations=%s",
            node_name,
            contextualized_violations2,
        )
        raise RuntimeError(
            f"{node_name} narrative grounding falló incluso tras un reprompt: "
            f"{contextualized_violations2}. Job marcado como fallido para evitar narrativa "
            "con números o citas no ancladas."
        )
    print(f"[{node_name}] Reprompt narrative grounding OK")
    return prose


_M5_DECISION_MATRIX_COLUMNS = ("acción", "KPI esperado", "riesgo", "modelo soporte")
_M5_DECISION_MATRIX_HEADER_ALIASES = {
    "accion": "accion",
    "accion ejecutiva": "accion",
    "accion recomendada": "accion",
    "kpi esperado": "kpi esperado",
    "indicador esperado": "kpi esperado",
    "riesgo": "riesgo",
    "riesgo principal": "riesgo",
    "modelo soporte": "modelo soporte",
    "modelo de soporte": "modelo soporte",
    "soporte modelo": "modelo soporte",
}


def _split_markdown_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped or "|" not in stripped:
        return []
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_markdown_separator_row(cells: list[str]) -> bool:
    if not cells:
        return False
    for cell in cells:
        compact = cell.replace(" ", "")
        if re.fullmatch(r":?-{3,}:?", compact) is None:
            return False
    return True


def _normalize_m5_matrix_header_cell(cell: str) -> str:
    compact = " ".join(cell.lower().split())
    without_accents = "".join(
        char
        for char in unicodedata.normalize("NFKD", compact)
        if not unicodedata.combining(char)
    )
    return _M5_DECISION_MATRIX_HEADER_ALIASES.get(without_accents, without_accents)


def _normalize_m5_matrix_header(cells: list[str]) -> tuple[str, ...]:
    return tuple(_normalize_m5_matrix_header_cell(cell) for cell in cells)


def _validate_m5_decision_matrix(markdown: str) -> list[str]:
    """Validate the Issue #242 M5 decision matrix Markdown contract."""
    expected = _normalize_m5_matrix_header(list(_M5_DECISION_MATRIX_COLUMNS))
    lines = markdown.splitlines()
    for line_index, line in enumerate(lines):
        header_cells = _split_markdown_table_row(line)
        if _normalize_m5_matrix_header(header_cells) != expected:
            continue
        if line_index + 1 >= len(lines):
            return ["missing_separator: la tabla no tiene fila separadora Markdown"]
        separator_cells = _split_markdown_table_row(lines[line_index + 1])
        if len(separator_cells) != len(expected) or not _is_markdown_separator_row(separator_cells):
            return ["invalid_separator: usa una fila Markdown tipo |---|---|---|---|"]

        row_count = 0
        malformed_rows: list[int] = []
        for data_index, data_line in enumerate(lines[line_index + 2 :], start=line_index + 3):
            data_cells = _split_markdown_table_row(data_line)
            if not data_cells:
                break
            if _is_markdown_separator_row(data_cells):
                continue
            if len(data_cells) != len(expected):
                malformed_rows.append(data_index)
                continue
            row_count += 1

        violations: list[str] = []
        if malformed_rows:
            violations.append(f"malformed_rows: filas con columnas inválidas {malformed_rows}")
        if not 4 <= row_count <= 6:
            violations.append(
                f"row_count: la matriz debe tener 4-6 filas de datos; tiene {row_count}"
            )
        return violations

    return [
        "missing_matrix: falta tabla Markdown con columnas exactas "
        "acción | KPI esperado | riesgo | modelo soporte"
    ]


def _invoke_m5_content_with_contract(
    *,
    llm: Any,
    prompt: str,
    metrics_block: str,
    grounding_enabled: bool,
    require_decision_matrix: bool,
    variant: str | None = None,
) -> str:
    prose = _invoke_narrative_with_grounding(
        node_name="m5_content_generator",
        llm=llm,
        prompt=prompt,
        metrics_block=metrics_block,
        grounding_enabled=grounding_enabled,
        variant=variant,
    )
    if not require_decision_matrix:
        return prose

    matrix_violations = _validate_m5_decision_matrix(prose)
    if not matrix_violations:
        return prose

    bullet_list = "\n".join(f"- {violation}" for violation in matrix_violations)
    print(
        "[m5_content_generator] Matriz de decisión M5 inválida. "
        "Reprompt explícito (1/1)."
    )
    reprompt = (
        prompt
        + "\n\n# CORRECCIÓN OBLIGATORIA DE MATRIZ DE DECISIÓN M5\n"
        + "Reescribe la salida COMPLETA manteniendo el contrato de grounding "
        + "narrativo y agregando una tabla Markdown de matriz de decisión con "
        + "exactamente estas columnas: acción | KPI esperado | riesgo | modelo soporte. "
        + "La tabla debe tener entre 4 y 6 filas de datos. Violaciones detectadas:\n"
        + bullet_list
    )
    response = llm.invoke(reprompt)
    corrected = sanitize_markdown(_extract_text(response))
    grounding_violations = (
        validate_narrative_grounding(corrected, metrics_block)
        if grounding_enabled
        else []
    )
    corrected_matrix_violations = _validate_m5_decision_matrix(corrected)
    # Issue #337 — the matrix reprompt can reintroduce a leak in the "modelo
    # soporte" cell, so re-check the unselected model UNCONDITIONALLY (never gated
    # by grounding_enabled). Scan ``corrected`` (raw prose, matrix included), never
    # a KPI-stripped variant. No-op ([]) for contrast / None.
    leak_violations_2 = detect_unselected_model_mentions(corrected, variant)
    if grounding_violations or corrected_matrix_violations or leak_violations_2:
        logger.error(
            "[m5_content_generator] Reprompt M5 falló — grounding=%s matrix=%s fuga=%s",
            grounding_violations,
            corrected_matrix_violations,
            leak_violations_2,
        )
        raise RuntimeError(
            "m5_content_generator falló validación de matriz de decisión o "
            "grounding tras un reprompt. Job marcado como fallido."
        )
    print("[m5_content_generator] Reprompt matriz de decisión OK")
    return corrected

# Issue 4.1 — M3 CONTENT GENERATOR
def m3_content_generator(state: ADAMState, config: RunnableConfig) -> dict:
    """M3 bifurcado por perfil:
    - business: Auditor de Evidencia (M3_AUDIT_PROMPT)     → m3_mode = "audit"
    - ml_ds:    Architect Engineer   (M3_EXPERIMENT_PROMPT) → m3_mode = "experiment"

    Solo se ejecuta en harvard_with_eda (el grafo lo salta en harvard_only).
    """
    try:
        cfg = Configuration.from_runnable_config(config)

        context = _build_base_context(state)
        context.update({
            "contexto_m1": state.get("doc1_narrativa", "")[:8000],
            "contexto_m2": state.get("doc2_eda", "") or "DATASET_UNAVAILABLE",
            # Default vacío: solo business+clasificacion lo rellena (más abajo).
            # M3_AUDIT_PROMPT referencia {lr_business_block}; los prompts ml_ds no,
            # así que la clave extra es ignorada por .format() en ese branch.
            "lr_business_block": "",
        })

        profile = state.get("studentProfile", "business")
        grounding_update: dict[str, str] = {}
        metrics_block = ""
        grounding_enabled = False
        if profile == "ml_ds":
            # Resolve the classification narrative variant (lr_only / rf_only /
            # lr_rf_contrast) so the LLM only receives sections relevant to the
            # algorithms the teacher actually selected. This mirrors the existing
            # notebook variant dispatch and eliminates hallucinated RF content in
            # single-LR jobs (and vice-versa for single-RF jobs).
            _algoritmos_raw = _extract_state_algoritmos(state)
            _algorithm_mode = _extract_state_algorithm_mode(state)
            _primary_family, _ = _resolve_primary_family(_algoritmos_raw)
            if _primary_family == "clasificacion":
                _variant, _narrative_variant_warning = _resolve_classification_notebook_variant(
                    algorithm_mode=_algorithm_mode,
                    algoritmos=_algoritmos_raw,
                )
                if _narrative_variant_warning:
                    logger.warning(
                        "[m3_content_generator] narrative variant fallback — "
                        "variant=%s algoritmos=%r reason: %s",
                        _variant,
                        _algoritmos_raw,
                        _narrative_variant_warning,
                    )
                _effective_prompt_by_family: dict[str, str] = {
                    **M3_CONTENT_PROMPT_BY_FAMILY,
                    "clasificacion": M3_CONTENT_PROMPT_CLASSIFICATION_BY_VARIANT[_variant],
                }
            else:
                _effective_prompt_by_family = M3_CONTENT_PROMPT_BY_FAMILY
            prompt, metrics_block, grounding_enabled, grounding_update = _select_narrative_prompt(
                state,
                "m3_content_generator",
                _effective_prompt_by_family,
                M3_EXPERIMENT_PROMPT,
            )
            tag = "m3_experiment_engineer"
            m3_mode = "experiment"
            # ml_ds: el m3_content alimenta directamente el prompt del notebook
            # generator. Calidad de razonamiento aquí ⇒ menos ambigüedad en la
            # sección 3 (hipótesis, criterio de descarte, sesgos). Por eso Pro-
            # medium con cadena de fallback (Pro-low → Flash-low).
            # Modelos vía Configuration para respetar overrides por env var
            # (ARCHITECT_MODEL / WRITER_MODEL) — útil para rollouts y tests.
            _m3_common = dict(
                model=resolve_node_model(cfg, NODE_M3_CONTENT, cfg.architect_model),
                temperature=0.6,
                max_retries=2,
                max_output_tokens=16384,
                api_key=os.getenv("GEMINI_API_KEY"),
                rate_limiter=_rate_limiter,
            )
            primary = ChatGoogleGenerativeAI(thinking_level="medium", **_m3_common)
            pro_low = ChatGoogleGenerativeAI(thinking_level="low", **_m3_common)
            # Flash fallback: thinking_level="low" explícito (no dependemos del
            # default del SDK). "low" basta porque ya estamos en modo degradado
            # por incidente global de Pro y queremos minimizar latencia extra.
            flash_fb = ChatGoogleGenerativeAI(
                model=cfg.writer_model,
                temperature=0.6,
                thinking_level="low",
                max_retries=2,
                max_output_tokens=16384,
                api_key=os.getenv("GEMINI_API_KEY"),
                rate_limiter=_rate_limiter,
            )
            llm = primary.with_fallbacks([pro_low, flash_fb])
        else:
            prompt = M3_AUDIT_PROMPT
            tag = "m3_audit"
            m3_mode = "audit"
            # LR-business (light, Issue 3A): si el algoritmo es de la familia
            # clasificacion (p. ej. Logistic Regression), inyectamos el bloque que
            # hace al auditor razonar sobre la decisión apoyada en el modelo, en
            # lenguaje gerencial y SIN jerga DS. Otras familias business → sin bloque.
            _business_family, _ = _resolve_primary_family(_extract_state_algoritmos(state))
            if _business_family == "clasificacion":
                context["lr_business_block"] = M3_AUDIT_LR_BUSINESS_BLOCK
            # business: contenido narrativo de auditoría sin notebook downstream;
            # Flash-medium con fallback a 2.5-flash (ya en _get_writer_llm) basta.
            llm = _get_writer_llm(cfg.writer_model, temperature=0.6, thinking_level="medium")

        context["computed_metrics_block"] = metrics_block
        m3 = _invoke_narrative_with_grounding(
            node_name="m3_content_generator",
            llm=llm,
            prompt=prompt.format(**context),
            metrics_block=metrics_block,
            grounding_enabled=grounding_enabled,
        )
        print(f"[{tag}] {len(m3)} chars | m3_mode={m3_mode}")
        return {
            "m3_content": m3,
            "m3_mode": m3_mode,
            "current_agent": "m3_content_generator",
            **grounding_update,
        }
    except RuntimeError:
        raise
    except Exception as e:
        logger.error("[m3_content_generator] ERROR: %s", e, exc_info=True)
        return {"m3_content": "[M3_NOT_EXECUTED]", "m3_mode": "audit"}


# Issue 4.3 — M3 QUESTIONS GENERATOR
# ─────────────────────────────────────────────────────────
# M3 question coherence — reprompt-once-then-DEGRADE (M3 sibling of #412/#413).
# Mirrors `_apply_eda_questions_coherence`. The pure validator lives in m3_grounding.py;
# this gates it to the classification family for BOTH profiles behind the
# `m3_question_coherence` kill-switch and reprompts once on a violation.
# ─────────────────────────────────────────────────────────

_M3_VIOLATION_CODES = (
    ("M3_SECTION_REF_NONEXISTENT", "section_ref"),
    ("MODELO_NO_SELECCIONADO", "unselected_model"),
)


def _m3_violation_types(violations: list[str]) -> list[str]:
    """Enumerated short codes for structured logging — never the raw message (no PII)."""
    codes: list[str] = []
    for violation in violations:
        for prefix, code in _M3_VIOLATION_CODES:
            if violation.startswith(prefix) and code not in codes:
                codes.append(code)
    return codes


def _build_m3_coherence_reprompt(
    violations: list[str], *, profile: str, variant: str | None, numeros: list[Any]
) -> str:
    """Focused reprompt (CONCATENATED, never ``.format`` — the already-formatted prompt and
    this suffix both carry ``{}`` from the JSON schema). Carries the concrete fix (the valid
    section tokens for the profile + the forbidden model when single-model) and demands the
    SAME questions with the SAME ``numero`` so the downstream ``M3-Q{numero}`` answer/grading
    key is preserved — load-bearing because ``GeneradorPreguntasOutput`` does NOT bound length.
    """
    bullet_list = "\n".join(f"- {violation}" for violation in violations)
    valid_sections = ", ".join(sorted(allowed_sections_for(profile)))
    forbidden_line = ""
    if variant == CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY:
        forbidden_line = "NO menciones Random Forest (el modelo seleccionado es Logistic Regression).\n"
    elif variant == CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY:
        forbidden_line = "NO menciones Logistic Regression (el modelo seleccionado es Random Forest).\n"
    numeros_str = ", ".join(str(numero) for numero in numeros)
    return (
        "\n\n# CORRECCIÓN OBLIGATORIA DE COHERENCIA (Módulo 3)\n"
        "Algunas preguntas citan una sección inexistente en `m3_section_ref` o nombran un "
        "modelo no seleccionado. "
        f"Regenera EXACTAMENTE {len(numeros)} preguntas con el MISMO schema y los MISMOS "
        f"`numero` ({numeros_str}): cada `m3_section_ref` debe ser una sección válida del "
        "Módulo 3 y ninguna pregunta debe nombrar el modelo no seleccionado.\n"
        f"Secciones válidas: {valid_sections}.\n"
        f"{forbidden_line}"
        "Incoherencias detectadas:\n" + bullet_list
    )


def _apply_m3_questions_coherence(
    *,
    llm: Any,
    prompt: str,
    state: ADAMState,
    preguntas_dict: list[dict],
    profile: str,
    variant: str | None,
) -> list[dict]:
    """Validate + reprompt-once-then-DEGRADE the M3 question coherence.

    Gated to the classification family for BOTH profiles (business + ml_ds) via
    ``_is_classification_family`` (the SAME gate M1/M2 use) behind the
    ``m3_question_coherence`` kill-switch; a byte-identical no-op otherwise. On a violation
    it reprompts ONCE (one Flash call) with the concrete fix; the corrected set is accepted
    ONLY if it preserves the question count AND the ``numero`` sequence (the answer/grading
    key ``M3-Q{numero}``) AND is now coherent — otherwise it degrades to the pass-1 questions.
    Best-effort: ANY throw (including a reprompt ``RuntimeError``, which the node would
    otherwise re-raise and fail the job) degrades to pass-1. Never raises.

    ``prompt`` is the ALREADY-formatted string; the reprompt is built by CONCATENATION (never
    re-``.format``). ``profile``/``variant`` are resolved by the caller and feed the two checks.
    ``state`` is read ONLY for the gate and ``case_id`` logging — never ``m3_content`` /
    ``m3_metrics_summary`` / the notebook branch — so the parallel notebook fan-out stays independent.
    """
    log_extra = {"node": "m3_questions_generator", "case_id": state.get("case_id")}
    try:
        if not settings.m3_question_coherence or not _is_classification_family(state):
            return preguntas_dict
        violations = validate_m3_questions_coherence(
            preguntas_dict, profile=profile, variant=variant
        )
        if not violations:
            return preguntas_dict
        numeros = [q.get("numero") for q in preguntas_dict]
        logger.info(
            "[m3_questions] reprompt de coherencia M3 disparado",
            extra={
                **log_extra,
                "violation_count": len(violations),
                "violation_types": _m3_violation_types(violations),
            },
        )
        reprompt = prompt + _build_m3_coherence_reprompt(
            violations, profile=profile, variant=variant, numeros=numeros
        )
        try:
            resultado: GeneradorPreguntasOutput = llm.with_structured_output(
                GeneradorPreguntasOutput
            ).invoke(reprompt)
            corrected = [p.model_dump() for p in resultado.preguntas]
        except (ValidationError, OutputParserException, ValueError) as exc:
            logger.warning(
                "[m3_questions] reprompt de coherencia M3 inválido — degrada a pass-1: %s",
                exc,
                extra=log_extra,
            )
            return preguntas_dict
        # Identity guard: a reprompt that drops/adds/renumbers a question would corrupt the
        # `M3-Q{numero}` answer/grading key — reject it. List equality = count + order + values,
        # and is the ONLY count protection because `GeneradorPreguntasOutput` is unbounded.
        if [q.get("numero") for q in corrected] != numeros:
            logger.warning(
                "[m3_questions] reprompt M3 alteró conteo/numero — degrada a pass-1",
                extra=log_extra,
            )
            return preguntas_dict
        residual = validate_m3_questions_coherence(corrected, profile=profile, variant=variant)
        if not residual:
            logger.info(
                "[m3_questions] coherencia M3 corregida por reprompt",
                extra={**log_extra, "degraded": False},
            )
            return corrected
        logger.warning(
            "[m3_questions] coherencia M3 degradada tras reprompt",
            extra={
                **log_extra,
                "violation_types": _m3_violation_types(residual),
                "degraded": True,
            },
        )
        return preguntas_dict
    except Exception as exc:  # best-effort — a coherence pass must never fail the job
        logger.warning(
            "[m3_questions] validador de coherencia M3 falló (best-effort): %s",
            exc,
            extra=log_extra,
        )
        return preguntas_dict


def m3_questions_generator(state: ADAMState, config: RunnableConfig) -> dict:
    """Genera preguntas de M3 bifurcadas por perfil:
    - business: M3_AUDIT_QUESTIONS_PROMPT    (3 preguntas, refs 3.1–3.5, auditoría de evidencia)
    - ml_ds:    M3_EXPERIMENT_QUESTIONS_PROMPT (3 preguntas, refs exp.*, diseño experimental)
    """
    try:
        cfg = Configuration.from_runnable_config(config)
        llm = _get_writer_llm(cfg.writer_model, temperature=0.5, thinking_level="low")

        context = _build_base_context(state)
        context.update({
            "eda_report": state.get("doc2_eda", "")[:4000],
            "m3_content": state.get("m3_content", ""),
        })

        profile, family = _resolve_generation_focus(state)
        # `resolved_variant` is None for every cohort EXCEPT ml_ds+clf (set below); the M3
        # coherence wrapper passes it to the unselected-model guard (no-op when None), so
        # business / ml_ds-non-clf never enter Check B. Initialized here so the call site
        # below always has it defined (no NameError on the else branches).
        resolved_variant: str | None = None
        if profile == "ml_ds":
            if family == "clasificacion":
                _algoritmos_raw = _extract_state_algoritmos(state)
                _algorithm_mode = _extract_state_algorithm_mode(state)
                _variant, _q_variant_warning = _resolve_classification_notebook_variant(
                    algorithm_mode=_algorithm_mode,
                    algoritmos=_algoritmos_raw,
                )
                if _q_variant_warning:
                    logger.warning(
                        "[m3_questions_generator] question variant fallback — "
                        "variant=%s algoritmos=%r reason: %s",
                        _variant,
                        _algoritmos_raw,
                        _q_variant_warning,
                    )
                resolved_variant = _variant
                prompt = M3_CLASSIFICATION_QUESTIONS_BY_VARIANT.get(
                    _variant,
                    M3_CLASSIFICATION_QUESTIONS_BY_VARIANT["lr_rf_contrast"],
                )
                tag = f"m3_classification_questions_{_variant}"
            else:
                prompt = M3_EXPERIMENT_QUESTIONS_PROMPT
                tag = "m3_experiment_questions"
        else:
            prompt = M3_AUDIT_QUESTIONS_PROMPT
            tag = "m3_audit_questions"

        # Capture the formatted prompt so the coherence wrapper can CONCATENATE its
        # correction suffix onto it (never a second `.format()` — JSON schema braces).
        formatted = prompt.format(**context)
        resultado: GeneradorPreguntasOutput = llm.with_structured_output(
            GeneradorPreguntasOutput
        ).invoke(formatted)

        preguntas = [p.model_dump() for p in resultado.preguntas]
        preguntas = _apply_m3_questions_coherence(
            llm=llm,
            prompt=formatted,
            state=state,
            preguntas_dict=preguntas,
            profile=profile,
            variant=resolved_variant,
        )
        print(f"[{tag}] {len(preguntas)} preguntas")
        return {"m3_questions": preguntas, "current_agent": "m3_questions_generator"}
    except RuntimeError:
        raise
    except Exception as e:
        logger.error("[m3_questions_generator] ERROR: %s", e, exc_info=True)
        return {"m3_questions": [], "current_agent": "m3_questions_generator"}


# ══════════════════════════════════════════════════════════════════════════════
# Issue #233 — Post-LLM family-consistency validator
# Catches the rare case where the specialized prompt strays into another
# family's API surface (e.g. a clustering notebook emitting `train_test_split`
# or a regression notebook emitting `roc_auc_score`). The notebook generator
# reprompts ONCE on violation and fails the job if a second attempt also
# strays — better to fail loudly than ship a runtime-broken notebook.
# ══════════════════════════════════════════════════════════════════════════════

# Substrings whose presence in the generated notebook proves a family violation.
# Kept narrow on purpose (only API tokens unique to other families) to minimize
# false positives. The validator strips Jupytext markdown cells and code-comment
# lines before scanning (see ``_strip_jupytext_for_validation``), so pedagogical
# echoes of these tokens in markdown/comments do NOT count — only executable
# import statements and call sites do.
_FAMILY_PROHIBITED_PATTERNS: dict[str, tuple[str, ...]] = {
    "clustering": (
        "train_test_split(",
        "roc_auc_score",
        "confusion_matrix",
        "ConfusionMatrixDisplay",
        "classification_report",
        "f1_score(",
        "mean_squared_error(",
        "r2_score(",
        "from sklearn.model_selection import train_test_split",
    ),
    "serie_temporal": (
        "train_test_split(",
        "roc_auc_score",
        "confusion_matrix",
        "ConfusionMatrixDisplay",
        "classification_report",
        "silhouette_score(",
        "davies_bouldin_score(",
        "from sklearn.cluster import",
        "from sklearn.model_selection import train_test_split",
    ),
    "regresion": (
        "roc_auc_score",
        "confusion_matrix",
        "ConfusionMatrixDisplay",
        "classification_report",
        "silhouette_score(",
        "davies_bouldin_score(",
        "auto_arima",
        "from prophet import",
        "from sklearn.cluster import",
    ),
    "clasificacion": (
        "silhouette_score(",
        "davies_bouldin_score(",
        "auto_arima",
        "from prophet import",
        "from sklearn.cluster import",
        "from statsmodels.tsa.arima",
    ),
}


# Issue #236 — Required-token validator for the Harvard ml_ds quality bar.
#
# Unlike `_FAMILY_PROHIBITED_PATTERNS` (which rejects cross-family API leakage),
# this map enumerates pedagogical artefacts the notebook MUST contain. Today it
# is populated only for ``clasificacion`` because the v1 quality push targets
# Logistic Regression vs Random Forest. Other families return ``()`` from the
# ``.get(family, ())`` lookup, so they remain bit-identical to the pre-#236
# behaviour (no FALTANTE entries can be raised against them).
#
# Two kinds of tokens live here:
#   * Section sentinels (``# === SECTION:<id> ===``) — force the LLM to emit
#     the 8 mandatory pedagogical sections in a parser-friendly shape
#     (Issue #238 added ``cost_matrix`` to the original 7 from #236).
#   * Canonical sklearn API tokens (``DummyClassifier``, ``StratifiedKFold``,
#     ``ColumnTransformer``, ``cross_val_score``, ``roc_curve(``,
#     ``precision_recall_curve(``, ``confusion_matrix(``, ``predict_proba(``)
#     — guarantee the sections do real work.
#
# Required tokens split in two buckets so each is checked against the right
# corpus (PR #244 review):
#
#   * ``_FAMILY_REQUIRED_SENTINELS`` — section-marker comments
#     (``# === SECTION:<id> ===``). These are Python ``#`` comments and would
#     be erased by ``_strip_jupytext_for_validation``, so we MUST scan them
#     against the RAW notebook text.
#   * ``_FAMILY_REQUIRED_APIS`` — canonical sklearn API tokens
#     (``DummyClassifier``, ``StratifiedKFold``, ``ColumnTransformer``,
#     ``cross_val_score``, ``roc_curve(``, ``precision_recall_curve(``).
#     These MUST be scanned against the STRIPPED text so the LLM cannot
#     satisfy the validator by merely mentioning the identifier inside a
#     markdown preamble or a Python comment — they have to appear in
#     executable code (call site or import) for the section to do real work.
#
# Both maps remain populated only for ``clasificacion`` (Issue #236 v1 scope).
# Other families return ``()`` from the ``.get`` lookup and remain
# bit-identical to pre-#236 behaviour (no FALTANTE entries can ever fire).
_FAMILY_REQUIRED_SENTINELS: dict[str, tuple[str, ...]] = {
    "clasificacion": (
        # #353 — NÚCLEO esencial (contrast). El recorte sacó de la superficie
        # OBLIGATORIA las celdas frágiles/redundantes y NO evaluadas por M4/M5:
        # roc_curves, pr_curves (Issue #240/curvas) y tuning/interpretabilidad
        # avanzada (tuning_lr/tuning_rf/interp_lr/interp_rf de Issue #240). Las
        # features top se re-sourcean barato dentro de pipeline_lr (coef_) y
        # pipeline_rf (feature_importances_), así metrics_summary_json mantiene el
        # ancla sin esas celdas. Reintroducir el deep-dive requiere ADR.
        "# === SECTION:dummy_baseline ===",
        "# === SECTION:pipeline_lr ===",
        "# === SECTION:pipeline_rf ===",
        "# === SECTION:cv_scores ===",
        "# === SECTION:comparison_table ===",
        # Issue #246 — ConfusionMatrixDisplay normalizada por fila (umbral 0.5).
        "# === SECTION:confusion_matrix ===",
        # Issue #238 — celda de threshold tuning con matriz de costos del negocio.
        "# === SECTION:cost_matrix ===",
        # Issue #239 — executor/parser contract. This sentinel must ship in
        # the same diff as the executor that parses the emitted marker.
        "# === SECTION:metrics_summary_json ===",
    ),
}

_FAMILY_REQUIRED_APIS: dict[str, tuple[str, ...]] = {
    "clasificacion": (
        # #353 — APIs del NÚCLEO. Se eliminaron roc_curve(/precision_recall_curve(
        # (curvas fuera del núcleo) y GridSearchCV(/RandomizedSearchCV(/
        # permutation_importance(/PartialDependenceDisplay (tuning+interp de #240
        # fuera del núcleo). Los 3 variants comparten este set de núcleo.
        "DummyClassifier",
        "ColumnTransformer",
        "StratifiedKFold",
        "cross_val_score",
        "train_test_split(",
        # Issue #238 — la celda cost_matrix usa confusion_matrix() para barrer
        # thresholds y predict_proba() para obtener scores continuos. Ambos
        # tienen que aparecer en código ejecutable, no solo en markdown.
        "confusion_matrix(",
        "predict_proba(",
        # Issue #246 — celda confusion_matrix usa ConfusionMatrixDisplay para
        # render visual normalizado por fila. Debe aparecer como import/call en
        # código ejecutable, no solo en markdown.
        "ConfusionMatrixDisplay",
    ),
}

_CLASSIFICATION_REQUIRED_SENTINELS_BY_VARIANT: dict[str, tuple[str, ...]] = {
    # #353 — single-model NÚCLEO (7 sentinelas): dummy + un pipeline + cv +
    # comparison + confusion + cost + metrics. Sin roc/pr/tuning/interp.
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY: (
        "# === SECTION:dummy_baseline ===",
        "# === SECTION:pipeline_lr ===",
        "# === SECTION:cv_scores ===",
        "# === SECTION:comparison_table ===",
        "# === SECTION:confusion_matrix ===",
        "# === SECTION:cost_matrix ===",
        "# === SECTION:metrics_summary_json ===",
    ),
    CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY: (
        "# === SECTION:dummy_baseline ===",
        "# === SECTION:pipeline_rf ===",
        "# === SECTION:cv_scores ===",
        "# === SECTION:comparison_table ===",
        "# === SECTION:confusion_matrix ===",
        "# === SECTION:cost_matrix ===",
        "# === SECTION:metrics_summary_json ===",
    ),
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST: _FAMILY_REQUIRED_SENTINELS["clasificacion"],
}

_CLASSIFICATION_REQUIRED_APIS_BY_VARIANT: dict[str, tuple[str, ...]] = {
    # #353 — tras el recorte los 3 variants comparten el MISMO set de APIs de
    # núcleo (sin GridSearchCV/RandomizedSearchCV/permutation_importance/PDP/
    # roc_curve/precision_recall_curve).
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY: _FAMILY_REQUIRED_APIS["clasificacion"],
    CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY: _FAMILY_REQUIRED_APIS["clasificacion"],
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST: _FAMILY_REQUIRED_APIS["clasificacion"],
}

_CLASSIFICATION_PROHIBITED_PATTERNS_BY_VARIANT: dict[str, tuple[str, ...]] = {
    # #353 — se conservan SOLO las prohibiciones de modelo cruzado (anti-leak del
    # modelo no seleccionado). Los tokens de tuning/interp (RandomizedSearchCV/
    # permutation_importance/PartialDependenceDisplay/GridSearchCV) se quitaron de
    # las prohibiciones porque esas secciones ya no existen en ninguna variante.
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY: (
        "RandomForestClassifier",
        "pipe_rf",
        "best_rf",
        "auc_rf",
        "RandomForest",
    ),
    CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY: (
        "LogisticRegression",
        "pipe_lr",
        "best_lr",
        "auc_lr",
    ),
}

# Back-compat alias: external callers and Issue #233 unit tests may still
# reference the legacy combined map. Keep it as a derived view so future code
# can migrate to the explicit pair without an import break.
_FAMILY_REQUIRED_PATTERNS: dict[str, tuple[str, ...]] = {
    family: _FAMILY_REQUIRED_SENTINELS.get(family, ())
    + _FAMILY_REQUIRED_APIS.get(family, ())
    for family in set(_FAMILY_REQUIRED_SENTINELS) | set(_FAMILY_REQUIRED_APIS)
}


def _strip_jupytext_for_validation(notebook_text: str) -> str:
    """Return only the executable Python from a Jupytext Percent notebook.

    The per-family prompts enumerate forbidden tokens in their ``Lista NEGRA``
    sections, so an obedient LLM frequently echoes those names back as
    pedagogical markdown or as ``#``-prefixed code comments. Scanning the
    raw notebook would treat such pedagogy as a violation and trigger a
    false-positive reprompt → potential job failure on a clean notebook.

    Strategy:
      * Drop every ``# %% [markdown]`` cell (everything until the next ``# %%``
        header or EOF).
      * Inside ``# %%`` code cells, drop pure comment lines (``^\\s*#``) and
        strip ``#``-suffix inline comments from non-empty code lines.
      * Keep string literals untouched — they can still smuggle a forbidden
        call (e.g. ``eval("roc_auc_score(...)")``) and the validator should
        catch that.

    Returns the stripped text, ready for substring scanning.
    """
    lines = notebook_text.splitlines()
    out: list[str] = []
    in_markdown = False
    for raw in lines:
        stripped = raw.lstrip()
        if stripped.startswith("# %% [markdown]"):
            in_markdown = True
            continue
        if stripped.startswith("# %%"):
            in_markdown = False
            continue
        if in_markdown:
            continue
        # Skip pure-comment lines inside code cells.
        if stripped.startswith("#"):
            continue
        # Strip trailing inline comments (``code  # comment``) — naive split
        # on " #" is enough; we don't try to preserve "#" inside strings
        # because the inline-comment heuristic is intentionally conservative.
        if " #" in raw:
            raw = raw.split(" #", 1)[0]
        out.append(raw)
    return "\n".join(out)


def _validate_notebook_family_consistency(
    family: str,
    code: str,
    notebook_variant: str | None = None,
) -> list[str]:
    """Return notebook violations for ``family`` (prohibited + required tokens).

    Two independent checks are combined into a single flat list of strings so
    that the existing reprompt-once-then-fail policy in ``m3_notebook_generator``
    keeps a single integration point.

    Result format
    -------------
    * Prohibited tokens (cross-family API leakage) are returned as **bare
      strings** matching the pattern (e.g. ``"silhouette_score("``). This
      preserves backwards compatibility with the Issue #233 unit tests and the
      reprompt block which references the prompt's ``Lista NEGRA`` section.
    * Required tokens missing from the notebook (Issue #236, classification
      Harvard ml_ds quality bar) are returned with a ``"FALTANTE: "`` prefix.
      The reprompt block can split on this prefix to build a corrective
      instruction that explicitly lists the missing artefacts.

    Empty list = pass. Non-empty = the LLM strayed; caller reprompts once and
    fails the job if the second attempt still has any entry.

    Scoping rules (anti false-positive AND anti false-negative — PR #244)
    ---------------------------------------------------------------------
    * Prohibited scan runs on the **stripped** code (markdown + ``#`` comments
      removed) so the prompt's own ``Lista NEGRA`` echoes don't trip it.
    * Required **sentinels** scan runs on the **raw** code because they ARE
      ``#``-prefixed lines that the strip pass would erase. The contract says
      they must appear as the first line of their cell.
    * Required **APIs** scan runs on the **stripped** code so the LLM cannot
      cheat by mentioning ``DummyClassifier`` only inside a markdown
      pedagogical preamble or a ``# Comentario`` line. They have to appear in
      executable code (call site or import) for the section to do real work.
    """
    violations: list[str] = []

    scannable = _strip_jupytext_for_validation(code)

    prohibited = _FAMILY_PROHIBITED_PATTERNS.get(family, ())
    if family == "clasificacion" and notebook_variant:
        prohibited = prohibited + _CLASSIFICATION_PROHIBITED_PATTERNS_BY_VARIANT.get(
            notebook_variant,
            (),
        )
    if prohibited:
        violations.extend(p for p in prohibited if p in scannable)

    if family == "clasificacion" and notebook_variant:
        sentinels = _CLASSIFICATION_REQUIRED_SENTINELS_BY_VARIANT.get(
            notebook_variant,
            _FAMILY_REQUIRED_SENTINELS.get(family, ()),
        )
    else:
        sentinels = _FAMILY_REQUIRED_SENTINELS.get(family, ())
    violations.extend(f"FALTANTE: {token}" for token in sentinels if token not in code)

    if family == "clasificacion" and notebook_variant:
        apis = _CLASSIFICATION_REQUIRED_APIS_BY_VARIANT.get(
            notebook_variant,
            _FAMILY_REQUIRED_APIS.get(family, ()),
        )
    else:
        apis = _FAMILY_REQUIRED_APIS.get(family, ())
    violations.extend(f"FALTANTE: {token}" for token in apis if token not in scannable)

    return violations


def _detect_unsafe_constructs(code: str) -> list[str]:
    """Return safety violations for a generated notebook, generation-side.

    Reuses the AST-only ``scrub_notebook_for_safe_execution`` (no subprocess) so
    the single denylist (``locals``/``globals``/``eval``/denied imports/…) is the
    one source of truth shared with the execution-time scrub in
    ``m3_notebook_executor``. The scrubber fails fast on the first offending cell,
    so this returns at most one finding per call — enough to drive the
    reprompt-once mechanism. The finding is prefixed with ``"INSEGURO: "`` so it
    flows through the same ``violations`` list as ``FALTANTE:``/prohibited entries
    in ``_invoke_m3_notebook_algo_section``.

    Empty list = clean. Catching the unsafe construct here (before the notebook is
    stored in state) lets the SAME reprompt that strips ``locals()`` also keep the
    family-required APIs/sentinels intact, instead of the disjoint two-stage path
    where the execution-time scrub triggers a blind full regeneration that can drop
    a required artefact (Issue: M3 ml_ds clasificación ``locals()`` escalation).
    """
    try:
        scrub_notebook_for_safe_execution(code)
    except M3NotebookExecutionError as exc:
        if exc.kind in ("unsafe_code", "syntax_error"):
            return [f"INSEGURO: {exc}"]
        return [f"INSEGURO: {exc.kind}"]
    except Exception as exc:
        # Defensivo: el detector NUNCA debe crashear el job. `ast.parse` puede
        # lanzar RecursionError/ValueError (no SyntaxError) ante código patológico
        # generado por el LLM (p. ej. una expresión plana de miles de términos).
        # Cualquier fallo inesperado del scrubber se reporta como INSEGURO y se
        # enruta por el reprompt-once → falla cerrada con mensaje claro, jamás
        # como excepción opaca.
        return [f"INSEGURO: scrub_error:{type(exc).__name__}"]
    return []


class M3NotebookValidationError(RuntimeError):
    """Raised when the M3 notebook fails family/safety validation after all retries.

    Subclasses ``RuntimeError`` so existing ``except RuntimeError`` handlers (and the
    authoring worker's failure classification) keep working unchanged. Carries the
    structured ``violations`` and a bounded, secret-redacted snapshot of the last
    model output so operators can diagnose WHAT the model produced — without ever
    leaking it into the teacher-facing error message.
    """

    def __init__(
        self,
        message: str,
        *,
        violations: list[str],
        last_output: str,
    ) -> None:
        super().__init__(message)
        self.violations = list(violations)
        # Bounded + redacted at construction so callers can persist it verbatim.
        self.last_output = _bounded_diagnostic(last_output, limit=4000)


@dataclass(frozen=True)
class _M3NotebookGenerationContext:
    llm: Any
    escalation_llm: Any
    family: str
    notebook_variant: ClassificationNotebookVariant | None
    base_template: str
    prompt: str
    algoritmos_raw: list[str]


def _get_m3_notebook_llm(cfg: Configuration) -> Any:
    # Fase 1 downgrade-now: the notebook primary defaults to Flash (writer_model).
    # LOW-risk because m3_notebook_executor runs the notebook for real and gates on
    # AUC∈[0.55,0.99], and _validate_notebook_family_consistency reprompts once.
    # Reversible per-node via node_model_overrides (e.g. canary back to Pro).
    model = resolve_node_model(cfg, NODE_M3_NOTEBOOK, cfg.writer_model)
    nb_primary = _build_gemini(model, temperature=0.3, thinking_level="medium", max_output_tokens=24576)
    # Stable Flash fallback for transient API errors on the primary.
    nb_stable_flash = _build_gemini("gemini-2.5-flash", temperature=0.3, max_output_tokens=24576)
    return nb_primary.with_fallbacks([nb_stable_flash])


def _get_m3_notebook_escalation_llm(cfg: Configuration) -> Any:
    # Reliability escalation tier: the happy path runs Flash (``_get_m3_notebook_llm``);
    # if Flash strays on the strict clasificación contract (missing required API or
    # an unsafe construct), the reprompt(s) escalate to Pro. Pro is far more likely
    # to satisfy the 27-token contract and obey Rule 8 in one pass. Only the rare
    # failing job pays for Pro, so the Fase-1 Flash happy-path cost win is preserved.
    # NOT a reuse of ``_get_architect_llm`` — that attaches code_execution tools,
    # wrong for emitting long Jupytext. Same 24576/temp-0.3 contract as the Flash
    # tier; never collapse the .with_fallbacks net. Reversible per-node via
    # NODE_M3_NOTEBOOK_ESCALATION (override to a Flash model to disable escalation).
    model = resolve_node_model(cfg, NODE_M3_NOTEBOOK_ESCALATION, cfg.architect_model)
    pro_high = _build_gemini(model, temperature=0.3, thinking_level="high", max_output_tokens=24576)
    pro_medium = _build_gemini(model, temperature=0.3, thinking_level="medium", max_output_tokens=24576)
    stable_flash = _build_gemini("gemini-2.5-flash", temperature=0.3, max_output_tokens=24576)
    return pro_high.with_fallbacks([pro_medium, stable_flash])


def _prepare_m3_notebook_generation_context(
    state: ADAMState,
    config: RunnableConfig,
) -> _M3NotebookGenerationContext:
    cfg = Configuration.from_runnable_config(config)
    llm = _get_m3_notebook_llm(cfg)
    escalation_llm = _get_m3_notebook_escalation_llm(cfg)

    context = _build_base_context(state)
    case_title = state.get("titulo", "Caso de Estudio") or "Caso de Estudio"
    # Use .replace() — NOT .format() — because the template contains Python code
    # with curly braces (dict comprehensions, f-strings) that .format() misparses.
    base_template = M3_NOTEBOOK_BASE_TEMPLATE.replace("{case_title}", case_title)

    algoritmos_raw = _extract_state_algoritmos(state)
    family, legacy_warning = _resolve_primary_family(algoritmos_raw)
    if family is None or family not in PROMPT_BY_FAMILY:
        print(
            f"[m3_notebook_generator] Familia no resuelta para algoritmos="
            f"{algoritmos_raw!r} — usando fallback 'clasificacion'"
        )
        family = "clasificacion"
        legacy_warning = (
            f"Algoritmos {algoritmos_raw!r} no mapearon a ninguna familia "
            f"del catálogo Issue #233; se generó notebook con plantilla de clasificación."
        )

    algorithm_mode = _extract_state_algorithm_mode(state)
    notebook_variant: ClassificationNotebookVariant | None = None
    prompt_template = PROMPT_BY_FAMILY[family]
    if family == "clasificacion":
        notebook_variant, variant_warning = _resolve_classification_notebook_variant(
            algorithm_mode=algorithm_mode,
            algoritmos=algoritmos_raw,
        )
        prompt_template = CLASSIFICATION_NOTEBOOK_PROMPT_BY_VARIANT[notebook_variant]
        if variant_warning:
            legacy_warning = f"{legacy_warning}\n{variant_warning}" if legacy_warning else variant_warning

    print(
        f"[m3_notebook_generator] Familia despachada: {family!r} "
        f"(variant={notebook_variant!r}, mode={algorithm_mode!r}, algoritmos={algoritmos_raw!r})"
    )

    meta = get_dispatch_meta(family)
    familias_meta = [
        {
            "familia": meta["familia"],
            "family_label": meta["family_label"],
            "algoritmos": list(algoritmos_raw) if algoritmos_raw else [meta["familia"]],
            "visualizacion": meta["visualizacion"],
            "prerequisito": meta["prerequisito"],
            "fragments_hint": meta["fragments_hint"],
        }
    ]

    contract_block = _format_dataset_contract_block(
        state.get("dataset_schema_required")
    )
    # #348 — target CONTRACT-FIRST en la celda ejecutada `dummy_baseline`. El
    # nombre del contrato se inyecta como literal Python en el notebook, así que
    # `_safe_contract_target_name` exige que sea un identificador válido (guarda
    # del límite LLM→código). Vacío ("") → la celda cae al alias-first heredado;
    # presente → el notebook entrena ese target o emite REQUISITO FALTANTE.
    contract_target_name = _safe_contract_target_name(state.get("dataset_schema_required"))
    gap_warnings = list(state.get("data_gap_warnings") or [])
    if legacy_warning:
        gap_warnings.append(legacy_warning)
    gaps_block = _format_data_gap_warnings_block(
        gap_warnings,
        empty_message="(sin brechas detectadas — schema cubre el contrato)",
    )

    prompt = prompt_template.format(
        m3_content=(state.get("m3_content", "") or "")[:2000],
        algoritmos=json.dumps(algoritmos_raw, ensure_ascii=False),
        familias_meta=json.dumps(familias_meta, ensure_ascii=False),
        case_title=case_title,
        output_language=context.get("output_language", "es"),
        dataset_contract_block=contract_block,
        data_gap_warnings_block=gaps_block,
        contract_target_name=contract_target_name,
    )
    # Inject static TOC cell for classification variants — zero LLM overhead.
    # For non-classification families notebook_variant is None, so we use "".
    toc_cell = (
        "" if notebook_variant is None else TOC_MARKDOWN_CELL_BY_VARIANT.get(notebook_variant, "")
    )
    base_template = base_template.replace("{toc_cell}", toc_cell)
    return _M3NotebookGenerationContext(
        llm=llm,
        escalation_llm=escalation_llm,
        family=family,
        notebook_variant=notebook_variant,
        base_template=base_template,
        prompt=prompt,
        algoritmos_raw=algoritmos_raw,
    )


def _build_m3_notebook_validation_correction(
    family: str,
    violations: list[str],
    notebook_variant: str | None = None,
) -> str:
    missing = [v.removeprefix("FALTANTE: ") for v in violations if v.startswith("FALTANTE: ")]
    unsafe_hits = [v.removeprefix("INSEGURO: ") for v in violations if v.startswith("INSEGURO: ")]
    prohibited_hits = [
        v
        for v in violations
        if not v.startswith("FALTANTE: ") and not v.startswith("INSEGURO: ")
    ]
    corrective_blocks: list[str] = ["\n\n# CORRECCIÓN OBLIGATORIA"]
    if notebook_variant:
        corrective_blocks.append(
            f"# Variante de notebook requerida: {notebook_variant}. "
            "No agregues secciones, métricas ni imports de modelos fuera de esa variante."
        )
    if unsafe_hits:
        bullet_list = "\n".join(f"#   - {tok}" for tok in unsafe_hits)
        corrective_blocks.append(
            "# Tu salida anterior usó introspección dinámica o un escape de runtime PROHIBIDO\n"
            "# en una celda ejecutable (el kernel limpio la rechaza):\n"
            f"{bullet_list}\n"
            "# PROHIBIDO usar globals(), locals(), vars(), getattr(...), __builtins__,\n"
            "# __import__, eval(...) o exec(...) en cualquier celda ejecutable.\n"
            "# Si necesitas comprobar si una variable existe, usa try/except NameError.\n"
            "# Ejemplo permitido:\n"
            "# try:\n"
            "#     X_train\n"
            "#     y_train\n"
            "# except NameError:\n"
            "#     # recrear splits con train_test_split(...)\n"
            "# Reescribe la salida COMPLETA conservando TODAS las sentinelas y APIs requeridas."
        )
    if prohibited_hits:
        corrective_blocks.append(
            f"# Tu salida anterior emitió código ejecutable de OTRAS familias prohibidas para '{family}'.\n"
            "# Releé la sección 'Lista NEGRA' del prompt y reescribe la salida COMPLETA\n"
            "# usando EXCLUSIVAMENTE la API estable declarada para esta familia.\n"
            "# Los nombres prohibidos pueden aparecer en celdas markdown como advertencia pedagógica,\n"
            "# pero NUNCA como import, call site, ni dentro de un string ejecutable."
        )
    if missing:
        bullet_list = "\n".join(f"#   - {tok}" for tok in missing)
        corrective_blocks.append(
            "# Tu salida anterior NO incluyó artefactos pedagógicos OBLIGATORIOS\n"
            f"# para la familia '{family}'. Reescribe la salida COMPLETA asegurándote\n"
            "# de que aparezcan literalmente (sentinelas como comentario Python al inicio\n"
            "# de la celda correspondiente; identificadores como import o call real):\n"
            f"{bullet_list}"
        )
    return "\n".join(corrective_blocks)


def _validate_m3_notebook_algo_section(
    family: str,
    algo_section: str,
    notebook_variant: str | None,
) -> list[str]:
    """Family-consistency + (clasificacion-only) safety violations as one flat list.

    Safety scrub is scoped to clasificacion — the ONLY family the executor runs and
    scrubs (m3_notebook_executor gate), the only family the bug occurred in, and the
    only one with a required-API contract. The other 3 families' notebooks are never
    executed server-side, so applying the denylist there would be new policy with
    false-positive risk (e.g. dir()/getattr() in pedagogical code), not a bug fix.
    Keep blast radius == executor scope.
    """
    violations = _validate_notebook_family_consistency(family, algo_section, notebook_variant)
    if family == "clasificacion":
        violations += _detect_unsafe_constructs(algo_section)
    return violations


def _invoke_m3_notebook_algo_section(
    *,
    llm: Any,
    prompt: str,
    family: str,
    notebook_variant: str | None,
    node_name: str,
    execution_correction: str | None = None,
    escalation_llm: Any | None = None,
    max_attempts: int = M3_NOTEBOOK_MAX_ATTEMPTS,
) -> str:
    """Generate the algo section, validating family + safety, escalating on retry.

    Attempt 1 runs ``llm`` (Flash, the cheap happy path). If the output violates the
    family/safety contract, every subsequent attempt runs on ``escalation_llm``
    (Pro) — far more likely to satisfy the strict clasificación contract and obey
    Rule 8 in one pass. For clasificacion, a deterministic ``locals()`` existence-
    guard repair runs BEFORE validation on every attempt, so the most common unsafe
    idiom never even needs a reprompt. After ``max_attempts`` the job fails closed
    with ``M3NotebookValidationError`` (never ship a runtime-broken notebook).
    """
    prompt_with_context = prompt if not execution_correction else prompt + "\n\n" + execution_correction
    retry_llm = escalation_llm or llm
    max_attempts = max(2, max_attempts)

    current_prompt = prompt_with_context
    algo_section = ""
    violations: list[str] = []
    for attempt in range(1, max_attempts + 1):
        active_llm = llm if attempt == 1 else retry_llm
        tier = "flash" if active_llm is llm else "escalated"
        response = active_llm.invoke(current_prompt)
        algo_section = sanitize_markdown(_extract_text(response))
        # Deterministic repair of the sanctioned existence-guard idiom (clasificacion
        # only) — kills the most common INSEGURO cause without burning a reprompt.
        if family == "clasificacion":
            algo_section = repair_locals_existence_guards(algo_section)
        print(
            f"[{node_name}] Sección módulos LLM (intento {attempt}/{max_attempts}, "
            f"tier={tier}): {len(algo_section)} chars"
        )

        violations = _validate_m3_notebook_algo_section(family, algo_section, notebook_variant)
        if not violations:
            if attempt > 1:
                print(f"[{node_name}] Reprompt OK (intento {attempt}) — familia={family}, chars={len(algo_section)}")
            return algo_section

        if attempt >= max_attempts:
            break

        missing = [v.removeprefix("FALTANTE: ") for v in violations if v.startswith("FALTANTE: ")]
        unsafe_hits = [v.removeprefix("INSEGURO: ") for v in violations if v.startswith("INSEGURO: ")]
        prohibited_hits = [
            v
            for v in violations
            if not v.startswith("FALTANTE: ") and not v.startswith("INSEGURO: ")
        ]
        print(
            f"[{node_name}] Violación detectada (familia={family}, "
            f"prohibited={prohibited_hits}, faltantes={missing}, inseguros={unsafe_hits}). "
            f"Reprompt {attempt}/{max_attempts - 1} (tier siguiente={'escalated' if retry_llm is not llm else 'flash'})."
        )
        current_prompt = prompt_with_context + _build_m3_notebook_validation_correction(
            family,
            violations,
            notebook_variant,
        )

    logger.error(
        "[%s] Reprompt agotado (%d intentos) — familia=%s violations=%s",
        node_name, max_attempts, family, violations,
    )
    raise M3NotebookValidationError(
        f"M3 notebook generator no satisfizo las validaciones de notebook "
        f"(familia/seguridad) para '{family}' incluso tras {max_attempts - 1} reprompts: "
        f"{violations}. "
        f"Job marcado como fallido para evitar shipping de notebook roto.",
        violations=violations,
        last_output=algo_section,
    )


def _generate_m3_notebook_code(
    state: ADAMState,
    config: RunnableConfig,
    *,
    node_name: str,
    execution_correction: str | None = None,
) -> tuple[str, str]:
    generation_context = _prepare_m3_notebook_generation_context(state, config)
    algo_section = _invoke_m3_notebook_algo_section(
        llm=generation_context.llm,
        escalation_llm=generation_context.escalation_llm,
        prompt=generation_context.prompt,
        family=generation_context.family,
        notebook_variant=generation_context.notebook_variant,
        node_name=node_name,
        execution_correction=execution_correction,
    )
    return generation_context.base_template + "\n\n" + algo_section, generation_context.family


# Graceful-degradation placeholder: a safe, non-executable Jupytext markdown cell
# shown when the notebook could not be produced/validated. The executor noops on the
# degraded flag, so this is never executed; the frontend renders a "regenerate" panel.
M3_NOTEBOOK_DEGRADED_PLACEHOLDER = (
    "# %% [markdown]\n"
    "# ## Notebook no disponible\n"
    "#\n"
    "# El notebook de experimentación no pudo generarse automáticamente para este\n"
    "# caso. El resto del caso está completo. Usa **Regenerar notebook** para\n"
    "# reintentar la generación.\n"
)


def _degraded_notebook_update(*, node: str, reason: str) -> dict[str, Any]:
    """State update that degrades the M3 notebook to a placeholder without failing
    the case. The job still completes; the teacher can regenerate on demand."""
    return {
        "m3_notebook_code": M3_NOTEBOOK_DEGRADED_PLACEHOLDER,
        "m3_notebook_degraded": True,
        "m3_notebook_degraded_reason": reason,
        "current_agent": node,
    }


def m3_notebook_generator(state: ADAMState, config: RunnableConfig) -> dict:
    """Genera el notebook del Experiment Engineer — ÚNICO notebook del sistema.

    GUARDS OBLIGATORIOS (doble):
      1. studentProfile == "ml_ds"
      2. output_depth == "visual_plus_notebook"
    Si cualquiera falla → noop. Ningún otro nodo del sistema genera notebooks.

    Output: m3_notebook_code (Jupytext Percent → frontend convierte a .ipynb)

    Arquitectura (Issue #233 — per-family dispatch):
      - Sección base : M3_NOTEBOOK_BASE_TEMPLATE (estático, cero alucinaciones).
      - Sección módulos: PROMPT_BY_FAMILY[family] — UN prompt especializado por
        familia (clasificacion / regresion / clustering / serie_temporal). El
        contrato Issue #230 garantiza que los algoritmos del caso comparten
        familia (en contrast mode), así que SIEMPRE hay un único prompt.
      - Post-LLM: ``_validate_notebook_family_consistency`` revisa que el código
        no contenga API de otras familias (anti-alucinación). Si hay violación,
        se hace UN reprompt explícito; si vuelve a fallar, el job falla con un
        mensaje en español y un log estructurado.
    """
    profile = state.get("studentProfile", "business")
    output_depth = state.get("output_depth", "")

    if profile != "ml_ds":
        print("[m3_notebook_generator] Noop — perfil business no recibe notebook")
        return {}
    if output_depth != "visual_plus_notebook":
        print(f"[m3_notebook_generator] Noop — output_depth='{output_depth}' != visual_plus_notebook")
        return {}

    try:
        final_notebook, _family = _generate_m3_notebook_code(
            state,
            config,
            node_name="m3_notebook_generator",
        )
        print(f"[m3_notebook_generator] Notebook ensamblado: {len(final_notebook)} chars")
        return {"m3_notebook_code": final_notebook, "current_agent": "m3_notebook_generator"}
    except M3NotebookValidationError as exc:
        # Graceful degradation (never ship a runtime-broken notebook): after all
        # retries the notebook could not satisfy the family/safety contract. Instead
        # of killing the whole 6-module case, ship it with the other 5 modules + a
        # placeholder and let the teacher regenerate the notebook on demand.
        logger.warning(
            "[m3_notebook_generator] Notebook degradado tras agotar reintentos: %s",
            exc.violations,
        )
        return _degraded_notebook_update(
            node="m3_notebook_generator", reason="validation_exhausted"
        )
    except Exception as e:
        logger.error("[m3_notebook_generator] ERROR: %s", e, exc_info=True)
        return _degraded_notebook_update(
            node="m3_notebook_generator", reason="unexpected_error"
        )


def m3_notebook_executor(state: ADAMState, config: RunnableConfig) -> dict:
    """Execute and validate the M3 classification notebook in a subprocess.

    Graceful degradation: a notebook that cannot be executed/validated (missing
    dataset, crash after correction, blocking quality gate) degrades to a placeholder
    instead of killing the whole case — a runtime-broken notebook is never shipped,
    only a placeholder, and the teacher can regenerate on demand.
    """

    output_depth = state.get("output_depth", "")
    if output_depth != "visual_plus_notebook":
        return {}

    profile, family = _resolve_generation_focus(
        state,
        default_unresolved_ml_ds_to_classification=True,
    )
    if profile != "ml_ds" or family != "clasificacion":
        return {}

    case_id = state.get("case_id") or "unknown"

    # The generator already degraded the notebook — do NOT try to execute the
    # placeholder; keep the degraded state and noop.
    if state.get("m3_notebook_degraded"):
        print("[m3_notebook_executor] Noop — notebook ya degradado por el generador")
        return {}

    try:
        return _run_m3_notebook_execution(state, config, case_id=case_id, family=family)
    except Exception as exc:
        logger.warning(
            "[m3_notebook_executor] Notebook degradado tras fallo de ejecución: %s",
            exc,
            extra={"case_id": case_id, "family": family},
        )
        return _degraded_notebook_update(node="m3_notebook_executor", reason="execution_failed")


def _run_m3_notebook_execution(
    state: ADAMState,
    config: RunnableConfig,
    *,
    case_id: str,
    family: str,
) -> dict:
    """Inner executor body. Raises on any failure; the caller degrades on raise."""
    dataset_rows = state.get("doc7_dataset") or []
    if not isinstance(dataset_rows, list) or not dataset_rows:
        logger.error(
            "[m3_notebook_executor] missing doc7_dataset; failing closed",
            extra={"case_id": case_id, "family": family},
        )
        raise RuntimeError(
            "m3_notebook_executor requiere doc7_dataset para ejecutar el notebook "
            "de clasificación. Job marcado como fallido para evitar métricas inventadas."
        )

    notebook_code = str(state.get("m3_notebook_code") or "")
    if not notebook_code.strip():
        raise RuntimeError(
            "m3_notebook_executor no recibió m3_notebook_code. "
            "Job marcado como fallido para evitar shipping de notebook roto."
        )

    # #349 — declared contract target for the defense-in-depth identity cross-check.
    # Empty ("") when there is no contract / a non-identifier name → the guard no-ops.
    # This is the SAME value injected into the notebook as {contract_target_name} (#348),
    # so in the happy path the modeled target_col equals it.
    expected_target = _safe_contract_target_name(state.get("dataset_schema_required"))

    code_was_corrected = False
    for attempt in (1, 2):
        try:
            logger.info(
                "[m3_notebook_executor] attempt=%s start",
                attempt,
                extra={"case_id": case_id, "family": family},
            )
            result = execute_m3_notebook(
                notebook_code=notebook_code,
                dataset_rows=cast(list[dict[str, Any]], dataset_rows),
            )
            # #349 — cross-check the modeled target against the declared contract target.
            # The mismatch warning (blocking) takes precedence over the non-blocking
            # AUC-out-of-range warning; a missing/invalid marker leaves metrics None, so
            # build_target_identity_warning returns None and the marker warning surfaces
            # unchanged. The AUC gate stays non-blocking.
            identity_warning = build_target_identity_warning(result.metrics_summary, expected_target)
            combined_warning = identity_warning or result.quality_warning
            if is_m3_quality_warning_blocking(combined_warning, result.metrics_summary):
                raise M3NotebookExecutionError(
                    "M3 notebook quality gate failed.",
                    diagnostics=combined_warning,
                    kind="quality_gate",
                )
            logger.info(
                "[m3_notebook_executor] attempt=%s success warning=%s",
                attempt,
                combined_warning,
                extra={"case_id": case_id, "family": family},
            )
            # #349 — strip the internal identity signal (`target_col`) before persisting so
            # the M4/M5 grounding block (build_computed_metrics_block) stays byte-identical
            # for all ml_ds+clf (churn included). It is an executor-internal cross-check
            # input, not a computed metric. Non-mutating copy (never del the frozen
            # dataclass's dict). The cross-check above already consumed it.
            metrics_for_state = (
                None
                if result.metrics_summary is None
                else {
                    key: value
                    for key, value in result.metrics_summary.items()
                    if key != "target_col"
                }
            )
            update: dict[str, Any] = {
                "current_agent": "m3_notebook_executor",
                "m3_metrics_summary": metrics_for_state,
            }
            if combined_warning:
                update["m3_quality_warning"] = combined_warning
            if code_was_corrected:
                update["m3_notebook_code"] = notebook_code
            return update
        except M3NotebookExecutionError as exc:
            logger.warning(
                "[m3_notebook_executor] attempt=%s failed kind=%s",
                attempt,
                exc.kind,
                extra={"case_id": case_id, "family": family},
            )
            if attempt == 2:
                raise RuntimeError(
                    "m3_notebook_executor falló incluso tras un reprompt de corrección. "
                    "Job marcado como fallido para evitar shipping de notebook roto."
                ) from exc

            correction = format_execution_failure_for_prompt(exc)
            notebook_code, corrected_family = _generate_m3_notebook_code(
                state,
                config,
                node_name="m3_notebook_executor",
                execution_correction=correction,
            )
            if corrected_family != "clasificacion":
                raise RuntimeError(
                    f"m3_notebook_executor recibió corrección para familia {corrected_family!r}; "
                    "se esperaba 'clasificacion'."
                )
            code_was_corrected = True

    raise RuntimeError("m3_notebook_executor alcanzó un estado imposible de ejecución.")


# Issue 4.4 — M4 CONTENT GENERATOR
def m4_content_generator(state: ADAMState, config: RunnableConfig) -> dict:
    """Genera el análisis de impacto económico y operativo (Módulo 4).
    Corre en m4_flow tanto para harvard_only como harvard_with_eda.
    Si no hay M2/M3, el prompt usa fallback basado en Exhibits del M1.
    """
    try:
        cfg = Configuration.from_runnable_config(config)
        llm = _get_m4_llm(
            resolve_node_model(cfg, NODE_M4_CONTENT, cfg.architect_model),
            cfg.writer_model,
            temperature=0.5,
        )

        context = _build_base_context(state)
        context.update({
            # Fix M-03: 8000 chars — M4 proyecta impacto por opción A/B/C.
            # Con 6000 chars las opciones al final de la narrativa quedaban fuera.
            "contexto_m1": state.get("doc1_narrativa", "")[:8000],
            "contexto_m2": state.get("doc2_eda", "") or "DATASET_UNAVAILABLE",
            "contexto_m3": state.get("m3_content", "") or "[M3_NOT_EXECUTED]",
            "anexo_financiero": state.get("doc1_anexo_financiero", ""),
        })
        # Issue #330 — narrativa M4 variant-aware para ml_ds + clasificación.
        # Réplica del dispatch de M3 (m3_content_generator): resolver lr_only/rf_only/
        # lr_rf_contrast y sobreescribir solo la clave "clasificacion" para que la prosa
        # de impacto contraste (o NO contraste) según la intención del docente. Cualquier
        # otro caso (business, o familias no-clasificación) pasa el dict original intacto.
        _algoritmos_raw = _extract_state_algoritmos(state)
        _algorithm_mode = _extract_state_algorithm_mode(state)
        _profile, _primary_family = _resolve_generation_focus(state)
        # Issue #437 (ADR 0003, Fase 1) — select the NEUTRAL value-frame-agnostic prompt set
        # when settings.impact_lens is on (the default); else the original FINANCIAL set, which
        # makes the kill-switch-off path byte-identical to pre-#437.
        _lens_on = settings.impact_lens
        _by_family = M4_PROMPT_BY_FAMILY_NEUTRAL if _lens_on else M4_PROMPT_BY_FAMILY
        _variant_dict = (
            M4_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT_NEUTRAL
            if _lens_on else M4_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT
        )
        _default_prompt = M4_CONTENT_GENERATOR_PROMPT_NEUTRAL if _lens_on else M4_CONTENT_GENERATOR_PROMPT
        _business_prompt = (
            M4_BUSINESS_PROMPT_CLASSIFICATION_NEUTRAL if _lens_on else M4_BUSINESS_PROMPT_CLASSIFICATION
        )
        variant: str | None = None
        if _profile == "ml_ds" and _primary_family == "clasificacion":
            _variant, _variant_warning = _resolve_classification_notebook_variant(
                algorithm_mode=_algorithm_mode,
                algoritmos=_algoritmos_raw,
            )
            variant = _variant
            if _variant_warning:
                logger.warning(
                    "[m4_content_generator] narrative variant fallback — "
                    "variant=%s algoritmos=%r reason: %s",
                    _variant, _algoritmos_raw, _variant_warning,
                )
            _effective_prompt_by_family: dict[str, str] = {
                **_by_family,
                "clasificacion": _variant_dict[_variant],
            }
        else:
            _effective_prompt_by_family = _by_family
        prompt_template, metrics_block, grounding_enabled, grounding_update = (
            _select_narrative_prompt(
                state,
                "m4_content_generator",
                _effective_prompt_by_family,
                _default_prompt,
            )
        )
        # Issue #306 — business+clasificación cierra el arco LR (probabilidad × valor en riesgo).
        # No-op para ml_ds y para business no-clasificación.
        prompt_template = _maybe_business_classification_prompt(
            state, prompt_template, _business_prompt
        )
        # Issue #437 — append the «MARCO DE VALOR» hint for the resolved lens (brace-free, so it is
        # safe before .format). financial_roi reproduces ROI/Payback/NPV; off-path skips it entirely.
        if _lens_on:
            prompt_template = prompt_template + build_impact_lens_hint(_resolve_impact_lens(state))
        context["computed_metrics_block"] = metrics_block

        m4 = _invoke_narrative_with_grounding(
            node_name="m4_content_generator",
            llm=llm,
            prompt=prompt_template.format(**context),
            metrics_block=metrics_block,
            grounding_enabled=grounding_enabled,
            variant=variant,
        )
        print(f"[m4_content_generator] {len(m4)} chars")
        # Logger-only backstop (M4_DEPLOYMENT_DEDUP): flag a residual duplicate deployment
        # recommendation that survived the prompt fix. ``variant`` is non-None only for
        # ml_ds + clasificación, so this is a byte-identical no-op elsewhere. Best-effort —
        # never raises, never reprompts, never mutates ``m4`` (does not fail the job).
        if settings.m4_deployment_dedup:
            log_duplicate_deployment_sections(
                m4, variant=variant, case_id=state.get("case_id")
            )
        # Issue #436 — logger-only backstop: warn if the narrative still carries a benchmark-fabrication
        # tell despite the prompt fix. ALL profiles/families (domain-wide risk). Best-effort — never
        # reprompts, mutates, or fails the job (the wrapper swallows all exceptions internally, so it
        # cannot trip this node's outer except that would degrade M4 to an error placeholder).
        if settings.m4_fabrication_guard:
            log_narrative_benchmark_fabrication(
                m4, node="m4_content_generator", case_id=state.get("case_id")
            )
        # Issue #437 follow-up — logger-only backstop: warn if a machine ``word__x`` identifier
        # (e.g. an sklearn ColumnTransformer ``num__col`` feature name) survived in the narrative.
        # The deterministic strip in ``build_computed_metrics_block`` is the cure; this is the net
        # for any other injection path. ALL profiles/families. Best-effort — never reprompts,
        # mutates, or fails the job (the wrapper swallows all exceptions internally).
        if settings.case_identifier_leak_guard:
            log_raw_identifier_leak(
                m4, node="m4_content_generator", case_id=state.get("case_id")
            )
        return {
            "m4_content": m4,
            "current_agent": "m4_content_generator",
            **grounding_update,
        }
    except RuntimeError:
        raise
    except Exception as e:
        logger.error("[m4_content_generator] ERROR: %s", e, exc_info=True)
        return {"m4_content": "[M4_GENERATION_ERROR]", "current_agent": "m4_content_generator"}


# Issue 4.5 — M4 CHART GENERATOR (ambos perfiles)
def _m4_chart_violation_types(violations_per_chart: list[tuple[int, list[str]]]) -> list[str]:
    """Enumerated, deduplicated violation prefixes (no raw chart text/PII) for structured logs."""
    types: set[str] = set()
    for _index, violations in violations_per_chart:
        for violation in violations:
            types.add(violation.split(":", 1)[0])
    return sorted(types)


def _apply_m4_chart_grounding(
    *,
    llm: Any,
    formatted_prompt: str,
    state: ADAMState,
    charts: list[dict],
    variant: str | None,
    metrics_block: str,
) -> list[dict]:
    """Validate + reprompt-once-then-DROP the M4 financial-chart coherence.

    Gated to the classification family for BOTH profiles (business + ml_ds) via
    ``_is_classification_family`` (the SAME gate M1/M2/M5 use) behind the ``m4_chart_grounding``
    kill-switch; a byte-identical no-op otherwise. On a violation it reprompts ONCE with the concrete
    fix; any chart that STILL cites an unverified model metric, an unselected-model leak, or an
    invented "benchmark" figure after the reprompt is DROPPED (never shipped). It NEVER fails a job
    and NEVER shows false data — the chart-node philosophy (mirrors ``drop_sensitivity_charts``).

    ``formatted_prompt`` is the ALREADY-formatted chart prompt; the reprompt is built by CONCATENATION
    (never re-``.format`` — chart/JSON braces). ``variant`` is the RESOLVED notebook variant (None for
    business / contrast → the leak guard is a no-op). The wrapper mutates only the returned list — no
    shared-state write, so there is no LangGraph fan-out merge hazard with ``m4_questions_generator``.
    Best-effort: ANY throw degrades to the input ``charts``. Never raises.
    """
    log_extra = {"node": "m4_chart_generator", "case_id": state.get("case_id")}
    try:
        if not settings.m4_chart_grounding or not _is_classification_family(state):
            return charts
        violations = validate_m4_chart_grounding(
            charts, metrics_block=metrics_block, variant=variant
        )
        if not violations:
            return charts
        logger.info(
            "[m4_chart_generator] reprompt de coherencia de gráficos disparado",
            extra={
                **log_extra,
                "violation_count": sum(len(v) for _i, v in violations),
                "violation_types": _m4_chart_violation_types(violations),
            },
        )
        reprompt = formatted_prompt + build_m4_chart_grounding_reprompt(
            violations, metrics_block=metrics_block
        )
        try:
            result: EDAChartGeneratorOutput = llm.with_structured_output(
                EDAChartGeneratorOutput
            ).invoke(reprompt)
            candidate = [c.model_dump() for c in result.charts]
        except (ValidationError, OutputParserException, ValueError) as exc:
            logger.warning(
                "[m4_chart_generator] reprompt de coherencia inválido — degrada a pass-1: %s",
                exc,
                extra=log_extra,
            )
            candidate = charts
        # Residual = DROP, by RE-VALIDATION (the reprompt regenerates the whole set, so the pass-1
        # indices are meaningless). Keep only the charts that are now clean; if that empties the set,
        # fall back to pass-1 minus its violators (never ship a violation, never needlessly empty).
        candidate_bad = {i for i, _v in validate_m4_chart_grounding(
            candidate, metrics_block=metrics_block, variant=variant
        )}
        survivors = [c for i, c in enumerate(candidate) if i not in candidate_bad]
        if survivors:
            base_len = len(candidate)
        else:
            pass1_bad = {i for i, _v in violations}
            survivors = [c for i, c in enumerate(charts) if i not in pass1_bad]
            base_len = len(charts)
        dropped = base_len - len(survivors)
        if dropped > 0:
            logger.warning(
                "[m4_chart_generator] coherencia de gráficos: %d gráfico(s) descartado(s) tras reprompt",
                dropped,
                extra={**log_extra, "dropped_count": dropped, "degraded": True},
            )
        else:
            logger.info(
                "[m4_chart_generator] coherencia de gráficos corregida por reprompt",
                extra={**log_extra, "degraded": False},
            )
        return survivors
    except Exception as exc:  # best-effort — a coherence pass must never fail the job
        logger.warning(
            "[m4_chart_generator] validador de coherencia de gráficos falló (best-effort): %s",
            exc,
            extra=log_extra,
        )
        return charts


def m4_chart_generator(state: ADAMState, config: RunnableConfig) -> dict:
    """Gráficos financieros para M4. Ambos perfiles."""
    try:
        cfg = Configuration.from_runnable_config(config)
        # Fix C-05: _get_chart_llm (16384 tokens) para JSON pesado de múltiples charts
        llm = _get_chart_llm(cfg.writer_model, temperature=0.4, thinking_level="minimal")

        context = _build_base_context(state)
        context.update({
            "m4_content": state.get("m4_content", ""),
            "anexo_financiero": state.get("doc1_anexo_financiero", ""),
            "algorithm_mode": _extract_state_algorithm_mode(state) or "single",
            "computed_metrics_block": build_computed_metrics_block(state.get("m3_metrics_summary")),
        })

        # M4-chart-trim: versión vigente = 2 gráficos (Payback + Comparativa A/B/C); el Gráfico de
        # Sensibilidad (Tornado) se retiró. El kill-switch M4_CHART_DROP_SENSITIVITY=false revierte a
        # los prompts LEGACY (3 gráficos) Y desactiva el backstop → comportamiento byte-idéntico al
        # previo, sin redeploy.
        use_legacy_charts = not settings.m4_chart_drop_sensitivity
        # Issue #437 (ADR 0003, Fase 1) — the Impact Lens applies ONLY on the current 2-chart path;
        # the 3-chart tornado revert (M4_CHART_DROP_SENSITIVITY=false) skips it entirely (full legacy).
        _lens_on = settings.impact_lens and not use_legacy_charts
        if use_legacy_charts:
            charts_by_family = M4_CHARTS_PROMPT_BY_FAMILY_LEGACY
            default_chart_prompt = M4_CHART_GENERATOR_PROMPT_LEGACY
            business_chart_prompt = M4_CHART_BUSINESS_PROMPT_CLASSIFICATION_LEGACY
        elif _lens_on:
            charts_by_family = M4_CHARTS_PROMPT_BY_FAMILY_NEUTRAL
            default_chart_prompt = M4_CHART_GENERATOR_PROMPT_NEUTRAL
            business_chart_prompt = M4_CHART_BUSINESS_PROMPT_CLASSIFICATION_NEUTRAL
        else:
            charts_by_family = M4_CHARTS_PROMPT_BY_FAMILY
            default_chart_prompt = M4_CHART_GENERATOR_PROMPT
            business_chart_prompt = M4_CHART_BUSINESS_PROMPT_CLASSIFICATION

        prompt = _resolve_family_prompt(state, charts_by_family, default_chart_prompt)
        # Issue #319 — business+clasificación alinea los gráficos con la narrativa LR (#306):
        # priorización por probabilidad de evento × valor en riesgo. No-op para ml_ds y demás familias.
        prompt = _maybe_business_classification_prompt(state, prompt, business_chart_prompt)
        # Issue #437 — append the «MARCO DE VALOR» hint (brace-free) on the 2-chart lens path.
        if _lens_on:
            prompt = prompt + build_impact_lens_hint(_resolve_impact_lens(state))
        formatted_prompt = prompt.format(**context)
        result: EDAChartGeneratorOutput = llm.with_structured_output(
            EDAChartGeneratorOutput
        ).invoke(formatted_prompt)
        charts = [c.model_dump() for c in result.charts]

        # Grounding de coherencia de gráficos (ml_ds+clf y business+clf): reprompt-once-then-DROP de
        # cualquier gráfico que cite una métrica del modelo no verificada (anclada al M3 ejecutado),
        # nombre un modelo no seleccionado, o inflija lenguaje de fabricación ("benchmarks"). Cierra
        # el gap "los charts no pasan por los guards de #243/#337". Best-effort, gateado por
        # M4_CHART_GROUNDING; no-op byte-idéntico para no-clasificación. La variante de notebook
        # RESUELTA (None salvo ml_ds+clf, espeja m5_questions_generator) alimenta el guard de fuga.
        _chart_variant: str | None = None
        if _is_ml_ds_classification(state, default_unresolved_ml_ds_to_classification=True):
            _chart_variant, _ = _resolve_classification_notebook_variant(
                algorithm_mode=_extract_state_algorithm_mode(state),
                algoritmos=_extract_state_algoritmos(state),
            )
        charts = _apply_m4_chart_grounding(
            llm=llm,
            formatted_prompt=formatted_prompt,
            state=state,
            charts=charts,
            variant=_chart_variant,
            metrics_block=context["computed_metrics_block"],
        )

        # Backstop determinista (solo en el camino vigente): elimina cualquier gráfico de
        # sensibilidad/tornado residual que el LLM emita pese al prompt de 2 gráficos. INNER try para
        # que un fallo del backstop NUNCA vacíe los charts ni caiga al except externo (que devuelve []).
        if not use_legacy_charts:
            try:
                charts, dropped = drop_sensitivity_charts(charts)
                if dropped:
                    logger.warning(
                        "[m4_chart_generator] dropped %d residual sensitivity chart(s)",
                        dropped,
                        extra={"node": "m4_chart_generator", "dropped": dropped},
                    )
            except Exception:  # pragma: no cover - defensive; never fail/empty a job
                logger.exception("[m4_chart_generator] sensitivity-drop backstop failed")
        # Issue #436 — logger-only backstop over the FINAL chart set (after the clf reprompt-then-DROP and
        # the sensitivity drop, so for clf it sees the cleaned set → no double-count). ALL families. Warns
        # if a residual benchmark-fabrication tell survives the prompt fix; never reprompts/mutates/fails.
        if settings.m4_fabrication_guard:
            log_chart_benchmark_fabrication(
                charts, node="m4_chart_generator", case_id=state.get("case_id")
            )
        print(f"[m4_chart_generator] {len(charts)} charts generados")
        return {"m4_charts": charts, "current_agent": "m4_chart_generator"}
    except Exception as e:
        logger.error("[m4_chart_generator] ERROR: %s", e, exc_info=True)
        return {"m4_charts": [], "current_agent": "m4_chart_generator"}


# ─────────────────────────────────────────────────────────
# FASE 5 — NODOS BARRERA (fan-in)
# ─────────────────────────────────────────────────────────
def eda_phase2_sync(state: ADAMState) -> dict:
    """Fan-in final de EDA: limpia §4 residual e inyecta CTA condicional.

    v9 Hybrid Architecture: las preguntas socráticas ya NO se inyectan en el
    reporte markdown — el frontend las renderiza como cajas interactivas desde
    doc2_preguntas_eda (JSON). Este sync node ahora:
    1. Limpia cualquier §4 residual que el LLM pueda generar por inercia.
    2. Inyecta un CTA (Call to Action) condicional según student_profile.
    """
    doc2_eda = state.get("doc2_eda", "")

    if not doc2_eda:
        print("[eda_phase2_sync] Sin reporte EDA — skip")
        return {}

    # ── Paso 1: Limpieza defensiva — eliminar §4 residual si el LLM la generó ──
    # Regex con re.DOTALL para capturar contenido multi-línea dentro de §4.
    # Busca: ## 4. Preguntas Socráticas (con variaciones de acentos/puntuación)
    # Elimina todo desde el H2 hasta el siguiente H2 o fin de documento.
    pattern_s4 = re.compile(
        r'\n*##\s*4\.?\s*Preguntas\s*Socr[aá]ticas[^\n]*\n[\s\S]*?(?=\n##\s|\Z)',
        flags=re.IGNORECASE | re.DOTALL
    )
    doc2_eda_clean = pattern_s4.sub('', doc2_eda).rstrip()

    if doc2_eda_clean != doc2_eda.rstrip():
        print("[eda_phase2_sync] §4 residual eliminada del reporte EDA")

    # ── Paso 2: Inyectar CTA condicional según perfil ──
    profile = state.get("studentProfile", "business")

    if profile == "ml_ds":
        cta = (
            "\n\n---\n\n"
            "<p><em><strong>Tu turno:</strong> Con los insights del Módulo 2, "
            "avanza al Módulo 3 donde encontrarás el diseño experimental y el "
            "notebook ejecutable para validar los algoritmos. "
            "Responde las preguntas a continuación sobre el análisis exploratorio.</em></p>"
        )
    else:
        cta = (
            "\n\n---\n\n"
            "<p><em><strong>Tu turno:</strong> Analiza los gráficos interactivos generados "
            "en la plataforma y utiliza esos insights para responder a las preguntas en el "
            "formulario interactivo a continuación.</em></p>"
        )

    doc2_eda_final = doc2_eda_clean + cta
    print(f"[eda_phase2_sync] CTA inyectado para perfil '{profile}' — {len(doc2_eda_final)} chars")

    return {"doc2_eda": doc2_eda_final}


def synthesis_phase1_sync(state: ADAMState) -> dict:
    """Fan-in 1: m5_content + teaching_note_part1 listos.
    Después de este barrier, m5_questions_generator corre primero (secuencial),
    luego teaching_note_part2 con la consigna M5 disponible.
    """
    print("[synthesis_phase1_sync] Barrier 1 OK — m5_content disponible")
    return {}


# Resume sentinel prefix (e.g. "[TEACHING_NOTE_PART1_ERROR] ") makes _is_resumable_state_value
# recompute a catastrophically-failed part on resume. It must stay in the per-part state keys but
# NEVER reach the teacher-facing doc3_teaching_note — strip it from the COMPOSED note only. No-op
# (byte-identical) for the legacy and happy paths, which carry no sentinel.
_TEACHING_NOTE_ERROR_SENTINEL_RE = re.compile(r"^\[[A-Z0-9_]+_ERROR\]\s*")


def synthesis_phase2_sync(state: ADAMState) -> dict:
    """Fan-in 2: teaching_note_part2 + consigna M5 listos.
    Concatena las 2 partes de la Teaching Note en doc3_teaching_note.
    """
    part1 = _TEACHING_NOTE_ERROR_SENTINEL_RE.sub("", state.get("doc3_teaching_note_part1", ""))
    part2 = _TEACHING_NOTE_ERROR_SENTINEL_RE.sub("", state.get("doc3_teaching_note_part2", ""))
    full_note = f"{part1}\n\n{part2}".strip()
    print(f"[synthesis_phase2_sync] Teaching Note completa: {len(full_note)} chars")
    return {"doc3_teaching_note": full_note}


# ─────────────────────────────────────────────────────────
# v9 — M5 CONTENT GENERATOR: Informe de Resolución (Junta Directiva)
# Genera el reto final VISIBLE PARA EL ESTUDIANTE con 3 secciones:
#   Sección 1: Insight Destacado del Caso (sin spoiler — "El Dilema Directivo")
#   Sección 2: Introducción al reto de Junta Directiva + estructura de memorándum
#   Sección 3: Cierre del Sistema ADAM
# is_docente_only = False: este artefacto es student-facing.
# ─────────────────────────────────────────────────────────
def m5_content_generator(state: ADAMState, config: RunnableConfig) -> dict:
    """Genera el Informe de Resolución del Módulo 5 (student-facing).

    Redeseñado en v9: el artefacto es visible para el estudiante como reto de Junta
    Directiva. Contiene Insight Destacado (sin spoiler de decisión), introducción al
    reto y cierre del sistema. La solucion_esperada se genera en m5_questions_generator
    y son filtradas por frontend_output_adapter antes de llegar al estudiante.
    """
    try:
        cfg = Configuration.from_runnable_config(config)
        m5_model = resolve_node_model(cfg, NODE_M5_CONTENT, cfg.architect_model)
        logger.info("[m5_content_generator] llm model=%s", m5_model)
        llm = _get_m5_llm(m5_model, cfg.writer_model, temperature=0.6)

        context = _build_base_context(state)
        context.update({
            # 8000 chars incluye opciones A/B/C al final de la narrativa
            "contexto_m1": state.get("doc1_narrativa", "")[:8000],
            "contexto_m2": state.get("doc2_eda", "") or "DATASET_UNAVAILABLE",
            "contexto_m3": state.get("m3_content", "") or "[M3_NOT_EXECUTED]",
            "contexto_m4": state.get("m4_content", "") or "",
        })
        # Issue #330 — narrativa M5 variant-aware para ml_ds + clasificación.
        # Réplica del dispatch de M3/M4: la matriz de decisión ajusta su columna
        # "modelo soporte" a lr_only/rf_only/lr_rf_contrast. La cabecera de la matriz
        # se conserva en las 3 variantes, así que el contrato require_decision_matrix
        # de _invoke_m5_content_with_contract sigue intacto. business y familias
        # no-clasificación pasan el dict original sin cambios.
        _algoritmos_raw = _extract_state_algoritmos(state)
        _algorithm_mode = _extract_state_algorithm_mode(state)
        _profile, _primary_family = _resolve_generation_focus(state)
        variant: str | None = None
        if _profile == "ml_ds" and _primary_family == "clasificacion":
            _variant, _variant_warning = _resolve_classification_notebook_variant(
                algorithm_mode=_algorithm_mode,
                algoritmos=_algoritmos_raw,
            )
            variant = _variant
            if _variant_warning:
                logger.warning(
                    "[m5_content_generator] narrative variant fallback — "
                    "variant=%s algoritmos=%r reason: %s",
                    _variant, _algoritmos_raw, _variant_warning,
                )
            _effective_prompt_by_family: dict[str, str] = {
                **M5_PROMPT_BY_FAMILY,
                "clasificacion": M5_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT[_variant],
            }
        else:
            _effective_prompt_by_family = M5_PROMPT_BY_FAMILY
        prompt_template, metrics_block, grounding_enabled, grounding_update = (
            _select_narrative_prompt(
                state,
                "m5_content_generator",
                _effective_prompt_by_family,
                M5_CONTENT_GENERATOR_PROMPT,
            )
        )
        # Issue #306 — business+clasificación prioriza por el ranking de riesgo del modelo.
        # No-op para ml_ds y para business no-clasificación.
        prompt_template = _maybe_business_classification_prompt(
            state, prompt_template, M5_BUSINESS_PROMPT_CLASSIFICATION
        )
        # Issue #437 Fase 3 — append the value-frame hint (brace-free) so the M5 decision matrix's
        # "KPI esperado" column uses the resolved lens's value metric, not a default business indicator.
        # Skipped for financial_roi (the matrix's native frame) → byte-identical for the dominant cohort
        # even with the switch on. The matrix header stays byte-identical (it's in the import-time
        # constant; the hint is APPENDED). DD1: this consumes the SAME _resolve_impact_lens as M1/M4/M6.
        _m5_lens = _resolve_impact_lens(state)
        if settings.impact_lens and _m5_lens != DEFAULT_IMPACT_LENS:
            prompt_template = prompt_template + build_impact_lens_m5_hint(_m5_lens)
        context["computed_metrics_block"] = metrics_block

        m5 = _invoke_m5_content_with_contract(
            llm=llm,
            prompt=prompt_template.format(**context),
            metrics_block=metrics_block,
            grounding_enabled=grounding_enabled,
            require_decision_matrix=_is_ml_ds_classification(
                state,
                default_unresolved_ml_ds_to_classification=True,
            ),
            variant=variant,
        )
        print(f"[m5_content_generator] {len(m5)} chars")
        # Issue #437 follow-up — logger-only backstop (mirror of m4_content_generator): warn if a
        # machine ``word__x`` identifier survived in the M5 narrative. M5 shares the same
        # ``computed_metrics_block`` as M4, so the deterministic strip already cures the known path;
        # this is the net. Best-effort — never reprompts, mutates, or fails the job.
        if settings.case_identifier_leak_guard:
            log_raw_identifier_leak(
                m5, node="m5_content_generator", case_id=state.get("case_id")
            )
        return {
            "m5_content": m5,
            "current_agent": "m5_content_generator",
            **grounding_update,
        }
    except RuntimeError:
        raise
    except Exception as e:
        logger.error("[m5_content_generator] ERROR: %s", e, exc_info=True)
        return {"m5_content": "[M5_GENERATION_ERROR]", "current_agent": "m5_content_generator"}


# ─────────────────────────────────────────────────────────
# CONSTRUCCIÓN DE SUBGRAFOS (FASE 4 - ARQUITECTURA MODULAR)
# ─────────────────────────────────────────────────────────

RESUME_CACHE_STATE_KEY = "resume_cached_nodes"
_PARALLEL_NODES_WITHOUT_AGENT = {"case_writer", "case_questions"}
_RESUME_NODE_AGENT_OVERRIDES = {"eda_questions_generator": "doc3_generation"}
_RESUME_NODE_REQUIRED_OUTPUTS: dict[str, tuple[str, ...]] = {
    "case_architect": (
        "titulo",
        "industria",
        "company_profile",
        "dilema_brief",
        "doc1_instrucciones",
        "doc1_anexo_financiero",
        "doc1_anexo_operativo",
        "doc1_anexo_stakeholders",
    ),
    "case_writer": ("doc1_narrativa",),
    "case_questions": ("doc1_preguntas",),
    "eda_text_analyst": ("doc2_eda",),
    "eda_chart_generator": ("doc2_eda_charts",),
    "eda_questions_generator": ("doc2_preguntas_eda",),
    "m3_content_generator": ("m3_content", "m3_mode"),
    "m3_questions_generator": ("m3_questions",),
    "m3_notebook_generator": ("m3_notebook_code",),
    "m3_notebook_executor": ("m3_metrics_summary",),
    "m4_content_generator": ("m4_content",),
    "m4_questions_generator": ("m4_questions",),
    "m4_chart_generator": ("m4_charts",),
    "m5_content_generator": ("m5_content",),
    "m5_questions_generator": ("m5_questions",),
    "teaching_note_part1": ("doc3_teaching_note_part1",),
    "teaching_note_part2": ("doc3_teaching_note_part2",),
}


def _is_resumable_state_value(value: Any) -> bool:
    """Return True when a state value is usable for resume skip decisions."""
    if value is None:
        return False
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return False
        # Sentinel placeholders indicate generation failures and should be recomputed.
        if normalized.startswith("[") and ("_ERROR]" in normalized or "_NOT_EXECUTED]" in normalized):
            return False
        return True
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) > 0
    return True


def _artifact_cached_output_for_node(node_name: str, state: ADAMState) -> dict[str, Any] | None:
    cached_nodes = state.get(RESUME_CACHE_STATE_KEY)
    if not isinstance(cached_nodes, dict):
        return None
    node_payload = cached_nodes.get(node_name)
    if not isinstance(node_payload, dict):
        return None
    hydrated_payload = {
        key: value
        for key, value in node_payload.items()
        if _is_resumable_state_value(value)
    }
    return hydrated_payload or None


def _checkpoint_has_node_output(node_name: str, state: ADAMState) -> bool:
    if node_name == "m3_notebook_executor":
        return _is_resumable_state_value(state.get("m3_metrics_summary"))

    required_keys = _RESUME_NODE_REQUIRED_OUTPUTS.get(node_name, ())
    if not required_keys:
        return False
    return all(_is_resumable_state_value(state.get(key)) for key in required_keys)


def _skip_payload_for_node(node_name: str) -> dict[str, Any]:
    if node_name in _PARALLEL_NODES_WITHOUT_AGENT:
        return {}
    return {"current_agent": _RESUME_NODE_AGENT_OVERRIDES.get(node_name, node_name)}


def _with_resume_skip(node_name: str, node_callable: Any) -> Any:
    """Wrap a graph node to short-circuit when checkpoint/artifact state already exists."""

    def _wrapped(
        state: ADAMState,
        config: RunnableConfig | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        cached_payload = _artifact_cached_output_for_node(node_name, state)
        if cached_payload is not None:
            payload = dict(cached_payload)
            if node_name not in _PARALLEL_NODES_WITHOUT_AGENT:
                payload.setdefault("current_agent", _RESUME_NODE_AGENT_OVERRIDES.get(node_name, node_name))
            logger.info(
                "[resume_skip] node=%s source=artifact_cache keys=%s",
                node_name,
                sorted(payload.keys()),
            )
            return payload

        if _checkpoint_has_node_output(node_name, state):
            logger.info("[resume_skip] node=%s source=checkpoint_state", node_name)
            return _skip_payload_for_node(node_name)

        if config is None:
            return cast(dict[str, Any], node_callable(state, *args, **kwargs))

        return cast(dict[str, Any], node_callable(state, config, *args, **kwargs))

    return _wrapped

# Política de reintento estándar para manejar fallos de red / timeouts del LLM
# Verificado contra Context7 docs (langchain-ai/langgraph): RetryPolicy soporta
# backoff_factor (multiplica interval en cada intento), max_interval (techo en segundos),
# y jitter (añade aleatoriedad para evitar thundering herd). Todos los params son
# documentados en RetryPolicy.__init__ — no son kwargs experimentales.
standard_retry = RetryPolicy(
    max_attempts=3,
    initial_interval=1.0,
    backoff_factor=2.0,   # Fix B-04: 1s → 2s → 4s (exponencial)
    max_interval=30.0,    # Cap: nunca espera más de 30s entre reintentos
    jitter=True,          # Evita thundering herd con múltiples workers concurrentes
)

# --- 1. SUBGRAFO: DOC 1 (Arquitecto, Redactor, Preguntas) ---
doc1_builder = StateGraph(ADAMState)
doc1_builder.add_node("case_architect", _with_resume_skip("case_architect", case_architect), retry_policy=standard_retry)
doc1_builder.add_node("case_writer", _with_resume_skip("case_writer", case_writer), retry_policy=standard_retry)
doc1_builder.add_node("case_questions", _with_resume_skip("case_questions", case_questions), retry_policy=standard_retry)
doc1_builder.add_node("doc1_complete", doc1_complete)

doc1_builder.add_edge(START, "case_architect")
# Fan-out Paralelo: Writer y Questions se ejecutan al mismo tiempo.
# Fix C-02: NINGUNO de los dos nodos paralelos escribe 'current_agent'.
# Escribirlo en ambos causaría una race condition no-determinista (el último
# en terminar gana), ya que el reducer es Annotated[str, _last_value].
# case_architect ya lo setea como "case_architect" — los nodos paralelos
# lo heredan del state sin sobreescribirlo.
doc1_builder.add_edge("case_architect", "case_writer")
doc1_builder.add_edge("case_architect", "case_questions")
# Fan-in → END
doc1_builder.add_edge("case_writer", "doc1_complete")
doc1_builder.add_edge("case_questions", "doc1_complete")
doc1_builder.add_edge("doc1_complete", END)

doc1_graph = doc1_builder.compile()


# --- 1b. BARRERA M3 ---
def m3_sync(state: ADAMState) -> dict:
    """Fan-in: m3_questions + m3_notebook listos."""
    print("[m3_sync] M3 fan-in OK")
    return {}


# --- 2. SUBGRAFO: M3 ---
# business: m3_content (Auditor) → m3_questions_generator → m3_sync → END
# ml_ds:    m3_content (Experiment Engineer) → [m3_questions ∥ (m3_notebook → executor)] → m3_sync → END
# m3_notebook_generator/executor son noop para business y non-notebook depth.
m3_builder = StateGraph(ADAMState)
m3_builder.add_node(
    "m3_content_generator",
    _with_resume_skip("m3_content_generator", m3_content_generator),
    retry_policy=standard_retry,
)
m3_builder.add_node(
    "m3_questions_generator",
    _with_resume_skip("m3_questions_generator", m3_questions_generator),
    retry_policy=standard_retry,
)
m3_builder.add_node(
    "m3_notebook_generator",
    _with_resume_skip("m3_notebook_generator", m3_notebook_generator),
    retry_policy=standard_retry,
)
m3_builder.add_node(
    "m3_notebook_executor",
    _with_resume_skip("m3_notebook_executor", m3_notebook_executor),
)
m3_builder.add_node("m3_sync", m3_sync)

m3_builder.add_edge(START, "m3_content_generator")
m3_builder.add_edge("m3_content_generator", "m3_questions_generator")
m3_builder.add_edge("m3_content_generator", "m3_notebook_generator")
m3_builder.add_edge("m3_questions_generator", "m3_sync")
m3_builder.add_edge("m3_notebook_generator", "m3_notebook_executor")
m3_builder.add_edge("m3_notebook_executor", "m3_sync")
m3_builder.add_edge("m3_sync", END)

m3_graph = m3_builder.compile()


# --- 2b. BARRERA M4 ---
def m4_sync(state: ADAMState) -> dict:
    """Fan-in: m4_questions + m4_charts listos."""
    print("[m4_sync] M4 fan-in OK")
    return {}


# --- 3. SUBGRAFO: M4 (Impacto y Valor) ---
# m4_content → [m4_questions_generator ∥ m4_chart_generator] → m4_sync → END
m4_builder = StateGraph(ADAMState)
m4_builder.add_node(
    "m4_content_generator",
    _with_resume_skip("m4_content_generator", m4_content_generator),
    retry_policy=standard_retry,
)
m4_builder.add_node(
    "m4_questions_generator",
    _with_resume_skip("m4_questions_generator", m4_questions_generator),
    retry_policy=standard_retry,
)
m4_builder.add_node(
    "m4_chart_generator",
    _with_resume_skip("m4_chart_generator", m4_chart_generator),
    retry_policy=standard_retry,
)
m4_builder.add_node("m4_sync", m4_sync)

m4_builder.add_edge(START, "m4_content_generator")
# Fan-out: questions y charts corren en paralelo después de content
m4_builder.add_edge("m4_content_generator", "m4_questions_generator")
m4_builder.add_edge("m4_content_generator", "m4_chart_generator")
# Fan-in
m4_builder.add_edge("m4_questions_generator", "m4_sync")
m4_builder.add_edge("m4_chart_generator", "m4_sync")
m4_builder.add_edge("m4_sync", END)

m4_graph = m4_builder.compile()


# --- 4. SUBGRAFO: EDA ---
# Flujo: schema_designer → data_generator → data_validator [retry]
#   → eda_text_analyst → eda_chart_generator
#   → eda_questions_generator → eda_phase2_sync → END
# (M2 no genera notebook — es responsabilidad de m3_notebook_generator para ml_ds)
eda_builder = StateGraph(ADAMState)

# ── Dataset pipeline (3 nodos) ───────────────────────────────────────────────
eda_builder.add_node("schema_designer", _with_resume_skip("schema_designer", schema_designer), retry_policy=standard_retry)
eda_builder.add_node("data_generator", data_generator)
eda_builder.add_node("data_validator", data_validator)

# ── Resto del flujo EDA ──────────────────────────────────────────────────────
eda_builder.add_node(
    "eda_text_analyst",
    _with_resume_skip("eda_text_analyst", eda_text_analyst),
    retry_policy=standard_retry,
)
eda_builder.add_node(
    "eda_chart_generator",
    _with_resume_skip("eda_chart_generator", eda_chart_generator),
    retry_policy=standard_retry,
)
eda_builder.add_node(
    "eda_questions_generator",
    _with_resume_skip("eda_questions_generator", eda_questions_generator),
    retry_policy=standard_retry,
)
eda_builder.add_node("eda_phase2_sync", eda_phase2_sync)

# Dataset pipeline: schema_designer → data_serializer → data_validator
eda_builder.add_edge(START, "schema_designer")
eda_builder.add_edge("schema_designer", "data_generator")
eda_builder.add_edge("data_generator", "data_validator")

# Router condicional: retry si falla y quedan intentos, continuar si no
eda_builder.add_conditional_edges(
    "data_validator",
    _route_dataset_validation,
    {
        "data_generator": "data_generator",
        "eda_text_analyst": "eda_text_analyst",
    },
)

eda_builder.add_edge("eda_text_analyst", "eda_chart_generator")
eda_builder.add_edge("eda_chart_generator", "eda_questions_generator")
eda_builder.add_edge("eda_questions_generator", "eda_phase2_sync")
eda_builder.add_edge("eda_phase2_sync", END)

eda_graph = eda_builder.compile()

# --- 3. SUBGRAFO: SYNTHESIS v9 (doble barrier, Teaching Note dividida) ---
# Topología:
#   START → [m5_content_generator + teaching_note_part1]
#         → synthesis_phase1_sync
#         → m5_questions_generator → teaching_note_part2
#         → synthesis_phase2_sync → END
#
# Fix C-04 [VERIFIED-DOCS]: LangGraph mapea automáticamente el estado completo del
# padre al hijo en subgrafos compilados. El estado ADAMState heredado por synthesis_flow
# contiene m4_questions (escrito por m4_flow upstream en el grafo maestro) antes de
# que synthesis_flow ejecute. teaching_note_part1 puede leerlo directamente.
# Ref: LangGraph docs — "Compose Graphs as Subgraphs" / "How to add and use subgraphs".
#
# Post-sync1 es SECUENCIAL: m5_questions_generator → teaching_note_part2 → sync2.
# Ventaja: teaching_note_part2 recibe la consigna M5 ya escrita en state.
synthesis_builder = StateGraph(ADAMState)
synthesis_builder.add_node(
    "m5_content_generator",
    _with_resume_skip("m5_content_generator", m5_content_generator),
    retry_policy=standard_retry,
)
synthesis_builder.add_node(
    "teaching_note_part1",
    _with_resume_skip("teaching_note_part1", teaching_note_part1),
    retry_policy=standard_retry,
)
synthesis_builder.add_node("synthesis_phase1_sync", synthesis_phase1_sync)
synthesis_builder.add_node(
    "m5_questions_generator",
    _with_resume_skip("m5_questions_generator", m5_questions_generator),
    retry_policy=standard_retry,
)
synthesis_builder.add_node(
    "teaching_note_part2",
    _with_resume_skip("teaching_note_part2", teaching_note_part2),
    retry_policy=standard_retry,
)
synthesis_builder.add_node("synthesis_phase2_sync", synthesis_phase2_sync)

# Fan-out paralelo desde START
synthesis_builder.add_edge(START, "m5_content_generator")
synthesis_builder.add_edge(START, "teaching_note_part1")

# Fan-in a barrier intermedia
synthesis_builder.add_edge("m5_content_generator", "synthesis_phase1_sync")
synthesis_builder.add_edge("teaching_note_part1", "synthesis_phase1_sync")

# Secuencial post-sync1: consigna M5 disponible para teaching_note_part2.
synthesis_builder.add_edge("synthesis_phase1_sync", "m5_questions_generator")
synthesis_builder.add_edge("m5_questions_generator", "teaching_note_part2")
synthesis_builder.add_edge("teaching_note_part2", "synthesis_phase2_sync")
synthesis_builder.add_edge("synthesis_phase2_sync", END)

synthesis_graph = synthesis_builder.compile()

# ─────────────────────────────────────────────────────────
# CONSTRUCCIÓN DEL GRAFO ORQUESTADOR MAESTRO v8
# ─────────────────────────────────────────────────────────
# harvard_with_eda: input → doc1 → eda_flow → m3_flow → m4_flow → synthesis → output
# harvard_only:     input → doc1 →                       m4_flow → synthesis → output
master_builder = StateGraph(ADAMState, context_schema=Configuration)

master_builder.add_node("input_adapter", adapter_canonical_to_legacy)
master_builder.add_node("doc1_flow", doc1_graph)
master_builder.add_node("output_adapter_intermediate", adapter_legacy_to_canonical_output)
master_builder.add_node("eda_flow", eda_graph)
master_builder.add_node("m3_flow", m3_graph)        # v8: nuevo
master_builder.add_node("m4_flow", m4_graph)         # v8: nuevo
master_builder.add_node("synthesis_flow", synthesis_graph)
master_builder.add_node("output_adapter_final", adapter_legacy_to_canonical_output)

master_builder.add_edge(START, "input_adapter")
master_builder.add_edge("input_adapter", "doc1_flow")
master_builder.add_edge("doc1_flow", "output_adapter_intermediate")


def route_master(state: ADAMState) -> str:
    """Routing post-doc1: EDA path o direct-to-m4 path."""
    case_type = state.get("caseType", "harvard_only")
    if case_type == "harvard_with_eda":
        return "eda_flow"
    return "m4_flow"   # harvard_only: salta M2 y M3, directo a M4


master_builder.add_conditional_edges("output_adapter_intermediate", route_master, {
    "eda_flow": "eda_flow",
    "m4_flow": "m4_flow",
})

# Path harvard_with_eda: EDA → M3 → M4 → Synthesis
master_builder.add_edge("eda_flow", "m3_flow")
master_builder.add_edge("m3_flow", "m4_flow")

# Convergencia: ambos paths llegan a m4_flow → synthesis → final
master_builder.add_edge("m4_flow", "synthesis_flow")
master_builder.add_edge("synthesis_flow", "output_adapter_final")
master_builder.add_edge("output_adapter_final", END)


class DurableCheckpointUnavailableError(RuntimeError):
    """Raised when the durable async LangGraph checkpoint path cannot initialize."""


_graph_singleton: Any | None = None
_graph_singleton_loop: asyncio.AbstractEventLoop | None = None
_graph_singleton_lock: asyncio.Lock | None = None
_graph_singleton_lock_loop: asyncio.AbstractEventLoop | None = None
_graph_singleton_lock_guard = threading.Lock()


def reset_graph_singleton() -> None:
    """Clear the cached compiled graph and its loop-bound initialization lock."""
    global _graph_singleton, _graph_singleton_loop
    global _graph_singleton_lock, _graph_singleton_lock_loop

    _graph_singleton = None
    _graph_singleton_loop = None
    _graph_singleton_lock = None
    _graph_singleton_lock_loop = None
    logger.info("[graph] Reset compiled graph singleton")


def _get_graph_lock(current_loop: asyncio.AbstractEventLoop) -> asyncio.Lock:
    """Return a loop-bound lock for async graph singleton initialization."""
    global _graph_singleton_lock, _graph_singleton_lock_loop

    with _graph_singleton_lock_guard:
        if _graph_singleton_lock is None or _graph_singleton_lock_loop is not current_loop:
            # Keep the lock loop separate from the compiled-graph loop marker so a
            # new event loop cannot accidentally reuse a graph/checkpointer created
            # for a previous loop.
            _graph_singleton_lock_loop = current_loop
            _graph_singleton_lock = asyncio.Lock()
    return _graph_singleton_lock


_BOOTSTRAP_SETUP_WARNING_MS = 10000.0
_BOOTSTRAP_COMPILE_WARNING_MS = 5000.0
_BOOTSTRAP_PHASE_BUDGET_RATIO = 0.8


def _bootstrap_timeout_budget_ms() -> float:
    """Return the outer bootstrap budget used by authoring wait_for()."""
    configured_timeout = settings.authoring_bootstrap_timeout_seconds
    if configured_timeout is not None and configured_timeout > 0:
        return float(configured_timeout) * 1000.0

    normalized_environment = settings.environment.strip().lower()
    return 120000.0 if normalized_environment == "development" else 60000.0


def _log_bootstrap_phase_threshold(
    *,
    phase_label: str,
    elapsed_ms: float,
    warning_ms: float,
    extra: dict[str, Any],
) -> None:
    """Emit slow-path signals without changing bootstrap control flow."""
    budget_ms = _bootstrap_timeout_budget_ms()
    if elapsed_ms >= budget_ms * _BOOTSTRAP_PHASE_BUDGET_RATIO:
        logger.error(
            "[graph] LangGraph bootstrap %s consumed most of the outer bootstrap budget",
            phase_label,
            extra=extra,
        )
    elif elapsed_ms > warning_ms:
        logger.warning(
            "[graph] LangGraph bootstrap %s exceeded slow-path threshold",
            phase_label,
            extra=extra,
        )


async def _log_checkpointer_setup_failure(
    *,
    pool: Any,
    exc: BaseException,
    setup_ms: float,
    checkpoint_migrations_version: int | None,
    is_first_init: bool,
    loop_id: int,
) -> None:
    """Emit enriched setup failure diagnostics without masking the original error."""
    diagnostics: dict[str, Any] = {}
    try:
        diagnostics = await collect_langgraph_bootstrap_diagnostics(cast(Any, pool))
    except Exception as diag_exc:
        logger.warning(
            "[graph] Bootstrap diagnostics collection failed: %s",
            diag_exc,
            extra={
                "loop_id": loop_id,
                "bootstrap_setup_ms": setup_ms,
                "checkpoint_migrations_version": checkpoint_migrations_version,
                "bootstrap_is_first_init": is_first_init,
            },
        )

    event_message = (
        "[graph] AsyncPostgresSaver setup cancelled"
        if isinstance(exc, asyncio.CancelledError)
        else "[graph] AsyncPostgresSaver setup failed"
    )
    logger.error(
        event_message,
        exc_info=(type(exc), exc, exc.__traceback__),
        extra={
            "loop_id": loop_id,
            "bootstrap_setup_ms": setup_ms,
            "checkpoint_migrations_version": checkpoint_migrations_version,
            "bootstrap_is_first_init": is_first_init,
            **snapshot_langgraph_pool_stats(pool),
            "pg_stat_activity": diagnostics.get("pg_stat_activity", []),
            "pg_locks": diagnostics.get("pg_locks", []),
        },
    )


async def _build_async_postgres_checkpointer(*, is_first_init: bool) -> AsyncPostgresSaver:
    """Build the durable async Postgres checkpointer inside an active event loop."""
    current_loop = asyncio.get_running_loop()
    loop_id = id(current_loop)
    pool: Any | None = None
    checkpoint_migrations_version: int | None = None
    setup_started_at: float | None = None

    try:
        pool = await get_langgraph_checkpointer_async_pool()
        checkpoint_migrations_version = await get_checkpoint_migrations_version(pool)
        logger.debug(
            "[graph] Initializing AsyncPostgresSaver",
            extra={
                "loop_id": loop_id,
                "checkpoint_migrations_version": checkpoint_migrations_version,
                "bootstrap_is_first_init": is_first_init,
            },
        )
        checkpointer = AsyncPostgresSaver(cast(Any, pool))
        setup_started_at = time.perf_counter()
        # Idempotent bootstrap for local/tests where Alembic metadata may be recreated.
        await checkpointer.setup()
    except asyncio.CancelledError as exc:
        setup_ms = 0.0 if setup_started_at is None else round((time.perf_counter() - setup_started_at) * 1000, 3)
        if pool is not None:
            await _log_checkpointer_setup_failure(
                pool=pool,
                exc=exc,
                setup_ms=setup_ms,
                checkpoint_migrations_version=checkpoint_migrations_version,
                is_first_init=is_first_init,
                loop_id=loop_id,
            )
        else:
            logger.error(
                "[graph] AsyncPostgresSaver setup cancelled before pool bootstrap finished",
                exc_info=(type(exc), exc, exc.__traceback__),
                extra={
                    "loop_id": loop_id,
                    "bootstrap_setup_ms": setup_ms,
                    "checkpoint_migrations_version": checkpoint_migrations_version,
                    "bootstrap_is_first_init": is_first_init,
                },
            )
        await clean_authoring_runtime(
            reason="graph_bootstrap_cancelled",
            timeout_seconds=5.0,
            clear_active_jobs=False,
        )
        raise
    except Exception as exc:
        setup_ms = 0.0 if setup_started_at is None else round((time.perf_counter() - setup_started_at) * 1000, 3)
        if pool is not None:
            await _log_checkpointer_setup_failure(
                pool=pool,
                exc=exc,
                setup_ms=setup_ms,
                checkpoint_migrations_version=checkpoint_migrations_version,
                is_first_init=is_first_init,
                loop_id=loop_id,
            )
        else:
            logger.error(
                "[graph] AsyncPostgresSaver setup failed before pool bootstrap finished",
                exc_info=(type(exc), exc, exc.__traceback__),
                extra={
                    "loop_id": loop_id,
                    "bootstrap_setup_ms": setup_ms,
                    "checkpoint_migrations_version": checkpoint_migrations_version,
                    "bootstrap_is_first_init": is_first_init,
                },
            )
        await clean_authoring_runtime(
            reason="graph_bootstrap_failed",
            timeout_seconds=5.0,
            clear_active_jobs=False,
        )
        raise

    setup_ms = 0.0 if setup_started_at is None else round((time.perf_counter() - setup_started_at) * 1000, 3)
    logger.info(
        "[graph] AsyncPostgresSaver initialized",
        extra={
            "loop_id": loop_id,
            "bootstrap_setup_ms": setup_ms,
            "checkpoint_migrations_version": checkpoint_migrations_version,
            "bootstrap_is_first_init": is_first_init,
        },
    )
    _log_bootstrap_phase_threshold(
        phase_label="setup()",
        elapsed_ms=setup_ms,
        warning_ms=_BOOTSTRAP_SETUP_WARNING_MS,
        extra={
            "loop_id": loop_id,
            "bootstrap_setup_ms": setup_ms,
            "checkpoint_migrations_version": checkpoint_migrations_version,
            "bootstrap_is_first_init": is_first_init,
        },
    )
    return checkpointer


async def get_graph() -> Any:
    """Return the compiled master graph backed by a durable async checkpointer.

    This is a lazy singleton per active event loop so the async saver is always
    created under the loop that will later execute `graph.astream(...)`.
    """
    global _graph_singleton, _graph_singleton_loop

    current_loop = asyncio.get_running_loop()
    if _graph_singleton is not None and _graph_singleton_loop is current_loop:
        return _graph_singleton

    async with _get_graph_lock(current_loop):
        if _graph_singleton is not None and _graph_singleton_loop is current_loop:
            return _graph_singleton

        is_first_init = _graph_singleton is None
        bootstrap_started_at = time.perf_counter()
        checkpointer = await _build_async_postgres_checkpointer(is_first_init=is_first_init)
        compile_started_at = time.perf_counter()
        compiled_graph = master_builder.compile(name="adam-agent", checkpointer=checkpointer)
        compile_ms = round((time.perf_counter() - compile_started_at) * 1000, 3)
        total_ms = round((time.perf_counter() - bootstrap_started_at) * 1000, 3)
        _graph_singleton = compiled_graph
        _graph_singleton_loop = current_loop
        logger.info(
            "[graph] Compiled master graph with AsyncPostgresSaver",
            extra={
                "loop_id": id(current_loop),
                "bootstrap_compile_ms": compile_ms,
                "bootstrap_total_ms": total_ms,
                "bootstrap_is_first_init": is_first_init,
            },
        )
        _log_bootstrap_phase_threshold(
            phase_label="compile()",
            elapsed_ms=compile_ms,
            warning_ms=_BOOTSTRAP_COMPILE_WARNING_MS,
            extra={
                "loop_id": id(current_loop),
                "bootstrap_compile_ms": compile_ms,
                "bootstrap_total_ms": total_ms,
                "bootstrap_is_first_init": is_first_init,
            },
        )
        return compiled_graph

