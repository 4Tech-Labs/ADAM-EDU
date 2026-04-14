# AGENTS.md

## Backend Scope

This directory contains the FastAPI backend, Alembic migrations, ORM models, and the LangGraph-powered authoring pipeline.

## Local Bootstrap

For a normal local backend session:

```powershell
cd C:\Users\Juan Camilo Dorado\Downloads\ADAM-EDU
docker compose up -d adam-edu-postgres
supabase start

cd backend
uv sync --dev
uv run alembic upgrade head
uv run python -m shared.app
```

`docker compose up` starts PostgreSQL, but it does not apply migrations. `uv run alembic upgrade head` is required for a usable local schema.
Supabase CLI owns auth/session local on `http://localhost:54321`. The repo app database
stays on `localhost:5434`, not the Supabase local database on `54322`.

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
- `src/shared/` owns app composition, DB, ORM, sanitization, progress snapshot endpoints, and shared contracts.
- `shared/` must not absorb new product domains.
- Use absolute imports. Do not add `sys.path` mutations.
- Keep application schema changes in Alembic migrations under `alembic/versions/`.

## Supabase Infrastructure Guardrails

- Treat Supavisor transaction mode (`:6543`) as the default production connection path for backend database access.
- Teacher authoring progress is Supabase-native: durable state in Postgres + Realtime via `postgres_changes` on `public.authoring_jobs`.
- Do not introduce manual SSE pub/sub systems, in-memory progress buses, or custom stream fanout layers for this progress path.
- Do not introduce complex queue reclaimers/orchestrators for this progress path unless an approved ADR changes the architecture.

## Database Rules

- Runtime schema management goes through Alembic.
- Keep `backend/.env.example` aligned with actual local defaults.
- If a change affects setup or schema expectations, update `README.md` in the same PR.
- Tests may bootstrap schema differently from the app runtime; do not treat that as permission to skip migrations in real app flows.
- If a migration tightens identity-bridge assumptions, prefer reset/reseed of local data over hand-editing legacy rows to bypass the migration.

## Sensitive Areas

- `src/shared/app.py`
- `src/shared/database.py`
- `src/shared/models.py`
- `src/case_generator/**`

Changes in these areas should stay tightly scoped and validated.
