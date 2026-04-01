"""Baseline E2E live test ejecutable con pytest."""

import asyncio
import json
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

pytestmark = pytest.mark.live_llm


def _truncate_canonical_output(payload: dict) -> dict:
    state_copy = payload.copy()
    for key, value in state_copy["content"].items():
        if isinstance(value, str) and len(value) > 50:
            state_copy["content"][key] = value[:50] + "..."
    return state_copy


async def _run_e2e_test() -> None:
    from case_generator.graph import master_builder

    memory = MemorySaver()
    graph = master_builder.compile(checkpointer=memory)
    config = {"configurable": {"thread_id": "test_e2e_thread_001"}}

    input_payload = {
        "messages": [("user", "Generar caso Harvard de prueba E2E")],
        "subject": "Supply Chain",
        "syllabusModule": "Logística Internacional",
        "academicLevel": "Maestría",
        "industry": "Retail Logistics",
        "caseType": "harvard_with_eda",
        "studentProfile": "business",
        "guidingQuestion": "¿Debería la empresa subcontratar su logística de última milla o invertir en flota propia?",
        "scenarioDescription": "Una empresa de retail evalúa su logística interna vs tercerizada.",
        "suggestedTechniques": ["Time Series", "Cost-Benefit Analysis"],
    }

    print("--- 1. INICIANDO GRAFO CON PAYLOAD CANONICO ---")
    print(json.dumps(input_payload, indent=2, ensure_ascii=False))

    try:
        async for event in graph.astream(input_payload, config=config):
            for node in event:
                print(f"-> Nodo completado: {node}")
    except BaseException as exc:
        print(f"Error o interrupción: {exc}")

    current_state = graph.get_state(config)
    current_values = getattr(current_state, "values", {})
    print("\n--- 2. ESTADO PAUSADO (HITL) ---")
    print(f"Next tasks: {current_state.next}")
    assert current_values.get("canonical_output"), "canonical_output no presente en el estado pausado"
    print(
        json.dumps(
            _truncate_canonical_output(current_values["canonical_output"]),
            indent=2,
            ensure_ascii=False,
        )
    )

    print("\n--- 3. REANUDANDO GRAFO (APROBANDO EDA) ---")
    try:
        async for event in graph.astream(Command(resume="approve"), config=config):
            for node in event:
                print(f"-> Nodo completado: {node}")
    except BaseException as exc:
        print(f"Error o interrupción: {exc}")

    final_state = graph.get_state(config)
    final_values = getattr(final_state, "values", {})
    print("\n--- 4. ESTADO FINAL (COMPLETO) ---")
    assert final_values.get("canonical_output"), "canonical_output no presente en el estado final"
    print(
        json.dumps(
            _truncate_canonical_output(final_values["canonical_output"]),
            indent=2,
            ensure_ascii=False,
        )
    )


def test_e2e_baseline() -> None:
    asyncio.run(_run_e2e_test())

