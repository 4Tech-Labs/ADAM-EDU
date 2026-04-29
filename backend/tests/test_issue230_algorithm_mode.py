"""Issue #230 — algorithm mode toggle (single | contrast).

Covers:
- ``classify_tier`` keyword routing
- ``get_algorithm_catalog`` shape + caching + invalid args
- ``_validate_techniques_strict`` contract (single, contrast, errors)
- ``GET /api/authoring/algorithm-catalog`` endpoint
- ``POST /api/authoring/jobs`` validation gate + ``task_payload`` shape
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from case_generator.suggest_service import (
    _validate_techniques_strict,
    classify_tier,
    get_algorithm_catalog,
)
from shared.database import SessionLocal
from shared.models import AuthoringJob


pytestmark = pytest.mark.shared_db_commit_visibility


# ──────────────────────────────────────────────────────────────────────────────
# Pure-unit: classify_tier
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "technique, expected",
    [
        ("Regresión Lineal + Ridge/Lasso + Residuals", "baseline"),
        ("Logistic Regression + Random Forest + SHAP", "challenger"),
        ("XGBoost con tuning de hiperparámetros", "challenger"),
        ("LSTM para series temporales", "challenger"),
        ("DBSCAN para detección de grupos atípicos", "challenger"),
        ("K-Means + Silhouette + PCA", "baseline"),
        ("Prophet con regresores externos", "challenger"),
        ("Scorecard de riesgo con reglas de negocio", "baseline"),
    ],
)
def test_classify_tier_keywords(technique: str, expected: str) -> None:
    assert classify_tier(technique) == expected


# ──────────────────────────────────────────────────────────────────────────────
# Pure-unit: get_algorithm_catalog
# ──────────────────────────────────────────────────────────────────────────────

def _items(profile: str) -> list[dict]:
    return get_algorithm_catalog(profile, "harvard_with_eda")["items"]


def _baselines_of(profile: str) -> list[dict]:
    return [it for it in _items(profile) if it["tier"] == "baseline"]


def _challengers_of(profile: str) -> list[dict]:
    return [it for it in _items(profile) if it["tier"] == "challenger"]


def test_catalog_business_harvard_with_eda_has_baseline() -> None:
    items = _items("business")
    assert items, "catalog must not be empty"
    assert _baselines_of("business"), "business must expose baselines"
    # Business profile may legitimately expose zero challengers.
    for it in items:
        assert set(it.keys()) == {"name", "family", "family_label", "tier"}


def test_catalog_ml_ds_exposes_challengers() -> None:
    baselines = _baselines_of("ml_ds")
    challengers = _challengers_of("ml_ds")
    assert baselines and challengers
    seen = {it["name"].lower() for it in baselines}
    for tech in challengers:
        assert tech["name"].lower() not in seen


def test_catalog_ml_ds_has_more_challengers_than_business() -> None:
    assert len(_challengers_of("ml_ds")) >= len(_challengers_of("business"))


def test_catalog_ml_ds_excludes_lstm() -> None:
    names = {it["name"].lower() for it in _items("ml_ds")}
    assert not any("lstm" in n for n in names), "LSTM was removed from the catalog (Issue #230 follow-up)"


def test_catalog_items_are_grouped_by_family() -> None:
    families = {it["family"] for it in _items("ml_ds")}
    # Issue #233 — canonical 4-family taxonomy. nlp/recomendacion deprecated.
    assert families == {"clasificacion", "regresion", "clustering", "serie_temporal"}
    # family_label is non-empty and human-readable.
    for it in _items("ml_ds"):
        assert it["family_label"] and isinstance(it["family_label"], str)


# Issue #233 — 4×2 catalog invariants.
def test_catalog_has_exactly_4_families() -> None:
    families = {it["family"] for it in _items("ml_ds")}
    assert families == {"clasificacion", "regresion", "clustering", "serie_temporal"}


def test_catalog_each_family_has_max_2_algorithms() -> None:
    items = _items("ml_ds")
    by_family: dict[str, list[dict]] = {}
    for it in items:
        by_family.setdefault(it["family"], []).append(it)
    for fam, members in by_family.items():
        assert len(members) <= 2, f"familia {fam} excede el cap de 2: {members}"


def test_catalog_each_family_has_exactly_one_baseline() -> None:
    items = _items("ml_ds")
    by_family: dict[str, list[dict]] = {}
    for it in items:
        by_family.setdefault(it["family"], []).append(it)
    for fam, members in by_family.items():
        baselines = [m for m in members if m["tier"] == "baseline"]
        assert len(baselines) == 1, f"familia {fam} debe tener 1 baseline: {members}"


def test_catalog_business_only_baselines() -> None:
    items = _items("business")
    assert items, "business debe exponer al menos los baselines"
    for it in items:
        assert it["tier"] == "baseline", f"business no debe ver challengers: {it}"
    families = {it["family"] for it in items}
    assert families == {"clasificacion", "regresion", "clustering", "serie_temporal"}


def test_catalog_ml_ds_has_8_algorithms() -> None:
    # 4 families × 2 tiers (baseline + challenger) = 8 entries for ml_ds.
    assert len(_items("ml_ds")) == 8


def test_catalog_no_legacy_algorithms_exposed() -> None:
    # Issue #233 — these names were removed from the canonical catalog.
    forbidden = {"xgboost", "ridge", "lasso", "lstm", "svm", "naive bayes"}
    names = {it["name"].lower() for it in _items("ml_ds")}
    assert names.isdisjoint(forbidden), f"algoritmos legacy reaparecieron: {names & forbidden}"


def test_catalog_invalid_profile_raises() -> None:
    with pytest.raises(ValueError, match="Invalid profile"):
        get_algorithm_catalog("teacher", "harvard_with_eda")


def test_catalog_invalid_case_type_raises() -> None:
    with pytest.raises(ValueError, match="Invalid case_type"):
        get_algorithm_catalog("business", "video_lecture")


def test_catalog_is_cached() -> None:
    a = get_algorithm_catalog("business", "harvard_with_eda")
    b = get_algorithm_catalog("business", "harvard_with_eda")
    assert a is b  # lru_cache returns the same object


# ──────────────────────────────────────────────────────────────────────────────
# Pure-unit: _validate_techniques_strict
# ──────────────────────────────────────────────────────────────────────────────

def _baseline(profile: str = "business") -> str:
    return _baselines_of(profile)[0]["name"]


def _challenger(profile: str = "ml_ds") -> str:
    # Return a challenger from the SAME family as ``_baseline(profile)`` so
    # tests that build a contrast pick stay valid under the family-coherence
    # rule. Falls back to the first challenger when the baseline family lacks one.
    base_family = _baselines_of(profile)[0]["family"]
    same_family = [it for it in _challengers_of(profile) if it["family"] == base_family]
    pool = same_family or _challengers_of(profile)
    return pool[0]["name"]


def test_validate_single_ok() -> None:
    _validate_techniques_strict(
        [_baseline()], profile="business", case_type="harvard_with_eda", mode="single"
    )


def test_validate_single_accepts_challenger_too() -> None:
    _validate_techniques_strict(
        [_challenger("ml_ds")], profile="ml_ds", case_type="harvard_with_eda", mode="single"
    )


def test_validate_single_empty_raises() -> None:
    with pytest.raises(ValueError, match="al menos un algoritmo"):
        _validate_techniques_strict(
            [], profile="business", case_type="harvard_with_eda", mode="single"
        )


def test_validate_single_too_many_raises() -> None:
    with pytest.raises(ValueError, match="exactamente 1 algoritmo"):
        _validate_techniques_strict(
            [_baseline(), _baseline()],
            profile="business",
            case_type="harvard_with_eda",
            mode="single",
        )


def test_validate_single_unknown_technique_raises() -> None:
    with pytest.raises(ValueError, match="fuera del catálogo"):
        _validate_techniques_strict(
            ["Algoritmo Inventado XYZ"],
            profile="business",
            case_type="harvard_with_eda",
            mode="single",
        )


def test_validate_contrast_ok_ml_ds() -> None:
    _validate_techniques_strict(
        [_baseline("ml_ds"), _challenger("ml_ds")],
        profile="ml_ds",
        case_type="harvard_with_eda",
        mode="contrast",
    )


def test_validate_contrast_requires_two() -> None:
    with pytest.raises(ValueError, match="exactamente 2 algoritmos"):
        _validate_techniques_strict(
            [_baseline("ml_ds")],
            profile="ml_ds",
            case_type="harvard_with_eda",
            mode="contrast",
        )


def test_validate_contrast_baseline_in_challenger_slot_raises() -> None:
    baselines = _baselines_of("ml_ds")
    with pytest.raises(ValueError, match="challenger"):
        _validate_techniques_strict(
            [baselines[0]["name"], baselines[1]["name"]],
            profile="ml_ds",
            case_type="harvard_with_eda",
            mode="contrast",
        )


def test_validate_contrast_cross_family_raises() -> None:
    """Issue #230 follow-up: baseline + challenger must share a family."""
    baselines = _baselines_of("ml_ds")
    challengers = _challengers_of("ml_ds")
    # Find a baseline + challenger from DIFFERENT families.
    cross_baseline = baselines[0]
    cross_challenger = next(
        (c for c in challengers if c["family"] != cross_baseline["family"]),
        None,
    )
    assert cross_challenger is not None, "need at least two families with challengers for this test"
    with pytest.raises(ValueError, match="misma familia"):
        _validate_techniques_strict(
            [cross_baseline["name"], cross_challenger["name"]],
            profile="ml_ds",
            case_type="harvard_with_eda",
            mode="contrast",
        )


def test_validate_contrast_same_algo_raises() -> None:
    pick = _baseline("ml_ds")
    with pytest.raises(ValueError, match="no pueden ser el mismo"):
        _validate_techniques_strict(
            [pick, pick],
            profile="ml_ds",
            case_type="harvard_with_eda",
            mode="contrast",
        )


def test_validate_contrast_challenger_in_primary_slot_raises() -> None:
    challenger = _challenger("ml_ds")
    baseline = _baseline("ml_ds")
    with pytest.raises(ValueError, match="primer algoritmo debe ser un baseline"):
        _validate_techniques_strict(
            [challenger, baseline],
            profile="ml_ds",
            case_type="harvard_with_eda",
            mode="contrast",
        )


# ──────────────────────────────────────────────────────────────────────────────
# Endpoint: GET /api/authoring/algorithm-catalog
# ──────────────────────────────────────────────────────────────────────────────

def test_algorithm_catalog_endpoint_ok(client) -> None:
    resp = client.get(
        "/api/authoring/algorithm-catalog",
        params={"profile": "ml_ds", "case_type": "harvard_with_eda"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["profile"] == "ml_ds"
    assert body["case_type"] == "harvard_with_eda"
    items = body["items"]
    assert isinstance(items, list) and items
    for it in items:
        assert set(it.keys()) == {"name", "family", "family_label", "tier"}
        assert it["tier"] in {"baseline", "challenger"}
    # No LSTM in the curated catalog.
    assert not any("lstm" in it["name"].lower() for it in items)


def test_algorithm_catalog_endpoint_invalid_profile_422(client) -> None:
    resp = client.get(
        "/api/authoring/algorithm-catalog",
        params={"profile": "teacher", "case_type": "harvard_with_eda"},
    )
    assert resp.status_code == 422


def test_algorithm_catalog_endpoint_missing_param_422(client) -> None:
    resp = client.get(
        "/api/authoring/algorithm-catalog",
        params={"profile": "ml_ds"},
    )
    assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────────────
# Intake: POST /api/authoring/jobs algorithm gate + task_payload shape
# ──────────────────────────────────────────────────────────────────────────────

def _intake_payload(course_id: str, **overrides) -> dict:
    payload = {
        "assignment_title": "Issue230 Test",
        "course_id": course_id,
        "syllabus_module": "m1",
        "topic_unit": "u1",
        "target_groups": ["Grupo 01"],
        "case_type": "harvard_with_eda",
        "student_profile": "business",
    }
    payload.update(overrides)
    return payload


def _seed_teacher_with_course(seed_identity, seed_course_with_syllabus, db):
    teacher_id = "00000000-0000-0000-0000-000000000230"
    teacher_email = "issue230teacher@example.edu"
    teacher = seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    course = seed_course_with_syllabus(
        university_id=teacher["membership"].university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Issue 230 Course",
    )
    db.commit()
    return teacher_id, teacher_email, course


def test_intake_eda_without_picks_returns_422(
    client, db, auth_headers_factory, seed_identity, seed_course_with_syllabus
) -> None:
    teacher_id, teacher_email, course = _seed_teacher_with_course(
        seed_identity, seed_course_with_syllabus, db
    )
    headers = auth_headers_factory(sub=teacher_id, email=teacher_email)
    payload = _intake_payload(course.id)  # no algorithm_primary
    with patch("fastapi.BackgroundTasks.add_task"):
        resp = client.post("/api/authoring/jobs", json=payload, headers=headers)
    assert resp.status_code == 422
    assert "algoritmo" in resp.json()["detail"].lower()


def test_intake_contrast_missing_challenger_returns_422(
    client, db, auth_headers_factory, seed_identity, seed_course_with_syllabus
) -> None:
    teacher_id, teacher_email, course = _seed_teacher_with_course(
        seed_identity, seed_course_with_syllabus, db
    )
    headers = auth_headers_factory(sub=teacher_id, email=teacher_email)
    payload = _intake_payload(
        course.id,
        algorithm_mode="contrast",
        algorithm_primary=_baseline("ml_ds"),
        student_profile="ml_ds",
    )
    with patch("fastapi.BackgroundTasks.add_task"):
        resp = client.post("/api/authoring/jobs", json=payload, headers=headers)
    assert resp.status_code == 422
    assert "challenger" in resp.json()["detail"].lower()


def test_intake_unknown_algorithm_returns_422(
    client, db, auth_headers_factory, seed_identity, seed_course_with_syllabus
) -> None:
    teacher_id, teacher_email, course = _seed_teacher_with_course(
        seed_identity, seed_course_with_syllabus, db
    )
    headers = auth_headers_factory(sub=teacher_id, email=teacher_email)
    payload = _intake_payload(
        course.id,
        algorithm_mode="single",
        algorithm_primary="Algoritmo Inventado",
    )
    with patch("fastapi.BackgroundTasks.add_task"):
        resp = client.post("/api/authoring/jobs", json=payload, headers=headers)
    assert resp.status_code == 422
    assert "catálogo" in resp.json()["detail"].lower()


def test_intake_single_ok_persists_payload_shape(
    client, db, auth_headers_factory, seed_identity, seed_course_with_syllabus
) -> None:
    teacher_id, teacher_email, course = _seed_teacher_with_course(
        seed_identity, seed_course_with_syllabus, db
    )
    headers = auth_headers_factory(sub=teacher_id, email=teacher_email)
    primary = _baseline("business")
    payload = _intake_payload(
        course.id,
        algorithm_mode="single",
        algorithm_primary=primary,
    )
    with patch("fastapi.BackgroundTasks.add_task"):
        resp = client.post("/api/authoring/jobs", json=payload, headers=headers)
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]

    db2 = SessionLocal()
    try:
        job = db2.query(AuthoringJob).filter(AuthoringJob.id == job_id).first()
        assert job is not None
        assert job.task_payload["algorithm_mode"] == "single"
        assert job.task_payload["algoritmos"] == [primary]
    finally:
        db2.close()


def test_intake_contrast_ok_persists_two_algorithms(
    client, db, auth_headers_factory, seed_identity, seed_course_with_syllabus
) -> None:
    teacher_id, teacher_email, course = _seed_teacher_with_course(
        seed_identity, seed_course_with_syllabus, db
    )
    headers = auth_headers_factory(sub=teacher_id, email=teacher_email)
    baseline = _baseline("ml_ds")
    challenger = _challenger("ml_ds")
    payload = _intake_payload(
        course.id,
        student_profile="ml_ds",
        algorithm_mode="contrast",
        algorithm_primary=baseline,
        algorithm_challenger=challenger,
    )
    with patch("fastapi.BackgroundTasks.add_task"):
        resp = client.post("/api/authoring/jobs", json=payload, headers=headers)
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]

    db2 = SessionLocal()
    try:
        job = db2.query(AuthoringJob).filter(AuthoringJob.id == job_id).first()
        assert job is not None
        assert job.task_payload["algorithm_mode"] == "contrast"
        assert job.task_payload["algoritmos"] == [baseline, challenger]
    finally:
        db2.close()


def test_intake_harvard_only_business_allows_empty_picks(
    client, db, auth_headers_factory, seed_identity, seed_course_with_syllabus
) -> None:
    teacher_id, teacher_email, course = _seed_teacher_with_course(
        seed_identity, seed_course_with_syllabus, db
    )
    headers = auth_headers_factory(sub=teacher_id, email=teacher_email)
    payload = _intake_payload(course.id, case_type="harvard_only")
    with patch("fastapi.BackgroundTasks.add_task"):
        resp = client.post("/api/authoring/jobs", json=payload, headers=headers)
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]

    db2 = SessionLocal()
    try:
        job = db2.query(AuthoringJob).filter(AuthoringJob.id == job_id).first()
        assert job is not None
        assert job.task_payload["algorithm_mode"] == "single"
        assert job.task_payload["algoritmos"] == []
    finally:
        db2.close()
