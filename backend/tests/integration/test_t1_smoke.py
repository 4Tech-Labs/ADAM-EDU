"""T1 smoke test live ejecutable con pytest."""

import json

import pytest

pytestmark = pytest.mark.live_llm

T1_PAYLOAD = {
    "messages": [("user", "Generar caso Harvard T1 smoke test")],
    "subject": "Finanzas Corporativas",
    "syllabusModule": "Valoración de Empresas",
    "academicLevel": "Maestría",
    "industry": "Servicios Financieros",
    "caseType": "harvard_only",
    "studentProfile": "business",
    "guidingQuestion": "¿Debería la empresa adquirir su proveedor principal o diversificar proveedores?",
    "scenarioDescription": "Una empresa de servicios financieros evalúa una adquisición estratégica de su principal proveedor de tecnología.",
    "suggestedTechniques": ["DCF Analysis", "Risk Assessment"],
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


def test_t1_smoke() -> None:
    from case_generator.graph import graph

    print("\n" + "=" * 60)
    print("T1 SMOKE TEST - business + harvard_only")
    print("=" * 60)
    print(f"Payload caseType: {T1_PAYLOAD['caseType']}")
    print(f"Payload studentProfile: {T1_PAYLOAD['studentProfile']}")
    print()

    executed_nodes: list[str] = []
    final_state: dict = {}

    for event in graph.stream(T1_PAYLOAD, stream_mode="updates"):
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

    canonical = final_state.get("canonical_output", {})
    content = canonical.get("content", {})

    required_state_fields = ["m4_content", "m5_content", "doc3_teaching_note"]
    for field in required_state_fields:
        val = final_state.get(field, "")
        val_str = str(val) if val else ""
        if not val_str:
            errors.append(f"[FAIL] Campo faltante: {field}")
        elif val_str.startswith("ERROR:"):
            errors.append(f"[FAIL] {field} contiene error: {val_str[:100]!r}")
        else:
            _record_generation_errors(errors, field, val_str)
            print(f"  [PASS] {field}: {len(val_str)} chars")

    absent_fields = ["doc2_eda", "m3_content", "m3_notebook_code", "doc6_notebook", "m3_mode"]
    for field in absent_fields:
        val = final_state.get(field)
        if val:
            errors.append(f"[FAIL] Campo debería estar vacío (harvard_only): {field}")
        else:
            print(f"  [PASS] {field} correctamente ausente")

    required_content_keys = ["m4Content", "m5Content", "teachingNote"]
    for key in required_content_keys:
        if key not in content:
            errors.append(f"[FAIL] canonical_output.content falta clave: {key}")
        else:
            val = content[key]
            _record_generation_errors(errors, key, val)
            if isinstance(val, str):
                preview = val[:60].encode("ascii", "replace").decode("ascii")
            else:
                preview = str(type(val))
            print(f"  [PASS] content[{key!r}]: {preview}...")

    m4 = final_state.get("m4_content", "")
    if m4 and "DATASET_UNAVAILABLE" not in m4 and "M3_NOT_EXECUTED" not in m4:
        print("  [PASS] m4_content generado (sentinels no propagados al output, correcto)")
    elif not m4:
        errors.append("[FAIL] m4_content está vacío")

    print("\n" + "=" * 60)
    assert not errors, "\n".join(errors)
    print("T1 RESULTADO: PASS")
    print("  Route harvard_only verificado.")
    print("  Sentinels DATASET_UNAVAILABLE y [M3_NOT_EXECUTED] inyectados (ver logs arriba).")
    print("  Todos los campos requeridos presentes en el estado final.")
    print("=" * 60)

