"""T4 smoke test ejecutable con pytest.

Verifica el path largo para ``ml_ds`` y trata ``doc6_notebook`` como
campo legacy obsoleto que debe permanecer ausente.
"""

import json

import pytest

pytestmark = pytest.mark.live_llm

T4_PAYLOAD = {
    "messages": [("user", "Generar caso Harvard T4 smoke test")],
    "subject": "Machine Learning en Operaciones",
    "syllabusModule": "Optimizacion con ML",
    "academicLevel": "Maestria",
    "industry": "Logistica y Cadena de Suministro",
    "caseType": "harvard_with_eda",
    "studentProfile": "ml_ds",
    "edaDepth": "charts_plus_code",
    "guidingQuestion": "Deberia la empresa implementar un modelo de demand forecasting o un sistema de reorder automatico?",
    "scenarioDescription": "Una empresa logistica evalua como reducir el costo de inventario usando modelos predictivos.",
    "suggestedTechniques": ["ARIMA", "XGBoost", "Safety Stock Optimization"],
    "includePythonCode": True,
}

NODES_EXPECTED = {
    "input_adapter",
    "doc1_flow",
    "output_adapter_intermediate",
    "eda_flow",
    "m3_flow",
    "m4_flow",
    "synthesis_flow",
    "output_adapter_final",
}
CONTENT_KEYS_REQUIRED = [
    "narrative",
    "edaReport",
    "edaCharts",
    "m3Content",
    "m4Content",
    "m5Content",
    "teachingNote",
]


def safe_preview(val: object, n: int = 60) -> str:
    if isinstance(val, str):
        return val[:n].encode("ascii", "replace").decode("ascii")
    if isinstance(val, list):
        return f"[list len={len(val)}]"
    return str(type(val))


def _record_generation_errors(errors: list[str], field_name: str, value: object) -> None:
    if not isinstance(value, str):
        return

    sentinels = {
        "m4_content": "[M4_GENERATION_ERROR]",
        "m5_content": "[M5_GENERATION_ERROR]",
        "m4Content": "[M4_GENERATION_ERROR]",
        "m5Content": "[M5_GENERATION_ERROR]",
    }
    sentinel = sentinels.get(field_name)
    if sentinel and sentinel in value:
        errors.append(f"[FAIL] {field_name} contiene sentinel {sentinel}")


def test_t4_smoke() -> None:
    from case_generator.graph import graph

    print("\n" + "=" * 60)
    print("T4 SMOKE TEST -- ml_ds + harvard_with_eda + notebook")
    print("=" * 60)
    print(f"caseType: {T4_PAYLOAD['caseType']}  studentProfile: {T4_PAYLOAD['studentProfile']}")
    print(f"edaDepth: {T4_PAYLOAD['edaDepth']}  includePythonCode: {T4_PAYLOAD['includePythonCode']}")
    print()

    executed_nodes: list[str] = []
    final_state: dict = {}

    for event in graph.stream(T4_PAYLOAD, stream_mode="updates"):
        for node_name, node_output in event.items():
            executed_nodes.append(node_name)
            print(f"  [OK] Nodo completado: {node_name}")
            if isinstance(node_output, dict):
                final_state.update(node_output)

    print("\n--- NODOS EJECUTADOS ---")
    print(json.dumps(executed_nodes, indent=2, ensure_ascii=False))

    errors: list[str] = []

    for node in NODES_EXPECTED:
        if node not in executed_nodes:
            errors.append(f"[FAIL] Nodo esperado ausente: {node}")
        else:
            print(f"  [PASS] Nodo ejecutado: {node}")

    od = final_state.get("output_depth")
    if od != "visual_plus_notebook":
        errors.append(f"[FAIL] output_depth={od!r}, esperado 'visual_plus_notebook'")
    else:
        print(f"  [PASS] output_depth: {od!r}")

    notebook = final_state.get("m3_notebook_code", "")
    if not notebook or len(notebook) < 50:
        errors.append(f"[FAIL] m3_notebook_code ausente o muy corto: {len(notebook)} chars")
    else:
        print(f"  [PASS] m3_notebook_code: {len(notebook)} chars")

    nb_legacy = final_state.get("doc6_notebook", "")
    if nb_legacy and len(nb_legacy) > 10:
        errors.append(f"[FAIL] doc6_notebook presente ({len(nb_legacy)} chars) - campo obsoleto, no debe escribirse")
    else:
        print("  [PASS] doc6_notebook: ausente (correcto - campo obsoleto)")

    if notebook and "np.random" in notebook:
        errors.append("[FAIL] m3_notebook_code contiene np.random - datos sintéticos prohibidos")
    elif notebook:
        print("  [PASS] m3_notebook_code: sin np.random (guardrail datos inventados OK)")

    m3_mode = final_state.get("m3_mode")
    if m3_mode != "experiment":
        errors.append(f"[FAIL] m3_mode={m3_mode!r}, esperado 'experiment' para ml_ds")
    else:
        print(f"  [PASS] m3_mode: {m3_mode!r}")

    m3_charts = final_state.get("m3_charts")
    if not m3_charts:
        print("  [INFO] m3_charts: vacío (m3_chart_generator pendiente de implementación)")
    else:
        print(f"  [INFO] m3_charts: {len(m3_charts)} charts")

    doc2_eda = final_state.get("doc2_eda", "")
    if not doc2_eda:
        errors.append("[FAIL] doc2_eda ausente")
    else:
        print(f"  [PASS] doc2_eda: {len(doc2_eda)} chars")

    dataset = final_state.get("doc7_dataset", [])
    if not dataset:
        print("  [WARN] doc7_dataset vacío (0 filas) -- dataset_generator issue pendiente")
    elif len(dataset) < 24:
        print(f"  [WARN] doc7_dataset solo {len(dataset)} filas (mínimo esperado: 24 para ml_ds)")
    else:
        print(f"  [PASS] doc7_dataset: {len(dataset)} filas")

    charts_eda = final_state.get("doc2_eda_charts", [])
    if not charts_eda:
        errors.append("[FAIL] doc2_eda_charts ausente o vacio")
    else:
        print(f"  [PASS] doc2_eda_charts: {len(charts_eda)} charts")

    m3 = final_state.get("m3_content", "")
    if not m3 or m3.startswith("?"):
        errors.append(f"[FAIL] m3_content ausente o con error: {m3[:80]!r}")
    else:
        print(f"  [PASS] m3_content: {len(m3)} chars")
        audit_markers = ["## 3.1", "## 3.2", "## 3.3", "Semáforo de Evidencia"]
        if any(marker in m3 for marker in audit_markers):
            errors.append("[FAIL] m3_content parece Auditoría de Evidencia (secciones 3.x) - ml_ds debe recibir Experiment Engineer")
        experiment_markers = ["Hipótesis", "Métrica de éxito", "Condición de descarte"]
        if not any(marker in m3 for marker in experiment_markers):
            errors.append("[FAIL] m3_content no contiene marcadores de Experiment Engineer (Hipótesis/Métrica de éxito/Condición de descarte)")
        else:
            print("  [PASS] m3_content: marcadores Experiment Engineer presentes")

    m3_questions = final_state.get("m3_questions", [])
    valid_exp_refs = {"exp.hipotesis", "exp.sesgo", "exp.validacion", "exp.descarte"}
    if m3_questions:
        bad_refs = [
            q.get("m3_section_ref")
            for q in m3_questions
            if isinstance(q, dict) and q.get("m3_section_ref") not in valid_exp_refs
        ]
        if bad_refs:
            errors.append(f"[FAIL] m3_questions contiene m3_section_ref invalidos (esperado exp.*): {bad_refs}")
        else:
            print(f"  [PASS] m3_questions: {len(m3_questions)} preguntas con refs exp.* correctas")
    else:
        print("  [WARN] m3_questions: vacío o ausente")

    m4 = final_state.get("m4_content", "")
    if not m4:
        errors.append("[FAIL] m4_content ausente")
    elif "DATASET_UNAVAILABLE" in m4:
        errors.append("[FAIL] m4_content contiene sentinel DATASET_UNAVAILABLE")
    elif "M3_NOT_EXECUTED" in m4:
        errors.append("[FAIL] m4_content contiene sentinel [M3_NOT_EXECUTED]")
    else:
        _record_generation_errors(errors, "m4_content", m4)
        print(f"  [PASS] m4_content: {len(m4)} chars (sin sentinels)")

    for field in ["m5_content", "doc3_teaching_note"]:
        val = final_state.get(field, "")
        val_str = str(val) if val else ""
        if not val_str:
            errors.append(f"[FAIL] {field} ausente")
        elif val_str.startswith("?") or val_str.startswith("ERROR:"):
            errors.append(f"[FAIL] {field} contiene error: {val_str[:100]!r}")
        else:
            _record_generation_errors(errors, field, val_str)
            print(f"  [PASS] {field}: {len(val_str)} chars")

    canonical = final_state.get("canonical_output", {})
    content = canonical.get("content", {})
    for key in CONTENT_KEYS_REQUIRED:
        if key not in content:
            errors.append(f"[FAIL] canonical_output.content falta clave: {key}")
        else:
            _record_generation_errors(errors, key, content[key])
            print(f"  [PASS] content[{key!r}]: {safe_preview(content[key])}...")

    if "m3NotebookCode" not in content:
        errors.append("[FAIL] content['m3NotebookCode'] ausente (ml_ds + visual_plus_notebook)")
    else:
        print(f"  [PASS] content['m3NotebookCode']: {safe_preview(content['m3NotebookCode'])}...")

    if "notebookCode" in content and content["notebookCode"]:
        errors.append("[FAIL] content['notebookCode'] presente - campo obsoleto, M2 ya no genera notebook")

    print("\n" + "=" * 60)
    assert not errors, "\n".join(errors)
    print("T4 RESULTADO: PASS")
    print("  Path completo ml_ds + harvard_with_eda + visual_plus_notebook verificado.")
    print("  m3_notebook_code generado, m3_mode='experiment', output_depth correcto.")
    print("=" * 60)

