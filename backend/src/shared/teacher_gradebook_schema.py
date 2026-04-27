from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class TeacherCourseGradebookCourse(StrictModel):
    id: str
    title: str
    code: str
    students_count: int = Field(ge=0)
    cases_count: int = Field(ge=0)
    average_score_scale: float = Field(gt=0)


class TeacherCourseGradebookCase(StrictModel):
    assignment_id: str
    title: str
    status: Literal["published"]
    available_from: datetime | None
    deadline: datetime | None
    max_score: float = Field(ge=0)


TeacherCourseGradebookStatus = Literal["not_started", "in_progress", "submitted", "graded"]


class TeacherCourseGradebookCell(StrictModel):
    assignment_id: str
    status: TeacherCourseGradebookStatus
    score: float | None = Field(default=None, ge=0)
    graded_at: datetime | None


class TeacherCourseGradebookStudent(StrictModel):
    membership_id: str
    full_name: str
    email: str
    enrolled_at: datetime
    average_score: float | None = Field(default=None, ge=0)
    grades: list[TeacherCourseGradebookCell]


class TeacherCourseGradebookResponse(StrictModel):
    course: TeacherCourseGradebookCourse
    cases: list[TeacherCourseGradebookCase]
    students: list[TeacherCourseGradebookStudent]


class TeacherCaseSubmissionRow(StrictModel):
    membership_id: str
    full_name: str
    email: str
    course_id: str
    course_code: str
    enrolled_at: datetime
    status: TeacherCourseGradebookStatus
    submitted_at: datetime | None
    score: float | None = Field(default=None, ge=0)
    max_score: float = Field(ge=0)
    graded_at: datetime | None


class TeacherCaseSubmissionsResponse(StrictModel):
    case: TeacherCourseGradebookCase
    submissions: list[TeacherCaseSubmissionRow]


class TeacherCaseSubmissionDetailQuestion(StrictModel):
    id: str
    order: int = Field(ge=1)
    statement: str
    context: str | None = None
    expected_solution: str
    student_answer: str | None = None
    student_answer_chars: int = Field(ge=0)
    is_answer_from_draft: bool


class TeacherCaseSubmissionDetailModule(StrictModel):
    id: Literal["M1", "M2", "M3", "M4", "M5"]
    title: str
    questions: list[TeacherCaseSubmissionDetailQuestion]


class TeacherCaseSubmissionDetailCase(StrictModel):
    id: str
    title: str
    deadline: datetime | None
    available_from: datetime | None
    course_id: str
    course_code: str
    course_name: str
    teaching_note: str | None = None


class TeacherCaseSubmissionDetailStudent(StrictModel):
    membership_id: str
    full_name: str
    email: str
    enrolled_at: datetime


class TeacherCaseSubmissionDetailResponseState(StrictModel):
    status: TeacherCourseGradebookStatus
    first_opened_at: datetime | None
    last_autosaved_at: datetime | None
    submitted_at: datetime | None
    snapshot_id: str | None = None
    snapshot_hash: str | None = None


class TeacherCaseSubmissionDetailGradeSummary(StrictModel):
    status: Literal["in_progress", "submitted", "graded"] | None = None
    score: Decimal | None = None
    max_score: Decimal = Field(ge=0)
    graded_at: datetime | None = None

    @field_serializer("score", "max_score", when_used="json")
    def _serialize_decimals(self, value: Decimal | None) -> float | None:
        if value is None:
            return None
        return float(value)


class TeacherCaseSubmissionDetailResponse(StrictModel):
    payload_version: Literal[1] = 1
    case: TeacherCaseSubmissionDetailCase
    student: TeacherCaseSubmissionDetailStudent
    response_state: TeacherCaseSubmissionDetailResponseState
    grade_summary: TeacherCaseSubmissionDetailGradeSummary
    modules: list[TeacherCaseSubmissionDetailModule]