# Contributing to ADAM-EDU

ADAM-EDU se mantiene con un flujo estricto por pull request. `main` es la rama estable y nadie debe empujar cambios directos a esa rama.

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

## Secretos y entorno

- No subas secretos al repositorio.
- Usa `backend/.env.example` como plantilla.
- Los valores reales deben vivir en entornos locales o en GitHub Actions Secrets.

## Criterio de revisión

- El cambio debe ser legible y acotado.
- El PR debe explicar qué cambió, por qué cambió y cómo se validó.
- Si cambias contratos, flujos o setup, actualiza también la documentación relevante.
