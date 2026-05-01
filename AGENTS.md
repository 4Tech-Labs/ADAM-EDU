# AGENTS.md

## Project Context

ADAM-EDU is a teacher authoring + preview MVP for pedagogical business cases.

This repository currently supports:

- teacher form suggestions via `/api/suggest`
- asynchronous authoring job intake via `/api/authoring/jobs`
- LangGraph-based case generation
- Supabase Realtime progress updates (`postgres_changes`)
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
- `backend/src/shared/` owns FastAPI app composition, DB, ORM, shared contracts, and progress snapshot endpoints.
- `frontend/src/` follows the stable top-level split `app / features / shared`.
- `shared/` must not become a catch-all for new product logic.
- Use absolute imports by domain. Do not reintroduce `sys.path` hacks or deep relative import chains.
- Alembic is the schema mechanism for the application runtime. Do not rely on ad hoc table creation in normal app startup.

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

Ordinary backend DB-backed tests now run under a per-test dedicated connection + outer
transaction + `SAVEPOINT` session contract. Keep shared seed fixtures flush-only by default.
Use explicit pytest markers for carve-outs:

- `ddl_isolation` for temp-database or DDL-heavy tests
- `shared_db_commit_visibility` for tests that require real cross-connection committed visibility and fall back to `TRUNCATE` cleanup

Issue 23 also introduces `backend/sql/rls_policies.sql` as a separate artifact. Alembic
does not apply that file. Treat it as an explicit secondary-RLS deployment step only for
Supabase or another environment that exposes compatible Auth helpers like `auth.uid()`.

## Sensitive Areas

- `backend/src/case_generator/**` is the most sensitive part of the repo.
- Prompt boundaries, graph orchestration, and LLM-facing payload handling need extra caution.
- Database setup and migrations must stay aligned with `backend/alembic/` and `backend/.env.example`.

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
- Issue #240 amplía `_FAMILY_REQUIRED_SENTINELS["clasificacion"]` con `tuning_lr/tuning_rf/interp_lr/interp_rf` y `_FAMILY_REQUIRED_APIS["clasificacion"]` con `GridSearchCV/RandomizedSearchCV/permutation_importance/PartialDependenceDisplay`. Las celdas declaran modo rápido por tamaño (>2000 skip tuning, >5000 cv/n_iter reducidos), guard `is_binary` y self-bootstrap. VIF se calcula sin `statsmodels` (fallback `1/(1-R²)` con `LinearRegression`). SHAP NO se duplica en `interp_rf`: vive en la Regla J global. Cero cambios a otras familias ni a `_FAMILY_PROHIBITED_PATTERNS`.

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
