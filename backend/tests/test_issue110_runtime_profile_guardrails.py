from __future__ import annotations

from pathlib import Path

import pytest

from shared.app import _build_uvicorn_runtime_profile


REPO_ROOT = Path(__file__).resolve().parents[2]


def _clear_runtime_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_name in [
        "APP_ENV",
        "ENVIRONMENT",
        "APP_HOST",
        "APP_PORT",
        "APP_WORKERS",
        "APP_TIMEOUT_KEEP_ALIVE",
        "APP_TIMEOUT_GRACEFUL_SHUTDOWN",
    ]:
        monkeypatch.delenv(env_name, raising=False)


def _read_repo_file(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_runtime_profile_matrix_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_runtime_env(monkeypatch)

    monkeypatch.setenv("ENVIRONMENT", "production")
    profile = _build_uvicorn_runtime_profile([])
    assert profile.reload is False

    monkeypatch.setenv("APP_ENV", "development")
    profile = _build_uvicorn_runtime_profile([])
    assert profile.reload is True


def test_dev_reload_scope_is_source_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "development")

    profile = _build_uvicorn_runtime_profile([])
    expected_excludes = {
        ".venv/*",
        "*/.venv/*",
        "*site-packages*",
        "node_modules/*",
        "*/node_modules/*",
        ".git/*",
        "*/.git/*",
        "build/*",
        "*/build/*",
        "dist/*",
        "*/dist/*",
    }

    assert profile.reload is True
    assert profile.reload_dirs == [str((REPO_ROOT / "backend" / "src").resolve())]
    assert expected_excludes.issubset(set(profile.reload_excludes))


def test_reload_excludes_cover_dependency_churn_patterns(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "development")

    profile = _build_uvicorn_runtime_profile([])

    # These patterns prevent restarts triggered by external dependency/file churn.
    for expected_pattern in ("*site-packages*", "*/.venv/*", "*/node_modules/*"):
        assert expected_pattern in profile.reload_excludes


def test_non_dev_rejects_reload_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")

    with pytest.raises(RuntimeError, match="Reload is forbidden"):
        _build_uvicorn_runtime_profile(["--reload"])


def test_non_dev_defaults_are_institutional(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")

    profile = _build_uvicorn_runtime_profile([])

    assert profile.reload is False
    assert profile.workers == 2
    assert profile.timeout_keep_alive == 30
    assert profile.timeout_graceful_shutdown == 60


def test_command_surfaces_are_consistent() -> None:
    expected_commands = {
        "Makefile": "uv run python -m shared.app",
        "CONTRIBUTING.md": "uv run --directory backend python -m shared.app",
        "docs/runbooks/local-dev-auth.md": "uv run --directory backend python -m shared.app",
        "backend/AGENTS.md": "uv run python -m shared.app",
        "CLAUDE.md": "uv run python -m shared.app",
    }

    for relative_path, command_fragment in expected_commands.items():
        content = _read_repo_file(relative_path)
        assert command_fragment in content, f"Missing command fragment in {relative_path}"
        assert "uvicorn shared.app:app --reload" not in content


def test_ci_guardrail_fails_when_reload_appears_in_prod_path() -> None:
    production_surfaces = [
        "backend/Dockerfile.worker",
        "docs/runbooks/cloud-run-deploy.md",
    ]

    for relative_path in production_surfaces:
        content = _read_repo_file(relative_path)
        bad_lines = [
            line
            for line in content.splitlines()
            if (
                (line.strip().lower().startswith("uvicorn ") or line.strip().lower().startswith("uv run "))
                and "--reload" in line.lower()
            )
        ]
        assert not bad_lines, f"Unsafe reload command found in production surface {relative_path}: {bad_lines[0]}"
