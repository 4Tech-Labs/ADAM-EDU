import os
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field


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

    @classmethod
    def from_runnable_config(
        cls, config: Optional[RunnableConfig] = None
    ) -> "Configuration":
        """Create a Configuration instance from a RunnableConfig."""
        configurable = (
            config["configurable"] if config and "configurable" in config else {}
        )
        raw_values: dict[str, Any] = {
            name: os.environ.get(name.upper(), configurable.get(name))
            for name in cls.model_fields.keys()
        }
        values = {k: v for k, v in raw_values.items() if v is not None}
        return cls(**values)
