from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy import select

from shared.models import Assignment, AssignmentCourse, Membership
from shared.models import Syllabus, SyllabusRevision
from shared.syllabus_schema import TeacherSyllabusPayload, derive_syllabus_grounding_context


def _auth_headers(auth_headers_factory, *, user_id: str, email: str) -> dict[str, str]:
    return auth_headers_factory(sub=user_id, email=email)


def _syllabus_payload() -> dict[str, object]:
    return {
        "department": "Gestion de las Organizaciones",
        "knowledge_area": "Economia, Administracion, Contaduria y afines",
        "nbc": "Administracion",
        "version_label": "2026.1",
        "academic_load": "48 horas",
        "course_description": "Curso enfocado en estrategia y toma de decisiones en ecosistemas digitales.",
        "general_objective": "Aplicar marcos estrategicos a contextos empresariales complejos.",
        "specific_objectives": [
            "Analizar escenarios competitivos.",
            "Evaluar decisiones de crecimiento.",
        ],
        "modules": [
            {
                "module_id": "m1",
                "module_title": "Fundamentos de estrategia digital",
                "weeks": "1-3",
                "module_summary": "Panorama general de la estrategia en contextos digitales.",
                "learning_outcomes": ["Identificar drivers competitivos."],
                "units": [
                    {
                        "unit_id": "1.1",
                        "title": "Evolucion estrategica",
                        "topics": "Transformacion digital, ventaja competitiva, plataformas.",
                    }
                ],
                "cross_course_connections": "Conecta con innovacion y analitica.",
            }
        ],
        "evaluation_strategy": [
            {
                "activity": "Caso escrito",
                "weight": 40,
                "linked_objectives": ["O1"],
                "expected_outcome": "Analisis estructurado con recomendaciones.",
            }
        ],
        "didactic_strategy": {
            "methodological_perspective": "Aprendizaje basado en casos.",
            "pedagogical_modality": "Seminario presencial con talleres.",
        },
        "integrative_project": "Disenar una recomendacion estrategica para una empresa digital.",
        "bibliography": ["Porter - Competitive Strategy", "Ries - Lean Startup"],
        "teacher_notes": "Enfatizar diagnostico y consistencia argumentativa.",
    }


def _insert_syllabus(db, *, course, membership_id: str, payload: dict[str, object], revision: int = 1) -> Syllabus:
    validated_payload = TeacherSyllabusPayload.model_validate(payload)
    saved_at = datetime.now(timezone.utc)
    grounding = derive_syllabus_grounding_context(
        course_id=course.id,
        course_title=course.title,
        academic_level=course.academic_level,
        syllabus=validated_payload,
        revision=revision,
        saved_at=saved_at,
        saved_by_membership_id=membership_id,
    ).model_dump(mode="json")
    syllabus = Syllabus(
        course_id=course.id,
        revision=revision,
        department=validated_payload.department,
        knowledge_area=validated_payload.knowledge_area,
        nbc=validated_payload.nbc,
        version_label=validated_payload.version_label,
        academic_load=validated_payload.academic_load,
        course_description=validated_payload.course_description,
        general_objective=validated_payload.general_objective,
        specific_objectives=list(validated_payload.specific_objectives),
        modules=[module.model_dump(mode="json") for module in validated_payload.modules],
        evaluation_strategy=[item.model_dump(mode="json") for item in validated_payload.evaluation_strategy],
        didactic_strategy=validated_payload.didactic_strategy.model_dump(mode="json"),
        integrative_project=validated_payload.integrative_project,
        bibliography=list(validated_payload.bibliography),
        teacher_notes=validated_payload.teacher_notes,
        ai_grounding_context=grounding,
        saved_at=saved_at,
        saved_by_membership_id=membership_id,
    )
    db.add(syllabus)
    db.flush()
    db.add(
        SyllabusRevision(
            syllabus_id=syllabus.id,
            revision=revision,
            snapshot={
                **payload,
                "ai_grounding_context": grounding,
                "revision": revision,
                "saved_at": saved_at.isoformat(),
                "saved_by_membership_id": membership_id,
            },
            saved_at=saved_at,
            saved_by_membership_id=membership_id,
        )
    )
    db.flush()
    return syllabus


def test_issue88_teacher_courses_returns_assigned_courses_with_student_counts(
    client,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000881"
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-courses@example.edu"
    teacher = seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id=university_id,
        full_name="Teacher Courses",
    )
    course_b = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Zoologia Aplicada",
        code="BIO-220",
        status="inactive",
    )
    course_a = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Analisis de Casos",
        code="ADM-101",
    )
    active_student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="student-active@example.edu",
        role="student",
        university_id=university_id,
        full_name="Student Active",
    )
    suspended_student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="student-suspended@example.edu",
        role="student",
        university_id=university_id,
        full_name="Student Suspended",
        membership_status="suspended",
    )
    seed_course_membership(course_id=course_a.id, membership_id=active_student["membership"].id)
    seed_course_membership(course_id=course_a.id, membership_id=suspended_student["membership"].id)

    response = client.get(
        "/api/teacher/courses",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "courses": [
            {
                "id": course_a.id,
                "title": "Analisis de Casos",
                "code": "ADM-101",
                "semester": "2026-I",
                "academic_level": "Pregrado",
                "status": "active",
                "students_count": 1,
                "active_cases_count": 0,
            },
            {
                "id": course_b.id,
                "title": "Zoologia Aplicada",
                "code": "BIO-220",
                "semester": "2026-I",
                "academic_level": "Pregrado",
                "status": "inactive",
                "students_count": 0,
                "active_cases_count": 0,
            },
        ],
        "total": 2,
    }


def test_issue88_teacher_courses_counts_only_active_published_assignments_per_course(
    client,
    db,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000981"
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-course-counts@example.edu"
    teacher = seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id=university_id,
        full_name="Teacher Counts",
    )
    course_a = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Analitica Avanzada",
        code="AA-101",
    )
    course_b = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Business Strategy",
        code="BS-202",
    )
    reference_now = datetime.now(timezone.utc)
    db.add_all(
        [
            Assignment(
                teacher_id=teacher_user_id,
                course_id=course_a.id,
                title="Course A Active Future",
                status="published",
                deadline=reference_now + timedelta(days=3),
            ),
            Assignment(
                teacher_id=teacher_user_id,
                course_id=course_a.id,
                title="Course A Active Null Deadline",
                status="published",
                deadline=None,
            ),
            Assignment(
                teacher_id=teacher_user_id,
                course_id=course_a.id,
                title="Course A Draft",
                status="draft",
                deadline=reference_now + timedelta(days=5),
            ),
            Assignment(
                teacher_id=teacher_user_id,
                course_id=course_a.id,
                title="Course A Expired",
                status="published",
                deadline=reference_now - timedelta(minutes=1),
            ),
            Assignment(
                teacher_id=teacher_user_id,
                course_id=course_b.id,
                title="Course B Active Future",
                status="published",
                deadline=reference_now + timedelta(days=1),
            ),
            Assignment(
                teacher_id=teacher_user_id,
                course_id=None,
                title="Unassigned Published",
                status="published",
                deadline=reference_now + timedelta(days=2),
            ),
        ]
    )
    db.commit()

    response = client.get(
        "/api/teacher/courses",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )

    assert response.status_code == 200, response.text
    counts_by_course_id = {
        course["id"]: course["active_cases_count"]
        for course in response.json()["courses"]
    }
    assert counts_by_course_id == {
        course_a.id: 2,
        course_b.id: 1,
    }


def test_issue180_teacher_courses_counts_multi_course_targets(
    client,
    db,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000180"
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-multi-target-counts@example.edu"
    teacher = seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id=university_id,
        full_name="Teacher Multi Target Counts",
    )
    anchor_course = seed_course(
        university_id=teacher["membership"].university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Anchor Course",
        code="ANCH-101",
    )
    secondary_course = seed_course(
        university_id=teacher["membership"].university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Secondary Course",
        code="SEC-202",
    )

    db.add(
        Assignment(
            teacher_id=teacher_user_id,
            course_id=anchor_course.id,
            title="Multi Target Published",
            status="published",
            deadline=datetime.now(timezone.utc) + timedelta(days=1),
            assignment_courses=[
                AssignmentCourse(course_id=anchor_course.id),
                AssignmentCourse(course_id=secondary_course.id),
            ],
        )
    )
    db.commit()

    response = client.get(
        "/api/teacher/courses",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )

    assert response.status_code == 200, response.text
    counts_by_course_id = {
        course["id"]: course["active_cases_count"]
        for course in response.json()["courses"]
    }
    assert counts_by_course_id == {
        anchor_course.id: 1,
        secondary_course.id: 1,
    }


def test_issue88_teacher_courses_only_returns_authenticated_teacher_courses(
    client,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000882"
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-owned@example.edu",
        role="teacher",
        university_id=university_id,
        full_name="Teacher Owned",
    )
    other_teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-other@example.edu",
        role="teacher",
        university_id=university_id,
        full_name="Teacher Other",
    )
    owned_course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Owned Course",
        code="OWN-101",
    )
    seed_course(
        university_id=university_id,
        teacher_membership_id=other_teacher["membership"].id,
        title="Foreign Course",
        code="FOR-201",
    )

    response = client.get(
        "/api/teacher/courses",
        headers=_auth_headers(auth_headers_factory, user_id=teacher["profile"].id, email="teacher-owned@example.edu"),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "courses": [
            {
                "id": owned_course.id,
                "title": "Owned Course",
                "code": "OWN-101",
                "semester": "2026-I",
                "academic_level": "Pregrado",
                "status": "active",
                "students_count": 0,
                "active_cases_count": 0,
            }
        ],
        "total": 1,
    }


def test_issue88_teacher_courses_returns_empty_when_teacher_has_no_courses(
    client,
    seed_identity,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000883"
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-empty@example.edu"
    seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id=university_id,
        full_name="Teacher Empty",
    )

    response = client.get(
        "/api/teacher/courses",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"courses": [], "total": 0}


def test_issue88_teacher_courses_missing_token_returns_401(client) -> None:
    response = client.get("/api/teacher/courses")

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_token"


def test_issue88_teacher_courses_student_token_returns_403(
    client,
    seed_identity,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000884"
    student_user_id = str(uuid.uuid4())
    student_email = "student-only@example.edu"
    seed_identity(
        user_id=student_user_id,
        email=student_email,
        role="student",
        university_id=university_id,
        full_name="Student Only",
    )

    response = client.get(
        "/api/teacher/courses",
        headers=_auth_headers(auth_headers_factory, user_id=student_user_id, email=student_email),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "teacher_role_required"


def test_issue88_teacher_courses_admin_token_returns_403(
    client,
    seed_identity,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000885"
    admin_user_id = str(uuid.uuid4())
    admin_email = "admin-only@example.edu"
    seed_identity(
        user_id=admin_user_id,
        email=admin_email,
        role="university_admin",
        university_id=university_id,
        create_legacy_user=False,
        full_name="Admin Only",
    )

    response = client.get(
        "/api/teacher/courses",
        headers=_auth_headers(auth_headers_factory, user_id=admin_user_id, email=admin_email),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "teacher_role_required"


def test_issue88_teacher_courses_enforces_tenant_isolation(
    client,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_a = "10000000-0000-0000-0000-000000000886"
    university_b = "10000000-0000-0000-0000-000000000887"
    teacher_a_id = str(uuid.uuid4())
    teacher_a_email = "teacher-a@example.edu"
    teacher_a = seed_identity(
        user_id=teacher_a_id,
        email=teacher_a_email,
        role="teacher",
        university_id=university_a,
        full_name="Teacher A",
    )
    teacher_b = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-b@example.edu",
        role="teacher",
        university_id=university_b,
        full_name="Teacher B",
    )
    course_a = seed_course(
        university_id=university_a,
        teacher_membership_id=teacher_a["membership"].id,
        title="Course A",
        code="TA-101",
    )
    seed_course(
        university_id=university_b,
        teacher_membership_id=teacher_b["membership"].id,
        title="Course B",
        code="TB-101",
    )

    response = client.get(
        "/api/teacher/courses",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_a_id, email=teacher_a_email),
    )

    assert response.status_code == 200, response.text
    assert response.json()["courses"] == [
        {
            "id": course_a.id,
            "title": "Course A",
            "code": "TA-101",
            "semester": "2026-I",
            "academic_level": "Pregrado",
            "status": "active",
            "students_count": 0,
            "active_cases_count": 0,
        }
    ]


def test_issue88_teacher_courses_multiple_teacher_memberships_returns_409(
    client,
    db,
    seed_identity,
    auth_headers_factory,
) -> None:
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-multi@example.edu"
    seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000888",
        full_name="Teacher Multi",
    )
    seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000889",
        full_name="Teacher Multi",
        create_legacy_user=False,
    )

    response = client.get(
        "/api/teacher/courses",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "teacher_membership_context_required"

    memberships = db.scalars(
        db.query(Membership)
        .filter(Membership.user_id == teacher_user_id)
        .statement
    ).all()
    assert len(memberships) == 2


def test_issue88_teacher_course_detail_returns_composed_payload(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_access_link,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000890"
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-detail@example.edu"
    teacher = seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id=university_id,
        full_name="Teacher Detail",
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Gerencia Estrategica",
        code="ADM-330",
    )
    student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="student-detail@example.edu",
        role="student",
        university_id=university_id,
        full_name="Student Detail",
    )
    seed_course_membership(course_id=course.id, membership_id=student["membership"].id)
    access_link, raw_token = seed_course_access_link(course_id=course.id)
    _insert_syllabus(
        db,
        course=course,
        membership_id=teacher["membership"].id,
        payload=_syllabus_payload(),
    )

    response = client.get(
        f"/api/teacher/courses/{course.id}",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["course"] == {
        "id": course.id,
        "title": "Gerencia Estrategica",
        "code": "ADM-330",
        "semester": "2026-I",
        "academic_level": "Pregrado",
        "status": "active",
        "max_students": 30,
        "students_count": 1,
        "active_cases_count": 0,
    }
    assert payload["revision_metadata"]["current_revision"] == 1
    assert payload["revision_metadata"]["saved_by_membership_id"] == teacher["membership"].id
    assert payload["configuration"]["access_link_status"] == "active"
    assert payload["configuration"]["access_link_id"] == access_link.id
    assert payload["syllabus"]["department"] == "Gestion de las Organizaciones"
    assert payload["syllabus"]["ai_grounding_context"]["course_identity"] == {
        "course_id": course.id,
        "course_title": "Gerencia Estrategica",
        "academic_level": "Pregrado",
        "department": "Gestion de las Organizaciones",
        "knowledge_area": "Economia, Administracion, Contaduria y afines",
        "nbc": "Administracion",
    }
    assert payload["syllabus"]["ai_grounding_context"]["metadata"]["syllabus_revision"] == 1
    assert raw_token not in response.text


def test_issue88_teacher_course_detail_returns_active_case_count_for_owned_course(
    client,
    db,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000990"
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-detail-count@example.edu"
    teacher = seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id=university_id,
        full_name="Teacher Detail Count",
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Decision Science",
        code="DS-330",
    )
    _insert_syllabus(
        db,
        course=course,
        membership_id=teacher["membership"].id,
        payload=_syllabus_payload(),
    )
    reference_now = datetime.now(timezone.utc)
    db.add_all(
        [
            Assignment(
                teacher_id=teacher_user_id,
                course_id=course.id,
                title="Published Future",
                status="published",
                deadline=reference_now + timedelta(days=4),
            ),
            Assignment(
                teacher_id=teacher_user_id,
                course_id=course.id,
                title="Published No Deadline",
                status="published",
                deadline=None,
            ),
            Assignment(
                teacher_id=teacher_user_id,
                course_id=course.id,
                title="Draft Not Counted",
                status="draft",
                deadline=reference_now + timedelta(days=4),
            ),
            Assignment(
                teacher_id=teacher_user_id,
                course_id=course.id,
                title="Expired Not Counted",
                status="published",
                deadline=reference_now - timedelta(minutes=1),
            ),
        ]
    )
    db.commit()

    response = client.get(
        f"/api/teacher/courses/{course.id}",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )

    assert response.status_code == 200, response.text
    assert response.json()["course"]["active_cases_count"] == 2


def test_issue88_teacher_course_detail_student_token_returns_403(
    client,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000891"
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-detail-role@example.edu",
        role="teacher",
        university_id=university_id,
    )
    student_user_id = str(uuid.uuid4())
    student_email = "student-detail-role@example.edu"
    seed_identity(
        user_id=student_user_id,
        email=student_email,
        role="student",
        university_id=university_id,
    )
    course = seed_course(university_id=university_id, teacher_membership_id=teacher["membership"].id)

    response = client.get(
        f"/api/teacher/courses/{course.id}",
        headers=_auth_headers(auth_headers_factory, user_id=student_user_id, email=student_email),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "teacher_role_required"


def test_issue88_teacher_course_detail_admin_token_returns_403(
    client,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000892"
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-detail-admin@example.edu",
        role="teacher",
        university_id=university_id,
    )
    admin_user_id = str(uuid.uuid4())
    admin_email = "admin-detail@example.edu"
    seed_identity(
        user_id=admin_user_id,
        email=admin_email,
        role="university_admin",
        university_id=university_id,
        create_legacy_user=False,
    )
    course = seed_course(university_id=university_id, teacher_membership_id=teacher["membership"].id)

    response = client.get(
        f"/api/teacher/courses/{course.id}",
        headers=_auth_headers(auth_headers_factory, user_id=admin_user_id, email=admin_email),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "teacher_role_required"


def test_issue88_teacher_course_detail_non_owner_returns_404(
    client,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000893"
    owner = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-owner-detail@example.edu",
        role="teacher",
        university_id=university_id,
    )
    other_teacher_user_id = str(uuid.uuid4())
    other_teacher_email = "teacher-other-detail@example.edu"
    seed_identity(
        user_id=other_teacher_user_id,
        email=other_teacher_email,
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(university_id=university_id, teacher_membership_id=owner["membership"].id)

    response = client.get(
        f"/api/teacher/courses/{course.id}",
        headers=_auth_headers(auth_headers_factory, user_id=other_teacher_user_id, email=other_teacher_email),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "course_not_found"


def test_issue88_teacher_course_detail_enforces_tenant_isolation(
    client,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    owner = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-owner-tenant@example.edu",
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000894",
    )
    foreign_teacher_user_id = str(uuid.uuid4())
    foreign_teacher_email = "teacher-foreign-tenant@example.edu"
    seed_identity(
        user_id=foreign_teacher_user_id,
        email=foreign_teacher_email,
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000895",
    )
    course = seed_course(
        university_id="10000000-0000-0000-0000-000000000894",
        teacher_membership_id=owner["membership"].id,
    )

    response = client.get(
        f"/api/teacher/courses/{course.id}",
        headers=_auth_headers(auth_headers_factory, user_id=foreign_teacher_user_id, email=foreign_teacher_email),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "course_not_found"


def test_issue88_teacher_course_detail_multiple_teacher_memberships_returns_409(
    client,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-multi-detail@example.edu"
    first_teacher = seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000904",
        full_name="Teacher Multi Detail",
    )
    seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000905",
        full_name="Teacher Multi Detail",
        create_legacy_user=False,
    )
    course = seed_course(
        university_id="10000000-0000-0000-0000-000000000904",
        teacher_membership_id=first_teacher["membership"].id,
    )

    response = client.get(
        f"/api/teacher/courses/{course.id}",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "teacher_membership_context_required"


def test_issue88_teacher_course_syllabus_save_happy_path_creates_initial_syllabus(
    client,
    db,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000896"
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-save@example.edu"
    teacher = seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(university_id=university_id, teacher_membership_id=teacher["membership"].id)
    request_payload = {"expected_revision": 0, "syllabus": _syllabus_payload()}

    response = client.put(
        f"/api/teacher/courses/{course.id}/syllabus",
        json=request_payload,
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["revision_metadata"]["current_revision"] == 1
    assert payload["configuration"]["access_link_status"] == "missing"
    assert payload["syllabus"]["version_label"] == "2026.1"
    assert payload["syllabus"]["ai_grounding_context"]["metadata"]["saved_by_membership_id"] == teacher["membership"].id

    syllabus = db.scalar(select(Syllabus).where(Syllabus.course_id == course.id))
    revisions = db.scalars(
        select(SyllabusRevision)
        .where(SyllabusRevision.syllabus_id == syllabus.id)
        .order_by(SyllabusRevision.revision.asc())
    ).all()
    assert syllabus is not None
    assert syllabus.revision == 1
    assert syllabus.saved_by_membership_id == teacher["membership"].id
    assert len(revisions) == 1
    assert revisions[0].revision == 1
    assert revisions[0].snapshot["ai_grounding_context"]["metadata"]["syllabus_revision"] == 1


def test_issue88_teacher_course_syllabus_save_appends_revision_snapshots(
    client,
    db,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000897"
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-save-revisions@example.edu"
    teacher = seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(university_id=university_id, teacher_membership_id=teacher["membership"].id)

    first_payload = {"expected_revision": 0, "syllabus": _syllabus_payload()}
    first_response = client.put(
        f"/api/teacher/courses/{course.id}/syllabus",
        json=first_payload,
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )
    assert first_response.status_code == 200, first_response.text

    second_syllabus = deepcopy(_syllabus_payload())
    second_syllabus["version_label"] = "2026.2"
    second_syllabus["teacher_notes"] = "Actualizar conexiones interdisciplinarias."
    second_response = client.put(
        f"/api/teacher/courses/{course.id}/syllabus",
        json={"expected_revision": 1, "syllabus": second_syllabus},
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )

    assert second_response.status_code == 200, second_response.text
    payload = second_response.json()
    assert payload["revision_metadata"]["current_revision"] == 2
    assert payload["syllabus"]["version_label"] == "2026.2"
    assert payload["syllabus"]["teacher_notes"] == "Actualizar conexiones interdisciplinarias."
    assert payload["syllabus"]["ai_grounding_context"]["metadata"]["syllabus_revision"] == 2

    syllabus = db.scalar(select(Syllabus).where(Syllabus.course_id == course.id))
    revisions = db.scalars(
        select(SyllabusRevision)
        .where(SyllabusRevision.syllabus_id == syllabus.id)
        .order_by(SyllabusRevision.revision.asc())
    ).all()
    assert syllabus.revision == 2
    assert [revision.revision for revision in revisions] == [1, 2]
    assert revisions[0].snapshot["version_label"] == "2026.1"
    assert revisions[1].snapshot["version_label"] == "2026.2"


def test_issue88_teacher_course_syllabus_save_rejects_stale_revision(
    client,
    db,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000898"
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-stale@example.edu"
    teacher = seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(university_id=university_id, teacher_membership_id=teacher["membership"].id)
    _insert_syllabus(db, course=course, membership_id=teacher["membership"].id, payload=_syllabus_payload(), revision=1)

    response = client.put(
        f"/api/teacher/courses/{course.id}/syllabus",
        json={"expected_revision": 0, "syllabus": _syllabus_payload()},
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "stale_syllabus_revision"
    syllabus = db.scalar(select(Syllabus).where(Syllabus.course_id == course.id))
    revisions = db.scalars(select(SyllabusRevision).where(SyllabusRevision.syllabus_id == syllabus.id)).all()
    assert syllabus.revision == 1
    assert len(revisions) == 1


def test_issue88_teacher_course_syllabus_save_rejects_institutional_fields(
    client,
    db,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000899"
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-reject-fields@example.edu"
    teacher = seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(university_id=university_id, teacher_membership_id=teacher["membership"].id)
    invalid_payload = _syllabus_payload()
    invalid_payload["title"] = "Intento de editar campo institucional"

    response = client.put(
        f"/api/teacher/courses/{course.id}/syllabus",
        json={"expected_revision": 0, "syllabus": invalid_payload},
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )

    assert response.status_code == 422
    assert db.scalar(select(Syllabus).where(Syllabus.course_id == course.id)) is None


def test_issue88_teacher_course_syllabus_save_rejects_client_grounding_payload(
    client,
    db,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000900"
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-reject-grounding@example.edu"
    teacher = seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(university_id=university_id, teacher_membership_id=teacher["membership"].id)
    invalid_payload = _syllabus_payload()
    invalid_payload["ai_grounding_context"] = {"forged": True}

    response = client.put(
        f"/api/teacher/courses/{course.id}/syllabus",
        json={"expected_revision": 0, "syllabus": invalid_payload},
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )

    assert response.status_code == 422
    assert db.scalar(select(Syllabus).where(Syllabus.course_id == course.id)) is None


def test_issue88_teacher_course_syllabus_save_student_token_returns_403(
    client,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000901"
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-save-student@example.edu",
        role="teacher",
        university_id=university_id,
    )
    student_user_id = str(uuid.uuid4())
    student_email = "student-save@example.edu"
    seed_identity(
        user_id=student_user_id,
        email=student_email,
        role="student",
        university_id=university_id,
    )
    course = seed_course(university_id=university_id, teacher_membership_id=teacher["membership"].id)

    response = client.put(
        f"/api/teacher/courses/{course.id}/syllabus",
        json={"expected_revision": 0, "syllabus": _syllabus_payload()},
        headers=_auth_headers(auth_headers_factory, user_id=student_user_id, email=student_email),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "teacher_role_required"


def test_issue88_teacher_course_syllabus_save_admin_token_returns_403(
    client,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000902"
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-save-admin@example.edu",
        role="teacher",
        university_id=university_id,
    )
    admin_user_id = str(uuid.uuid4())
    admin_email = "admin-save@example.edu"
    seed_identity(
        user_id=admin_user_id,
        email=admin_email,
        role="university_admin",
        university_id=university_id,
        create_legacy_user=False,
    )
    course = seed_course(university_id=university_id, teacher_membership_id=teacher["membership"].id)

    response = client.put(
        f"/api/teacher/courses/{course.id}/syllabus",
        json={"expected_revision": 0, "syllabus": _syllabus_payload()},
        headers=_auth_headers(auth_headers_factory, user_id=admin_user_id, email=admin_email),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "teacher_role_required"


def test_issue88_teacher_course_syllabus_save_non_owner_returns_404(
    client,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000903"
    owner = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-owner-save@example.edu",
        role="teacher",
        university_id=university_id,
    )
    other_teacher_user_id = str(uuid.uuid4())
    other_teacher_email = "teacher-other-save@example.edu"
    seed_identity(
        user_id=other_teacher_user_id,
        email=other_teacher_email,
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(university_id=university_id, teacher_membership_id=owner["membership"].id)

    response = client.put(
        f"/api/teacher/courses/{course.id}/syllabus",
        json={"expected_revision": 0, "syllabus": _syllabus_payload()},
        headers=_auth_headers(auth_headers_factory, user_id=other_teacher_user_id, email=other_teacher_email),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "course_not_found"


def test_issue88_teacher_course_syllabus_save_enforces_tenant_isolation(
    client,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    owner = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-owner-save-tenant@example.edu",
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000906",
    )
    foreign_teacher_user_id = str(uuid.uuid4())
    foreign_teacher_email = "teacher-foreign-save-tenant@example.edu"
    seed_identity(
        user_id=foreign_teacher_user_id,
        email=foreign_teacher_email,
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000907",
    )
    course = seed_course(
        university_id="10000000-0000-0000-0000-000000000906",
        teacher_membership_id=owner["membership"].id,
    )

    response = client.put(
        f"/api/teacher/courses/{course.id}/syllabus",
        json={"expected_revision": 0, "syllabus": _syllabus_payload()},
        headers=_auth_headers(auth_headers_factory, user_id=foreign_teacher_user_id, email=foreign_teacher_email),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "course_not_found"


def test_issue88_teacher_course_syllabus_save_multiple_teacher_memberships_returns_409(
    client,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-multi-save@example.edu"
    first_teacher = seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000908",
        full_name="Teacher Multi Save",
    )
    seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000909",
        full_name="Teacher Multi Save",
        create_legacy_user=False,
    )
    course = seed_course(
        university_id="10000000-0000-0000-0000-000000000908",
        teacher_membership_id=first_teacher["membership"].id,
    )

    response = client.put(
        f"/api/teacher/courses/{course.id}/syllabus",
        json={"expected_revision": 0, "syllabus": _syllabus_payload()},
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "teacher_membership_context_required"
