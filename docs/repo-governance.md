# Repository Governance

`ADAM-EDU` opera hoy con gobernanza manual equivalente a una rama protegida, aunque GitHub no aplique todas las restricciones automáticamente en este plan.

## Reglas operativas

- `main` se considera rama protegida.
- Nadie hace push directo a `main`.
- Todo cambio entra por pull request.
- Todo PR debe pasar estos checks antes de mergear:
  - `backend-test`
  - `backend-typecheck`
  - `frontend-build`
  - `frontend-lint`
  - `frontend-test`
- El mecanismo de merge por defecto es `Squash and merge`.
- Si no hay PR, el cambio no existe.
- Cambios a tooling compartido de agentes (`.agents/skills/adam-orchestrator/`, `.codex/agents/`, `scripts/agents/`) deben entrar por ramas `agent/...` y PR dedicado.
- Los runtimes locales `.agents/skills/gstack*` y `.claude/skills/*` no forman parte del arbol versionado del producto.

## Permisos recomendados

- Developers humanos: `Write`
- Administradores: solo quienes necesiten settings, teams o secrets
- Agentes: rama + PR; nunca push directo a `main`

## Metadata recomendada del repo

Descripcion sugerida:

`Teacher authoring and preview MVP for pedagogical business cases built on LangGraph.`

Topics sugeridos:

- `langgraph`
- `fastapi`
- `react`
- `vite`
- `education`

## Labels base sugeridos

- `bug`
- `enhancement`
- `dependencies`
- `ci`
- `docs`

## Validación mínima por PR

1. El cambio vive en una rama corta y temática.
2. CI corre completo.
3. El autor revisa el diff final antes del merge.
4. El merge se hace por squash.
5. La rama se elimina después del merge.
