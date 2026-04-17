"""T2 smoke test live ejecutable con pytest."""

import json
import uuid

import pytest

pytestmark = [pytest.mark.live_llm, pytest.mark.asyncio]

T2_PAYLOAD = {
    "messages": [("user", "Generar caso Harvard T2 smoke test")],
    "subject": "Marketing Estrategico",
    "syllabusModule": "Segmentacion y Posicionamiento",
    "academicLevel": "Maestria",
    "industry": "Consumo Masivo",
    "caseType": "harvard_with_eda",
    "studentProfile": "business",
    "edaDepth": "charts_only",
    "guidingQuestion": "Deberia la empresa lanzar una linea premium o reforzar su marca masiva?",
    "scenarioDescription": "Una empresa de consumo masivo evalua si diversificar hacia el segmento premium.",
    "suggestedTechniques": ["Cluster Analysis", "Price Elasticity"],
    "includePythonCode": False,
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


async def test_t2_smoke() -> None:
    from case_generator.graph import get_graph

    graph = await get_graph()
    config = {"configurable": {"thread_id": f"test_t2_smoke-{uuid.uuid4()}"}}

    print("\n" + "=" * 60)
    print("T2 SMOKE TEST -- business + harvard_with_eda")
    print("=" * 60)
    print(f"caseType: {T2_PAYLOAD['caseType']}  studentProfile: {T2_PAYLOAD['studentProfile']}")
    print()

    executed_nodes: list[str] = []
    final_state: dict = {}

    async for event in graph.astream(T2_PAYLOAD, config=config, stream_mode="updates"):
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

    m4 = final_state.get("m4_content", "")
    if "DATASET_UNAVAILABLE" in m4:
        errors.append("[FAIL] m4_content contiene sentinel DATASET_UNAVAILABLE - EDA no llego a m4")
    elif "M3_NOT_EXECUTED" in m4:
        errors.append("[FAIL] m4_content contiene sentinel [M3_NOT_EXECUTED] - M3 no llego a m4")
    else:
        print("  [PASS] Sentinels ausentes en m4_content (correcto para harvard_with_eda)")

    eda_checks = {
        "doc2_eda": "EDA text report",
        "doc7_dataset": "dataset filas",
    }
    for field, label in eda_checks.items():
        val = final_state.get(field)
        if not val:
            errors.append(f"[FAIL] {field} ({label}) ausente")
        elif isinstance(val, list):
            print(f"  [PASS] {field}: {len(val)} filas")
        else:
            print(f"  [PASS] {field}: {len(str(val))} chars")

    charts = final_state.get("doc2_eda_charts", [])
    if not charts:
        errors.append("[FAIL] doc2_eda_charts ausente o vacio")
    else:
        print(f"  [PASS] doc2_eda_charts: {len(charts)} charts")

    m3 = final_state.get("m3_content", "")
    if not m3 or m3.startswith("?"):
        errors.append(f"[FAIL] m3_content ausente o con error: {m3[:80]!r}")
    else:
        print(f"  [PASS] m3_content: {len(m3)} chars")

    m3_charts = final_state.get("m3_charts")
    if m3_charts is None:
        print("  [PASS] m3_charts: None/ausente (noop para business)")
    elif isinstance(m3_charts, list) and len(m3_charts) == 0:
        print("  [PASS] m3_charts: [] (noop para business)")
    else:
        print(f"  [INFO] m3_charts: {len(m3_charts)} charts (inesperado para business, no es error)")

    required_state = ["m4_content", "m5_content", "doc3_teaching_note"]
    for field in required_state:
        val = final_state.get(field, "")
        val_str = str(val) if val else ""
        if not val_str:
            errors.append(f"[FAIL] {field} ausente")
        elif val_str.startswith("?") or val_str.startswith("ERROR:"):
            errors.append(f"[FAIL] {field} contiene error: {val_str[:100]!r}")
        else:
            _record_generation_errors(errors, field, val_str)
            print(f"  [PASS] {field}: {len(val_str)} chars")

    for nb_field in ("m3_notebook_code", "doc6_notebook"):
        nb_val = final_state.get(nb_field, "")
        if nb_val and len(nb_val) > 10:
            errors.append(f"[FAIL] {nb_field} presente en business profile ({len(nb_val)} chars) - solo ml_ds genera notebook")
        else:
            print(f"  [PASS] {nb_field}: ausente (correcto para business)")

    m3_mode = final_state.get("m3_mode")
    if m3_mode != "audit":
        errors.append(f"[FAIL] m3_mode={m3_mode!r}, esperado 'audit' para business")
    else:
        print(f"  [PASS] m3_mode: {m3_mode!r}")

    m3_questions = final_state.get("m3_questions", [])
    if m3_questions:
        valid_refs = {"3.1", "3.2", "3.3", "3.4", "3.5"}
        bad_refs = [
            q.get("m3_section_ref")
            for q in m3_questions
            if isinstance(q, dict) and q.get("m3_section_ref") not in valid_refs
        ]
        if bad_refs:
            errors.append(f"[FAIL] m3_questions contiene m3_section_ref invalidos (esperado 3.1-3.5): {bad_refs}")
        else:
            print(f"  [PASS] m3_questions: {len(m3_questions)} preguntas con refs 3.x correctas")
    else:
        print("  [WARN] m3_questions: vacio o ausente (puede ser error upstream)")

    canonical = final_state.get("canonical_output", {})
    content = canonical.get("content", {})
    for key in CONTENT_KEYS_REQUIRED:
        if key not in content:
            errors.append(f"[FAIL] canonical_output.content falta clave: {key}")
        else:
            _record_generation_errors(errors, key, content[key])
            print(f"  [PASS] content[{key!r}]: {safe_preview(content[key])}...")

    od = final_state.get("output_depth")
    if od != "visual_plus_technical":
        errors.append(f"[FAIL] output_depth={od!r}, esperado 'visual_plus_technical'")
    else:
        print(f"  [PASS] output_depth: {od!r}")

    print("\n" + "=" * 60)
    assert not errors, "\n".join(errors)
    print("T2 RESULTADO: PASS")
    print("  Route harvard_with_eda verificado: eda_flow -> m3_flow -> m4_flow.")
    print("  EDA, M3, M4, M5, Teaching Note y Resolution Report generados.")
    print("  Sentinels correctamente ausentes en m4_content.")
    print("=" * 60)

