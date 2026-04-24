from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from shared.syllabus_schema import TeacherCourseConfigurationResponse


class CourseAccessLinkRegenerateResponse(BaseModel):
    course_id: str
    access_link: str
    access_link_status: Literal["active"]


class TeacherCourseAccessLinkResponse(TeacherCourseConfigurationResponse):
    course_id: str