# AGENTS.md

## Frontend Scope

This directory contains the teacher-facing UI for authoring and preview.

## Structure Rules

- Keep the stable top-level structure: `src/app`, `src/features`, `src/shared`.
- Place new product logic inside an explicit feature, not inside generic utility buckets.
- Do not reintroduce folders such as `components`, `pages`, `hooks`, `helpers`, `common`, or `misc` at the top level.

## Current Product Invariants

- The teacher flow is the primary supported UI surface.
- Preview behavior and the current `M1..M6` structure are part of the active contract.
- Routing and app shell conventions under `src/app/` should remain consistent with the current `/app/` setup.

## Validation

Frontend changes should normally validate with:

```powershell
npm run lint
npm run test
npm run build
```

## Boundaries

- `src/app/` owns the shell, routing, and global setup.
- `src/features/teacher-authoring/` owns the teacher authoring flow.
- `src/features/case-preview/` owns rendering of the generated case preview.
- `src/shared/` owns API client, shared types, UI primitives, and cross-feature utilities.

## Forbidden Patterns

- Silent contract changes between frontend payloads and backend endpoints
- New domain logic hidden inside generic shared utilities
- Cosmetic-only churn across large UI areas without product value

If a frontend change alters user-visible workflow, keep `README.md` or related contributor docs aligned.
