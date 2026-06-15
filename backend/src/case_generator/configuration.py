"""Runtime configuration for the case-generation graph.

Holds the per-tier model defaults (``architect_model`` / ``writer_model``) and the
per-node override map used for eval-gated downgrades and cost canaries. See
``resolve_node_model`` for the resolution order.
"""

import json
import logging
import os
from typing import Any

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

logger = logging.getLogger("adam.configuration")

# ── Canonical node names for per-node model routing ─────
# These are the keys accepted by ``node_model_overrides`` and the ``current_agent``
# / cost-attribution tags. Keep them in sync with the node functions in graph.py.
NODE_CASE_ARCHITECT = "case_architect"
NODE_SCHEMA_DESIGNER = "schema_designer"
NODE_M3_CONTENT = "m3_content_generator"
NODE_M3_NOTEBOOK = "m3_notebook_generator"
NODE_M4_CONTENT = "m4_content_generator"
NODE_M5_CONTENT = "m5_content_generator"
NODE_M5_QUESTIONS = "m5_questions_generator"


class Configuration(BaseModel):
    """Configuración del sistema ADAM — pipeline con modelos diferenciados.

    architect_model  → case_architect (razonamiento complejo, verificación numérica)
    writer_model     → case_writer, case_questions, eda_text_analyst,
                       eda_chart_generator, eda_questions_generator
    """

    architect_model: str = Field(
        default="gemini-3.1-pro-preview",
        json_schema_extra={
            "description": (
                "Modelo Pro para el case_architect. "
                "Maneja diseño del caso, coherencia numérica de los Exhibits "
                "y ejecución de código Python para validar cálculos."
            )
        },
    )

    writer_model: str = Field(
        default="gemini-3-flash-preview",
        json_schema_extra={
            "description": (
                "Modelo Flash para redacción larga (case_writer), "
                "generación de preguntas y pipeline EDA. "
                "Recibe contexto ya preparado por el architect."
            )
        },
    )

    node_model_overrides: dict[str, str] = Field(
        default_factory=dict,
        json_schema_extra={
            "description": (
                "Override de modelo por-nodo. Llave = nombre de nodo (ver NODE_* "
                "constants), valor = model id. Vacío por defecto: cada nodo usa su "
                "tier baseline (architect_model/writer_model). Permite canary por "
                "% de casos vía run_config sin redeploy y revertir un solo nodo."
            )
        },
    )

    @classmethod
    def from_runnable_config(
        cls, config: RunnableConfig | None = None
    ) -> "Configuration":
        """Create a Configuration instance from a RunnableConfig.

        Precedence per field: env var (UPPER_SNAKE) > run_config["configurable"] >
        field default. ``node_model_overrides`` additionally accepts a JSON string
        from its env var (``NODE_MODEL_OVERRIDES``); a malformed value degrades to
        the configurable/default value instead of raising.
        """
        configurable = (
            config["configurable"] if config and "configurable" in config else {}
        )
        raw_values: dict[str, Any] = {
            name: os.environ.get(name.upper(), configurable.get(name))
            for name in cls.model_fields.keys()
        }
        # node_model_overrides may arrive as a JSON string via env; parse defensively.
        override_raw = raw_values.get("node_model_overrides")
        if isinstance(override_raw, str):
            try:
                raw_values["node_model_overrides"] = json.loads(override_raw)
            except (ValueError, TypeError):
                logger.warning(
                    "Configuration: NODE_MODEL_OVERRIDES is not valid JSON — ignoring"
                )
                raw_values["node_model_overrides"] = configurable.get("node_model_overrides")
        values = {k: v for k, v in raw_values.items() if v is not None}
        return cls(**values)


def resolve_node_model(cfg: "Configuration", node_name: str, default: str) -> str:
    """Resolve the model id for a graph node.

    Decision tree::

        node_model_overrides has node_name?
          ├─ yes → use the override (canary / per-node rollback / eval-gated downgrade)
          └─ no  → use ``default`` (the node's baseline tier: architect_model or writer_model)

    The ``default`` is supplied by each call site so the node's *committed* tier
    stays explicit in graph.py while remaining overridable without a redeploy.

    Tolerant of cfg-like objects (e.g. test doubles) that lack the attribute.
    """
    overrides = getattr(cfg, "node_model_overrides", None) or {}
    return overrides.get(node_name, default)
