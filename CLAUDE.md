# CLAUDE.md

## Project Context

ADAM-EDU is a teacher authoring + preview MVP for pedagogical business cases. The active product surface in this repository is the teacher flow: form assistance, authoring job intake, LangGraph-based generation, SSE progress, and preview rendering.

This repository does not currently publish a student runtime, full authentication, or a hardened production deployment surface.

## Instruction Canon

- `AGENTS.md` is the canonical instruction surface for Codex and compatible OpenAI-oriented agents.
- `CLAUDE.md` is the equivalent maintained instruction surface for Claude-oriented tooling.
- If an operational rule changes, update `AGENTS.md` and `CLAUDE.md` in the same PR.
- Human-facing setup and workflow details stay in `README.md`, `CONTRIBUTING.md`, and `docs/repo-governance.md`.

## Repo Rules

- Treat `main` as protected.
- Never push directly to `main`.
- Every non-trivial change must go through a branch and pull request.
- Default merge mode is `Squash and merge`.
- If a change affects setup, contracts, workflows, or contributor expectations, update the relevant documentation in the same change.

## Domain Map

- `backend/src/case_generator/`: authoring business logic, LangGraph orchestration, prompts, schemas, and downstream generation services.
- `backend/src/shared/`: FastAPI composition root, database access, ORM models, shared contracts, sanitization, and progress/SSE support.
- `frontend/src/app/`: application shell, router, entrypoint, and global styles.
- `frontend/src/features/teacher-authoring/`: teacher-facing authoring workflow.
- `frontend/src/features/case-preview/`: generated case preview and `M1..M6` rendering surface.
- `frontend/src/shared/`: shared API client, types, UI primitives, and cross-feature utilities.

## Architecture Boundaries

- Use absolute imports by domain.
- `shared/` must not become a catch-all for new business domains.
- `shared/` should not import business domains, except where composition requires it in the app root.
- Schema changes for the app runtime go through Alembic migrations.
- Keep `backend/.env.example`, local defaults, and documented setup aligned when database expectations change.

## Validation Commands

- Default backend suite: `uv run --directory backend pytest -q`
- Backend type checking: `uv run --directory backend mypy src`
- Frontend lint: `npm --prefix frontend run lint`
- Frontend tests: `npm --prefix frontend run test`
- Frontend build: `npm --prefix frontend run build`

Only run live LLM tests explicitly:

- `RUN_LIVE_LLM_TESTS=1 uv run --directory backend pytest -m live_llm -q`

## Sensitive Areas

- `backend/src/case_generator/**` is the most sensitive part of the repo.
- `backend/src/case_generator/graph.py` and `backend/src/case_generator/prompts.py` should not receive cosmetic-only edits.
- Prompt boundaries, graph orchestration, and LLM-facing payload construction require extra caution.
- Database setup, migrations, and ORM contracts must remain coherent across runtime, tests, and docs.

## Forbidden Patterns

- Secrets, API keys, tokens, credentials, or DSNs committed to code, prompts, fixtures, or docs
- New business logic embedded in migrations, routers, or prompt strings
- Cross-domain imports that bypass the current ownership boundaries
- Broad type-ignore suppression without a specific justification
- Reopening generic frontend top-level folders such as `components`, `pages`, `hooks`, `helpers`, `common`, or `misc`

## LLM Hygiene

- Never inject raw secrets or environment values into prompts.
- Treat user-controlled text as untrusted before crossing an LLM boundary.
- Prefer explicit state/context injection over blind prompt concatenation.
- Preserve or strengthen sanitization whenever prompt assembly changes.
- Prefer structured-output handling that tolerates validation errors and empty responses safely.

## Naming and Stability Rules

- Code, modules, and symbols stay in English.
- Spanish domain terms may remain when they are part of the pedagogical language or prompt contract.
- Keep the stable frontend split `app / features / shared`.
- Do not rename `case_generator`, `shared`, `app`, `teacher-authoring`, or `case-preview` without a dedicated refactor plan.
- Preserve the current `studentProfile` and `M1..M6` contracts unless the change explicitly coordinates backend, frontend, and docs updates.

## Local Environment Expectations

For a normal backend local session:

```powershell
cd C:\Users\Juan Camilo Dorado\Downloads\ADAM-EDU
docker compose up -d adam-edu-postgres

cd backend
uv sync --dev
uv run alembic upgrade head
uv run uvicorn shared.app:app --reload --host 0.0.0.0 --port 8000
```

`docker compose up` starts PostgreSQL, but does not apply migrations. Alembic bootstrap is required before using the API locally.
