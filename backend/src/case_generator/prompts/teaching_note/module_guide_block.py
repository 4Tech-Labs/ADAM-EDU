"""Deterministic per-module guide block for M6 (Teaching Note / "Solución Maestra").

The M6 teacher note's core section — "Recorrido por Módulo" — is assembled HERE, in pure
Python, NOT by the LLM. It states, for each module the case ACTUALLY has, what the student
sees + what they learn/do + the question format. Because the module roster (set, numbering,
bilingual labels) is code-assembled data, phantom / missing / mis-numbered modules are
structurally impossible, which is the coherence guarantee the redesign rests on.

Design contract (mirrors ``build_cost_matrix_block`` in
``prompts/clasificacion/M1_clasificacion/cost_block.py``):

* **Pure & total.** No LLM, no ``state`` read inside — the caller passes resolved flags.
* **Placeholder-free.** The returned string contains no ``{`` / ``}`` so the node's single
  ``.format(**context)`` cannot re-trigger the parser. (Em-dashes/digits are fine.)
* **Currency-token-free.** No ``$``/``€``/ISO code adjacent to a figure, so the composed
  ``enforce_usd_currency`` (#377) is a byte-identical no-op on this copy.
* **Mirrors ``getModuleConfig``** (``frontend/src/shared/case-viewer/caseViewerConfig.ts``):
  labels per ``isBusiness`` and EDA presence, M4 number ``4 if EDA else 2``, M5
  ``5 if EDA else 3``, M2/M3 only when ``case_type == "harvard_with_eda"``, never M6.

Wiring notes for the caller (see ``teaching_note_part1`` in ``graph.py``):

* ``is_business = (state.get("studentProfile") == "business")`` — STRICT equality, the same
  comparison ``getModuleConfig`` uses (``studentProfile === "business"``). Never the resolved
  ``context["student_profile"]`` (``_resolve_generation_focus`` lowercases/normalizes it).
* ``case_type = state.get("caseType", "harvard_only")`` — the same flag ``route_master`` gates
  ``eda_flow`` on.
* ``family = context.get("primary_family")`` — RESOLVED (a family string, or the literal
  ``"desconocida"`` fallback — never ``None``), reused from the ``_build_base_context`` the node
  already calls. ``state.get("primary_family")`` does NOT exist (always ``None``). ``is_clf``
  compares the resolved value strictly to ``"clasificacion"``, so ``"desconocida"`` → generic M2 line.
  ``is_clustering`` (Issue #471) compares strictly to ``"clustering"`` and is consumed ml_ds-ONLY
  (M1/M3 are nested in the ml_ds branch; M2 guards with ``and not is_business``) — mirroring the
  strict ``_is_ml_ds_clustering`` gate, so business+clustering stays byte-identical/generic.
* ``notebook_present = bool(state.get("m3_notebook_code")) and not state.get("m3_notebook_degraded")``
  — REALIZED state. The M3 notebook GENERATOR (graph.py) is family-AGNOSTIC (ml_ds regresión/
  clustering ship a real notebook too); only the EXECUTOR is clasificación-gated. So gating the
  M6 notebook clause on realized state (code present, not degraded) is both family-agnostic and
  truthful to what actually shipped. Documented limitation: ``POST .../regenerate-notebook`` re-runs
  only the M3 nodes, NOT the teaching note, so a notebook regenerated AFTER a degraded run leaves the
  M6 clause stale (omitted) — a minor under-description, never a false claim; accepted, not fixed.
"""

from __future__ import annotations

# Curated descriptive constants exposed for the drift tests. The M4 VERDICT literals ARE bound to
# the source M4 prompt (test_m4_verdict_literals_bound_to_source asserts they appear in
# prompts/_shared.py, modulo the `**bold**` markers). The word-count literals are NOT bound: the
# source prompts phrase them differently (e.g. _writer_base.py writes "900-1200" with a plain
# hyphen vs. "900–1.200" here), so they are validated for PRESENCE in the rendered block only and
# must be updated by hand if a module's length target changes (documented staleness risk).
M1_NARRATIVE_WORDS = "900–1.200"
M2_EDA_WORDS = "450–600"
M3_AUDIT_WORDS = "400–550"
M3_EXPERIMENT_WORDS = "350–650"
M4_WORDS = "850–1.050"
M5_WORDS = "400–550"
M4_VERDICT_BUSINESS = "Aprobar / Rechazar / Aprobar con condiciones"
M4_VERDICT_MLDS = "Desplegar / No desplegar / Desplegar con restricciones"

# Canonical bilingual labels — copied verbatim from getModuleConfig (caseViewerConfig.ts).
# A drift test asserts these stay equal to the TS literals.
_LABELS_BUSINESS: dict[str, str] = {
    "m1": "El Caso y el Dilema — Comprende la situación gerencial",
    "m2": "Lectura de los Datos — Interpreta la evidencia visual",
    "m3": "Auditoría de la Evidencia — Evalúa qué tan sólida es la evidencia",
    "m4": "Impacto en el Negocio — Cuantifica el valor y los trade-offs",
    "m5": "Recomendación Ejecutiva — Redacta el memorándum a la junta",
}
_LABELS_MLDS: dict[str, str] = {
    "m1": "Planteamiento del Problema — Traduce el reto a un problema de datos",
    "m2": "Exploración de Datos — Analiza el dataset y sus patrones",
    "m3": "Diseño del Experimento — Valida el modelo con rigor experimental",
    "m4": "Impacto y Valor — Convierte el modelo en valor de negocio",
    "m5": "Decisión Ejecutiva — Redacta el memorándum final a la dirección",
}

_EDA_CASE_TYPE = "harvard_with_eda"
_CLASSIFICATION_FAMILY = "clasificacion"
_CLUSTERING_FAMILY = "clustering"

# Issue #437 Fase 3 — the M4 module synopsis value frame per Impact Lens. CURATED + CURRENCY-TOKEN-FREE
# (no ``$``/``€``/ISO adjacent to a figure — ``test_block_byte_identical_through_usd_enforce`` requires
# the composed ``enforce_usd_currency`` to be a no-op here, so we do NOT reuse ``IMPACT_LENS_CATALOG``'s
# ``kpi_rows``, which carry currency tokens like ``(USD)``). ``financial_roi``/None reproduces today's exact tokens →
# byte-identical for every case without a non-financial lens. Keys mirror ``IMPACT_LENS_KEYS`` (a drift
# test asserts the set match). ``(value_noun, mlds_examples)``.
_M4_VALUE_FRAME_BY_LENS: dict[str, tuple[str, str]] = {
    "financial_roi": ("valor de negocio", "retorno, factibilidad de despliegue"),
    "operational_efficiency": ("valor operativo", "eficiencia, reducción de defectos/downtime"),
    "clinical_outcomes": ("valor clínico", "outcomes evitados, factibilidad de despliegue"),
    "learning_outcomes": ("valor educativo", "retención y aprendizaje"),
    "environmental_outcomes": ("valor ambiental", "servicios ecosistémicos, factibilidad de despliegue"),
}
_M4_VALUE_FRAME_DEFAULT = _M4_VALUE_FRAME_BY_LENS["financial_roi"]


def _roster(is_business: bool, case_type: str) -> list[tuple[str, int, str]]:
    """Return ``[(module_id, number, label), ...]`` for exactly the modules this case has.

    Mirrors ``getModuleConfig`` EXACTLY: always M1; M2+M3 only for ``harvard_with_eda``;
    M4 number ``4 if EDA else 2``; M5 ``5 if EDA else 3``; never M6.
    """
    is_eda = case_type == _EDA_CASE_TYPE
    labels = _LABELS_BUSINESS if is_business else _LABELS_MLDS
    roster: list[tuple[str, int, str]] = [("m1", 1, labels["m1"])]
    if is_eda:
        roster.append(("m2", 2, labels["m2"]))
        roster.append(("m3", 3, labels["m3"]))
    roster.append(("m4", 4 if is_eda else 2, labels["m4"]))
    roster.append(("m5", 5 if is_eda else 3, labels["m5"]))
    return roster


def module_guide_roster_ids(is_business: bool, case_type: str) -> list[str]:
    """Return just the module ids present in this case, e.g. ``["m1","m4","m5"]``.

    Shared by the node (to intersect LLM anchors), ``m6_grounding`` (out-of-roster check),
    and the prompt allowlist — a single source of truth for "which modules exist".
    """
    return [mod_id for mod_id, _num, _label in _roster(is_business, case_type)]


def build_roster_allowlist(is_business: bool, case_type: str) -> str:
    """Compact ``module_id: heading`` list injected into the part1 prompt as the allowlist.

    The LLM is told to anchor ONLY these modules and to reference ONLY these in the objectives.
    Placeholder-free.
    """
    lines = [
        f"- {mod_id}: Módulo {num} · {label}"
        for mod_id, num, label in _roster(is_business, case_type)
    ]
    return "\n".join(lines)


def _module_lines(
    mod_id: str,
    *,
    is_business: bool,
    is_clf: bool,
    is_clustering: bool,
    notebook_present: bool,
    lens: str | None = None,
) -> list[str]:
    """The 3 deterministic descriptive lines (Qué ve / Qué aprende / Formato) for one module.

    ``lens`` (Issue #437 Fase 3) reframes ONLY the M4 ``aprende`` value noun; ``None``/``financial_roi``
    keeps today's exact wording (byte-identical). It never touches the drift-locked LABELS or verdict.

    ``is_clustering`` (Issue #471) reframes M1/M2/M3 for the unsupervised clustering family. It is
    ml_ds-ONLY: M1/M3 are nested in the ``else`` of ``is_business`` (so business+clustering never
    reaches them), and M2 guards explicitly with ``and not is_business`` — mirroring the strict
    ``_is_ml_ds_clustering`` gate (graph.py), so business+clustering stays byte-identical/generic.
    """
    if mod_id == "m1":
        ve = (
            f"Una narrativa de {M1_NARRATIVE_WORDS} palabras con el dilema central, "
            "3 opciones estratégicas (A/B/C) y 3 Exhibits (financiero, operativo y de stakeholders)."
        )
        if is_business:
            aprende = (
                "Identifica el dilema gerencial real, mapea a los stakeholders y lee los Exhibits "
                "para formarse una hipótesis inicial."
            )
        elif is_clustering:
            # Unsupervised: no target variable. Frame the segmentation decision instead (#455/#471).
            aprende = (
                "Traduce el problema de negocio a un problema de datos: descubre segmentos latentes "
                "en datos sin etiquetar (aprendizaje no supervisado), plantea hipótesis de "
                "segmentación y reconoce los límites de la información."
            )
        else:
            aprende = (
                "Traduce el problema de negocio a un problema de datos: define la variable "
                "objetivo, plantea hipótesis analíticas y reconoce los límites de la información."
            )
        formato = (
            "3 preguntas de discusión (comprensión → análisis → evaluación); la última exige "
            "elegir A/B/C con información incompleta y nombrar el supuesto más frágil."
        )
        return [ve, aprende, formato]

    if mod_id == "m2":
        ve = (
            f"Un informe de Análisis Exploratorio de Datos (EDA) de {M2_EDA_WORDS} palabras, "
            "gráficas interactivas y la tabla del dataset."
        )
        aprende = (
            "Pasa de la intuición de la narrativa a la evidencia de los datos en lenguaje claro, "
            "confirmando o refutando la hipótesis del Módulo 1."
            if is_business
            else "Examina distribuciones, valores atípicos y correlaciones para confirmar o "
            "refutar la hipótesis del Módulo 1 con rigor técnico."
        )
        if is_clf:
            formato = (
                "2 preguntas socráticas abiertas: la Paradoja de la Exactitud (desbalance de clases) "
                "y el equilibrio entre precisión y exhaustividad."
            )
        elif is_clustering and not is_business:
            # Mirror EDA_QUESTIONS_GENERATOR_PROMPT_CLUSTERING (#456): P1 escala/distancia, P2
            # correlación + silhouette. ml_ds-only (business+clustering keeps the generic line).
            formato = (
                "2 preguntas socráticas abiertas: por qué estandarizar las features antes de "
                "aplicar K-Means (escala y distancia) y cómo juzgar la validez de los segmentos "
                "(correlación entre features y lectura del coeficiente de silhouette)."
            )
        else:
            formato = (
                "2 preguntas socráticas abiertas: el sesgo de confirmación en los datos y la "
                "diferencia entre correlación y causalidad."
            )
        return [ve, aprende, formato]

    if mod_id == "m3":
        if is_business:
            ve = (
                f"Una auditoría crítica de la evidencia ({M3_AUDIT_WORDS} palabras): puntos "
                "ciegos, supuestos implícitos, riesgos de interpretación y un veredicto de confianza."
            )
            aprende = "Aprende a dudar de forma constructiva de los hallazgos del Módulo 2 antes de decidir."
        else:
            if is_clustering:
                # Unsupervised segmentation, not a supervised experiment / causality (#457/#471).
                ve = (
                    f"Un diseño de segmentación ({M3_EXPERIMENT_WORDS} palabras) que conecta los "
                    "datos con la elección del número de grupos y la validación de su cohesión."
                )
                aprende = (
                    "Aprende a elegir el número de segmentos, validar su cohesión (silhouette) y "
                    "traducir cada grupo en un perfil accionable."
                )
            else:
                ve = (
                    f"Un diseño experimental ({M3_EXPERIMENT_WORDS} palabras) que conecta los datos "
                    "con la arquitectura de la solución y prueba la causalidad."
                )
                aprende = (
                    "Aprende a diseñar experimentos rigurosos, anticipar sesgos y definir criterios "
                    "de validación."
                )
            # Notebook clause is family-agnostic for ml_ds (DRY: applies to clustering + clf/reg).
            if notebook_present:
                ve += " Incluye un notebook de Python (Jupyter) con la implementación."
        formato = "3 preguntas de discusión (análisis, evaluación y síntesis)."
        return [ve, aprende, formato]

    if mod_id == "m4":
        ve = (
            f"Un análisis de impacto ({M4_WORDS} palabras) con la proyección numérica de las "
            "opciones, gráficas y una recomendación ejecutiva final."
        )
        value_noun, mlds_examples = _M4_VALUE_FRAME_BY_LENS.get(lens or "", _M4_VALUE_FRAME_DEFAULT)
        aprende = (
            f"Traduce la evidencia en {value_noun}, cuantifica los trade-offs y elige una "
            "opción justificada con datos."
            if is_business
            else f"Traduce el desempeño técnico del modelo en {value_noun} ({mlds_examples}) y "
            "decide con evidencia."
        )
        verdict = M4_VERDICT_BUSINESS if is_business else M4_VERDICT_MLDS
        formato = (
            "3 preguntas abiertas que citan métricas concretas; la recomendación cierra "
            f"con un veredicto {verdict}."
        )
        return [ve, aprende, formato]

    # m5
    ve = (
        f"Un «Informe de Resolución para la Junta Directiva» ({M5_WORDS} palabras) que plantea "
        "el dilema directivo final."
    )
    aprende = (
        "Sintetiza los módulos anteriores en una decisión ejecutiva final bajo incertidumbre, "
        "anclada en un marco de referencia reconocido."
    )
    formato = (
        "1 memorándum ejecutivo (Decisión / Evidencia / Riesgo / Implementación / Marco); el "
        "docente dispone de la respuesta modelo para calificar."
    )
    return [ve, aprende, formato]


def build_module_guide_block(
    *,
    is_business: bool,
    case_type: str,
    family: str | None,
    notebook_present: bool,
    anchors: dict[str, str] | None = None,
    lens: str | None = None,
) -> str:
    """Return the full ``## Recorrido por Módulo`` markdown section for this case.

    ``anchors`` maps ``module_id -> frase`` (the per-module case-specific line the LLM supplies).
    A module with no anchor simply omits the "Anclaje del caso" line (graceful degrade).
    The result is a markdown BULLET LIST with module headers separated by blank lines, because
    the frontend renders the note with ``marked({breaks:false})`` + justified paragraphs, which
    would otherwise fuse soft-wrapped lines into one paragraph.

    ``lens`` (Issue #437 Fase 3) reframes ONLY the M4 synopsis value noun by the resolved Impact Lens;
    ``None``/``financial_roi`` is byte-identical to today (the caller passes ``None`` when the lens
    kill-switch is off, keeping the OFF path byte-identical).
    """
    is_clf = (family or "") == _CLASSIFICATION_FAMILY
    is_clustering = (family or "") == _CLUSTERING_FAMILY
    anchors = anchors or {}

    out: list[str] = ["## Recorrido por Módulo", ""]
    for mod_id, num, label in _roster(is_business, case_type):
        ve, aprende, formato = _module_lines(
            mod_id,
            is_business=is_business,
            is_clf=is_clf,
            is_clustering=is_clustering,
            notebook_present=notebook_present,
            lens=lens,
        )
        out.append(f"**Módulo {num} · {label}**")
        out.append("")
        out.append(f"- **Qué ve el estudiante:** {ve}")
        out.append(f"- **Qué aprende / hace:** {aprende}")
        out.append(f"- **Formato de preguntas:** {formato}")
        anchor = anchors.get(mod_id)
        if anchor and anchor.strip():
            out.append(f"- **Anclaje del caso:** {anchor.strip()}")
        out.append("")

    # Trailing blank line trimmed so the synthesis concat stays tidy.
    return "\n".join(out).rstrip() + "\n"
