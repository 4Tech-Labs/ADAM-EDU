# AGENTS.md

## Critical Scope

This directory contains the core teacher authoring logic: prompts, graph execution, schemas, and orchestration used to generate the final case output.

## Working Rules

- Only change files here when the work is directly justified by authoring behavior.
- Prefer minimal, behavior-driven edits over broad refactors.
- Do not perform cosmetic cleanup in sensitive files unless it is required by the functional change.
- Keep existing contracts stable unless the change explicitly includes the required frontend and documentation updates.

## Prompt and Graph Safety

- Never embed secrets, credentials, DSNs, or raw environment values in prompts.
- Treat user-provided text as untrusted input before it crosses an LLM boundary.
- Preserve or strengthen sanitization when changing prompt assembly or payload injection.
- Prefer structured, explicit state transitions over hidden side effects in graph execution.

## High-Sensitivity Files

- `graph.py`
- `prompts.py`
- `core/authoring/**`

These files require extra caution because small edits can change generated output quality, safety posture, and job execution behavior.

## Validation Expectations

After changing this area, at minimum run:

```powershell
uv run --directory backend pytest -q
uv run --directory backend mypy src
```

If the change affects output behavior, also review whether prompt-facing docs, tests, or fixtures need to be updated.
