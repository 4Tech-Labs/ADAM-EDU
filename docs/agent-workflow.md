# Shared Agent Workflow

ADAM-EDU uses a Codex-first agent workflow so the team can share the same routing contract without vendoring third-party runtime trees into the repository.

## Official repo surfaces

- `.agents/skills/adam-orchestrator/` is the repo-scoped skill that routes substantial work by intent.
- `.codex/agents/` holds the repo-scoped custom subagents for bounded read-only sidecars.
- `scripts/agents/gstack.lock.json` pins the upstream gstack repository, ref, commit, and version.
- `scripts/agents/bootstrap.ps1` and `scripts/agents/bootstrap.sh` materialize the local runtime trees.

The generated runtimes stay local and mostly ignored by git:

- `.agents/skills/gstack*` for Codex
- `.claude/skills/*` for Claude compatibility

Do not hand-edit those generated trees. Rebuild them from the bootstrap scripts.

## Bootstrap

Windows PowerShell:

```powershell
pwsh -File scripts/agents/bootstrap.ps1
pwsh -File scripts/agents/bootstrap.ps1 -RuntimeHost codex
pwsh -File scripts/agents/bootstrap.ps1 -RuntimeHost claude
```

Bash:

```bash
./scripts/agents/bootstrap.sh
./scripts/agents/bootstrap.sh --host codex
./scripts/agents/bootstrap.sh --host claude
```

What bootstrap does:

1. Reads the pinned gstack lock file.
2. Clones or refreshes gstack into the ignored runtime tree for the selected host.
3. Checks out the pinned commit.
4. Runs upstream `setup` for that host.
5. Copies `adam-orchestrator` into `.claude/skills/adam-orchestrator` when Claude compatibility is requested.

On Windows, Git Bash is required because gstack `setup` is a bash entrypoint.

## How the team should work

Default workflow:

- Think -> Plan -> Build -> Review -> Test -> Ship -> Reflect

Natural-language-first examples:

- "piensa esta idea" -> `office-hours`, then `autoplan` or `plan-*`
- "esto se rompio" -> `investigate`
- "revisame esta rama" -> `review`
- "haz QA de staging" -> `qa` or `qa-only`
- "dejalo listo para PR" -> `review` -> `qa` -> `ship`

The user should not need to memorize gstack commands. `adam-orchestrator` is the first router for substantial work.

## Manual escape hatches

If someone wants an explicit entrypoint instead of natural language:

- use `adam-orchestrator` to route the task
- use the underlying gstack skill directly when the stage is already obvious

Small read-only questions can still be answered inline without invoking a workflow.

## Subagents

One agent owns the branch and the final change set.

Repo-scoped custom subagents:

- `pr_explorer`: read-only code-path exploration before changes
- `reviewer`: read-only review focused on correctness, security, and missing tests
- `code_mapper`: read-only mapping of frontend/backend ownership before edits

Allowed parallel sidecars:

- independent review
- report-only QA
- benchmark or health checks
- read-only exploration
- post-ship documentation updates

Do not parallelize:

- merge or deploy authority
- scope decisions
- conflicting write scopes
- sensitive edits in `backend/src/case_generator/**`

## Updating the pinned gstack lock

Use a dedicated `agent/...` branch and PR:

```powershell
pwsh -File scripts/agents/update-gstack-lock.ps1
```

```bash
./scripts/agents/update-gstack-lock.sh
```

After updating:

1. rerun bootstrap
2. validate the local runtime
3. update `README.md`, `CONTRIBUTING.md`, `AGENTS.md`, and `CLAUDE.md` in the same PR if the workflow contract changed

Update when a new gstack version adds skills the team needs or fixes a bug that affects the workflow. There is no fixed cadence; the `agent/...` PR gate is the review mechanism.
