"""Pydantic output schemas used by the active case-generation graph nodes.

These models describe the structured payloads returned by the authoring agents
that feed the teacher preview and downstream synthesis steps.
"""

import math
import re
import unicodedata
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from case_generator.impact_lens import DEFAULT_IMPACT_LENS, normalize_impact_lens


# USD-only product (Issue #370): el producto opera exclusivamente en dólares. Este sigue siendo
# el único allowlist (single source) — ahora con un solo código. `_normalize_currency` COERCE
# cualquier otro valor a "USD" en vez de rechazarlo (ver allí el porqué del coerce-no-reject).
_SUPPORTED_COST_CURRENCIES = frozenset({"USD"})
_MAX_BUSINESS_COST = 1_000_000_000.0
_MAX_BUSINESS_COST_RATIO = 1_000.0

# Issue F1 — prevalencia del evento objetivo anunciada en Exhibit 2. Un evento de
# clasificación debe ser una minoría aprendible: piso 1% (≥10 positivos a n=1000), techo 50%
# (un evento "raro" no debería ser mayoría; > 0.5 sería el complemento).
_MIN_TARGET_EVENT_RATE = 0.01
_MAX_TARGET_EVENT_RATE = 0.50


# ═══════════════════════════════════════════════════════
# ISSUE #225 — Dataset Schema Required Contract
# Emitido por case_architect, consumido por schema_designer + data_validator
# + m3_notebook_generator + EDA prompts. Garantiza que el dilema declarado en
# M1 esté soportado por columnas reales del dataset y que las features con
# riesgo de leakage temporal queden señaladas explícitamente.
# Ver: https://github.com/4Tech-Labs/ADAM-EDU/issues/225
# ═══════════════════════════════════════════════════════


class DatasetTargetSpec(BaseModel):
    """Variable objetivo declarada por case_architect para el dilema del caso.

    name: snake_case en inglés (ej: 'churn_flag', 'delivery_delay_minutes').
    role: tipo de problema ML que el dilema plantea.
    dtype: tipo de dato esperado en el dataset.
    description: qué representa la columna en negocio (1 línea).
    """

    name: str = Field(description="Nombre snake_case en inglés de la columna objetivo")
    role: Literal[
        "classification_target",
        "regression_target",
        "clustering_target",
        "anomaly_target",
        "ranking_target",
        "forecasting_target",
    ] = Field(description="Rol pedagógico/ML de la columna objetivo")
    # Issue #225 follow-up: "date" añadido para alinear con ColumnDefinition.type
    # (forecasting con índice temporal, targets de horizonte fechado).
    dtype: Literal["int", "float", "str", "date"] = Field(
        description="Tipo de dato Python esperado (alineado con ColumnDefinition.type)"
    )
    description: str = Field(description="Qué representa esta columna en negocio")


class DatasetFeatureSpec(BaseModel):
    """Feature declarada por case_architect como necesaria para resolver el dilema.

    temporal_offset_months: 0 = mismo período que el target, <0 = pasado (válida),
    >0 = futuro respecto al target → LEAKAGE por construcción.
    is_leakage_risk: marca explícita por nombre semántico (ej: 'retention_m12'
    cuando se predice churn del mes 0 es leakage aunque el offset no se conozca).
    """

    name: str = Field(description="Nombre snake_case en inglés de la columna feature")
    role: Literal["feature", "weak_feature", "control"] = Field(
        default="feature", description="Rol pedagógico de la feature"
    )
    # Issue #225 follow-up: "date" añadido para features temporales reales
    # (índice de tiempo en split temporal, lag features fechados).
    dtype: Literal["int", "float", "str", "date"] = Field(
        description="Tipo de dato Python esperado (alineado con ColumnDefinition.type)"
    )
    description: str = Field(description="Qué representa la feature y por qué importa al dilema")
    temporal_offset_months: Optional[int] = Field(
        default=None,
        description=(
            "Offset temporal vs período del target: 0=mismo período, <0=pasado (válida), "
            ">0=futuro (LEAKAGE)."
        ),
    )
    is_leakage_risk: bool = Field(
        default=False,
        description=(
            "Marca explícita: True si la feature es proxy del target o se mide después "
            "de que se conoce el target en producción."
        ),
    )
    # Issue #506 — prior de dirección económica OPCIONAL. Cuando la teoría del dominio fija el
    # SIGNO causal de la feature sobre el evento objetivo (ej: valoración contingente — a mayor
    # tarifa propuesta MENOR aceptación → "negative", ley de demanda), el generador determinista
    # del dataset acopla el target a la feature con ese signo, de modo que el coeficiente del
    # modelo NO quede económicamente invertido. Consumido SOLO en ml_ds + clasificación por
    # `_enforce_mlds_directional_target` (graph.py); inerte en otros perfiles/familias. `None` =
    # dirección desconocida/ambigua → comportamiento previo (signo no controlado).
    expected_direction: Optional[str] = Field(
        default=None,
        description=(
            "Dirección causal esperada de la feature sobre el evento objetivo binario: "
            "'positive' (a mayor valor, mayor probabilidad del evento), 'negative' (a mayor "
            "valor, menor probabilidad), o null si es ambigua/desconocida. Declárala SOLO cuando "
            "la teoría del dominio fije el signo (ej: ley de demanda → precio/tarifa = 'negative'; "
            "distancia al recurso ambiental = 'negative'; ingreso/calidad percibida = 'positive')."
        ),
    )
    # Issue #531 — rango típico realista de la feature en SUS unidades naturales (ej: un
    # `willingness_to_pay_usd` ∈ [10, 800], un `visit_recency_days` ∈ [1, 365]). OPCIONAL y
    # ADITIVO: default None → cero impacto en clasificación/regresión/serie_temporal/business
    # (sus builders no leen estos campos). Consumido SOLO por el builder de segmentación de
    # ml_ds + clustering (`graph._resolve_clustering_segmentation_columns`), que genera columnas
    # de dominio con valores plausibles en vez de los defaults genéricos [0,1]/[0,100] del
    # augmenter. Si el architect no los declara, el builder cae a una heurística por nombre/tipo.
    range_min: Optional[float] = Field(
        default=None,
        description=(
            "Mínimo típico de la feature en sus unidades naturales (solo clustering). "
            "Ej: willingness_to_pay_usd → 10. Déjalo null si no aplica."
        ),
    )
    range_max: Optional[float] = Field(
        default=None,
        description=(
            "Máximo típico de la feature en sus unidades naturales (solo clustering). "
            "Ej: willingness_to_pay_usd → 800. Déjalo null si no aplica."
        ),
    )

    @field_validator("expected_direction", mode="before")
    @classmethod
    def _coerce_expected_direction(cls, v: object) -> Optional[str]:
        # Coerce-never-reject (espejo de _normalize_currency / _coerce_lens): cualquier valor que
        # no sea exactamente 'positive'/'negative' (incl. no-str, vacío, typo, mayúsculas) → None.
        # NUNCA levanta: un Literal estricto abortaría TODO el parse de CaseArchitectOutput por una
        # etiqueta suelta del LLM, degradando el caso a un placeholder de error.
        if not isinstance(v, str):
            return None
        normalized = v.strip().lower()
        return normalized if normalized in {"positive", "negative"} else None

    @model_validator(mode="after")
    def _sanitize_range(self) -> "DatasetFeatureSpec":
        # Coerce-never-reject (espejo de _coerce_expected_direction / EntityDescriptor): un par de
        # rango inválido (no-finito, o min >= max) se NULIFICA a (None, None) en vez de levantar —
        # un ValidationError abortaría el parse de TODO el CaseArchitectOutput y degradaría el caso
        # a un placeholder de error. El builder de clustering cae entonces a su heurística por nombre.
        lo, hi = self.range_min, self.range_max
        valid = (
            isinstance(lo, (int, float))
            and isinstance(hi, (int, float))
            and not isinstance(lo, bool)
            and not isinstance(hi, bool)
            and math.isfinite(lo)
            and math.isfinite(hi)
            and lo < hi
        )
        if not valid:
            self.range_min = None
            self.range_max = None
        return self


class DatasetSchemaRequired(BaseModel):
    """Contrato emitido por case_architect: declara qué dataset necesita el caso.

    Este contrato es la única fuente de verdad para el alineamiento dilema↔dataset:
      * schema_designer lo consume al diseñar columns/constraints.
      * Un validador Python (post-schema_designer) verifica cobertura y aumenta
        el schema con columnas faltantes de forma determinista (cero tokens LLM).
      * data_validator usa target_column.name como variable objetivo canónica
        (en lugar de heurística por palabras clave).
      * m3_notebook_generator pasa target + leakage flags al prompt ALGO para
        evitar fallback silencioso al elegir target/features.
      * EDA prompts incorporan data_gap_warnings emitidos por el validador.

    Para perfil 'business' este campo es opcional. Para 'ml_ds' es obligatorio:
    sin contrato no hay garantía de que las preguntas socráticas y el notebook
    M3 puedan ejecutarse sobre el dataset generado.
    """

    target_column: DatasetTargetSpec = Field(
        description="Variable objetivo única que el dilema obliga a predecir/explicar"
    )
    feature_columns: list[DatasetFeatureSpec] = Field(
        default_factory=list,
        description=(
            "3-8 features que el dilema referencia explícitamente. Marcar "
            "is_leakage_risk=True para columnas que en producción se conocen "
            "después del target (ej: retention_m12 al predecir churn del mes 0)."
        ),
    )
    domain_features_required: list[str] = Field(
        default_factory=list,
        description=(
            "Categorías semánticas de features que deben existir aunque sus nombres "
            "exactos los decida schema_designer (ej: 'delivery_time', 'customer_segment'). "
            "Permite cobertura por significado, no solo por nombre."
        ),
    )
    min_signal_strength: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        description=(
            "Umbral mínimo aceptable de |correlación| entre target y mejor feature "
            "no-leakage. Usado por validador para detectar targets sintéticos sin señal."
        ),
    )
    notes: Optional[str] = Field(
        default=None,
        description="Notas opcionales del architect sobre el diseño del contrato",
    )
    # Issue #238 — matriz de costos del negocio para threshold tuning en M3.
    # Solo aplica cuando family == "clasificacion"; para otras familias debe
    # quedar None. Issue #242 endurece validación estricta de costos/currency.
    business_cost_matrix: Optional["BusinessCostMatrix"] = Field(
        default=None,
        description=(
            "Costos asimétricos del negocio (en USD) para tuning de "
            "threshold en clasificación. fp_cost = costo de un falso positivo "
            "(predecir 1 cuando es 0). fn_cost = costo de un falso negativo "
            "(predecir 0 cuando es 1). Si None, M3 usa fallback fp=1, fn=5."
        ),
    )
    # Issue F1 — prevalencia del evento objetivo (fracción target=1) anunciada en la fila
    # "Tasa de ocurrencia" de Exhibit 2. Solo ml_ds + clasificación binaria. El generador
    # determinista calibra la columna target a esta prevalencia (fuente única M1↔M2); si None,
    # usa el umbral histórico (~0.50). Mantiene Exhibit 2 ↔ dataset ↔ M3 prevalence coherentes.
    #
    # Los límites [_MIN, _MAX] NO se imponen como `ge`/`le` aquí a PROPÓSITO: un valor LLM fuera
    # de rango (p. ej. emitir 8.3 en vez de 0.083) levantaría un ValidationError que abortaría el
    # PARSE de TODO el `CaseArchitectOutput` y degradaría el caso entero a un placeholder de error.
    # En su lugar, `graph._validate_target_event_rate` aplica los límites de forma TOLERANTE
    # (fuera de rango → nulificado + warning, el caso COMPLETA con prevalencia ~0.50). Aquí solo
    # rechazamos NaN/inf (no representables como prevalencia y nunca recuperables).
    target_event_rate: Optional[float] = Field(
        default=None,
        description=(
            "Prevalencia del evento objetivo (fracción de filas con target=1); el rango válido es "
            "[0.01, 0.50]. DEBE coincidir con la 'Tasa de ocurrencia del evento' impresa en "
            "Exhibit 2 (8.3 % → 0.083). Solo ml_ds + clasificación binaria; None en otro caso. "
            "Fuera de rango se nulifica downstream (no falla el caso)."
        ),
    )

    @field_validator("target_event_rate")
    @classmethod
    def _finite_event_rate(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return v
        if not math.isfinite(v):
            raise ValueError("target_event_rate must be a finite number (no inf/nan)")
        return v


class BusinessCostMatrix(BaseModel):
    """Costos asimétricos del negocio para threshold tuning en M3 (Issue #238).

    Solo aplica para problemas de clasificación. Permite que el notebook M3
    construya una curva de costo total vs threshold y elija el óptimo en
    lugar de quedarse con el default 0.5.

        Validación strict-mode:
      * fp_cost > 0 y finito
      * fn_cost > 0 y finito
            * cada costo <= 1e9
            * ratio fp/fn plausible dentro de 1000:1 y 1:1000
            * currency coercida a "USD" (producto USD-only, Issue #370)
    """

    fp_cost: float = Field(
        gt=0,
        le=_MAX_BUSINESS_COST,
        description=(
            "Costo de un falso positivo en la moneda indicada por `currency`. "
            "Ej: en churn, costo de regalar una retención a un cliente que no "
            "se iba a ir. Debe ser > 0 y finito."
        ),
    )
    fn_cost: float = Field(
        gt=0,
        le=_MAX_BUSINESS_COST,
        description=(
            "Costo de un falso negativo en la moneda indicada por `currency`. "
            "Ej: en churn, costo de perder un cliente porque no se le ofreció "
            "retención. Debe ser > 0 y finito."
        ),
    )
    currency: str = Field(
        default="USD",
        description=(
            "Moneda del caso: el producto opera solo en dólares, así que SIEMPRE 'USD'. "
            "Cualquier otro valor se coerce a 'USD' (no se rechaza)."
        ),
    )

    @field_validator("fp_cost", "fn_cost")
    @classmethod
    def _finite_cost(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("cost must be a finite number (no inf/nan)")
        return v

    @field_validator("currency")
    @classmethod
    def _normalize_currency(cls, v: str) -> str:
        # USD-only product (Issue #370): empty / stray ISO code / garbage all COERCE to "USD".
        # We coerce rather than raise so a stray LLM label never propagates a ValidationError up
        # to ``_validate_business_cost_matrix`` (graph.py), which would nullify the WHOLE matrix
        # — dropping fp_cost/fn_cost and erasing the M3 cost asymmetry (fallback fp=1/fn=5).
        normalized = (v or "").strip().upper()
        if normalized not in _SUPPORTED_COST_CURRENCIES:
            return "USD"
        return normalized

    @model_validator(mode="after")
    def _validate_cost_ratio(self) -> "BusinessCostMatrix":
        high = max(self.fp_cost, self.fn_cost)
        low = min(self.fp_cost, self.fn_cost)
        if high / low > _MAX_BUSINESS_COST_RATIO:
            raise ValueError("fp_cost/fn_cost ratio must be within 1000:1")
        return self


# Issue #238 — resuelve la forward reference declarada en DatasetSchemaRequired
# para el campo `business_cost_matrix`. Pydantic v2 no resuelve string refs
# automáticamente cuando la clase referenciada se define después.
DatasetSchemaRequired.model_rebuild()


class ValueModel(BaseModel):
    """The case's value frame (Impact Lens) emitted by the architect (ADR 0003 Fase 2, #437).

    OPTIONAL refinement of the intake-resolved lens (decision D-A hybrid: the architect read the
    full teacher input, so its lens is a more-informed secondary signal than the intake-dropdown
    default). Prompt-side only: NOT student-facing, NOT in case_sanitization. Costs stay USD (DD3);
    this reframes only the VALUE side. Coerce-never-reject: an invalid/absent lens coerces to the
    default so a stray LLM label never nullifies the architect output (mirrors
    ``BusinessCostMatrix._normalize_currency``).
    """

    lens: str = Field(
        default=DEFAULT_IMPACT_LENS,
        description=(
            "Marco de valor del caso, uno de: financial_roi, operational_efficiency, "
            "clinical_outcomes, learning_outcomes, environmental_outcomes. Elige el que mejor "
            "refleje el DOMINIO del caso (salud→clinical_outcomes, educación→learning_outcomes, "
            "manufactura/logística→operational_efficiency, medio ambiente/sostenibilidad/servicios "
            "ecosistémicos→environmental_outcomes, comercial/financiero→financial_roi). Valor "
            "inválido se coerce al default (no se rechaza)."
        ),
    )
    primary_metric_name: str = Field(
        default="",
        description=(
            "La métrica de VALOR primaria del caso en lenguaje gerencial (p.ej. 'ROI', "
            "'readmisiones evitadas', 'retención de estudiantes', 'tasa de defecto'). El lado del "
            "COSTO sigue en USD."
        ),
    )
    kpi_rows: list[str] = Field(
        default_factory=list,
        description=(
            "2-3 etiquetas de KPI de VALOR para el veredicto de M4 (§4.5), acordes a `lens`. "
            "Vacío permitido (M4 cae al catálogo de la lente)."
        ),
    )

    @field_validator("lens")
    @classmethod
    def _coerce_lens(cls, v: str) -> str:
        # Coerce-never-reject (mirror _normalize_currency): unknown/empty lens → default.
        return normalize_impact_lens(v)


# ═══════════════════════════════════════════════════════
# DOCUMENTO 1 — Caso de Negocio (3 agentes)
# ═══════════════════════════════════════════════════════


# Issue #513 (EPIC #511) — entity descriptor for ml_ds + clustering coherence.
_ENTITY_PREFIX_DEFAULT = "cliente"
_ENTITY_PREFIX_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _sanitize_entity_prefix(raw: object) -> str | None:
    """Sanitize an LLM-emitted entity ``snake_prefix`` to a safe column-name stem, or ``None``.

    The prefix becomes a DataFrame/CSV column ``{prefix}_id`` and an index value
    ``{prefix}_00001`` consumed by the student notebook + Plotly, so it must be a plain ASCII
    snake_case identifier. Rules (coerce-never-reject; the caller falls back to the default on
    ``None``): NFKD accent-fold (``niño`` → ``nino``), lowercase, collapse any run of non
    ``[a-z0-9_]`` into ``_``, strip leading digits/underscores and trailing underscores, drop a
    redundant trailing ``_id`` (so a stray ``cliente_id`` does not become ``cliente_id_id``), then
    require ``^[a-z][a-z0-9_]*$``. Returns ``None`` when the input is not a non-empty string or
    cannot be reduced to a valid stem.
    """
    if not isinstance(raw, str):
        return None
    # NFKD → drop combining marks → ASCII (accent-fold), lowercase.
    ascii_only = (
        unicodedata.normalize("NFKD", raw)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
        .strip()
    )
    cleaned = re.sub(r"[^a-z0-9_]+", "_", ascii_only)
    cleaned = re.sub(r"^[_0-9]+", "", cleaned).strip("_")
    if cleaned.endswith("_id"):
        cleaned = cleaned[:-3].strip("_")
    if not _ENTITY_PREFIX_RE.match(cleaned):
        return None
    return cleaned


class EntityDescriptor(BaseModel):
    """Unit-of-analysis entity for an ml_ds + clustering case, emitted by the architect (#513).

    A K-Means case segments ENTITIES (centros, pacientes, zonas, estudiantes, clientes…). The
    architect narrates one entity + a population count; the deterministic data layer renames the
    dataset index to ``{snake_prefix}_00001`` and the column to ``{snake_prefix}_id`` so the CSV the
    student downloads matches the M1 story (Opción A — the data adapts to the narrative). Only
    ``snake_prefix`` drives the data; ``singular``/``plural`` carry the human entity words for the
    column description + the coherence oracle.

    Bulletproof coerce-never-reject: ``case_architect`` degrades the WHOLE M1 to an error
    placeholder if ANY field raises a ``ValidationError`` (graph.py ``except Exception``), so every
    field has a ``mode="before"`` coercer that falls back to a safe default instead of raising, and
    the parent ``CaseArchitectOutput`` drops a non-dict ``entity_descriptor`` to ``None`` (mirrors
    ``BusinessCostMatrix._normalize_currency`` / ``ValueModel._coerce_lens``).
    """

    singular: str = Field(
        default="cliente",
        description="Entidad en singular, español (p.ej. 'centro de distribución', 'paciente', 'zona').",
    )
    plural: str = Field(
        default="clientes",
        description="Entidad en plural, español (p.ej. 'centros de distribución', 'pacientes', 'zonas').",
    )
    snake_prefix: str = Field(
        default=_ENTITY_PREFIX_DEFAULT,
        description=(
            "Prefijo snake_case ASCII de la entidad para el id del dataset (p.ej. 'centro', "
            "'paciente', 'zona'). El dataset usará la columna `{snake_prefix}_id` con valores "
            "`{snake_prefix}_00001`. Una sola raíz, minúsculas, sin acentos ni espacios."
        ),
    )

    @field_validator("singular", mode="before")
    @classmethod
    def _coerce_singular(cls, v: object) -> str:
        return v.strip() if isinstance(v, str) and v.strip() else "cliente"

    @field_validator("plural", mode="before")
    @classmethod
    def _coerce_plural(cls, v: object) -> str:
        return v.strip() if isinstance(v, str) and v.strip() else "clientes"

    @field_validator("snake_prefix", mode="before")
    @classmethod
    def _coerce_prefix(cls, v: object) -> str:
        return _sanitize_entity_prefix(v) or _ENTITY_PREFIX_DEFAULT


class CaseArchitectOutput(BaseModel):
    """Salida del Case Architect — cimientos del caso (Documento 1).

    Genera el perfil de empresa, el dilema, las instrucciones al estudiante,
    el título, y los 3 Exhibits (Financiero, Operativo, Stakeholders).
    Los campos company_profile y dilema_brief son contexto interno
    para case_writer y case_questions.
    """

    titulo: str = Field(
        description="Nombre de la empresa ficticia + problema central (1 línea)"
    )
    industria: str = Field(
        description=(
            "Sustantivo específico del sector. Ej: 'SaaS B2B para PYMES latinoamericanas', "
            "'retail B2B', 'fintech latinoamericana'. NO usar descripciones largas. "
            "dataset_generator lo consume directamente."
        )
    )
    company_profile: str = Field(
        description=(
            "Perfil completo de la empresa ficticia: nombre, industria, "
            "tamaño, protagonista decisor, historia (4-6 hitos), "
            "contexto de mercado (3-5 bullets). 300-500 palabras."
        )
    )
    dilema_brief: str = Field(
        description=(
            "Resumen ejecutivo del dilema: problema central, restricciones "
            "(tiempo, caja, regulación, capacidad, reputación, mercado) "
            "y 3 opciones estratégicas (A, B, C) con beneficio, riesgo "
            "y señal de éxito a 90 días. 400-600 palabras."
        )
    )
    instrucciones_estudiante: str = Field(
        description="Instrucciones para el estudiante — máx 150 palabras"
    )
    pregunta_eje: Optional[str] = Field(
        default=None,
        description=(
            "Pregunta directiva central del caso. Solo aplica para studentProfile='ml_ds' "
            "y familia de clasificación; debe formular una decisión gerencial, no técnica."
        ),
    )
    anexo_financiero: str = Field(
        description=(
            "Exhibit 1 — Tabla Markdown con datos financieros: "
            "Ingresos, Costos, EBITDA, Margen neto, Caja, "
            "Inversión propuesta (≤ 8% de revenue). "
            "Columnas: Métrica | Año N-1 | Año N (Estimado)"
        )
    )
    anexo_operativo: str = Field(
        description=(
            "Exhibit 2 — Tabla Markdown con métricas operativas. "
            "Mínimo 6 filas con dos períodos comparativos."
        )
    )
    anexo_stakeholders: str = Field(
        description=(
            "Exhibit 3 — Tabla Markdown con mapa de stakeholders. "
            "Columnas: Actor | Interés | Incentivo | Riesgo | Postura (A/B/C). "
            "Mínimo 6 actores."
        )
    )
    # Issue #225 — Contrato dataset↔dilema. Optional para no romper perfil
    # 'business' ni casos legados. Para ml_ds, schema_designer + validador
    # garantizan cobertura cuando está presente; cuando es None, el pipeline
    # opera con el comportamiento heurístico previo.
    dataset_schema_required: Optional[DatasetSchemaRequired] = Field(
        default=None,
        description=(
            "Contrato que declara variable objetivo y features que el dilema requiere "
            "del dataset. Obligatorio para perfil 'ml_ds'. Consumido por schema_designer, "
            "data_validator, m3_notebook_generator y prompts EDA."
        ),
    )
    # Issue #437 (ADR 0003 Fase 2) — Impact Lens value frame. Optional; the architect's more-
    # informed refinement of the intake-resolved lens (D-A hybrid). Prompt-side only (NOT canonical
    # / student-facing). Populated only when the lens-aware architect prompt block is active
    # (settings.impact_lens_architect); None otherwise → the intake-resolved lens stands.
    value_model: Optional[ValueModel] = Field(
        default=None,
        description=(
            "Marco de valor del caso (Impact Lens): {lens, primary_metric_name, kpi_rows}. "
            "Reencuadra solo el lado del VALOR; los costos siguen en USD (DD3)."
        ),
    )
    # Issue #513 (EPIC #511) — entity descriptor for ml_ds + clustering. Optional; the architect
    # emits the unit-of-analysis entity (and its population count via the prompt hint) so the
    # deterministic data layer renames the dataset index to {snake_prefix}_00001 / column
    # {snake_prefix}_id, making the CSV match the M1 narrative (Opción A). Prompt-side / internal
    # (NOT canonical / student-facing, NOT in case_sanitization). Populated only when the entity
    # hint is active (mlds_clustering_structure AND mlds_clustering_entity_coherence); None
    # otherwise → the data layer falls back to the #468 user_id behavior (byte-identical).
    entity_descriptor: Optional[EntityDescriptor] = Field(
        default=None,
        description=(
            "Entidad unidad-de-análisis del caso de segmentación (ml_ds + clustering): "
            "{singular, plural, snake_prefix}. El dataset usará la columna `{snake_prefix}_id`."
        ),
    )

    @field_validator("entity_descriptor", mode="before")
    @classmethod
    def _coerce_entity_descriptor(cls, v: object) -> object:
        # Bulletproof: a non-dict emission (bare string / list / scalar) → None instead of a
        # ValidationError that would degrade the WHOLE architect output to an error placeholder
        # (graph.py case_architect `except Exception`). A dict is validated by EntityDescriptor,
        # whose per-field coercers never raise.
        return v if isinstance(v, (dict, EntityDescriptor)) else None




# ═══════════════════════════════════════════════════════
# DOCUMENTO 2 — Reporte EDA (2 agentes)
# ═══════════════════════════════════════════════════════


class EDAChartSpec(BaseModel):
    """Structured Plotly chart specification rendered by the teacher preview.

    Issue #237: añadidos `data_source` y `anchored_question` opcionales para
    distinguir el path Python-determinista (familia clasificación) del path
    LLM-JSON original. Ambos son back-compat (frontend ignora claves extra).
    """
    id: str = Field(description="ID único snake_case (ej: 'revenue_trend_q3')")
    title: str = Field(description="Título orientado al insight")
    subtitle: str = Field(description="Insight clave en una línea")
    description: Optional[str] = Field(default=None, description="Explicación básica de métricas")
    library: Literal["plotly"] = Field(description="Siempre 'plotly'")
    chart_type: str = Field(
        # Issue #237 review: NO incluir `bar` en la descripción visible al
        # LLM. El path LLM-JSON tiene un prompt que prohíbe `bar`; sólo el
        # builder Python-determinista (clasificación ml_ds) lo emite, y
        # ese path no pasa por with_structured_output() así que la
        # descripción no necesita anunciarlo.
        description="scatter|heatmap|violin|box"
    )
    traces: list[dict] = Field(
        default_factory=list,
        description="Array de trace objects Plotly. Cada trace tiene: type, x/y (o z para heatmap), name, y propiedades específicas del tipo."
    )
    layout: dict = Field(
        default_factory=dict,
        description="Plotly layout config: xaxis (title), yaxis (title), showlegend, template ('plotly_white')"
    )
    source: str = Field(default="", description="'Dataset ADAM — {case_id}' — nunca inventar valores")
    notes: str = Field(default="", description="Insight clave + descripción de agregaciones aplicadas si las hay")
    academic_rationale: Optional[str] = Field(
        default=None,
        description="Por qué este tipo de gráfico es el adecuado para este dato específico"
    )
    # Issue #237 — observabilidad/contrato; opcionales para back-compat.
    data_source: Optional[Literal["python_builder", "llm_json"]] = Field(
        default=None,
        description="Origen del payload del chart: 'python_builder' (deterministico, familia clasificación) o 'llm_json' (path LLM original).",
    )
    anchored_question: Optional[str] = Field(
        default=None,
        description="Pregunta socrática anclada al chart (Issue #237). Renderizado UI = follow-up.",
    )



class EDAChartGeneratorOutput(BaseModel):
    """Salida compartida de los nodos de charts — cantidad variable según el nodo/path.

    M2 EDA (`eda_chart_generator`):
      - Path LLM-JSON original (business y otras familias ml_ds): 3 charts.
      - Path Python-determinista (Issue #237, ml_ds + clasificación): 5 charts.
      - El cap final lo aplica el nodo `eda_chart_generator` en `graph.py`.
    M4 financiero (`m4_chart_generator`): 2 charts (Payback + Comparativa A/B/C); el
      Gráfico de Sensibilidad/Tornado se retiró. La variante 3-gráficos se reactiva con el
      kill-switch `M4_CHART_DROP_SENSITIVITY=false`.

    No hay `min_length`/validador de cantidad: cada nodo gobierna su propio conteo por prompt
    (+ backstop determinista en M4), así que el schema acepta cualquier longitud.
    """

    charts: list[EDAChartSpec] = Field(
        description="Charts estructurados para visualización; la cantidad depende del nodo (M2: 3-5, M4: 2)."
    )


class EDAAnnotateOnlyAnnotation(BaseModel):
    """Issue #237 — un par (description, notes) por chart para el annotate-only path."""

    id: str = Field(description="ID del chart al que pertenece la anotación (debe coincidir con un chart del builder)")
    description: str = Field(default="", description="Descripción pedagógica ≤500 chars")
    notes: str = Field(default="", description="Notas pedagógicas ≤300 chars")


class EDAAnnotateOnlyOutput(BaseModel):
    """Issue #237 — salida del LLM en el path Python-determinista de clasificación.

    El LLM SOLO escribe `description` y `notes` por chart. Cualquier otro campo
    devuelto por el modelo se descarta en el merge defensivo del nodo.
    """

    annotations: list[EDAAnnotateOnlyAnnotation] = Field(
        description="Una entrada por chart Python-construido (≤5)"
    )


# ═══════════════════════════════════════════════════════
# DOCUMENTO 3 — Preguntas EDA (1 agente)
# ═══════════════════════════════════════════════════════

class PreguntaMinimalista(BaseModel):
    """Reusable question schema used across narrative, EDA, and module outputs."""
    numero: int = Field(description="Número secuencial de la pregunta (1, 2, 3...)")
    titulo: str = Field(description="Título corto y descriptivo de la pregunta")
    enunciado: str = Field(description="El cuerpo principal de la pregunta dirigido al estudiante")
    solucion_esperada: str = Field(description="Respuesta o análisis esperado, visible solo para el docente")
    # Campos opcionales v8 — presentes según el tipo de pregunta
    bloom_level: Optional[str] = None          # M1, M2, M3, M4, M5
    exhibit_ref: Optional[str] = None          # M1 y M2
    chart_ref: Optional[str] = None            # M2
    m3_section_ref: Optional[str] = None       # M3
    m4_section_ref: Optional[str] = None       # M4
    modules_integrated: Optional[list[str]] = None  # M5

class GeneradorPreguntasOutput(BaseModel):
    """Salida estructurada combinada para los nodos generadores de preguntas."""
    preguntas: list[PreguntaMinimalista] = Field(description="Lista de preguntas generadas")


class GeneradorPreguntasM1Output(BaseModel):
    """Salida del case_questions — exactamente 3 preguntas M1."""
    preguntas: list[PreguntaMinimalista] = Field(
        min_length=3,
        max_length=3,
        description="Exactamente 3 preguntas pedagógicas del Módulo 1",
    )

    @field_validator("preguntas")
    @classmethod
    def _validate_sequential_numbers(
        cls,
        preguntas: list[PreguntaMinimalista],
    ) -> list[PreguntaMinimalista]:
        numeros = [pregunta.numero for pregunta in preguntas]
        if numeros != [1, 2, 3]:
            raise ValueError(
                "Las preguntas M1 deben estar numeradas exactamente como 1, 2, 3."
            )
        return preguntas


# ═══════════════════════════════════════════════════════
# MÓDULO 5 — Memorándum final (schema aislado de PreguntaMinimalista)
# Diferencia clave: solucion_esperada sin límite de 60 palabras — es el
# memorándum modelo que el docente usa como referencia de calificación comparativa.
# is_solucion_docente_only = True siempre — se filtra en frontend_output_adapter.
# ═══════════════════════════════════════════════════════

class PreguntaM5(BaseModel):
    """Pregunta única del Módulo 5 — Memorándum de decisión final.

    Diferencias vs PreguntaMinimalista:
      - numero: siempre 1 (un único reto final tipo memorándum)
      - solucion_esperada: memorándum modelo con decisión, evidencia, riesgo y plan
      - bloom_level: restringido a 'evaluation' | 'synthesis'
      - modules_integrated: requerido (siempre integra múltiples módulos)
      - is_solucion_docente_only: siempre True — frontend_output_adapter filtra este campo
    """
    numero: Literal[1] = Field(description="Número fijo del reto final: siempre 1")
    titulo: str = Field(description="Título corto y descriptivo de la pregunta (≤8 palabras)")
    enunciado: str = Field(description="Consigna dirigida al estudiante para redactar el memorándum final")
    solucion_esperada: str = Field(
        description=(
            "Memorándum modelo docente-only que toma una decisión final del caso, "
            "usa evidencia concreta de M1-M4, aborda el riesgo principal, define un "
            "plan de implementación y explicita el razonamiento académico/gerencial. "
            "Visible SOLO al docente. Usado como referencia para calificación por IA."
        )
    )
    bloom_level: Literal["evaluation", "synthesis"]
    modules_integrated: list[str] = Field(
        description="Módulos que el estudiante debe integrar para responder (ej: ['M1','M3','M4'])"
    )
    is_solucion_docente_only: bool = Field(
        default=True,
        description="Siempre True — solucion_esperada se filtra del payload al estudiante"
    )


class GeneradorPreguntasM5Output(BaseModel):
    """Salida del m5_questions_generator — exactamente 1 memorándum final."""
    preguntas: list[PreguntaM5] = Field(
        min_length=1,
        max_length=1,
        description="Exactamente 1 consigna de memorándum de decisión final",
    )


# ═══════════════════════════════════════════════════════
# MÓDULO 2 EDA — Preguntas Socráticas (aislado de PreguntaMinimalista)
# ═══════════════════════════════════════════════════════

class EDASocraticQuestion(BaseModel):
    """Pregunta socrática exclusiva del Módulo 2 EDA.

    Modelo AISLADO de PreguntaMinimalista para no romper M1, M3, M4, M5.
    Diferencias vs PreguntaMinimalista:
      - solucion_esperada es str (párrafo único docente-only, máx 120 palabras)
      - task_type clasifica si la respuesta es texto o requiere notebook
    """
    numero: int = Field(description="Número secuencial de la pregunta (1 o 2)")
    titulo: str = Field(description="Título corto y descriptivo de la pregunta (≤8 palabras)")
    enunciado: str = Field(description="El cuerpo principal de la pregunta dirigido al estudiante")
    solucion_esperada: str = Field(description="Respuesta modelo en un párrafo fluido (máx 120 palabras, visible solo para el docente)")
    bloom_level: str = Field(description="Nivel Bloom: analysis|evaluation|synthesis")
    chart_ref: Optional[str] = Field(default=None, description="ID del gráfico referenciado (chart_01, etc.)")
    exhibit_ref: Optional[str] = Field(default=None, description="Exhibit 1|Exhibit 2|Dataset|Ninguno")
    task_type: Literal["text_response"] = Field(
        default="text_response",
        description="Tipo de tarea: siempre text_response — M2 no genera notebook"
    )


class EDAQuestionsOutput(BaseModel):
    """Salida del eda_questions_generator — EXACTAMENTE 2 preguntas socráticas."""
    preguntas: list[EDASocraticQuestion] = Field(description="Exactamente 2 preguntas socráticas EDA")


# ═══════════════════════════════════════════════════════
# MÓDULO 6 — Teaching Note "Guía del Docente" (intro estructurada)
# El "Recorrido por Módulo" (§2) lo ensambla Python de forma determinista
# (build_module_guide_block) → el LLM solo aporta la sinopsis, el público,
# 3 objetivos y UNA frase de anclaje por módulo del allowlist.
# ═══════════════════════════════════════════════════════

class TeachingNoteAnchor(BaseModel):
    """Una frase de anclaje del caso para un módulo del roster (M6 §2)."""
    modulo_id: str = Field(
        description="Id del módulo a anclar: m1, m2, m3, m4 o m5 — usa SOLO los del allowlist provisto"
    )
    frase: str = Field(
        description="UNA frase (≤22 palabras) que conecta ese módulo con el dilema/empresa/sector REAL del caso"
    )


class TeachingNoteIntroOutput(BaseModel):
    """Salida estructurada de teaching_note_part1: §1 Resumen + anclajes de §2.

    ``objetivos`` se deja SIN longitud fija (se piden 3 en el prompt) para no provocar
    un ``ValidationError`` autoinfligido que degradaría la nota sin necesidad. ``anclajes``
    se intersecta en Python con el roster real (ids desconocidos se descartan; faltante →
    el módulo simplemente no muestra la línea "Anclaje del caso").
    """
    resumen_markdown: str = Field(
        description="Sinopsis ejecutiva del dilema central, ≤90 palabras, en prosa markdown SIN encabezados"
    )
    publico_objetivo: str = Field(
        description="Una sola línea: para qué perfil y nivel de estudiante es este caso"
    )
    objetivos: list[str] = Field(
        default_factory=list,
        description="3 objetivos de aprendizaje (verbos de acción) que referencien SOLO los módulos del caso",
    )
    anclajes: list[TeachingNoteAnchor] = Field(
        default_factory=list,
        description="Una frase de anclaje por cada módulo del allowlist provisto",
    )


# ═══════════════════════════════════════════════════════
# FASE 5 — Dataset Sintético (dataset_generator)
# ═══════════════════════════════════════════════════════

class DatasetRow(BaseModel):
    """Una fila del dataset sintético generado para el caso."""
    period: str = Field(description="Período temporal, ej: 'Q1 2023', 'Año 1', 'Mes 3'")
    variable: str = Field(description="Nombre de la variable, ej: 'Revenue', 'Churn Rate', 'NPS'")
    value: float = Field(description="Valor numérico de la métrica")
    unit: str = Field(description="Unidad de medida, ej: 'USD millones', '%', 'puntos'")
    category: str = Field(description="Categoría: 'financial' | 'operational' | 'market'")
    source: str = Field(description="Fuente de referencia: 'Exhibit 1' | 'Exhibit 2' | 'EDA simulado'")


class DatasetGeneratorOutput(BaseModel):
    """Salida del dataset_generator — dataset estructurado para análisis y descarga."""
    dataset_name: str = Field(description="Nombre descriptivo del dataset")
    description: str = Field(description="Una línea: qué representa el dataset")
    rows: list[DatasetRow] = Field(description="Mínimo 24 filas (4 periodos × 6 variables)")
    column_schema: list[str] = Field(
        description="Nombres de columnas en orden: ['period','variable','value','unit','category','source']"
    )


# ═══════════════════════════════════════════════════════
# DATASET PIPELINE v8 — Schemas internos (3 nodos)
# schema_designer → data_serializer → data_validator
# ═══════════════════════════════════════════════════════

class ColumnDefinition(BaseModel):
    """Definición de una columna del dataset. Output de schema_designer."""
    name: str = Field(description="Nombre de la columna, snake_case en inglés")
    type: Literal["int", "float", "str", "date"] = Field(description="Tipo de dato Python")
    description: str = Field(description="Qué representa esta columna en el negocio")
    range_min: Optional[float] = Field(default=None, description="Valor mínimo numérico")
    range_max: Optional[float] = Field(default=None, description="Valor máximo numérico")
    nullable: bool = Field(default=False, description="True solo para nulos intencionales en ml_ds")
    trend: Optional[Literal["up", "down", "stable"]] = Field(
        default=None, description="Tendencia temporal para generación vectorizada"
    )
    dependency: Optional[dict] = Field(
        default=None,
        description="Dependencia de otra columna. Ej: {depends_on: 'revenue', relationship: 'inverse', noise_factor: 0.1}"
    )


class DatasetConstraints(BaseModel):
    """Constraints matemáticos que el data_serializer debe respetar."""
    revenue_annual_total: float = Field(description="Suma anual de revenue extraída del Exhibit 1")
    cost_annual_total: Optional[float] = Field(default=None)
    ebitda_annual_total: Optional[float] = Field(default=None)
    tolerance_pct: float = Field(default=0.05, description="Tolerancia ±5% para validación")
    revenue_column: str = Field(default="revenue", description="Nombre de la columna de revenue en el dataset")


class DatasetSchema(BaseModel):
    """Output del schema_designer. Input del data_serializer y data_validator."""
    columns: list[ColumnDefinition]
    n_rows: int = Field(description="Número exacto de filas a generar")
    time_granularity: Literal["monthly", "quarterly", "annual", "daily"] = Field(default="monthly")
    constraints: DatasetConstraints
    reasoning_summary: str = Field(default="", description="Justificación breve de las decisiones de diseño")
