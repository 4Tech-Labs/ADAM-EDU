from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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