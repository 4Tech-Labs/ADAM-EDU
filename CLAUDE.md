# CLAUDE.md

## Project Context

ADAM-EDU is a teacher authoring + preview MVP for pedagogical business cases. The active product surface in this repository is the teacher flow: form assistance, authoring job intake, LangGraph-based generation, Supabase Realtime progress, and preview rendering.

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

## Shared Agent Tooling

- The repo-scoped routing skill lives in `.agents/skills/adam-orchestrator/`.
- Repo-scoped custom subagents live in `.codex/agents/`.
- `scripts/agents/gstack.lock.json` pins the upstream gstack repository, ref, commit, and version used by the team.
- `.agents/skills/gstack*` and `.claude/skills/*` are generated local runtimes. Rebuild them with:
  - `pwsh -File scripts/agents/bootstrap.ps1`
  - or `./scripts/agents/bootstrap.sh`
- Changes to agent tooling belong in dedicated `agent/...` branches and PRs.
- If agent tooling changes, update `README.md`, `CONTRIBUTING.md`, `AGENTS.md`, and `CLAUDE.md` in the same PR.

## gstack

Use the repo-driven gstack runtime materialized from the pinned lock in `scripts/agents/gstack.lock.json`.

- This repo is Codex-first. Claude support is kept as a compatible bootstrap path, not as the canonical source-of-truth layout.
- Start substantial work through `adam-orchestrator`.
- Let `adam-orchestrator` dispatch to the right gstack skill by intent.
- Use gstack browser skills for browser-heavy QA and manual verification flows.

## Skill routing

- For implementation, debugging, review, QA, release, ideation, design, or security work, invoke `adam-orchestrator` first.
- `adam-orchestrator` routes the request into the correct gstack workflow. Do not force the user to memorize slash commands.
- Small read-only questions, code explanations, and narrow factual requests can be answered directly without invoking a workflow.
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

## Domain Map

- `backend/src/case_generator/`: authoring business logic, LangGraph orchestration, prompts, schemas, and downstream generation services.
- `backend/src/shared/`: FastAPI composition root, database access, ORM models, shared contracts, sanitization, and progress snapshot endpoints.
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

## Auth Error Precedence

- For protected backend authz routes in `backend/src/shared/**`, evaluate auth failures in this order:
  - `verified_identity -> profile_state -> membership_state -> password_rotation -> role/context -> handler`
- `profile_incomplete` belongs only to profile-state failures, including missing profile rows or missing required profile fields.
- `membership_required` belongs only to membership-state failures.
- `password_rotation_required` blocks protected business routes after identity/profile/membership pass.
- `GET /api/auth/me` remains bootstrap-safe, bypasses shared required-profile-field checks and `password_rotation_required`, and still returns actor state including `must_rotate_password` when the profile row exists.
- `POST /api/auth/change-password` is explicitly exempt from the shared password-rotation guard so it cannot self-block.

## Supabase Infrastructure Guardrails

- ADAM-EDU production progress infrastructure is Supabase-native: Postgres durability + Supabase Realtime (`postgres_changes` on `public.authoring_jobs`).
- Treat Supavisor transaction mode (`:6543`) as the default production connection path for backend database access.
- Do not introduce manual SSE pub/sub systems, in-memory progress buses, or custom long-lived stream fanout layers for teacher authoring progress.
- Do not introduce complex queue reclaimers/orchestrators for this progress path unless an approved ADR explicitly changes the architecture.
- If a change proposes moving away from Supabase Realtime or Supavisor defaults, require a dedicated ADR and synchronized updates to `README.md`, `CONTRIBUTING.md`, `AGENTS.md`, and `CLAUDE.md` in the same PR.

## Validation Commands

- Default backend suite: `uv run --directory backend pytest -q`
- Backend type checking: `uv run --directory backend mypy src`
- Frontend lint: `npm --prefix frontend run lint`
- Frontend tests: `npm --prefix frontend run test`
- Frontend build: `npm --prefix frontend run build`

Issue 23 adds a migration test that creates and drops temporary databases. In the default
local Docker Postgres this works with the `postgres` user. On other Postgres environments,
the backend test suite now assumes `CREATE DATABASE` and `DROP DATABASE` privileges.

Ordinary backend DB-backed tests now run under a per-test dedicated connection + outer
transaction + `SAVEPOINT` session contract. Shared seed fixtures should stay flush-only by
default. Use explicit pytest markers for carve-outs:

- `ddl_isolation` for temp-database or DDL-heavy tests
- `shared_db_commit_visibility` for tests that require real cross-connection committed visibility and fall back to `TRUNCATE` cleanup

Issue 23 also introduces `backend/sql/rls_policies.sql` as a separate artifact. Alembic
does not apply that file. Treat it as an explicit secondary-RLS deployment step only for
Supabase or another environment that exposes compatible Auth helpers like `auth.uid()`.

Only run live LLM tests explicitly:

- `RUN_LIVE_LLM_TESTS=1 uv run --directory backend pytest -m live_llm -q`

## Sensitive Areas

- `backend/src/case_generator/**` is the most sensitive part of the repo.
- `backend/src/case_generator/graph.py` and `backend/src/case_generator/prompts.py` should not receive cosmetic-only edits.
- Prompt boundaries, graph orchestration, and LLM-facing payload construction require extra caution.
- Database setup, migrations, and ORM contracts must remain coherent across runtime, tests, and docs.

## Authoring Algorithm Picks (Issue #230)

- The teacher form picks algorithms from a canonical catalog instead of accepting up to five free-text chips.
- `POST /api/authoring/jobs` accepts the breaking fields `algorithm_mode` (`"single" | "contrast"`), `algorithm_primary`, and `algorithm_challenger`. The legacy `suggested_techniques` body field has been removed; do not reintroduce it.
- Algorithm picks are validated server-side at intake by `_validate_techniques_strict` whenever `case_type == "harvard_with_eda"` or `student_profile == "ml_ds"`. They are persisted into `task_payload` as `algorithm_mode` plus `algoritmos: list[str]` of length 0, 1, or 2.
- `GET /api/authoring/algorithm-catalog?profile=...&case_type=...` returns the canonical declarative catalog as `{profile, case_type, items: [{name, family, family_label, tier}]}` where `tier ∈ {"baseline", "challenger"}` and `family ∈ {clasificacion, regresion, clustering, serie_temporal}` (Issue #233 — 4×2 catalog, max 2 algorithms per family, exactly 1 baseline per family). The endpoint is open (no PII), `Literal`-validated, and re-checked at intake.
- Family-coherence rule: in `contrast` mode the baseline and the challenger MUST belong to the same `family`. The backend rejects cross-family contrast picks (e.g. Logistic Regression vs Prophet) at intake with a 422 and a teacher-friendly Spanish message. The frontend `AlgorithmSelector` filters the challenger options to the baseline family. The LLM suggester is taught the same rule via prompt boundary AND the post-LLM `_snap_item` filter, so it cannot cross families even if the model strays.
- LSTM has been removed from the canonical ml_ds time-series catalog. Do not reintroduce LSTM (or other heavy DL surrogates) without an ADR.
- The `business` profile may legitimately expose only baseline items (no challengers in any family). The frontend disables the "2 algoritmos" mode in that case; the backend rejects contrast picks with a teacher-friendly message. Do not silently fall back to `single` on the backend.

## M3 Notebook Per-Family Dispatch (Issue #233)

- The M3 notebook generator (`m3_notebook_generator` in `backend/src/case_generator/graph.py`) dispatches to ONE specialized prompt per algorithm family instead of a single monolithic prompt.
- `case_generator.prompts.PROMPT_BY_FAMILY` exposes exactly 4 keys: `clasificacion`, `regresion`, `clustering`, `serie_temporal`. The legacy `M3_NOTEBOOK_ALGO_PROMPT` symbol is preserved as a back-compat alias for `M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION`.
- Family is resolved with `family_of(name)` first, then `resolve_legacy_family(name)` for historical task_payloads (XGBoost, Ridge, NLP, etc.). On no match the dispatcher falls back to `clasificacion` and emits a `legacy_warning` appended to the data-gap block.
- After the LLM call, `_validate_notebook_family_consistency(family, code)` checks the output against `_FAMILY_PROHIBITED_PATTERNS` (other-family API tokens like `train_test_split(` in clustering, `roc_auc_score` in regression). On violation the dispatcher reprompts ONCE with the explicit forbidden-tokens list; if the second attempt also violates, it raises `RuntimeError` and the job is marked failed. Never ship a runtime-broken notebook.
- The single registry of truth lives in `case_generator.suggest_service.ALGORITHM_CATALOG`. The legacy `ALGORITHM_REGISTRY` dict in `graph.py` has been removed.
- Deprecated families (`nlp`, `recomendacion`, `grafos`, `anomalias`, `segmentacion`, `clasificacion_tabular`, `regresion_tabular`, `nlp_text_mining`) are no longer exposed by the catalog and degrade to `clasificacion` via the legacy resolver. Do not reintroduce them without an ADR.
- Issue #240 amplía `_FAMILY_REQUIRED_SENTINELS["clasificacion"]` con `tuning_lr/tuning_rf/interp_lr/interp_rf` y `_FAMILY_REQUIRED_APIS["clasificacion"]` con `GridSearchCV/RandomizedSearchCV/permutation_importance/PartialDependenceDisplay`. Las celdas declaran modo rápido por tamaño en cascada de mayor a menor (orden importa para alcanzabilidad: >5000 ⊂ >2000): `>5000 → SKIP tuning`, `>2000 → cv/n_iter reducidos`, `≤ 2000 → grilla completa`., guard `is_binary` y self-bootstrap. VIF se calcula sin `statsmodels` (fallback `1/(1-R²)` con `LinearRegression`). SHAP NO se duplica en `interp_rf`: vive en la Regla J global. Cero cambios a otras familias ni a `_FAMILY_PROHIBITED_PATTERNS`.

## Narrative Grounding (Issue #243)

- Narrative grounding applies only when `family == "clasificacion"` for M3-content, M4, and M5. The other three families keep their existing prompt strings and must not receive `{computed_metrics_block}`.
- Until #C-EXEC provides `m3_metrics_summary`, `build_computed_metrics_block(None)` emits a clear fallback placeholder, validation is disabled for that run, and `narrative_grounding_warning` is persisted.
- `validate_narrative_grounding` rejects citations with `CITA:` and unanchored model-metric numbers with `UNANCHORED:`. Business numbers from M2, Exhibits, or M4 are allowed. Numeric tolerance is ±2 percentage points for percentage-like values and ±2% relative for scalar values.
- The narrative nodes reprompt once with the `CITA:` / `UNANCHORED:` bullet list. A second violation raises `RuntimeError` so the job fails instead of shipping fabricated metrics.

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

For local auth + backend work, treat the repo as two local planes:

- app DB local via `docker compose up -d adam-edu-postgres` on host `5434`
- auth/session local via `supabase start` on `http://localhost:54321`

Use `docs/runbooks/local-dev-auth.md` as the canonical runbook when setup or auth-local
workflow changes.

For a normal backend local session:

```powershell
cd C:\Users\Juan Camilo Dorado\Downloads\ADAM-EDU
docker compose up -d adam-edu-postgres
supabase start

cd backend
uv sync --dev
uv run alembic upgrade head
uv run python -m shared.app
```

`docker compose up` starts PostgreSQL, but does not apply migrations. Alembic bootstrap is required before using the API locally.
`DATABASE_URL` stays on `localhost:5434`. Do not point it at the Supabase local database on `54322`.
