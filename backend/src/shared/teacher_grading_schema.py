from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final, Literal

from pydantic import Field, field_serializer, model_validator

from shared.teacher_gradebook_schema import StrictModel

RubricLevel = Literal["excelente", "bien", "aceptable", "insuficiente", "no_responde"]
GradedBy = Literal["human", "ai", "hybrid"]
FeedbackSource = Literal["human", "ai_suggested", "ai_edited_by_human"]
PublicationState = Literal["draft", "published"]
Intent = Literal["save_draft", "publish"]
GradeModuleId = Literal["M1", "M2", "M3", "M4", "M5"]

RUBRIC_TO_SCORE: Final[dict[RubricLevel, float]] = {
    "excelente": 1.0,
    "bien": 0.8,
    "aceptable": 0.6,
    "insuficiente": 0.3,
    "no_responde": 0.0,
}


class TeacherGradeQuestionPayload(StrictModel):
    question_id: str
    rubric_level: RubricLevel | None = None
    feedback_question: str | None = Field(default=None, max_length=2000)
    source: FeedbackSource = "human"


class TeacherGradeModulePayload(StrictModel):
    module_id: GradeModuleId
    weight: Decimal = Field(ge=0, le=1)
    feedback_module: str | None = Field(default=None, max_length=2000)
    source: FeedbackSource = "human"
    questions: list[TeacherGradeQuestionPayload]

    @field_serializer("weight", when_used="json")
    def _serialize_weight(self, value: Decimal) -> float:
        return float(value)


class TeacherGradeRequestBody(StrictModel):
    payload_version: Literal[1] = 1
    snapshot_hash: str
    intent: Intent
    modules: list[TeacherGradeModulePayload]
    feedback_global: str | None = Field(default=None, max_length=4000)
    graded_by: GradedBy = "human"

    @model_validator(mode="after")
    def _validate_weight_sum(self) -> "TeacherGradeRequestBody":
        if not self.modules:
            return self

        total_weight = sum(module.weight for module in self.modules)
        if abs(total_weight - Decimal("1.0")) > Decimal("0.001"):
            raise ValueError("module weights must sum to 1.0")

        module_ids = [module.module_id for module in self.modules]
        if len(set(module_ids)) != len(module_ids):
            raise ValueError("module_ids must be unique")

        return self


class TeacherGradeQuestionResponse(StrictModel):
    question_id: str
    rubric_level: RubricLevel | None = None
    feedback_question: str | None = Field(default=None, max_length=2000)


class TeacherGradeModuleResponse(StrictModel):
    module_id: GradeModuleId
    weight: Decimal = Field(ge=0, le=1)
    feedback_module: str | None = Field(default=None, max_length=2000)
    questions: list[TeacherGradeQuestionResponse]

    @field_serializer("weight", when_used="json")
    def _serialize_weight(self, value: Decimal) -> float:
        return float(value)


class TeacherGradeResponse(StrictModel):
    payload_version: Literal[1] = 1
    snapshot_hash: str
    publication_state: PublicationState
    version: int = Field(ge=1)
    score_normalized: float | None = Field(default=None, ge=0, le=1)
    score_display: Decimal | None = Field(default=None, ge=0)
    max_score_display: Decimal = Field(default=Decimal("5.0"), ge=0)
    modules: list[TeacherGradeModuleResponse]
    feedback_global: str | None = Field(default=None, max_length=4000)
    graded_at: datetime | None = None
    published_at: datetime | None = None
    last_modified_at: datetime
    graded_by: GradedBy = "human"

    @field_serializer("score_display", "max_score_display", when_used="json")
    def _serialize_decimals(self, value: Decimal | None) -> float | None:
        if value is None:
            return None
        return float(value)