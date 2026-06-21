from __future__ import annotations

import concurrent.futures
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from shared.database import engine
from shared.models import (
    Assignment,
    CaseGrade,
    CaseQuestionGrade,
    StudentCaseResponse,
)
from shared.teacher_context import TeacherContext
from shared.teacher_gradebook_schema import TeacherQuestionGradeUpsertRequest
from shared.teacher_grading import upsert_question_grade

_REF_NOW = datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc)


def _auth_headers(auth_headers_factory, *, user_id: str, email: str) -> dict[str, str]:
    return auth_headers_factory(sub=user_id, email=email)


def _canonical(question_arrays: dict[str, list[dict]] | None = None) -> dict[str, object]:
    content: dict[str, object] = {
        "instructions": "Lee y responde.",
        "narrative": "Narrativa",
    }
    if question_arrays is None:
        question_arrays = {
            "caseQuestions": [{"numero": 1, "titulo": "P1", "enunciado": "E1", "solucion_esperada": "S1"}],
            "edaQuestions": [{"numero": 2, "titulo": "P2", "enunciado": "E2", "solucion_esperada": "S2"}],
            "m3Questions": [{"numero": 3, "titulo": "P3", "enunciado": "E3", "solucion_esperada": "S3"}],
            "m4Questions": [{"numero": 4, "titulo": "P4", "enunciado": "E4", "solucion_esperada": "S4"}],
            "m5Questions": [{"numero": 5, "titulo": "P5", "enunciado": "E5", "solucion_esperada": "S5"}],
        }
    content.update(question_arrays)
    return {
        "title": "Caso grading",
        "caseType": "harvard_with_eda",
        "studentProfile": "business",
        "content": content,
    }


def _seed_assignment(db, *, teacher_user_id: str, course_id: str, canonical: dict[str, object]) -> Assignment:
    assignment = Assignment(
        teacher_id=teacher_user_id,
        course_id=course_id,
        title="Assignment",
        canonical_output=canonical,
        status="published",
        available_from=_REF_NOW - timedelta(days=3),
        deadline=_REF_NOW + timedelta(days=7),
    )
    db.add(assignment)
    db.flush()
    return assignment


def _seed_response(db, *, membership_id: str, assignment_id: str, status: str) -> StudentCaseResponse:
    response = StudentCaseResponse(
        membership_id=membership_id,
        assignment_id=assignment_id,
        status=status,
        answers={},
        version=1,
        first_opened_at=_REF_NOW - timedelta(hours=4),
        last_autosaved_at=_REF_NOW - timedelta(hours=4),
        submitted_at=_REF_NOW - timedelta(hours=2) if status == "submitted" else None,
    )
    db.add(response)
    db.flush()
    return response


class _Fixture:
    def __init__(self, *, teacher, student, course, assignment, headers):
        self.teacher = teacher
        self.student = student
        self.course = course
        self.assignment = assignment
        self.headers = headers

    @property
    def membership_id(self) -> str:
        return self.student["membership"].id

    def url(self, question_id: str) -> str:
        return f"/api/teacher/cases/{self.assignment.id}/submissions/{self.membership_id}/questions/{question_id}/grade"


def _setup(
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
    *,
    university_id: str,
    response_status: str | None = "submitted",
    canonical: dict[str, object] | None = None,
    teacher_email: str = "teacher@example.edu",
) -> _Fixture:
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email=teacher_email,
        role="teacher",
        university_id=university_id,
    )
    student = seed_identity(
        user_id=str(uuid.uuid4()),
        email=f"student-{uuid.uuid4().hex[:8]}@example.edu",
        role="student",
        university_id=university_id,
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Curso",
        code=f"C-{uuid.uuid4().hex[:6]}",
    )
    seed_course_membership(course_id=course.id, membership_id=student["membership"].id)
    assignment = _seed_assignment(
        db,
        teacher_user_id=teacher["legacy_user"].id,
        course_id=course.id,
        canonical=canonical or _canonical(),
    )
    if response_status is not None:
        _seed_response(
            db,
            membership_id=student["membership"].id,
            assignment_id=assignment.id,
            status=response_status,
        )
    headers = _auth_headers(
        auth_headers_factory,
        user_id=teacher["legacy_user"].id,
        email=teacher["legacy_user"].email,
    )
    return _Fixture(teacher=teacher, student=student, course=course, assignment=assignment, headers=headers)


def _body(points: float, *, max_points: float = 10, feedback: str | None = None) -> dict[str, object]:
    return {"points_awarded": points, "max_points": max_points, "feedback": feedback}


# --------------------------------------------------------------------------- happy paths


def test_grade_one_question_partial_keeps_submitted_null(
    client, db, seed_identity, seed_course, seed_course_membership, auth_headers_factory
) -> None:
    fx = _setup(db, seed_identity, seed_course, seed_course_membership, auth_headers_factory,
                university_id=str(uuid.uuid4()))
    db.commit()

    resp = client.put(fx.url("M1-Q1"), json=_body(8, feedback="Bien"), headers=fx.headers)
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["grade"]["points_awarded"] == 8.0
    assert payload["grade"]["max_points"] == 10.0
    assert payload["grade"]["feedback"] == "Bien"
    assert payload["is_case_fully_graded"] is False
    assert payload["graded_question_count"] == 1
    assert payload["total_question_count"] == 5
    assert payload["grade_summary"]["status"] == "submitted"
    assert payload["grade_summary"]["score"] is None

    db.expire_all()
    grade = db.scalar(select(CaseGrade).where(CaseGrade.assignment_id == fx.assignment.id))
    assert grade is not None and grade.status == "submitted" and grade.score is None
    assert grade.max_score == __import__("decimal").Decimal("5.00")


def test_grade_all_questions_marks_graded_with_normalized_score(
    client, db, seed_identity, seed_course, seed_course_membership, auth_headers_factory
) -> None:
    fx = _setup(db, seed_identity, seed_course, seed_course_membership, auth_headers_factory,
                university_id=str(uuid.uuid4()))
    db.commit()

    points = {"M1-Q1": 10, "M2-Q2": 10, "M3-Q3": 5, "M4-Q4": 0, "M5-Q5": 5}
    last = None
    for qid, pts in points.items():
        last = client.put(fx.url(qid), json=_body(pts), headers=fx.headers)
        assert last.status_code == 200, last.text

    payload = last.json()
    assert payload["is_case_fully_graded"] is True
    assert payload["graded_question_count"] == 5
    # 30 / 50 * 5 = 3.0 on the 0-5 course scale
    assert payload["grade_summary"]["status"] == "graded"
    assert payload["grade_summary"]["score"] == 3.0
    assert payload["grade_summary"]["max_score"] == 5.0

    db.expire_all()
    grade = db.scalar(select(CaseGrade).where(CaseGrade.assignment_id == fx.assignment.id))
    assert grade.status == "graded" and grade.graded_at is not None
    assert grade.graded_by_membership_id == fx.teacher["membership"].id


def test_grade_rounds_normalized_score(
    client, db, seed_identity, seed_course, seed_course_membership, auth_headers_factory
) -> None:
    fx = _setup(db, seed_identity, seed_course, seed_course_membership, auth_headers_factory,
                university_id=str(uuid.uuid4()))
    db.commit()
    # 7/10 across 5 equal questions -> 35/50*5 = 3.5
    for qid in ["M1-Q1", "M2-Q2", "M3-Q3", "M4-Q4", "M5-Q5"]:
        client.put(fx.url(qid), json=_body(7), headers=fx.headers)
    detail = client.get(
        f"/api/teacher/cases/{fx.assignment.id}/submissions/{fx.membership_id}", headers=fx.headers
    ).json()
    assert detail["grade_summary"]["score"] == 3.5


# --------------------------------------------------------------------------- D1 gate


def test_grade_rejected_when_response_not_submitted(
    client, db, seed_identity, seed_course, seed_course_membership, auth_headers_factory
) -> None:
    fx = _setup(db, seed_identity, seed_course, seed_course_membership, auth_headers_factory,
                university_id=str(uuid.uuid4()), response_status="draft")
    db.commit()
    resp = client.put(fx.url("M1-Q1"), json=_body(5), headers=fx.headers)
    assert resp.status_code == 422
    assert resp.json()["detail"] == "response_not_submitted"
    db.expire_all()
    assert db.scalar(select(CaseQuestionGrade)) is None
    assert db.scalar(select(CaseGrade)) is None


def test_grade_rejected_when_no_response_exists(
    client, db, seed_identity, seed_course, seed_course_membership, auth_headers_factory
) -> None:
    fx = _setup(db, seed_identity, seed_course, seed_course_membership, auth_headers_factory,
                university_id=str(uuid.uuid4()), response_status=None)
    db.commit()
    resp = client.put(fx.url("M1-Q1"), json=_body(5), headers=fx.headers)
    assert resp.status_code == 422
    assert resp.json()["detail"] == "response_not_submitted"


# --------------------------------------------------------------------------- clear / revert (H4/H11/D2)


def test_clear_one_of_n_reverts_without_stale_graded_at(
    client, db, seed_identity, seed_course, seed_course_membership, auth_headers_factory
) -> None:
    fx = _setup(db, seed_identity, seed_course, seed_course_membership, auth_headers_factory,
                university_id=str(uuid.uuid4()))
    db.commit()
    qids = ["M1-Q1", "M2-Q2", "M3-Q3", "M4-Q4", "M5-Q5"]
    for qid in qids:
        client.put(fx.url(qid), json=_body(8), headers=fx.headers)

    # clear one -> reverts to submitted with NO stale graded_at/score
    cleared = client.delete(fx.url("M3-Q3"), headers=fx.headers)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["grade"] is None
    assert cleared.json()["grade_summary"]["status"] == "submitted"
    assert cleared.json()["grade_summary"]["score"] is None
    db.expire_all()
    grade = db.scalar(select(CaseGrade).where(CaseGrade.assignment_id == fx.assignment.id))
    assert grade.status == "submitted" and grade.score is None and grade.graded_at is None

    # re-grade it -> graded again
    re = client.put(fx.url("M3-Q3"), json=_body(8), headers=fx.headers)
    assert re.json()["grade_summary"]["status"] == "graded"


def test_clear_all_deletes_case_grade_row(
    client, db, seed_identity, seed_course, seed_course_membership, auth_headers_factory
) -> None:
    fx = _setup(db, seed_identity, seed_course, seed_course_membership, auth_headers_factory,
                university_id=str(uuid.uuid4()))
    db.commit()
    qids = ["M1-Q1", "M2-Q2", "M3-Q3", "M4-Q4", "M5-Q5"]
    for qid in qids:
        client.put(fx.url(qid), json=_body(8), headers=fx.headers)
    for qid in qids:
        client.delete(fx.url(qid), headers=fx.headers)

    db.expire_all()
    assert db.scalar(select(CaseGrade).where(CaseGrade.assignment_id == fx.assignment.id)) is None
    assert db.scalar(select(CaseQuestionGrade).where(CaseQuestionGrade.assignment_id == fx.assignment.id)) is None
    # gradebook/detail cell reverts to the student's real (submitted) state
    detail = client.get(
        f"/api/teacher/cases/{fx.assignment.id}/submissions/{fx.membership_id}", headers=fx.headers
    ).json()
    assert detail["grade_summary"]["status"] is None
    assert detail["response_state"]["status"] == "submitted"


def test_clear_nonexistent_is_idempotent(
    client, db, seed_identity, seed_course, seed_course_membership, auth_headers_factory
) -> None:
    fx = _setup(db, seed_identity, seed_course, seed_course_membership, auth_headers_factory,
                university_id=str(uuid.uuid4()))
    db.commit()
    resp = client.delete(fx.url("M1-Q1"), headers=fx.headers)
    assert resp.status_code == 200
    assert resp.json()["grade"] is None
    assert resp.json()["graded_question_count"] == 0


# --------------------------------------------------------------------------- validation


def test_invalid_question_id_rejected(
    client, db, seed_identity, seed_course, seed_course_membership, auth_headers_factory
) -> None:
    fx = _setup(db, seed_identity, seed_course, seed_course_membership, auth_headers_factory,
                university_id=str(uuid.uuid4()))
    db.commit()
    resp = client.put(fx.url("M9-Q9"), json=_body(5), headers=fx.headers)
    assert resp.status_code == 422
    assert resp.json()["detail"] == "invalid_question_id"
    db.expire_all()
    assert db.scalar(select(CaseQuestionGrade)) is None


def test_points_above_max_rejected(
    client, db, seed_identity, seed_course, seed_course_membership, auth_headers_factory
) -> None:
    fx = _setup(db, seed_identity, seed_course, seed_course_membership, auth_headers_factory,
                university_id=str(uuid.uuid4()))
    db.commit()
    resp = client.put(fx.url("M1-Q1"), json=_body(11, max_points=10), headers=fx.headers)
    assert resp.status_code == 422


def test_max_points_zero_rejected(
    client, db, seed_identity, seed_course, seed_course_membership, auth_headers_factory
) -> None:
    fx = _setup(db, seed_identity, seed_course, seed_course_membership, auth_headers_factory,
                university_id=str(uuid.uuid4()))
    db.commit()
    resp = client.put(fx.url("M1-Q1"), json=_body(0, max_points=0), headers=fx.headers)
    assert resp.status_code == 422


def test_case_with_no_gradeable_questions_rejected(
    client, db, seed_identity, seed_course, seed_course_membership, auth_headers_factory
) -> None:
    fx = _setup(db, seed_identity, seed_course, seed_course_membership, auth_headers_factory,
                university_id=str(uuid.uuid4()), canonical=_canonical(question_arrays={}))
    db.commit()
    resp = client.put(fx.url("M1-Q1"), json=_body(5), headers=fx.headers)
    assert resp.status_code == 422
    assert resp.json()["detail"] == "case_has_no_gradeable_questions"


def test_resave_is_idempotent_single_row(
    client, db, seed_identity, seed_course, seed_course_membership, auth_headers_factory
) -> None:
    fx = _setup(db, seed_identity, seed_course, seed_course_membership, auth_headers_factory,
                university_id=str(uuid.uuid4()))
    db.commit()
    client.put(fx.url("M1-Q1"), json=_body(5), headers=fx.headers)
    client.put(fx.url("M1-Q1"), json=_body(9, feedback="upd"), headers=fx.headers)
    db.expire_all()
    rows = db.scalars(
        select(CaseQuestionGrade).where(
            CaseQuestionGrade.assignment_id == fx.assignment.id,
            CaseQuestionGrade.question_id == "M1-Q1",
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].points_awarded == __import__("decimal").Decimal("9.00")
    assert rows[0].feedback == "upd"


# --------------------------------------------------------------------------- H1 duplicate numero


def test_duplicate_numero_uses_distinct_per_card_denominator(
    client, db, seed_identity, seed_course, seed_course_membership, auth_headers_factory
) -> None:
    # M3 has two questions both numero=3 -> they collapse to one gradeable id (M3-Q3).
    canonical = _canonical(question_arrays={
        "caseQuestions": [{"numero": 1, "titulo": "P1", "enunciado": "E1", "solucion_esperada": "S1"}],
        "m3Questions": [
            {"numero": 3, "titulo": "P3a", "enunciado": "E3a", "solucion_esperada": "S3a"},
            {"numero": 3, "titulo": "P3b", "enunciado": "E3b", "solucion_esperada": "S3b"},
        ],
    })
    fx = _setup(db, seed_identity, seed_course, seed_course_membership, auth_headers_factory,
                university_id=str(uuid.uuid4()), canonical=canonical)
    db.commit()
    # distinct gradeable ids: {M1-Q1, M3-Q3} -> total 2, no premature graded
    r1 = client.put(fx.url("M1-Q1"), json=_body(8), headers=fx.headers)
    assert r1.json()["total_question_count"] == 2
    assert r1.json()["is_case_fully_graded"] is False
    r2 = client.put(fx.url("M3-Q3"), json=_body(8), headers=fx.headers)
    assert r2.json()["is_case_fully_graded"] is True
    db.expire_all()
    rows = db.scalars(select(CaseQuestionGrade).where(CaseQuestionGrade.assignment_id == fx.assignment.id)).all()
    assert len(rows) == 2  # one row per distinct id, no silent merge beyond the shared id


# --------------------------------------------------------------------------- detail injection


def test_detail_returns_grade_per_question(
    client, db, seed_identity, seed_course, seed_course_membership, auth_headers_factory
) -> None:
    fx = _setup(db, seed_identity, seed_course, seed_course_membership, auth_headers_factory,
                university_id=str(uuid.uuid4()))
    db.commit()
    client.put(fx.url("M1-Q1"), json=_body(7, feedback="ok"), headers=fx.headers)
    detail = client.get(
        f"/api/teacher/cases/{fx.assignment.id}/submissions/{fx.membership_id}", headers=fx.headers
    ).json()
    by_id = {q["id"]: q for module in detail["modules"] for q in module["questions"]}
    assert by_id["M1-Q1"]["grade"]["points_awarded"] == 7.0
    assert by_id["M1-Q1"]["grade"]["feedback"] == "ok"
    assert by_id["M2-Q2"]["grade"] is None


def test_detail_view_survives_grade_load_failure(
    client, db, seed_identity, seed_course, seed_course_membership, auth_headers_factory, monkeypatch
) -> None:
    """If loading per-question grades fails (e.g. case_question_grades migration not yet applied),
    the submission-detail view must still return 200 WITHOUT grades — never 500."""
    fx = _setup(db, seed_identity, seed_course, seed_course_membership, auth_headers_factory,
                university_id=str(uuid.uuid4()))
    db.commit()

    def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated: relation case_question_grades does not exist")

    monkeypatch.setattr("shared.teacher_reads._load_question_grades_by_qid", _boom)

    resp = client.get(
        f"/api/teacher/cases/{fx.assignment.id}/submissions/{fx.membership_id}", headers=fx.headers
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    questions = [q for module in payload["modules"] for q in module["questions"]]
    assert questions  # the core view still renders the questions
    assert all(q["grade"] is None for q in questions)  # degraded cleanly: no grades, no 500


# --------------------------------------------------------------------------- IDOR (H10)


def test_idor_cross_teacher_put_and_delete_404_no_write(
    client, db, seed_identity, seed_course, seed_course_membership, auth_headers_factory
) -> None:
    university_id = str(uuid.uuid4())
    fx = _setup(db, seed_identity, seed_course, seed_course_membership, auth_headers_factory,
                university_id=university_id, teacher_email="owner@example.edu")
    other_teacher = seed_identity(
        user_id=str(uuid.uuid4()), email="intruder@example.edu", role="teacher", university_id=university_id
    )
    db.commit()
    intruder_headers = _auth_headers(
        auth_headers_factory, user_id=other_teacher["legacy_user"].id, email="intruder@example.edu"
    )
    put_resp = client.put(fx.url("M1-Q1"), json=_body(5), headers=intruder_headers)
    assert put_resp.status_code == 404
    del_resp = client.delete(fx.url("M1-Q1"), headers=intruder_headers)
    assert del_resp.status_code == 404
    db.expire_all()
    assert db.scalar(select(CaseQuestionGrade)) is None
    assert db.scalar(select(CaseGrade)) is None


# --------------------------------------------------------------------------- concurrency (H3)
#
# Driven at the SERVICE level with independent engine-bound sessions (one per thread) so the
# UNIQUE collision and SELECT ... FOR UPDATE blocking actually occur. The default transactional
# harness shares one connection (no real concurrency), so these carry shared_db_commit_visibility.

_SessionMaker = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def _context_for(fx: _Fixture, university_id: str) -> TeacherContext:
    return TeacherContext(
        auth_user_id=fx.teacher["legacy_user"].id,
        teacher_membership_id=fx.teacher["membership"].id,
        university_id=university_id,
    )


def _grade_via_service(ctx, assignment_id, membership_id, qid, barrier):
    session = _SessionMaker()
    try:
        barrier.wait()
        upsert_question_grade(
            session,
            ctx,
            assignment_id=assignment_id,
            membership_id=membership_id,
            question_id=qid,
            request=TeacherQuestionGradeUpsertRequest(
                points_awarded=Decimal("8"), max_points=Decimal("10"), feedback=None
            ),
        )
    finally:
        session.close()


@pytest.mark.shared_db_commit_visibility
def test_concurrent_first_grade_yields_single_case_grade_row(
    db, seed_identity, seed_course, seed_course_membership, auth_headers_factory
) -> None:
    university_id = str(uuid.uuid4())
    fx = _setup(db, seed_identity, seed_course, seed_course_membership, auth_headers_factory,
                university_id=university_id)
    db.commit()
    ctx = _context_for(fx, university_id)
    barrier = threading.Barrier(2)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(_grade_via_service, ctx, fx.assignment.id, fx.membership_id, "M1-Q1", barrier),
            executor.submit(_grade_via_service, ctx, fx.assignment.id, fx.membership_id, "M2-Q2", barrier),
        ]
        for future in concurrent.futures.as_completed(futures):
            future.result()  # re-raise any error

    db.expire_all()
    case_grades = db.scalars(select(CaseGrade).where(CaseGrade.assignment_id == fx.assignment.id)).all()
    assert len(case_grades) == 1
    question_grades = db.scalars(
        select(CaseQuestionGrade).where(CaseQuestionGrade.assignment_id == fx.assignment.id)
    ).all()
    assert len(question_grades) == 2


@pytest.mark.shared_db_commit_visibility
def test_concurrent_last_two_questions_reaches_graded(
    db, seed_identity, seed_course, seed_course_membership, auth_headers_factory
) -> None:
    university_id = str(uuid.uuid4())
    fx = _setup(db, seed_identity, seed_course, seed_course_membership, auth_headers_factory,
                university_id=university_id)
    db.commit()
    ctx = _context_for(fx, university_id)

    # grade 3 of 5 sequentially on a dedicated session, committed for cross-connection visibility
    seq_session = _SessionMaker()
    try:
        for qid in ["M1-Q1", "M2-Q2", "M3-Q3"]:
            upsert_question_grade(
                seq_session, ctx,
                assignment_id=fx.assignment.id, membership_id=fx.membership_id, question_id=qid,
                request=TeacherQuestionGradeUpsertRequest(points_awarded=Decimal("8"), max_points=Decimal("10"), feedback=None),
            )
    finally:
        seq_session.close()

    barrier = threading.Barrier(2)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(_grade_via_service, ctx, fx.assignment.id, fx.membership_id, "M4-Q4", barrier),
            executor.submit(_grade_via_service, ctx, fx.assignment.id, fx.membership_id, "M5-Q5", barrier),
        ]
        for future in concurrent.futures.as_completed(futures):
            future.result()

    db.expire_all()
    grade_row = db.scalar(select(CaseGrade).where(CaseGrade.assignment_id == fx.assignment.id))
    assert grade_row is not None and grade_row.status == "graded"
    assert grade_row.max_score == Decimal("5.00")
