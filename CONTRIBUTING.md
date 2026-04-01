# Contributing to ADAM-EDU

ADAM-EDU se mantiene con un flujo estricto por pull request. `main` es la rama estable y nadie debe empujar cambios directos a esa rama.

## Manual Governance

Mientras GitHub no fuerce toda la proteccion de rama en este plan, el equipo adopta estas reglas como politica operativa:

- si no hay PR, el cambio no existe
- `main` no recibe pushes directos
- el autor no mergea hasta revisar checks y contexto del cambio
- el merge operativo es `Squash and merge`
- los 5 checks requeridos son:
  - `backend-test`
  - `backend-typecheck`
  - `frontend-build`
  - `frontend-lint`
  - `frontend-test`

## Flujo de trabajo

1. Crea una rama desde `main`.
2. Usa un nombre corto y tematico:
   - `feat/...`
   - `fix/...`
   - `chore/...`
   - `agent/...`
3. Mantén cada cambio enfocado. No mezcles funcionalidad, refactor y housekeeping en el mismo PR.
4. Ejecuta los checks locales antes de abrir el PR.
5. Abre un pull request.
6. Usa `squash merge` cuando el PR esté aprobado y con checks verdes.

## Checks locales obligatorios

```powershell
uv run --directory backend pytest -q
uv run --directory backend mypy src
npm --prefix frontend run lint
npm --prefix frontend run build
npm --prefix frontend run test
```

## Reglas para agentes

- Los agentes trabajan solo por rama y PR.
- Un agente no debe empujar directo a `main`.
- Si el cambio toca más de un subsistema, el PR debe abrirse como draft.
- Si un agente encuentra cambios ajenos en el árbol, debe preservarlos y trabajar alrededor de ellos.

- Tooling local de agentes, como `.agents/`, no debe commitearse como parte de cambios de producto salvo que el objetivo del PR sea mantener ese tooling deliberadamente.

## Secretos y entorno

- No subas secretos al repositorio.
- Usa `backend/.env.example` como plantilla.
- Los valores reales deben vivir en entornos locales o en GitHub Actions Secrets.

## Criterio de revisión

- El cambio debe ser legible y acotado.
- El PR debe explicar qué cambió, por qué cambió y cómo se validó.
- Si cambias contratos, flujos o setup, actualiza también la documentación relevante.
- Si el PR toca más de un subsistema, déjalo como draft hasta cerrar alcance y validación.

## Permisos mínimos recomendados

- colaboradores normales: `Write`
- admins: solo quienes necesiten gestionar settings o secrets
- agentes: trabajo por rama y PR, sin bypass sobre `main`
