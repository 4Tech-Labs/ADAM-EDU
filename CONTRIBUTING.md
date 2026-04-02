# Contributing to ADAM-EDU

ADAM-EDU se mantiene con un flujo estricto por pull request. `main` es la rama estable y nadie debe empujar cambios directos a esa rama.

## Manual Governance

Mientras GitHub no fuerce toda la proteccion de rama, el equipo adopta estas reglas como politica operativa:

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
3. Manten cada cambio enfocado. No mezcles funcionalidad, refactor y housekeeping en el mismo PR.
4. Ejecuta los checks locales antes de abrir el PR.
5. Abre un pull request.
6. Usa `squash merge` cuando el PR este aprobado y con checks verdes.

Si una migracion nueva endurece contratos de identidad o esquema, no parchees datos locales
a mano para forzar que pase. Resetea la base local y vuelve a sembrarla antes de rerun
`uv run --directory backend alembic upgrade head`.

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
- Si el cambio toca mas de un subsistema, el PR debe abrirse como draft.
- Si un agente encuentra cambios ajenos en el arbol, debe preservarlos y trabajar alrededor de ellos.

- La skill local del proyecto vive en `.agents/skills/adam-orchestrator/`.
- Los subagentes repo-scoped viven en `.codex/agents/`.
- El lock y bootstrap de gstack viven en `scripts/agents/`.
- `.agents/skills/gstack*` y `.claude/skills/*` son runtimes locales generados. No deben commitearse.
- Si cambias agent tooling, usa rama `agent/...` y PR dedicado.
- Despues de tocar agent tooling, rerun `bootstrap` y valida el runtime local antes de abrir el PR.

## Workflow compartido de agentes

El equipo trabaja por etapas, no por skills sueltas:

- Think -> Plan -> Build -> Review -> Test -> Ship -> Reflect

El entrypoint por defecto para trabajo sustancial es `adam-orchestrator`. Esa skill decide si el request debe ir a `office-hours`, `investigate`, `review`, `qa`, `ship` u otra skill de `gstack`.

Comandos de bootstrap:

```powershell
pwsh -File scripts/agents/bootstrap.ps1
```

```bash
./scripts/agents/bootstrap.sh
```

Si una persona ya tiene una instalacion global personal de `gstack`, puede mantenerla como fallback, pero la referencia compartida del equipo sigue siendo el lock pinneado y la configuracion repo-scoped de este repo.

## Secretos y entorno

- No subas secretos al repositorio.
- Usa `backend/.env.example` como plantilla.
- Los valores reales deben vivir en entornos locales o en GitHub Actions Secrets.

## Criterio de revision

- El cambio debe ser legible y acotado.
- El PR debe explicar que cambio, por que cambio y como se valido.
- Si cambias contratos, flujos o setup, actualiza tambien la documentacion relevante.
- Si el PR toca mas de un subsistema, dejalo como draft hasta cerrar alcance y validacion.

## Permisos minimos recomendados

- colaboradores normales: `Write`
- admins: solo quienes necesiten gestionar settings o secrets
- agentes: trabajo por rama y PR, sin bypass sobre `main`
