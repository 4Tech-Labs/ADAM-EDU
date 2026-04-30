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
  m3_flow: m3_content_generator → [m3_questions_generator ∥ m3_notebook_generator] → m3_sync
           (m3_notebook_generator: noop si output_depth != "visual_plus_notebook")
  m4_flow: m4_content → [m4_questions ∥ m4_charts] → m4_sync
  synthesis_flow: [m5_content ∥ teaching_note_part1]
                  → sync1 → m5_questions → teaching_note_part2 → sync2

Total nodos LLM por path:
  harvard_only (business): ~10 llamadas
  harvard_with_eda (ml_ds + notebook): ~19 llamadas

Modelos:
  architect_model (Pro): case_architect, schema_designer
  m3 (Pro chain) : m3_content_generator (ml_ds), m3_notebook_generator
  writer_model (Flash): m3_content_generator (business), demás nodos LLM
  chart_llm (Flash, 16K tokens): chart generators (M2, M3, M4)
  Cadenas de fallback (depende del nodo, no es global):
    - _get_writer_llm  / _get_chart_llm    : primary -> gemini-2.5-flash
    - _get_architect_llm                   : Pro-high -> Pro-medium -> gemini-3-flash-preview
    - _get_m5_llm                          : Pro -> gemini-3-flash-preview -> gemini-2.5-flash
    - schema_designer (M2 inline)          : Pro-medium -> Pro-low -> gemini-3-flash-preview
    - m3_content_generator (ml_ds inline)  : Pro-medium -> Pro-low -> gemini-3-flash-preview
    - m3_notebook_generator (inline)       : Pro-medium -> Pro-low -> gemini-3-flash-preview
  Python puro (0 tokens): data_generator, data_validator, barriers sync

Resiliencia (v9):
  - InMemoryRateLimiter: 10 req/s por instancia Cloud Run (burst 20)
  - .with_fallbacks: primary → gemini-2.5-flash automático en caída de API
  - Fallback graceful: todos los nodos LLM retornan sentinel en vez de raise
  - RetryPolicy: backoff exponencial (1s → 2s → 4s, max 30s, jitter ON)
    - Timeout global: 900 segundos por job (authoring.py)
  - AsyncPostgresSaver: checkpointer para resume-from-failure
    - get_graph(): singleton lazy por event loop para evitar reuse cruzado en tests/workers async
"""

import asyncio
import json
import logging
import os
import random
import re
import threading
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

logger = logging.getLogger("adam.graph")
from pydantic import ValidationError

from dotenv import load_dotenv
from langchain_core.exceptions import OutputParserException
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_core.runnables import RunnableConfig
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver as LangGraphAsyncPostgresSaver
from langgraph.graph import StateGraph, START, END
from langgraph.types import RetryPolicy
from psycopg.errors import UndefinedTable

from case_generator.state import ADAMState
from case_generator.configuration import Configuration
from case_generator.prompts import (
    CASE_ARCHITECT_PROMPT,
    CASE_QUESTIONS_PROMPT,
    CASE_WRITER_PROMPT,
    EDA_ANNOTATE_ONLY_PROMPT,
    EDA_CHART_GENERATOR_PROMPT,
    EDA_QUESTIONS_GENERATOR_PROMPT,
    EDA_TEXT_ANALYST_PROMPT,
    M4_QUESTIONS_GENERATOR_PROMPT,
    M5_QUESTIONS_GENERATOR_PROMPT,
    # v8 M3 — prompts por perfil (aliases backward-compat también disponibles)
    M3_AUDIT_PROMPT,
    M3_EXPERIMENT_PROMPT,
    M3_AUDIT_QUESTIONS_PROMPT,
    M3_EXPERIMENT_QUESTIONS_PROMPT,
    M3_NOTEBOOK_BASE_TEMPLATE,
    PROMPT_BY_FAMILY,
    M4_CONTENT_GENERATOR_PROMPT,
    M4_CHART_GENERATOR_PROMPT,
    M5_CONTENT_GENERATOR_PROMPT,
    TEACHING_NOTE_PART1_PROMPT,
    TEACHING_NOTE_PART2_PROMPT,
    SCHEMA_DESIGNER_PROMPT,
)
from case_generator.suggest_service import (
    family_of,
    get_dispatch_meta,
    resolve_legacy_family,
)
from case_generator.tools_and_schemas import (
    CaseArchitectOutput,
    EDAAnnotateOnlyOutput,
    EDAChartGeneratorOutput,
    GeneradorPreguntasOutput,
    GeneradorPreguntasM5Output,
    EDAQuestionsOutput,
    DatasetSchema,
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


# ─── LLM Factory ────────────────────────────────────────


def _get_writer_llm(
    model: str,
    temperature: float = 0.7,
    thinking_level: str = "low",
):
    """LLM estándar (Flash) para redacción y structured output.
    Fallback automático a gemini-2.5-flash si el primary falla.
    """
    primary = ChatGoogleGenerativeAI(
        model=model,
        temperature=temperature,
        thinking_level=thinking_level,
        max_retries=2,
        max_output_tokens=8192,
        api_key=os.getenv("GEMINI_API_KEY"),
        rate_limiter=_rate_limiter,
    )
    # Fallback: modelo anterior estable. Mismos prompts funcionan sin cambios.
    fallback = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=temperature,
        max_output_tokens=8192,
        max_retries=2,
        api_key=os.getenv("GEMINI_API_KEY"),
        rate_limiter=_rate_limiter,
    )
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
    primary = ChatGoogleGenerativeAI(
        model=model,
        temperature=temperature,
        thinking_level=thinking_level,
        max_retries=2,
        max_output_tokens=16384,
        api_key=os.getenv("GEMINI_API_KEY"),
        rate_limiter=_rate_limiter,
        model_kwargs={"tools": [{"code_execution": {}}]},
    )
    # Cadena de fallbacks ordenada:
    #   1) Pro con thinking_level="medium": misma calidad de modelo, menos
    #      reasoning tokens. Cubre fallos transitorios (rate limit, 5xx puntual,
    #      parser error en una respuesta).
    #   2) Flash: red de seguridad final por si Pro está caído globalmente.
    pro_fallback_medium = ChatGoogleGenerativeAI(
        model=model,
        temperature=temperature,
        thinking_level="medium",
        max_retries=2,
        max_output_tokens=16384,
        api_key=os.getenv("GEMINI_API_KEY"),
        rate_limiter=_rate_limiter,
        model_kwargs={"tools": [{"code_execution": {}}]},
    )
    flash_fallback = ChatGoogleGenerativeAI(
        model="gemini-3-flash-preview",
        temperature=temperature,
        max_output_tokens=16384,
        max_retries=2,
        api_key=os.getenv("GEMINI_API_KEY"),
        rate_limiter=_rate_limiter,
    )
    return primary.with_fallbacks([pro_fallback_medium, flash_fallback])


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
    primary = ChatGoogleGenerativeAI(
        model=model,
        temperature=temperature,
        thinking_level=thinking_level,
        max_retries=2,
        max_output_tokens=16384,
        api_key=os.getenv("GEMINI_API_KEY"),
        rate_limiter=_rate_limiter,
    )
    fallback = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=temperature,
        max_output_tokens=16384,
        max_retries=2,
        api_key=os.getenv("GEMINI_API_KEY"),
        rate_limiter=_rate_limiter,
    )
    return primary.with_fallbacks([fallback])


def _get_m5_llm(
    model: str,
    temperature: float = 0.5,
    thinking_level: str = "medium",
):
    """LLM Pro para m5_questions_generator — preguntas de Junta Directiva.

    Usa architect_model (Pro) porque M5 es la evaluación final integrativa:
    3 preguntas × solucion_esperada 250-300 palabras + JSON = ~3000-4000 tokens.
    Con thinking_level="medium" el modelo consume ~2-4K tokens de reasoning
    adicionales — el mismo bug silencioso de _get_chart_llm aplica aquí.
    Fix: 16384 tokens de output garantizan que las 3 solucion_esperada se completen.

    Cadena de 3 fallbacks para resiliencia ante spikes 503:
    1. gemini-3.1-pro-preview  (thinking="medium" — calidad máxima)
    2. gemini-3-flash-preview   (thinking="minimal" — misma familia, menor costo)
    3. gemini-2.5-flash         (sin thinking — infraestructura distinta/estable)
    El 3er nivel cubre spikes que afectan toda la familia gemini-3-preview.
    """
    primary = ChatGoogleGenerativeAI(
        model=model,
        temperature=temperature,
        thinking_level=thinking_level,
        max_retries=2,
        max_output_tokens=16384,
        api_key=os.getenv("GEMINI_API_KEY"),
        rate_limiter=_rate_limiter,
    )
    fallback_flash = ChatGoogleGenerativeAI(
        model="gemini-3-flash-preview",
        temperature=temperature,
        thinking_level="minimal",
        max_output_tokens=16384,
        max_retries=2,
        api_key=os.getenv("GEMINI_API_KEY"),
        rate_limiter=_rate_limiter,
    )
    # Nivel 3 — generación anterior estable; no soporta thinking_level.
    fallback_stable = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=temperature,
        max_output_tokens=16384,
        max_retries=2,
        api_key=os.getenv("GEMINI_API_KEY"),
        rate_limiter=_rate_limiter,
    )
    return primary.with_fallbacks([fallback_flash, fallback_stable])


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
    return text.strip()


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

    return {
        "student_profile": profile,
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


# ─────────────────────────────────────────────────────────
# NODO 1 — CASE ARCHITECT (Pro con Code Execution)
# ─────────────────────────────────────────────────────────
def case_architect(state: ADAMState, config: RunnableConfig) -> dict:
    """Diseña los cimientos del caso: empresa, dilema, exhibits e instrucciones."""
    cfg = Configuration.from_runnable_config(config)
    llm = _get_architect_llm(cfg.architect_model, temperature=0.3, thinking_level="high")

    context = _build_base_context(state)
    context.update({
        "teacher_input": sanitize_untrusted_payload({
            "asignatura": state.get("asignatura", ""),
            "modulos": state.get("modulos", []),
            "nivel": state.get("nivel", "pregrado"),
            "perfil_estudiante": state.get("studentProfile", "business"),
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

    prompt = CASE_ARCHITECT_PROMPT.format(**context)

    try:
        result: CaseArchitectOutput = llm.with_structured_output(
            CaseArchitectOutput
        ).invoke(prompt)

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

        # Issue #238 — valida la matriz de costos del negocio para threshold
        # tuning en M3. Resolvemos la familia desde task_payload.algoritmos
        # (mismo orden que el dispatcher M3): family_of(name) → fallback
        # resolve_legacy_family(name) → None si no hay algoritmos. La política
        # es degrade-with-warning (no reprompts en M1).
        task_payload_obj = state.get("task_payload") or {}
        algoritmos_list: list = []
        if isinstance(task_payload_obj, dict):
            algoritmos_list = task_payload_obj.get("algoritmos") or []
        family_resolved: str | None = None
        if algoritmos_list:
            primary_algo = str(algoritmos_list[0])
            family_resolved = family_of(primary_algo)
            if family_resolved is None:
                legacy = resolve_legacy_family(primary_algo)
                if legacy is not None:
                    family_resolved = legacy[0]
        contract_dict, cost_warnings = _validate_business_cost_matrix(
            contract_dict, family_resolved, result.titulo
        )
        coherence_warnings = list(coherence_warnings) + cost_warnings

        return {
            "current_agent": "case_architect",
            "titulo": result.titulo,
            "industria": result.industria,
            "company_profile": result.company_profile,
            "dilema_brief": result.dilema_brief,
            "doc1_instrucciones": result.instrucciones_estudiante,
            "doc1_anexo_financiero": result.anexo_financiero,
            "doc1_anexo_operativo": result.anexo_operativo,
            "doc1_anexo_stakeholders": result.anexo_stakeholders,
            # downstream nodes leen state["dataset_schema_required"] y degradan
            # gracefully al comportamiento previo si es None.
            "dataset_schema_required": contract_dict,
            # Issue #228 — semilla de data_gap_warnings con detección de
            # mismatch título↔target. schema_designer concatenará sus propios
            # warnings (missing/leakage) preservando esta semilla.
            "data_gap_warnings": coherence_warnings,
        }
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

    prompt = CASE_WRITER_PROMPT.format(**context)

    try:
        # Invocación directa de texto crudo (sin JSON schema)
        # Esto permite que el modelo use todos sus tokens para escribir Markdown libremente
        response = llm.invoke(prompt)
        narrativa_raw = sanitize_markdown(_extract_text(response))
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
    """Genera las 6 preguntas de discusión del caso."""
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
    })

    prompt = CASE_QUESTIONS_PROMPT.format(**context)

    try:
        resultado: GeneradorPreguntasOutput = llm.with_structured_output(
            GeneradorPreguntasOutput
        ).invoke(prompt)
        
        preguntas_dict = [p.model_dump() for p in resultado.preguntas]
        print(f"[case_questions] {len(preguntas_dict)} preguntas generadas")
    except Exception as e:
        logger.error("[case_questions] ERROR tras reintentos: %s", e, exc_info=True)
        return {"doc1_preguntas": []}  # Degradación graceful — pipeline continúa sin preguntas M1

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
            "data_gap_warnings_block": (
                "\n".join(f"- {w}" for w in (state.get("data_gap_warnings") or []))
                or "(sin brechas detectadas — el dataset cubre el contrato dilema↔datos)"
            ),
        })

        prompt = EDA_TEXT_ANALYST_PROMPT.format(**context)

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

    Siempre computa correlation_matrix y cohort_matrix cuando hay datos
    suficientes — independientemente de si se identifica un target_col.
    Las regresiones lineales (target_vs_X) son opcionales y se omiten
    sin early-return cuando target_col no está disponible.

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
        # Filtra solo numéricas, redondea, y reemplaza NaN (varianza cero) con 0
        # para evitar errores de serialización JSON (json.dumps rechaza NaN nativo).
        numeric_df = df.select_dtypes(include=["number"])
        if len(numeric_df.columns) >= 2:
            corr_matrix = numeric_df.corr().round(2).fillna(0)
            results["correlation_matrix"] = {
                "x": list(corr_matrix.columns),
                "y": list(corr_matrix.columns),
                "z": corr_matrix.values.tolist(),
            }

        # ── 2. Cohort matrix (siempre, si las columnas existen) ───────────────
        retention_cols = sorted(
            [c for c in df.columns if c.startswith("retention_m")],
            key=lambda x: int(x.split("_m")[1])
        )
        if len(retention_cols) >= 2 and "period" in df.columns:
            # None en lugar de 0/NaN → Plotly los deja transparentes en el heatmap
            # (fillna(0) pintaría los huecos con el color más oscuro de la escala)
            cohort_rounded = df[retention_cols].round(4)
            cohort_z = [
                [None if pd.isna(v) else float(v) for v in row]
                for row in cohort_rounded.values.tolist()
            ]
            results["cohort_matrix"] = {
                "x": [c.replace("retention_", "").upper() for c in retention_cols],
                "y": df["period"].tolist(),
                "z": cohort_z,
            }

        # ── 3. Regresiones lineales (opcional — requiere target_col) ──────────
        target_col = _identify_target_variable(state, df)

        if not target_col or target_col not in df.columns:
            # No target → skip regressions, but still return matrices above
            return results

        if not pd.api.types.is_numeric_dtype(df[target_col]):
            unique_vals = df[target_col].dropna().unique()
            if len(unique_vals) == 2:
                df[target_col] = df[target_col].map({unique_vals[0]: 0, unique_vals[1]: 1})
            else:
                return results  # non-numeric target with >2 categories → skip regressions

        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
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


def _eda_classification_python_path(
    state: ADAMState, config: RunnableConfig, contract: dict | None
) -> dict | None:
    """Issue #237 — construye 6 charts EDA en Python y pide al LLM solo
    `description` + `notes`. Devuelve el dict de update del nodo o ``None``
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

        charts = generate_classification_eda_charts(df, target_col, contract)
        if not charts:
            logger.warning(
                "[eda_chart_generator/py] builder devolvió 0 charts — fallback a path LLM"
            )
            return None

        # Cap defensivo: el contrato Issue #237 son 6 charts.
        if len(charts) > 6:
            charts = charts[:6]

        # Annotate-only: pedimos al LLM solo description/notes por id.
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
            ]
            prompt = EDA_ANNOTATE_ONLY_PROMPT.format(
                charts_context_json=json.dumps(charts_context, ensure_ascii=False),
                case_id=state.get("case_id", "") or state.get("titulo", ""),
                student_profile=state.get("studentProfile", "ml_ds"),
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
            # Boundary Issue #237: errores del LLM nunca tumban el panel.
            logger.warning(
                "[eda_chart_generator/py] annotate-only LLM falló (%s) — sirviendo charts sin anotaciones",
                ann_err,
            )
            ann_by_id = {}

        # Merge defensivo: solo description/notes; preservamos data_source.
        for c in charts:
            cid = c.get("id", "")
            desc, notes = ann_by_id.get(cid, ("", ""))
            c["description"] = desc
            c["notes"] = notes
            c["data_source"] = "python_builder"

        # Validamos contra el schema antes de devolver (descartamos charts que rompan el contrato).
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
            logger.warning(
                "[eda_chart_generator/py] todos los charts fallaron validación — fallback a path LLM"
            )
            return None

        logger.info(
            "[eda_chart_generator/py] panel Python-determinista emitido: %d/%d charts",
            len(validated), len(charts),
        )
        return {
            "doc2_eda_charts": validated,
            "current_agent": "eda_chart_generator",
        }
    except Exception as e:  # noqa: BLE001
        logger.error(
            "[eda_chart_generator/py] ERROR no recuperable: %s — fallback a path LLM",
            e, exc_info=True,
        )
        return None


def eda_chart_generator(state: ADAMState, config: RunnableConfig) -> dict:
    """Extrae los charts JSON del reporte EDA (Documento 2 — parte charts).

    Contrato: el path LLM-JSON legacy emite exactamente 3 charts. El path
    Python-determinista (Issue #237, ml_ds + clasificacion) emite 6 charts.

    Issue #237 — para `studentProfile == "ml_ds"` y familia primaria
    `clasificacion`, los 6 charts se generan deterministicamente en Python
    y el LLM solo escribe `description`/`notes`. El path original
    (LLM-JSON monolítico) queda intacto para business y otras familias.
    """
    eda_report = state.get("doc2_eda", "")
    if not eda_report or "No disponible" in eda_report:
        print("[eda_chart_generator] Skipping: no hay reporte EDA válido")
        return {"doc2_eda_charts": [], "current_agent": "eda_chart_generator"}

    # ── Issue #237 dispatch ──────────────────────────────────────────────
    profile = state.get("studentProfile", "business")
    task_payload_obj = state.get("task_payload") or {}
    algoritmos_disp: list[str] = []
    if isinstance(task_payload_obj, dict):
        algoritmos_disp = list(task_payload_obj.get("algoritmos") or [])
    if not algoritmos_disp:
        algoritmos_disp = list(state.get("algoritmos") or [])
    primary_family, _legacy_warn = _resolve_primary_family(algoritmos_disp)
    if profile == "ml_ds" and primary_family == "clasificacion":
        contract = state.get("dataset_schema_required")
        py_update = _eda_classification_python_path(state, config, contract)
        if py_update is not None:
            return py_update
        # else: fall through to legacy LLM-JSON path with warning already logged.

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

        prompt = EDA_QUESTIONS_GENERATOR_PROMPT.format(**context)

        # v9 M2-Redesign: EDAQuestionsOutput con EDASocraticQuestion (solucion_esperada = objeto)
        resultado: EDAQuestionsOutput = llm.with_structured_output(
            EDAQuestionsOutput
        ).invoke(prompt)

        preguntas_eda_dict = [p.model_dump() for p in resultado.preguntas]
        print(f"[eda_questions_generator] {len(preguntas_eda_dict)} preguntas socráticas generadas")

        return {
            "doc2_preguntas_eda": preguntas_eda_dict,
            "current_agent": "doc3_generation",
        }

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


# ─────────────────────────────────────────────────────────
# HELPER — _build_fallback_schema (sin LLM, regex sobre Exhibit 1)
# ─────────────────────────────────────────────────────────

def _build_fallback_schema(state: ADAMState, max_rows: int, profile: str) -> dict:
    """Schema mínimo si schema_designer falla. Extrae revenue con regex del Exhibit 1."""
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

    if profile == "ml_ds":
        base_columns.extend([
            {"name": "customer_ltv",         "type": "float", "description": "Customer lifetime value",  "range_min": 500,  "range_max": 5000, "nullable": True,  "trend": "up",   "dependency": None},
            {"name": "engagement_score",     "type": "float", "description": "Score de engagement 0-1", "range_min": 0.1,  "range_max": 0.95, "nullable": True,  "trend": None,   "dependency": None},
            {"name": "ticket_text", "type": "str",   "description": "Texto libre de tickets o quejas del cliente",  "range_min": None, "range_max": None, "nullable": False, "trend": None, "dependency": None},
            {"name": "categoria",   "type": "str",   "description": "Categoría o clasificación del registro",        "range_min": None, "range_max": None, "nullable": False, "trend": None, "dependency": None},
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
_TITLE_TO_TARGET_TOKENS: dict[str, tuple[str, ...]] = {
    "retencion": ("churn", "retention", "renewal", "attrition"),
    "retención": ("churn", "retention", "renewal", "attrition"),
    "churn": ("churn", "retention", "attrition"),
    "abandono": ("churn", "attrition", "abandon"),
    "cancelacion": ("churn", "cancel", "attrition"),
    "cancelación": ("churn", "cancel", "attrition"),
    "fidelizacion": ("churn", "retention", "loyalty"),
    "fidelización": ("churn", "retention", "loyalty"),
    "retraso": ("delay", "late", "lateness", "delivery_time"),
    "demora": ("delay", "late", "lateness", "delivery_time"),
    "fraude": ("fraud", "fraudulent", "anomaly"),
    "fraud": ("fraud", "fraudulent", "anomaly"),
    "default": ("default", "delinquency", "credit_loss"),
    "morosidad": ("default", "delinquency", "overdue"),
    "ventas": ("sales", "revenue", "demand", "units_sold"),
    "demanda": ("demand", "sales", "units_sold", "forecast"),
    "ingresos": ("revenue", "sales", "income"),
    "rotacion": ("turnover", "attrition", "churn"),
    "rotación": ("turnover", "attrition", "churn"),
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

# Tokens de nombre del target que identifican targets de retención/churn;
# se usan para evitar inferir leakage por naming cuando el propio objetivo
# pertenece a esa misma familia (las retention_* features podrían ser lags
# válidos de auditoría temporal en ese caso).
_RETENTION_TARGET_NAME_TOKENS: tuple[str, ...] = (
    "churn", "retention", "renewal", "attrition", "loyalty",
)


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
        f"target_semantic_mismatch: el título sugiere [{matched_str}] "
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

    target_is_retention = (
        any(tok in target_name for tok in _RETENTION_TARGET_NAME_TOKENS)
        or target_role == "forecasting_target" and "retention" in target_name
    )
    if target_is_retention:
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


# ─────────────────────────────────────────────────────────
# NODO 1 — SCHEMA DESIGNER (Pro, thinking activo, output pequeño)
# ─────────────────────────────────────────────────────────

def schema_designer(state: ADAMState, config: RunnableConfig) -> dict:  # noqa: ARG001
    """NODO 1 del pipeline de dataset. Diseña schema y constraints.
    Usa gemini-3.1-pro-preview con thinking_level="medium" para máxima calidad.
    Dos candidatos con .with_fallbacks() para resiliencia ante 503.
    Responsabilidad ÚNICA: diseñar. NO genera filas.
    """
    profile = state.get("studentProfile", "business")
    # ml_ds: 200 filas (sin cambio). business: 100 (midpoint de 80-120, usado para
    # calcular rangos de revenue en el prompt; el LLM elige n_rows en 80-120).
    max_rows = 200 if profile == "ml_ds" else 100

    # Extraer familias ML requeridas para el Módulo 3 a partir del input del usuario.
    # _detect_algorithm_families resuelve por catálogo (Issue #233) con fallback legacy.
    algoritmos_raw = state.get("algoritmos", [])
    familias_detectadas = _detect_algorithm_families(algoritmos_raw) if algoritmos_raw else []
    ml_required_families = (
        ", ".join(familias_detectadas) if familias_detectadas else "clasificacion"
    )

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
    prompt = SCHEMA_DESIGNER_PROMPT.format(**context)

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
        model="gemini-3.1-pro-preview",
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
            schema_result = _augment_schema_with_contract(schema_result, contract)
            missing, leakage = _validate_schema_against_contract(schema_result, contract)
            # Issue #228 — preserva semillas de data_gap_warnings emitidas por
            # case_architect (ej: target_semantic_mismatch). LangGraph reemplaza
            # el canal en cada return, así que merge explícito.
            warnings_payload: list[str] = list(state.get("data_gap_warnings") or [])
            if missing:
                warnings_payload.extend(missing)
            if leakage:
                warnings_payload.extend(leakage)
            return {
                "dataset_schema": schema_result,
                "data_gap_warnings": warnings_payload,
            }
        except (ValidationError, Exception) as e:
            logger.error("[schema_designer] %s ERROR: %s", model_label, e, exc_info=True)

    print("[schema_designer] todos los intentos fallaron — usando fallback schema")
    fallback_schema = _build_fallback_schema(state, max_rows, profile)
    # Issue #225 — incluso en fallback respetamos el contrato del architect.
    contract = state.get("dataset_schema_required")
    fallback_schema = _augment_schema_with_contract(fallback_schema, contract)
    missing, leakage = _validate_schema_against_contract(fallback_schema, contract)
    # Issue #228 — preserva warnings sembrados por case_architect.
    warnings_payload = list(state.get("data_gap_warnings") or [])
    if missing:
        warnings_payload.extend(missing)
    if leakage:
        warnings_payload.extend(leakage)
    return {
        "dataset_schema": fallback_schema,
        "data_gap_warnings": warnings_payload,
    }


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


# ─────────────────────────────────────────────────────────
# HELPER — _generate_dataset_from_schema (Python puro, 0 tokens LLM)
# ─────────────────────────────────────────────────────────

def _generate_dataset_from_schema(schema: dict) -> list:
    """
    Genera filas de datos a partir del schema producido por schema_designer.
    Vectorizado con numpy. Cero tokens LLM. Determinista con seed derivado del schema.
    Soporta trend (up/down/stable) y dependency (linear/inverse) por columna.
    """
    import numpy as np

    columns = schema.get("columns", [])
    n_rows = schema.get("n_rows", 100)
    granularity = schema.get("time_granularity", "monthly")
    constraints = schema.get("constraints", {})

    # Seed determinista: mismo schema → mismo dataset siempre.
    # RNG local (no global) para evitar race conditions con usuarios concurrentes.
    case_seed = hash(json.dumps(schema, sort_keys=True)) % (2**31)
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
        else:
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
    for row in rows:
        rev  = float(row.get(revenue_col, 0) or 0)
        cost = float(row.get(cost_col_name, 0) or 0) if cost_col_name else 0
        if "ebitda" in row:
            row["ebitda"] = round(rev - cost, 2)
        if "margin_pct" in row:
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
    numeric_non_revenue = [
        c for c in columns
        if c["type"] in ("float", "int")
        and c["name"] != revenue_col
        and not c["name"].startswith("period")
        and not c["name"].startswith("retention_")
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
                    outlier_val = min(outlier_val, float(col_range_max) * 2)
                rows[idx][target_col] = round(outlier_val, 2)

    print(f"[_generate_dataset_from_schema] {len(rows)} filas generadas, {len(columns)} columnas")
    return rows


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

        rows = _generate_dataset_from_schema(schema)
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
# v8 — NODO: TEACHING NOTE PART 1 (§1 Sinopsis, §2 Guía, §3 Pauta)
# ─────────────────────────────────────────────────────────
def teaching_note_part1(state: ADAMState, config: RunnableConfig) -> dict:
    """Genera §1 Sinopsis y Público Objetivo, §2 Objetivos Bloom, §3 Plan de Clase.
    Corre en fan-out paralelo de synthesis_flow (no necesita m5_content).
    """
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
        response = llm.invoke(TEACHING_NOTE_PART1_PROMPT.format(**context))
        part1 = sanitize_markdown(_extract_text(response))
        print(f"[teaching_note_part1] {len(part1)} chars")
        return {"doc3_teaching_note_part1": part1, "current_agent": "teaching_note_part1"}
    except Exception as e:
        logger.error("[teaching_note_part1] ERROR: %s", e, exc_info=True)
        return {"doc3_teaching_note_part1": "⚠️ Error generando Teaching Note (parte 1)."}


# ─────────────────────────────────────────────────────────
# v8 — NODO: TEACHING NOTE PART 2 (§4 Rúbrica, §5 Benchmarks, §6 Notas)
# ─────────────────────────────────────────────────────────
def teaching_note_part2(state: ADAMState, config: RunnableConfig) -> dict:
    """Genera §4 Análisis del Caso (Tensiones Ocultas, FCE, Benchmarks del Sector).
    Corre secuencialmente después de m5_questions_generator (post sync1).
    """
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
        response = llm.invoke(TEACHING_NOTE_PART2_PROMPT.format(**context))
        part2 = sanitize_markdown(_extract_text(response))
        print(f"[teaching_note_part2] {len(part2)} chars, m5_qs={'yes' if m5_questions else 'no'}")
        return {"doc3_teaching_note_part2": part2, "current_agent": "teaching_note_part2"}
    except Exception as e:
        logger.error("[teaching_note_part2] ERROR: %s", e, exc_info=True)
        return {"doc3_teaching_note_part2": "⚠️ Error generando Teaching Note (parte 2).", "current_agent": "teaching_note_part2"}



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
        })

        resultado: GeneradorPreguntasOutput = llm.with_structured_output(
            GeneradorPreguntasOutput
        ).invoke(M4_QUESTIONS_GENERATOR_PROMPT.format(**context))

        preguntas = [p.model_dump() for p in resultado.preguntas]
        print(f"[m4_questions_generator] {len(preguntas)} preguntas")
        return {"m4_questions": preguntas, "current_agent": "m4_questions_generator"}
    except Exception as e:
        logger.error("[m4_questions_generator] ERROR: %s", e, exc_info=True)
        return {"m4_questions": [], "current_agent": "m4_questions_generator"}


# ─────────────────────────────────────────────────────────
# v7 — NODO: M5 QUESTIONS GENERATOR (Módulo Recomendación)
# ─────────────────────────────────────────────────────────
def m5_questions_generator(state: ADAMState, config: RunnableConfig) -> dict:
    """Genera 3 preguntas de Junta Directiva del Módulo 5.

    v9: usa GeneradorPreguntasM5Output (PreguntaM5) — solucion_esperada sin límite
    de 60 palabras, 4 párrafos (250-300 palabras), para calificación comparativa por IA.
    doc1_preguntas_complejas se pasa como historial de referencia (no como fuente):
    el LLM lo usa para no repetir temas ya evaluados en M1.
    Corre DESPUÉS de synthesis_phase1_sync — necesita m5_content del state.
    """
    try:
        cfg = Configuration.from_runnable_config(config)
        # temperature=0.5: balance entre creatividad en enunciados y consistencia estructural
        # Usa architect_model (Pro) + 16384 tokens — M5 es evaluación final integrativa.
        # Con thinking_level="medium" el budget de 8192 se truncaba silenciosamente.
        llm = _get_m5_llm(cfg.architect_model, temperature=0.5)

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
        # Fallback: si no hay preguntas con bloom_level, usar las últimas 3 (P4/P5/P6
        # son siempre analysis/evaluation/synthesis por diseño del CASE_QUESTIONS_PROMPT)
        if not complex_q and all_q:
            complex_q = all_q[-3:]

        context = _build_base_context(state)
        context.update({
            "m5_content": state.get("m5_content", ""),
            "doc1_preguntas_complejas": json.dumps(complex_q[:3], ensure_ascii=False),
            # main_risk_from_m3_m4 e implementation_timeframe vienen de _build_base_context
        })

        resultado: GeneradorPreguntasM5Output = llm.with_structured_output(
            GeneradorPreguntasM5Output
        ).invoke(M5_QUESTIONS_GENERATOR_PROMPT.format(**context))

        preguntas = [p.model_dump() for p in resultado.preguntas]
        print(f"[m5_questions_generator] {len(preguntas)} preguntas Junta Directiva")
        return {"m5_questions": preguntas, "current_agent": "m5_questions_generator"}
    except Exception as e:
        err_msg = str(e)
        # Re-raise errores transitorios → LangGraph RetryPolicy dispara con backoff
        # (max 3 intentos: 1s → 2s → 4s con jitter — ver standard_retry línea ~2805).
        # Sin este re-raise, el RetryPolicy nunca se activa porque el nodo "retorna" en lugar de "lanzar".
        if any(code in err_msg for code in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED")):
            logger.warning("[m5_questions_generator] ERROR TRANSITORIO (reintentando): %s", err_msg)
            raise
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
        })

        profile = state.get("studentProfile", "business")
        if profile == "ml_ds":
            prompt = M3_EXPERIMENT_PROMPT
            tag = "m3_experiment_engineer"
            m3_mode = "experiment"
            # ml_ds: el m3_content alimenta directamente el prompt del notebook
            # generator. Calidad de razonamiento aquí ⇒ menos ambigüedad en la
            # sección 3 (hipótesis, criterio de descarte, sesgos). Por eso Pro-
            # medium con cadena de fallback (Pro-low → Flash-low).
            # Modelos vía Configuration para respetar overrides por env var
            # (ARCHITECT_MODEL / WRITER_MODEL) — útil para rollouts y tests.
            _m3_common = dict(
                model=cfg.architect_model,
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
            # business: contenido narrativo de auditoría sin notebook downstream;
            # Flash-medium con fallback a 2.5-flash (ya en _get_writer_llm) basta.
            llm = _get_writer_llm(cfg.writer_model, temperature=0.6, thinking_level="medium")

        response = llm.invoke(prompt.format(**context))
        m3 = sanitize_markdown(_extract_text(response))
        print(f"[{tag}] {len(m3)} chars | m3_mode={m3_mode}")
        return {"m3_content": m3, "m3_mode": m3_mode, "current_agent": "m3_content_generator"}
    except Exception as e:
        logger.error("[m3_content_generator] ERROR: %s", e, exc_info=True)
        return {"m3_content": "[M3_NOT_EXECUTED]", "m3_mode": "audit"}


# Issue 4.3 — M3 QUESTIONS GENERATOR
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

        profile = state.get("studentProfile", "business")
        if profile == "ml_ds":
            prompt = M3_EXPERIMENT_QUESTIONS_PROMPT
            tag = "m3_experiment_questions"
        else:
            prompt = M3_AUDIT_QUESTIONS_PROMPT
            tag = "m3_audit_questions"

        resultado: GeneradorPreguntasOutput = llm.with_structured_output(
            GeneradorPreguntasOutput
        ).invoke(prompt.format(**context))

        preguntas = [p.model_dump() for p in resultado.preguntas]
        print(f"[{tag}] {len(preguntas)} preguntas")
        return {"m3_questions": preguntas, "current_agent": "m3_questions_generator"}
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
        "classification_report",
        "silhouette_score(",
        "davies_bouldin_score(",
        "from sklearn.cluster import",
        "from sklearn.model_selection import train_test_split",
    ),
    "regresion": (
        "roc_auc_score",
        "confusion_matrix",
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
        "# === SECTION:dummy_baseline ===",
        "# === SECTION:pipeline_lr ===",
        "# === SECTION:pipeline_rf ===",
        "# === SECTION:cv_scores ===",
        "# === SECTION:roc_curves ===",
        "# === SECTION:pr_curves ===",
        "# === SECTION:comparison_table ===",
        # Issue #238 — celda de threshold tuning con matriz de costos del negocio.
        "# === SECTION:cost_matrix ===",
    ),
}

_FAMILY_REQUIRED_APIS: dict[str, tuple[str, ...]] = {
    "clasificacion": (
        "DummyClassifier",
        "ColumnTransformer",
        "StratifiedKFold",
        "cross_val_score",
        "roc_curve(",
        "precision_recall_curve(",
        "train_test_split(",
        # Issue #238 — la celda cost_matrix usa confusion_matrix() para barrer
        # thresholds y predict_proba() para obtener scores continuos. Ambos
        # tienen que aparecer en código ejecutable, no solo en markdown.
        "confusion_matrix(",
        "predict_proba(",
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


def _validate_notebook_family_consistency(family: str, code: str) -> list[str]:
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
    if prohibited:
        violations.extend(p for p in prohibited if p in scannable)

    sentinels = _FAMILY_REQUIRED_SENTINELS.get(family, ())
    violations.extend(f"FALTANTE: {token}" for token in sentinels if token not in code)

    apis = _FAMILY_REQUIRED_APIS.get(family, ())
    violations.extend(f"FALTANTE: {token}" for token in apis if token not in scannable)

    return violations


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
        cfg = Configuration.from_runnable_config(config)

        # Notebook generator es el ÚNICO nodo del sistema que emite código Python
        # ejecutable en Colab. Cualquier alucinación o truncamiento se traduce en
        # un error visible al estudiante. Por eso usa cadena Pro resiliente:
        #   1) Pro thinking_level="medium" — primario. Subir a "high" arriesga
        #      truncar el Jupytext (muchas llaves, varios bloques try/except por
        #      familia algorítmica) por consumo de reasoning interno.
        #   2) Pro thinking_level="low"    — fallback transitorio sin degradar de
        #      modelo (cubre rate-limit, 5xx puntual, parser error de una vuelta).
        #   3) Flash thinking_level="medium" — red de seguridad final ante
        #      incidente global de Pro. Mantenemos "medium" en Flash porque el
        #      output es código y la consistencia importa más que la latencia.
        # Modelos vía Configuration para respetar overrides por env var
        # (ARCHITECT_MODEL / WRITER_MODEL) — el path notebook es el más sensible,
        # imprescindible que los rollouts/canaries lleguen también aquí.
        # max_output_tokens=24576 da margen para reasoning (~3-8k) + Jupytext de
        # 3 celdas × N familias (~6-12k chars) sin truncamiento silencioso.
        _nb_common = dict(
            model=cfg.architect_model,
            temperature=0.3,
            max_retries=2,
            max_output_tokens=24576,
            api_key=os.getenv("GEMINI_API_KEY"),
            rate_limiter=_rate_limiter,
        )
        nb_primary = ChatGoogleGenerativeAI(thinking_level="medium", **_nb_common)
        nb_pro_low = ChatGoogleGenerativeAI(thinking_level="low", **_nb_common)
        nb_flash = ChatGoogleGenerativeAI(
            model=cfg.writer_model,
            temperature=0.3,
            thinking_level="medium",
            max_retries=2,
            max_output_tokens=24576,
            api_key=os.getenv("GEMINI_API_KEY"),
            rate_limiter=_rate_limiter,
        )
        llm = nb_primary.with_fallbacks([nb_pro_low, nb_flash])

        context = _build_base_context(state)
        case_title = state.get("titulo", "Caso de Estudio") or "Caso de Estudio"
        # Use .replace() — NOT .format() — because the template contains Python code
        # with curly braces (dict comprehensions, f-strings) that .format() misparses.
        base_template = M3_NOTEBOOK_BASE_TEMPLATE.replace("{case_title}", case_title)

        # ── Family dispatch (Issue #233) ─────────────────────────────────────
        # The teacher form (Issue #230) guarantees algoritmos share a family
        # in contrast mode. We resolve the first algorithm to its family,
        # falling back to the legacy substring map for historical jobs.
        # Issue #237 — single resolution chain via ``_resolve_primary_family``
        # so EDA chart dispatch shares the exact same precedence.
        algoritmos_raw: list[str] = state.get("algoritmos", [])
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

        print(f"[m3_notebook_generator] Familia despachada: {family!r} (algoritmos={algoritmos_raw!r})")

        # Single-entry familias_meta: the prompt expects a list with metadata
        # for the active family; we collapse to one entry because per-family
        # dispatch makes multi-family notebooks impossible by construction.
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

        algo_section = ""
        try:
            # Issue #225 — pasa contrato + brechas al prompt para CONTRACT-FIRST
            # target resolution. Si no hay contrato/brechas, los bloques quedan
            # con texto neutro y el LLM aplica la lógica alias-first heredada.
            contract_block = _format_dataset_contract_block(
                state.get("dataset_schema_required")
            )
            gap_warnings = list(state.get("data_gap_warnings") or [])
            if legacy_warning:
                gap_warnings.append(legacy_warning)
            gaps_block = (
                "\n".join(f"- {w}" for w in gap_warnings)
                if gap_warnings
                else "(sin brechas detectadas — schema cubre el contrato)"
            )

            prompt_template = PROMPT_BY_FAMILY[family]

            def _render(template: str) -> str:
                return template.format(
                    m3_content=(state.get("m3_content", "") or "")[:2000],
                    algoritmos=json.dumps(algoritmos_raw, ensure_ascii=False),
                    familias_meta=json.dumps(familias_meta, ensure_ascii=False),
                    case_title=case_title,
                    output_language=context.get("output_language", "es"),
                    dataset_contract_block=contract_block,
                    data_gap_warnings_block=gaps_block,
                )

            prompt = _render(prompt_template)
            response = llm.invoke(prompt)
            algo_section = sanitize_markdown(_extract_text(response))
            print(f"[m3_notebook_generator] Sección módulos LLM (1ª pasada): {len(algo_section)} chars")

            # Issue #233 + #236 — post-LLM family-consistency check + reprompt-once.
            # Violations come pre-tagged: bare strings = prohibited cross-family
            # tokens (don't echo back to avoid amplification); ``"FALTANTE: ..."``
            # = required Harvard-quality artefacts missing (DO echo so the LLM
            # has a precise fixing target).
            violations = _validate_notebook_family_consistency(family, algo_section)
            if violations:
                missing = [v.removeprefix("FALTANTE: ") for v in violations if v.startswith("FALTANTE: ")]
                prohibited_hits = [v for v in violations if not v.startswith("FALTANTE: ")]
                print(
                    f"[m3_notebook_generator] Violación de familia detectada (familia={family}, "
                    f"prohibited={prohibited_hits}, faltantes={missing}). Reprompt explícito (1/1)."
                )
                corrective_blocks: list[str] = ["\n\n# CORRECCIÓN OBLIGATORIA"]
                if prohibited_hits:
                    # Belt-and-suspenders against reprompt amplification: we do
                    # NOT echo the offending prohibited tokens (the LLM might
                    # politely repeat them and re-trip the validator). Refer
                    # the model to the prompt's own ``Lista NEGRA`` section.
                    corrective_blocks.append(
                        f"# Tu salida anterior emitió código ejecutable de OTRAS familias prohibidas para '{family}'.\n"
                        "# Releé la sección 'Lista NEGRA' del prompt y reescribe la salida COMPLETA\n"
                        "# usando EXCLUSIVAMENTE la API estable declarada para esta familia.\n"
                        "# Los nombres prohibidos pueden aparecer en celdas markdown como advertencia pedagógica,\n"
                        "# pero NUNCA como import, call site, ni dentro de un string ejecutable."
                    )
                if missing:
                    # For FALTANTE we DO echo: the LLM needs to know exactly
                    # what to add. Sentinels are emitted verbatim.
                    bullet_list = "\n".join(f"#   - {tok}" for tok in missing)
                    corrective_blocks.append(
                        "# Tu salida anterior NO incluyó artefactos pedagógicos OBLIGATORIOS\n"
                        f"# para la familia '{family}'. Reescribe la salida COMPLETA asegurándote\n"
                        "# de que aparezcan literalmente (sentinelas como comentario Python al inicio\n"
                        "# de la celda correspondiente; identificadores como import o call real):\n"
                        f"{bullet_list}"
                    )
                reprompt = prompt + "\n".join(corrective_blocks)
                response2 = llm.invoke(reprompt)
                algo_section = sanitize_markdown(_extract_text(response2))
                violations2 = _validate_notebook_family_consistency(family, algo_section)
                if violations2:
                    logger.error(
                        "[m3_notebook_generator] Reprompt falló — familia=%s violations=%s",
                        family, violations2,
                    )
                    raise RuntimeError(
                        f"M3 notebook generator no satisfizo la familia "
                        f"'{family}' incluso tras un reprompt: {violations2}. "
                        f"Job marcado como fallido para evitar shipping de notebook roto."
                    )
                print(
                    f"[m3_notebook_generator] Reprompt OK — familia={family}, "
                    f"chars={len(algo_section)}"
                )
        except RuntimeError:
            # Re-raise to fail the job — the validator policy demands it.
            raise
        except Exception as e:
            logger.error("[m3_notebook_generator] Error en LLM módulos: %s", e, exc_info=True)
            algo_section = (
                "# %% [markdown]\n"
                "# ## Módulos Experimentales\n"
                "# ⚠️ Hubo un error generando los bloques de código.\n"
                "# Revisa el contenido del Módulo 3 para el diseño de los algoritmos."
            )

        final_notebook = base_template + "\n\n" + algo_section
        print(f"[m3_notebook_generator] Notebook ensamblado: {len(final_notebook)} chars")
        return {"m3_notebook_code": final_notebook, "current_agent": "m3_notebook_generator"}
    except RuntimeError:
        # Issue #233 — family-consistency violation after reprompt. Re-raise so
        # the worker can mark the job as failed; never ship a runtime-broken notebook.
        raise
    except Exception as e:
        logger.error("[m3_notebook_generator] ERROR: %s", e, exc_info=True)
        return {"m3_notebook_code": "# ⚠️ Error generando notebook M3. Revisa el Módulo 3."}


# Issue 4.4 — M4 CONTENT GENERATOR
def m4_content_generator(state: ADAMState, config: RunnableConfig) -> dict:
    """Genera el análisis de impacto económico y operativo (Módulo 4).
    Corre en m4_flow tanto para harvard_only como harvard_with_eda.
    Si no hay M2/M3, el prompt usa fallback basado en Exhibits del M1.
    """
    try:
        cfg = Configuration.from_runnable_config(config)
        llm = _get_writer_llm(cfg.writer_model, temperature=0.5, thinking_level="medium")

        context = _build_base_context(state)
        context.update({
            # Fix M-03: 8000 chars — M4 proyecta impacto por opción A/B/C.
            # Con 6000 chars las opciones al final de la narrativa quedaban fuera.
            "contexto_m1": state.get("doc1_narrativa", "")[:8000],
            "contexto_m2": state.get("doc2_eda", "") or "DATASET_UNAVAILABLE",
            "contexto_m3": state.get("m3_content", "") or "[M3_NOT_EXECUTED]",
            "anexo_financiero": state.get("doc1_anexo_financiero", ""),
        })

        response = llm.invoke(M4_CONTENT_GENERATOR_PROMPT.format(**context))
        m4 = sanitize_markdown(_extract_text(response))
        print(f"[m4_content_generator] {len(m4)} chars")
        return {"m4_content": m4, "current_agent": "m4_content_generator"}
    except Exception as e:
        logger.error("[m4_content_generator] ERROR: %s", e, exc_info=True)
        return {"m4_content": "[M4_GENERATION_ERROR]", "current_agent": "m4_content_generator"}


# Issue 4.5 — M4 CHART GENERATOR (ambos perfiles)
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
        })

        result: EDAChartGeneratorOutput = llm.with_structured_output(
            EDAChartGeneratorOutput
        ).invoke(M4_CHART_GENERATOR_PROMPT.format(**context))
        charts = [c.model_dump() for c in result.charts]
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
    luego teaching_note_part2 con m5_questions disponibles.
    """
    print("[synthesis_phase1_sync] Barrier 1 OK — m5_content disponible")
    return {}


def synthesis_phase2_sync(state: ADAMState) -> dict:
    """Fan-in 2: teaching_note_part2 + m5_questions listos.
    Concatena las 2 partes de la Teaching Note en doc3_teaching_note.
    """
    part1 = state.get("doc3_teaching_note_part1", "")
    part2 = state.get("doc3_teaching_note_part2", "")
    full_note = f"{part1}\n\n{part2}".strip()
    print(f"[synthesis_phase2_sync] Teaching Note completa: {len(full_note)} chars")
    return {"doc3_teaching_note": full_note}


# ─────────────────────────────────────────────────────────
# v9 — M5 CONTENT GENERATOR: Informe de Resolución (Junta Directiva)
# Genera el reto final VISIBLE PARA EL ESTUDIANTE con 3 secciones:
#   Sección 1: Insight Destacado del Caso (sin spoiler — "El Dilema Directivo")
#   Sección 2: Introducción al reto de Junta Directiva + regla de 4 párrafos
#   Sección 3: Cierre del Sistema ADAM
# is_docente_only = False: este artefacto es student-facing.
# ─────────────────────────────────────────────────────────
def m5_content_generator(state: ADAMState, config: RunnableConfig) -> dict:
    """Genera el Informe de Resolución del Módulo 5 (student-facing).

    Redeseñado en v9: el artefacto es visible para el estudiante como reto de Junta
    Directiva. Contiene Insight Destacado (sin spoiler de decisión), introducción al
    reto y cierre del sistema. Las solucion_esperada se generan en m5_questions_generator
    y son filtradas por frontend_output_adapter antes de llegar al estudiante.
    """
    try:
        cfg = Configuration.from_runnable_config(config)
        llm = _get_writer_llm(cfg.writer_model, temperature=0.6, thinking_level="medium")

        context = _build_base_context(state)
        context.update({
            # 8000 chars incluye opciones A/B/C al final de la narrativa
            "contexto_m1": state.get("doc1_narrativa", "")[:8000],
            "contexto_m2": state.get("doc2_eda", "") or "DATASET_UNAVAILABLE",
            "contexto_m3": state.get("m3_content", "") or "[M3_NOT_EXECUTED]",
            "contexto_m4": state.get("m4_content", "") or "",
        })

        response = llm.invoke(M5_CONTENT_GENERATOR_PROMPT.format(**context))
        m5 = sanitize_markdown(_extract_text(response))
        print(f"[m5_content_generator] {len(m5)} chars")
        return {"m5_content": m5, "current_agent": "m5_content_generator"}
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
# ml_ds:    m3_content (Experiment Engineer) → [m3_questions ∥ m3_notebook] → m3_sync → END
# m3_notebook_generator es noop para business.
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
m3_builder.add_node("m3_sync", m3_sync)

m3_builder.add_edge(START, "m3_content_generator")
m3_builder.add_edge("m3_content_generator", "m3_questions_generator")
m3_builder.add_edge("m3_content_generator", "m3_notebook_generator")
m3_builder.add_edge("m3_questions_generator", "m3_sync")
m3_builder.add_edge("m3_notebook_generator", "m3_sync")
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
# Ventaja: teaching_note_part2 recibe m5_questions ya escritos en state.
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

# Secuencial post-sync1: m5_questions disponibles para teaching_note_part2.
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

