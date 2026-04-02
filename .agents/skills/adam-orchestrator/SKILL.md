---
name: adam-orchestrator
description: |
  Shared workflow router for ADAM-EDU. Converts natural-language requests into the
  right gstack sprint stage without making the user memorize skill names. Use when
  the request is about planning, implementing, debugging, reviewing, QA, browser
  testing, shipping, or release follow-through in this repo. Keep small read-only
  questions inline when no workflow is needed.
---

# ADAM Orchestrator

Use this as the first stop for substantial work in ADAM-EDU.

## Goal

Route by intent, not by command memorization. The user should be able to say:

- "piensa esta idea"
- "esto se rompio"
- "revisame esta rama"
- "haz QA de staging"
- "dejalo listo para PR"

and get the right workflow automatically.

## Runtime expectations

- This repo-scoped skill lives in `.agents/skills/adam-orchestrator/`.
- Repo-scoped custom subagents live in `.codex/agents/`.
- gstack is materialized locally by bootstrap into:
  - `.agents/skills/gstack*` for Codex
  - `.claude/skills/*` for Claude compatibility
- If the local gstack runtime is missing, tell the user to run:
  - `pwsh -File scripts/agents/bootstrap.ps1`
  - or `./scripts/agents/bootstrap.sh`

## Routing rules

If the request is small, read-only, or purely explanatory, answer directly.

If the request needs a workflow, route to one primary gstack stage:

- Idea, brainstorming, "is this worth building", user problem framing:
  - `office-hours`
  - then `autoplan` or `plan-*` if the user wants the plan locked in
- Product scope, ambition, prioritization:
  - `plan-ceo-review`
- Architecture, execution plan, tests, edge cases:
  - `plan-eng-review`
- Design system, visual exploration, mockups:
  - `design-consultation`, `design-shotgun`, `plan-design-review`, `design-html`, `design-review`
- Bug, regression, stack trace, broken behavior:
  - `investigate`
- Code review, diff review, pre-landing review:
  - `review`
- QA pass, browser verification, staging validation:
  - `qa` or `qa-only`
- Browser-heavy manual flows:
  - `browse`, `connect-chrome`, `setup-browser-cookies`
- Security review:
  - `cso`
- PR prep, release prep, deploy:
  - `ship`
  - then `land-and-deploy`, `canary`, `document-release` when the stage calls for it
- Weekly summary or what shipped:
  - `retro`

## Pipeline defaults

Prefer stage-based pipelines:

- Think -> Plan -> Build -> Review -> Test -> Ship -> Reflect
- Bug fix -> `investigate` -> implementation -> `review` -> `qa` -> `ship`
- Feature release -> implementation -> `review` -> `qa` -> `ship`
- Approved PR -> `land-and-deploy` -> `canary` -> `document-release`

Do not make the user choose the skill unless the request is genuinely ambiguous.

## Subagent policy

One agent owns the branch and final decision path.

If Codex custom subagents are available, use them only for bounded parallel sidecars:

- `pr_explorer` for read-only code-path exploration before changes
- `reviewer` for independent read-only review of correctness, security, and tests
- `code_mapper` for read-only frontend/backend flow mapping before edits

Do not use subagents for:

- merge or deploy authority
- scope decisions
- conflicting writes in the same area
- parallel edits in `backend/src/case_generator/**`

## Repo policy reminders

- Work on a branch, never directly on `main`.
- Changes to agent tooling belong in dedicated `agent/...` PRs.
- If setup, workflow, or contributor behavior changes, update `README.md`, `CONTRIBUTING.md`, `AGENTS.md`, and `CLAUDE.md` in the same change.
