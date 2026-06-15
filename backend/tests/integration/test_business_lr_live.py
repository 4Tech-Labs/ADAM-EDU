"""Live e2e (opt-in) — business + Logistic Regression (Issue 8A del plan).

Ejecutar SOLO con:
    RUN_LIVE_LLM_TESTS=1 uv run --directory backend pytest -m live_llm \
        tests/integration/test_business_lr_live.py -q -s

Verifica el arco completo del cambio business+LR:
  * Los charts del M2 vienen del builder Python-determinista (`python_builder`),
    no del path LLM-JSON que producía los gráficos malos.
  * El set honesto aparece (financial_mirage + churn_drivers + cohorte/box).
  * El M3 razona la decisión apoyada en regresión logística en lenguaje gerencial.
  * El dataset sintético tiene una correlación NPS↔churn REAL (no inventada).
"""

import uuid

import pandas as pd
import pytest

pytestmark = [pytest.mark.live_llm, pytest.mark.asyncio]

BUSINESS_LR_PAYLOAD = {
    "messages": [("user", "Generar caso business + Logistic Regression")],
    "subject": "Estrategia de Retención",
    "syllabusModule": "Gestión de Clientes",
    "academicLevel": "Maestría",
    "industry": "Educación Digital",
    "caseType": "harvard_with_eda",
    "studentProfile": "business",
    "edaDepth": "charts_only",
    "guidingQuestion": (
        "¿Qué estrategia de intervención debería priorizar la dirección para mitigar la "
        "deserción, basándose en la probabilidad de abandono estimada por el modelo?"
    ),
    "scenarioDescription": (
        "Una universidad digital enfrenta una tasa de deserción del 22% en sus nuevas "
        "certificaciones y debe asignar un fondo limitado de becas de retención."
    ),
    "suggestedTechniques": ["Logistic Regression"],
    "includePythonCode": False,
}

# Tokens de jerga DS que el M3 business NO debería exponer como explicación técnica.
_JARGON = ("log-odds", "odds ratio", "auc", "roc", "gridsearch", "coeficiente de regresión")


async def test_business_lr_e2e() -> None:
    from case_generator.graph import get_graph

    graph = await get_graph()
    config = {"configurable": {"thread_id": f"business-lr-live-{uuid.uuid4()}"}}

    final_state: dict = {}
    async for event in graph.astream(BUSINESS_LR_PAYLOAD, config=config, stream_mode="updates"):
        for _node, node_output in event.items():
            if isinstance(node_output, dict):
                final_state.update(node_output)

    errors: list[str] = []

    # 1. Charts M2 vienen del builder Python-determinista.
    charts = final_state.get("doc2_eda_charts", [])
    if not charts:
        errors.append("[FAIL] doc2_eda_charts vacío — el builder business no emitió panel")
    else:
        non_python = [c.get("id") for c in charts if c.get("data_source") != "python_builder"]
        if non_python:
            errors.append(f"[FAIL] charts no-deterministas (LLM-JSON): {non_python}")
        ids = {c.get("id") for c in charts}
        if "financial_mirage" not in ids or "churn_drivers" not in ids:
            errors.append(f"[FAIL] faltan charts honestos esperados; ids={ids}")
        # Anti-doble-eje: ningún chart financiero define yaxis2.
        for c in charts:
            if c.get("id") == "financial_mirage" and "yaxis2" in (c.get("layout") or {}):
                errors.append("[FAIL] financial_mirage reintrodujo el doble eje Y")

    # 2. M3 razona la decisión LR en lenguaje gerencial.
    m3 = (final_state.get("m3_content") or "").lower()
    if not m3 or m3.startswith("[m3_not_executed]"):
        errors.append("[FAIL] m3_content ausente o no ejecutado")
    else:
        if "probabilidad de abandono" not in m3 and "regresión logística" not in m3:
            errors.append("[FAIL] M3 no menciona la decisión apoyada en el modelo LR")
        jargon_found = [t for t in _JARGON if t in m3]
        if jargon_found:
            errors.append(f"[FAIL] M3 business expone jerga DS: {jargon_found}")

    # 3. El dataset tiene una correlación NPS↔churn REAL.
    dataset = final_state.get("doc7_dataset", [])
    if dataset:
        df = pd.DataFrame(dataset)
        if {"nps", "churn_rate"}.issubset(df.columns):
            corr = df["nps"].corr(df["churn_rate"])
            if not (corr < -0.2):
                errors.append(f"[FAIL] NPS↔churn no correlacionan negativamente (corr={corr:.2f})")

    # 4. business no genera notebook.
    for nb in ("m3_notebook_code", "doc6_notebook"):
        if final_state.get(nb):
            errors.append(f"[FAIL] {nb} presente en business (solo ml_ds genera notebook)")

    assert not errors, "\n".join(errors)
