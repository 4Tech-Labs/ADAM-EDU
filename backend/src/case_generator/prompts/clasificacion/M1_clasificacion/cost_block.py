"""M1 P3 cost-grounding block (Issue #361) — clasificación family.

Builds the ``{cost_matrix_block}`` injected into ``CASE_QUESTIONS_PROMPT_CLASSIFICATION``
so that the M1 discussion question P3 grounds its asymmetric-cost trade-off in the SAME
single source the M3 notebook consumes — the normalized ``business_cost_matrix`` dict in
``state["dataset_schema_required"]`` (validated by ``_validate_business_cost_matrix`` →
``model_dump()``). Before #361, P3 was told to cite a per-event cost "según Exhibit 1",
but Exhibit 1 is an annual aggregate with no per-event cost, so the LLM fabricated a figure
independent from M3's matrix → a cross-module contradiction in the first thing a student reads.

Presentation rules (this is **student-facing** — unlike M3's teacher/notebook contract block):
  * **Business language only.** ``fp_cost`` → *costo de acción innecesaria*, ``fn_cost`` →
    *costo de omisión*. NEVER emit the raw DS keys (``fp_cost``/``fn_cost``) nor DS jargon
    ("falso positivo/negativo", "AUC", "threshold").
  * **Single source, not byte-identical to M3.** Both modules read the same normalized dict;
    M3's LLM copies the numbers from the contract JSON, so the guarantee is "same source",
    not "same rendered output".
  * **#360 coordination.** The cost figures are case PREMISES, not Exhibit cells, so the block
    instructs P3 to set ``exhibit_ref="Ninguno"``. That keeps the #360 Exhibit-coherence
    validator (``m1_grounding.validate_questions_exhibit_coherence``) from flagging the
    cost figure against an Exhibit table it can never appear in.
  * **Placeholder-safe.** The rendered string contains no ``{``/``}`` (numbers are floats;
    the currency token is gated on ``.isalpha()`` so a brace/symbol/whitespace value degrades
    to the qualitative block), so the node's single ``.format(**context)`` cannot re-trigger
    the parser — unconditionally, not just for validated input.

When the matrix is absent/``None``/malformed, the block degrades to a QUALITATIVE trade-off
(whom to prioritize under uncertainty) and never demands or invents a figure.
"""

from __future__ import annotations


def _format_cost_amount(value: float) -> str:
    """Render a cost magnitude cleanly: integers without decimals, else 2dp.

    Thousands are grouped with ``,`` (Python format spec, locale-independent → deterministic).
    Cosmetic only — the value's provenance (the shared matrix) is what matters, not its glyphs.
    """
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,.2f}"


def build_cost_matrix_block(business_cost_matrix: dict | None) -> str:
    """Return the curated, placeholder-free P3 cost block for the classification anchor.

    ``business_cost_matrix`` is the normalized sub-dict
    ``state["dataset_schema_required"]["business_cost_matrix"]`` (or ``None``). Any missing or
    non-numeric field degrades to the qualitative block (best-effort — the dict is already
    normalized, so this is belt-and-suspenders).
    """
    if isinstance(business_cost_matrix, dict):
        fp = business_cost_matrix.get("fp_cost")
        fn = business_cost_matrix.get("fn_cost")
        currency = business_cost_matrix.get("currency")
        if (
            isinstance(fp, (int, float))
            and not isinstance(fp, bool)
            and isinstance(fn, (int, float))
            and not isinstance(fn, bool)
            and isinstance(currency, str)
            # ISO 4217 codes are pure letters; `.isalpha()` is the defensive guarantee that
            # the currency token contributes no brace/symbol/whitespace to the rendered block,
            # so the placeholder-safety invariant holds for ANY input, not just validated ones.
            and currency.strip().isalpha()
        ):
            fp_str = _format_cost_amount(float(fp))
            fn_str = _format_cost_amount(float(fn))
            cur = currency.strip().upper()
            return (
                "MATRIZ DE COSTOS DEL CASO (premisa del enunciado — NO proviene de ningún Exhibit)\n"
                "Usa EXCLUSIVAMENTE estas dos cifras para el trade-off de costos de P3, en "
                "lenguaje de negocio (sin tecnicismos):\n"
                "- Costo de una acción innecesaria (intervenir con un caso que NO presentaría "
                f"el evento): {fp_str} {cur} por caso.\n"
                "- Costo de una omisión (NO actuar con un caso que SÍ presentaría el evento): "
                f"{fn_str} {cur} por caso.\n"
                "Estas cifras son PREMISAS dadas del caso, no celdas de un Exhibit: fija el campo "
                '`exhibit_ref` de P3 en "Ninguno". No las atribuyas a "Exhibit 1" ni a otro anexo, '
                "y no inventes montos adicionales."
            )
    return (
        "MATRIZ DE COSTOS DEL CASO: no disponible.\n"
        "El caso no define costos asimétricos cuantificados. Plantea el trade-off de P3 de forma "
        "CUALITATIVA: a qué grupo conviene priorizar bajo incertidumbre y por qué, SIN exigir ni "
        'inventar cifras de costo. Fija el campo `exhibit_ref` de P3 en "Ninguno".'
    )
