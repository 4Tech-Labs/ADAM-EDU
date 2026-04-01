# AGENTS.md

## Project Context

ADAM-EDU is a teacher authoring + preview MVP for pedagogical business cases.

This repository currently supports:

- teacher form suggestions via `/api/suggest`
- asynchronous authoring job intake via `/api/authoring/jobs`
- LangGraph-based case generation
- SSE progress updates
- teacher preview of the generated case

This repository does not currently include a student runtime, full authentication, or a hardened production deployment surface.

## Repo Rules

- Treat `main` as protected even when GitHub cannot enforce every rule automatically.
- Never push directly to `main`.
- Every change must go through a branch and pull request.
- Default merge mode is `Squash and merge`.
- If you change setup, contracts, workflows, or contributor behavior, update the relevant documentation in the same change.

## Documentation Map

- `README.md`: onboarding, local setup, Docker, Alembic, runtime commands
- `CONTRIBUTING.md`: branch, PR, validation, and collaboration workflow
- `docs/repo-governance.md`: repository governance and merge policy
- `CLAUDE.md`: equivalent agent guidance for Claude-oriented tooling

## Architecture Boundaries

- `backend/src/case_generator/` owns authoring business logic, prompts, schemas, and graph execution.
- `backend/src/shared/` owns FastAPI app composition, DB, ORM, shared contracts, and SSE support.
- `frontend/src/` follows the stable top-level split `app / features / shared`.
- `shared/` must not become a catch-all for new product logic.
- Use absolute imports by domain. Do not reintroduce `sys.path` hacks or deep relative import chains.
- Alembic is the schema mechanism for the application runtime. Do not rely on ad hoc table creation in normal app startup.

## Validation Commands

Run the relevant checks before opening a PR. Full default set:

```powershell
uv run --directory backend pytest -q
uv run --directory backend mypy src
npm --prefix frontend run lint
npm --prefix frontend run test
npm --prefix frontend run build
```

## Sensitive Areas

- `backend/src/case_generator/**` is the most sensitive part of the repo.
- Prompt boundaries, graph orchestration, and LLM-facing payload handling need extra caution.
- Database setup and migrations must stay aligned with `backend/alembic/` and `backend/.env.example`.

## Forbidden Patterns

- Secrets, tokens, keys, DSNs, or credentials committed to the repo
- New business logic hidden inside migrations, routers, or prompt strings
- Cross-domain imports that bypass the current ownership boundaries
- Reopening generic frontend folders such as `components`, `pages`, `hooks`, `helpers`, `common`, or `misc`
- Cosmetic-only edits in sensitive authoring files without functional justification

## Nested Guidance

More specific rules live in:

- `backend/AGENTS.md`
- `backend/src/case_generator/AGENTS.md`
- `frontend/AGENTS.md`

Files closer to the working directory are intended to add or override guidance for that area.
