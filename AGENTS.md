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
- `docs/runbooks/`: runbooks operativos, incluido el setup local canonico de auth y authoring
- `docs/adr/`: accepted architecture decisions, including the Fase 1 auth perimeter ADR
- `docs/repo-governance.md`: repository governance and merge policy
- `CLAUDE.md`: equivalent agent guidance for Claude-oriented tooling

## Shared Agent Tooling

- This repo is Codex-first. Claude remains a supported compatibility path, but it does not define the canonical repo layout.
- The repo-scoped routing skill lives in `.agents/skills/adam-orchestrator/`.
- Repo-scoped custom subagents live in `.codex/agents/`.
- `scripts/agents/gstack.lock.json` pins the upstream gstack repository, ref, commit, and version used by the team.
- `.agents/skills/gstack*` and `.claude/skills/*` are generated local runtimes. Keep them out of git and rebuild them with:
  - `pwsh -File scripts/agents/bootstrap.ps1`
  - or `./scripts/agents/bootstrap.sh`
- Changes to agent tooling belong in dedicated `agent/...` branches and PRs.
- If agent tooling changes, update `README.md`, `CONTRIBUTING.md`, `AGENTS.md`, and `CLAUDE.md` in the same PR.

## Skill Routing

- For substantial implementation, debugging, review, QA, release, ideation, design, or security work, invoke `adam-orchestrator` first.
- `adam-orchestrator` routes the request into the right gstack workflow. Do not make the user memorize individual skills.
- Small read-only questions, code explanations, and narrow factual requests can be answered directly without a workflow.
- Dispatch defaults:
  - ideas and brainstorming -> `office-hours`, then `autoplan` or `plan-*`
  - bugs, errors, regressions -> `investigate`
  - review of a diff, branch, or PR -> `review`
  - QA or staging verification -> `qa` or `qa-only`
  - release preparation -> `ship`, then `land-and-deploy`, `canary`, `document-release`
  - visual work -> `design-*`
  - security review -> `cso`
  - browser-heavy QA -> `browse`, `connect-chrome`, `setup-browser-cookies`
- One agent owns the branch and final decision path. Use repo-scoped subagents only for bounded read-only sidecars such as `pr_explorer`, `reviewer`, `code_mapper`, independent report-only QA, benchmark, read-only exploration, or post-ship docs.
- Do not use subagents for merge or deploy authority, scope decisions, conflicting writes, or parallel edits in `backend/src/case_generator/**`.
- Do not run `document-release` before `uv run --directory backend pytest -q` is green. Pre-PR docs sync belongs in the implementation diff itself.

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

Issue 23 adds a migration test that creates and drops temporary databases. In the default
local Docker Postgres this works with the `postgres` user. On other Postgres environments,
the backend test suite now assumes `CREATE DATABASE` and `DROP DATABASE` privileges.

Issue 23 also introduces `backend/sql/rls_policies.sql` as a separate artifact. Alembic
does not apply that file. Treat it as an explicit secondary-RLS deployment step only for
Supabase or another environment that exposes compatible Auth helpers like `auth.uid()`.

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

## Local Dev Auth

Cuando el cambio toque setup local o auth:

- usa `docs/runbooks/local-dev-auth.md` como fuente canonica
- distingue siempre los dos planos locales:
  - app DB del repo por `docker compose` en `5434`
  - auth/session local por `supabase start` en `54321`
- no documentes `5432` como puerto host local por defecto del repo
- no permitas ejemplos donde `DATABASE_URL` apunte al Postgres interno de Supabase local en `54322`
