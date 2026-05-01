from __future__ import annotations

from copy import deepcopy
from typing import Any


_ALLOWED_ROOT_FIELDS = (
    "caseId",
    "title",
    "subject",
    "syllabusModule",
    "guidingQuestion",
    "industry",
    "academicLevel",
    "caseType",
    "edaDepth",
    "studentProfile",
    "generatedAt",
    "outputDepth",
)

_ALLOWED_CONTENT_FIELDS = (
    "instructions",
    "preguntaEje",
    "narrative",
    "financialExhibit",
    "operatingExhibit",
    "stakeholdersExhibit",
    "edaReport",
    "edaCharts",
    "datasetRows",
    "doc7Dataset",
    "m3NotebookCode",
    "m3Content",
    "m3Charts",
    "m4Content",
    "m4Charts",
    "m5Content",
)

_TEACHER_ALLOWED_CONTENT_FIELDS = _ALLOWED_CONTENT_FIELDS + (
    "m5QuestionsSolutions",
    "teachingNote",
)

_QUESTION_FIELD_WHITELIST = (
    "numero",
    "titulo",
    "enunciado",
    "bloom_level",
    "m3_section_ref",
    "m4_section_ref",
    "modules_integrated",
    "is_solucion_docente_only",
    "chart_ref",
    "exhibit_ref",
    "task_type",
)

_TEACHER_QUESTION_FIELD_WHITELIST = _QUESTION_FIELD_WHITELIST + (
    "solucion_esperada",
    "rubric",
)

_QUESTION_ARRAY_FIELDS = (
    "caseQuestions",
    "edaQuestions",
    "m3Questions",
    "m4Questions",
    "m5Questions",
)


def _project_question(
    question: Any,
    *,
    question_field_whitelist: tuple[str, ...],
) -> dict[str, Any] | None:
    if not isinstance(question, dict):
        return None
    projected = {
        field: deepcopy(question[field])
        for field in question_field_whitelist
        if field in question
    }
    return projected or None


def _project_question_array(
    value: Any,
    *,
    question_field_whitelist: tuple[str, ...],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    projected_items: list[dict[str, Any]] = []
    for item in value:
        projected = _project_question(
            item,
            question_field_whitelist=question_field_whitelist,
        )
        if projected is not None:
            projected_items.append(projected)
    return projected_items


def _sanitize_canonical_output(
    canonical_output: dict[str, Any],
    *,
    allowed_content_fields: tuple[str, ...],
    question_field_whitelist: tuple[str, ...],
) -> dict[str, Any]:
    sanitized: dict[str, Any] = {
        field: deepcopy(canonical_output[field])
        for field in _ALLOWED_ROOT_FIELDS
        if field in canonical_output
    }

    content = canonical_output.get("content")
    sanitized_content: dict[str, Any] = {}
    if isinstance(content, dict):
        for field in allowed_content_fields:
            if field in content:
                if field != "m5QuestionsSolutions":
                    sanitized_content[field] = deepcopy(content[field])

        for field in _QUESTION_ARRAY_FIELDS:
            if field in content:
                sanitized_content[field] = _project_question_array(
                    content[field],
                    question_field_whitelist=question_field_whitelist,
                )

        if "m5QuestionsSolutions" in allowed_content_fields and "m5QuestionsSolutions" in content:
            sanitized_content["m5QuestionsSolutions"] = _project_question_array(
                content["m5QuestionsSolutions"],
                question_field_whitelist=question_field_whitelist,
            )

    sanitized["content"] = sanitized_content
    return sanitized


def sanitize_canonical_output_for_student(
    canonical_output: dict[str, Any],
) -> dict[str, Any]:
    """
    Strip teacher-only fields from canonical output before exposing it to students.

    Pipeline:
        canonical_output
            -> copy allowed root fields
            -> whitelist allowed content scalars
            -> project question arrays field-by-field
            -> omit teacher-only branches

    Removed:
      - content.caseQuestions[*].solucion_esperada
      - content.edaQuestions[*].solucion_esperada
      - content.m3Questions[*].solucion_esperada
      - content.m4Questions[*].solucion_esperada
      - content.m5Questions[*].solucion_esperada
      - content.m5QuestionsSolutions
      - content.teachingNote
    """
    return _sanitize_canonical_output(
        canonical_output,
        allowed_content_fields=_ALLOWED_CONTENT_FIELDS,
        question_field_whitelist=_QUESTION_FIELD_WHITELIST,
    )


def build_teacher_case_review_payload(
    canonical_output: dict[str, Any],
) -> dict[str, Any]:
    """
    Whitelist canonical_output fields safe to expose to a teacher reviewing a submission.

    Exposes:
      - content.{caseQuestions, edaQuestions, m3Questions, m4Questions, m5Questions}
        with student-visible pedagogical fields plus `solucion_esperada`.
      - content.m5QuestionsSolutions for teacher review flows.
      - content.teachingNote.

    Omits:
      - Raw authoring telemetry, prompts, job ids, validation traces, debug logs,
        and any other keys outside the explicit whitelist.
    """
    return _sanitize_canonical_output(
        canonical_output,
        allowed_content_fields=_TEACHER_ALLOWED_CONTENT_FIELDS,
        question_field_whitelist=_TEACHER_QUESTION_FIELD_WHITELIST,
    )