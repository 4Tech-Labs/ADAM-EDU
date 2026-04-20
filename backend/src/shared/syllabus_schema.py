from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SyllabusUnitPayload(StrictModel):
    unit_id: str
    title: str
    topics: str


class SyllabusModulePayload(StrictModel):
    module_id: str
    module_title: str
    weeks: str
    module_summary: str
    learning_outcomes: list[str]
    units: list[SyllabusUnitPayload]
    cross_course_connections: str


class EvaluationStrategyItemPayload(StrictModel):
    activity: str
    weight: float = Field(ge=0)
    linked_objectives: list[str]
    expected_outcome: str


class DidacticStrategyPayload(StrictModel):
    methodological_perspective: str
    pedagogical_modality: str


class TeacherSyllabusPayload(StrictModel):
    department: str
    knowledge_area: str
    nbc: str
    version_label: str
    academic_load: str
    course_description: str
    general_objective: str
    specific_objectives: list[str]
    modules: list[SyllabusModulePayload]
    evaluation_strategy: list[EvaluationStrategyItemPayload]
    didactic_strategy: DidacticStrategyPayload
    integrative_project: str
    bibliography: list[str]
    teacher_notes: str


class GroundingCourseIdentity(StrictModel):
    course_id: str
    course_title: str
    academic_level: str
    department: str
    knowledge_area: str
    nbc: str


class GroundingPedagogicalIntent(StrictModel):
    course_description: str
    general_objective: str
    specific_objectives: list[str]


class GroundingInstructionalScope(StrictModel):
    modules: list[SyllabusModulePayload]
    evaluation_strategy: list[EvaluationStrategyItemPayload]
    didactic_strategy: DidacticStrategyPayload


class GroundingGenerationHints(StrictModel):
    target_student_profile: str
    scenario_constraints: list[str]
    preferred_techniques: list[str]
    difficulty_signal: str
    forbidden_mismatches: list[str]


class GroundingMetadata(StrictModel):
    syllabus_revision: int = Field(ge=1)
    saved_at: datetime
    saved_by_membership_id: str


class SyllabusGroundingContext(StrictModel):
    course_identity: GroundingCourseIdentity
    pedagogical_intent: GroundingPedagogicalIntent
    instructional_scope: GroundingInstructionalScope
    generation_hints: GroundingGenerationHints
    metadata: GroundingMetadata


class TeacherSyllabusResponse(TeacherSyllabusPayload):
    ai_grounding_context: SyllabusGroundingContext


class TeacherSyllabusRevisionMetadataResponse(StrictModel):
    current_revision: int = Field(ge=0)
    saved_at: datetime | None
    saved_by_membership_id: str | None


class TeacherCourseInstitutionalResponse(StrictModel):
    id: str
    title: str
    code: str
    semester: str
    academic_level: str
    status: Literal["active", "inactive"]
    max_students: int
    students_count: int
    active_cases_count: int


class TeacherCourseConfigurationResponse(StrictModel):
    access_link_status: Literal["active", "missing"]
    access_link_id: str | None = None
    access_link_created_at: datetime | None = None
    join_path: str = "/app/join"


class TeacherCourseDetailResponse(StrictModel):
    course: TeacherCourseInstitutionalResponse
    syllabus: TeacherSyllabusResponse | None
    revision_metadata: TeacherSyllabusRevisionMetadataResponse
    configuration: TeacherCourseConfigurationResponse


class TeacherSyllabusSaveRequest(StrictModel):
    expected_revision: int = Field(ge=0)
    syllabus: TeacherSyllabusPayload


def derive_syllabus_grounding_context(
    *,
    course_id: str,
    course_title: str,
    academic_level: str,
    syllabus: TeacherSyllabusPayload,
    revision: int,
    saved_at: datetime,
    saved_by_membership_id: str,
) -> SyllabusGroundingContext:
    difficulty_signal = "foundational" if academic_level == "Pregrado" else "advanced"
    return SyllabusGroundingContext(
        course_identity=GroundingCourseIdentity(
            course_id=course_id,
            course_title=course_title,
            academic_level=academic_level,
            department=syllabus.department,
            knowledge_area=syllabus.knowledge_area,
            nbc=syllabus.nbc,
        ),
        pedagogical_intent=GroundingPedagogicalIntent(
            course_description=syllabus.course_description,
            general_objective=syllabus.general_objective,
            specific_objectives=list(syllabus.specific_objectives),
        ),
        instructional_scope=GroundingInstructionalScope(
            modules=list(syllabus.modules),
            evaluation_strategy=list(syllabus.evaluation_strategy),
            didactic_strategy=syllabus.didactic_strategy,
        ),
        generation_hints=GroundingGenerationHints(
            target_student_profile="",
            scenario_constraints=[],
            preferred_techniques=[],
            difficulty_signal=difficulty_signal,
            forbidden_mismatches=["No generar un caso que ignore el syllabus vigente del curso."],
        ),
        metadata=GroundingMetadata(
            syllabus_revision=revision,
            saved_at=saved_at,
            saved_by_membership_id=saved_by_membership_id,
        ),
    )