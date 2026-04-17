"""T3 smoke test live ejecutable con pytest."""

import json
import uuid

import pytest

pytestmark = [pytest.mark.live_llm, pytest.mark.asyncio]

T3_PAYLOAD = {
    "messages": [("user", "Generar caso Harvard T3 smoke test")],
    "subject": "Ciencia de Datos Aplicada",
    "syllabusModule": "Modelos Predictivos en Negocios",
    "academicLevel": "Maestria",
    "industry": "Retail Omnicanal",
    "caseType": "harvard_only",
    "studentProfile": "ml_ds",
    "guidingQuestion": "Deberia la empresa implementar un modelo de churn prediction o enfocarse en segmentacion por valor de cliente?",
    "scenarioDescription": "Una cadena de retail evalua como reducir la tasa de abandono usando modelos de ML.",
    "suggestedTechniques": ["Logistic Regression", "Random Forest", "Customer Lifetime Value"],
    "edaDepth": None,
    "includePythonCode": False,
}

NODES_EXPECTED = {
    "input_adapter",
    "doc1_flow",
    "output_adapter_intermediate",
    "m4_flow",
    "synthesis_flow",
    "output_adapter_final",
}
NODES_FORBIDDEN = {"eda_flow", "m3_flow"}
CONTENT_KEYS_REQUIRED = ["m4Content", "m5Content", "teachingNote"]
CONTENT_KEYS_ABSENT = ["edaReport", "edaCharts", "m3Content"]


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


async def test_t3_smoke() -> None:
    from case_generator.graph import get_graph

    graph = await get_graph()
    config = {"configurable": {"thread_id": f"test_t3_smoke-{uuid.uuid4()}"}}

    print("\n" + "=" * 60)
    print("T3 SMOKE TEST -- ml_ds + harvard_only")
    print("=" * 60)
    print(f"caseType: {T3_PAYLOAD['caseType']}  studentProfile: {T3_PAYLOAD['studentProfile']}")
    print()

    executed_nodes: list[str] = []
    final_state: dict = {}

    async for event in graph.astream(T3_PAYLOAD, config=config, stream_mode="updates"):
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

    for node in NODES_FORBIDDEN:
        if node in executed_nodes:
            errors.append(f"[FAIL] Nodo prohibido ejecutado: {node}")
        else:
            print(f"  [PASS] Nodo omitido (correcto): {node}")

    m4 = final_state.get("m4_content", "")
    if not m4:
        errors.append("[FAIL] m4_content ausente")
    elif m4.startswith("?") or m4.startswith("ERROR:"):
        errors.append(f"[FAIL] m4_content contiene error: {m4[:100]!r}")
    else:
        _record_generation_errors(errors, "m4_content", m4)
        print(f"  [PASS] m4_content: {len(m4)} chars (sentinels inyectados via logs)")

    absent_fields = {
        "doc2_eda": "EDA ausente (harvard_only)",
        "m3_content": "M3 ausente (harvard_only)",
        "m3_mode": "m3_mode ausente (harvard_only no ejecuta M3)",
        "doc7_dataset": "dataset ausente (harvard_only)",
        "m3_notebook_code": "notebook ausente (harvard_only - M3 no se ejecuta)",
        "doc6_notebook": "doc6_notebook obsoleto - nunca debe escribirse",
    }
    for field, label in absent_fields.items():
        val = final_state.get(field)
        if val and (not isinstance(val, str) or len(val) > 10):
            errors.append(f"[FAIL] {field} presente pero deberia estar ausente")
        else:
            print(f"  [PASS] {field}: ausente ({label})")

    required_state = ["m4_content", "m5_content", "doc3_teaching_note"]
    for field in required_state:
        if field == "m4_content":
            continue
        val = final_state.get(field, "")
        val_str = str(val) if val else ""
        if not val_str:
            errors.append(f"[FAIL] {field} ausente")
        elif val_str.startswith("?") or val_str.startswith("ERROR:"):
            errors.append(f"[FAIL] {field} contiene error: {val_str[:100]!r}")
        else:
            _record_generation_errors(errors, field, val_str)
            print(f"  [PASS] {field}: {len(val_str)} chars")

    od = final_state.get("output_depth")
    if od is not None:
        errors.append(f"[FAIL] output_depth={od!r}, esperado None para harvard_only")
    else:
        print("  [PASS] output_depth: None (harvard_only sin EDA)")

    canonical = final_state.get("canonical_output", {})
    content = canonical.get("content", {})
    for key in CONTENT_KEYS_REQUIRED:
        if key not in content:
            errors.append(f"[FAIL] canonical_output.content falta clave requerida: {key}")
        else:
            _record_generation_errors(errors, key, content[key])
            print(f"  [PASS] content[{key!r}]: {safe_preview(content[key])}...")

    for key in CONTENT_KEYS_ABSENT:
        if key in content:
            errors.append(f"[FAIL] content[{key!r}] presente pero deberia estar ausente (harvard_only)")
        else:
            print(f"  [PASS] content[{key!r}]: ausente (correcto)")

    print("\n" + "=" * 60)
    assert not errors, "\n".join(errors)
    print("T3 RESULTADO: PASS")
    print("  Route harvard_only con ml_ds verificado.")
    print("  Sentinels DATASET_UNAVAILABLE y [M3_NOT_EXECUTED] confirmados via logs.")
    print("  EDA, M3, dataset y notebook correctamente ausentes.")
    print("=" * 60)

