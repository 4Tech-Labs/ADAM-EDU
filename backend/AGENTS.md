# AGENTS.md

## Backend Scope

This directory contains the FastAPI backend, Alembic migrations, ORM models, and the LangGraph-powered authoring pipeline.

## Local Bootstrap

For a normal local backend session:

```powershell
cd C:\Users\Juan Camilo Dorado\Downloads\ADAM-EDU
docker compose up -d adam-edu-postgres

cd backend
uv sync --dev
uv run alembic upgrade head
uv run uvicorn shared.app:app --reload --host 0.0.0.0 --port 8000
```

`docker compose up` starts PostgreSQL, but it does not apply migrations. `uv run alembic upgrade head` is required for a usable local schema.

## Validation

Backend changes should normally validate with:

```powershell
uv run pytest -q
uv run mypy src
```

If the change touches live LLM behavior, only run marked live tests explicitly:

```powershell
$env:RUN_LIVE_LLM_TESTS="1"
uv run pytest -m live_llm -q
```

## Boundaries

- `src/case_generator/` owns teacher authoring business logic.
- `src/shared/` owns app composition, DB, ORM, sanitization, progress bus, and shared contracts.
- `shared/` must not absorb new product domains.
- Use absolute imports. Do not add `sys.path` mutations.
- Keep application schema changes in Alembic migrations under `alembic/versions/`.

## Database Rules

- Runtime schema management goes through Alembic.
- Keep `backend/.env.example` aligned with actual local defaults.
- If a change affects setup or schema expectations, update `README.md` in the same PR.
- Tests may bootstrap schema differently from the app runtime; do not treat that as permission to skip migrations in real app flows.

## Sensitive Areas

- `src/shared/app.py`
- `src/shared/database.py`
- `src/shared/models.py`
- `src/case_generator/**`

Changes in these areas should stay tightly scoped and validated.
