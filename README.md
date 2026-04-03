## ADAM EDU v8.0

ADAM EDU, en este corte, es un Teacher Authoring + Preview MVP. El repositorio publica el flujo docente que ya funciona: sugerencias para el formulario, generacion asincrona del caso con LangGraph, timeline por SSE y preview final para el profesor.

No incluye runtime de estudiante, super admin, auth real ni despliegue cloud endurecido. Esos frentes quedan fuera del alcance de esta subida para mantener el repo pequeno, honesto y estable.

Este repositorio evoluciona hoy como `ADAM-EDU`. El proyecto deriva del quickstart original de Gemini/LangGraph y conserva esa procedencia para fines de atribucion y trazabilidad, pero su desarrollo activo, gobernanza y flujo de colaboracion viven ya en esta linea de producto.

## Working Agreement

Mientras el repo opere sin enforcement completo de branch protection, `main` se trata como rama protegida por acuerdo operativo:

- nadie empuja directo a `main`
- todo cambio entra por pull request
- un PR solo se mergea con los 5 checks de CI en verde
- el merge operativo estandar es `Squash and merge`

La referencia viva para estas reglas esta en `CONTRIBUTING.md` y `docs/repo-governance.md`.

## Alcance actual

- `backend/src/case_generator/`: grafo LangGraph, prompts, schemas y servicios de authoring.
- `backend/src/shared/`: FastAPI app, DB, modelos, progress bus y contratos compartidos que siguen sosteniendo el flujo docente.
- `frontend/`: builder del profesor y preview editorial del caso generado.

La zona funcional principal del generador vive en `backend/src/case_generator/` y se mantiene congelada en este corte.

## Mapa de la raiz

- `docker-compose.yml`: stack local de desarrollo. Levanta la base PostgreSQL del proyecto y deja listo el entorno local base.
- `Dockerfile`: build contenedorizado del stack publicado. Se conserva para empaquetado del backend con el frontend compilado.
- `Makefile`: atajos opcionales para desarrollo en entornos Unix-like. Es conveniencia local, no la ruta principal de trabajo en Windows.
- `docs/adr/`: architecture decision records aceptados. Aqui vive la decision canonica del auth perimeter de Fase 1.
- `docs/runbooks/`: runbooks operativos del repo. Aqui vive el setup local canonico de auth y authoring.
- `docs/archive/MASTER_AUDIT_PLAN.md`: auditoria historica archivada. Se conserva como referencia, pero ya no gobierna el alcance operativo del repo.

### Root hygiene

La raiz del repo se mantiene minima y operativa. Artefactos locales generados como `.claude/`, `.vscode/`, `.mypy_cache/` y `.python-version` no forman parte del repo publicado. Las excepciones intencionales de agent tooling son `.agents/skills/adam-orchestrator/`, `.codex/agents/` y `scripts/agents/`.

## Mapa del backend

- `backend/src/case_generator/`: dominio funcional del producto. Aqui vive la logica de negocio del authoring, el grafo LangGraph, los prompts, adapters y servicios del generador de casos.
- `backend/src/shared/`: capa comun de app e infraestructura del MVP docente. Aqui viven FastAPI, base de datos, ORM, progress bus SSE, sanitizacion y contratos de soporte usados por el flujo docente.
- `backend/tests/`: validacion del backend docente. `tests/integration/` cubre validacion live del flujo/grafo y `tests/validation/` cubre shape y adapters.
- `backend/alembic/`: trazabilidad del esquema y migraciones historicas del backend.

`backend/src/shared/` tambien conserva modelos y schemas historicos retenidos por continuidad de base de datos y de contratos internos. Se mantienen en este corte aunque el repo publicado sea teacher-only.

### Naming freeze

En este corte no se renombran carpetas del backend.

- `case_generator` queda congelado porque es el nucleo funcional probado del repo.
- `shared` se conserva por estabilidad aunque sea un nombre generico.
- Cualquier rename futuro debe abrirse como refactor dedicado, no mezclado con el cierre de esta fase.

### Backend freeze zone

En limpiezas cosmeticas de esta fase no tocar:

- `backend/src/case_generator/graph.py`
- `backend/src/case_generator/prompts.py`

El endpoint interno `/api/internal/tasks/authoring_step` se conserva como seam de orquestacion interna/local. No implica que este repo publique ya un perimetro cloud endurecido.

## Mapa del frontend

- `frontend/src/app/`: shell del frontend. Aqui viven router, entrypoint, layout base y estilos globales.
- `frontend/src/features/teacher-authoring/`: flujo docente real. Contiene formulario, submit del job, SSE, timeline y estados del authoring.
- `frontend/src/features/case-preview/`: preview editorial del caso generado, incluyendo renderers y modulos `M1..M6`.
- `frontend/src/shared/`: piezas transversales del MVP. Aqui viven cliente API, tipos compartidos, header, toast, utilidades y primitives UI.

### Frontend naming freeze

En este corte no se renombran carpetas del frontend.

- `app`, `teacher-authoring`, `case-preview` y `shared` quedan congeladas como convencion estable del MVP.
- No reabrir carpetas top-level genericas como `components`, `pages`, `hooks`, `helpers`, `common` o `misc`.
- Si aparece nueva logica de producto, debe abrirse como feature explicita y no dentro de `shared/`.

## Flujo del MVP docente

1. `POST /api/suggest` ayuda a completar escenario y tecnicas del formulario.
2. `POST /api/authoring/jobs` es teacher-only y requiere bearer JWT valido; crea `Assignment` + `AuthoringJob` sin confiar en `teacher_id` del cliente.
3. `AuthoringService.run_job()` ejecuta el grafo y persiste el resultado.
4. `GET /api/authoring/jobs/{job_id}/progress` emite progreso por SSE autenticado con ownership exacto por docente.
5. `GET /api/authoring/jobs/{job_id}` permite polling autenticado del job.
6. `GET /api/authoring/jobs/{job_id}/result` devuelve el resultado persistido para preview del owner.
7. `GET /api/auth/me` expone `CurrentActor`, memberships y `must_rotate_password`.
8. `POST /api/invites/resolve`, `POST /api/invites/redeem`, `POST /api/auth/activate/password` y `POST /api/auth/activate/oauth/complete` consumen `invite_token` por body.

El frontend usa ese flujo para renderizar el timeline y el `CasePreview` del profesor.

## Setup local

El setup local canonico vive en [docs/runbooks/local-dev-auth.md](docs/runbooks/local-dev-auth.md).

Resumen corto:

- plano `authoring/app DB local`: `docker compose up -d adam-edu-postgres` en `5434`
- plano `auth local`: `supabase start` con API `54321`, DB `54322`, Studio `54323` y Mailpit `54324`
- referencias remotas: `5432` para session mode y `6543` para transaction mode, nunca como default local del repo

El error mas comun en esta fase es apuntar `DATABASE_URL` al Postgres de Supabase local.
No lo hagas. `DATABASE_URL` local del repo sigue apuntando a `localhost:5434`.

## Shared agent tooling

El repo usa un workflow de agentes Codex-first. La superficie oficial compartida es pequena y auditable:

- skill local del proyecto: `.agents/skills/adam-orchestrator/`
- subagentes repo-scoped: `.codex/agents/`
- bootstrap y lock pinneado de gstack: `scripts/agents/`

Los runtimes generados siguen siendo locales:

- Codex: `.agents/skills/gstack*`
- Claude: `.claude/skills/*`

No edites esos runtimes a mano. Rebuildlos con bootstrap.

Bootstrap recomendado en Windows:

```powershell
pwsh -File scripts/agents/bootstrap.ps1
pwsh -File scripts/agents/bootstrap.ps1 -RuntimeHost codex
pwsh -File scripts/agents/bootstrap.ps1 -RuntimeHost claude
```

Bootstrap equivalente en entornos bash:

```bash
./scripts/agents/bootstrap.sh
./scripts/agents/bootstrap.sh --host codex
./scripts/agents/bootstrap.sh --host claude
```

`bootstrap`:

1. lee `scripts/agents/gstack.lock.json`
2. clona o actualiza `gstack` al commit pinneado dentro del runtime ignorado por git
3. ejecuta `setup` para el host correspondiente
4. copia `adam-orchestrator` a `.claude/skills/adam-orchestrator` cuando se pide compatibilidad con Claude

El workflow esperado es natural-language-first. El equipo no deberia depender de memorizar skills una por una. El estandar oficial del repo es Codex-first, con Claude como compatibilidad derivada del mismo bootstrap. Para trabajo sustancial:

- el primer router es `adam-orchestrator`
- `adam-orchestrator` despacha a la skill correcta de `gstack`
- preguntas pequenas, read-only o puramente explicativas pueden resolverse inline

Ver guia completa: [docs/agent-workflow.md](docs/agent-workflow.md)

### Actualizar el pin de gstack

Hazlo solo en un PR dedicado `agent/...`:

```powershell
pwsh -File scripts/agents/update-gstack-lock.ps1
```

```bash
./scripts/agents/update-gstack-lock.sh
```

Luego rerun `bootstrap` y valida el runtime local.

### Fallback individual

Si alguien prefiere una instalacion global fuera del repo, puede mantenerla como entorno personal. No es la ruta principal del equipo y no sustituye el lock pinneado ni la skill local versionada en este repo.

### Prerrequisitos

- Docker Desktop o Docker Engine con Compose funcionando
- Supabase CLI instalada
- Python 3.12
- `uv`
- Node.js 22 + npm

`npx supabase ...` puede servir como fallback personal, pero la ruta principal del repo
asume CLI instalada y scaffold committeado.

### Arranque recomendado

Sigue el runbook:

- [docs/runbooks/local-dev-auth.md](docs/runbooks/local-dev-auth.md)

Ese runbook deja el flujo operativo en menos de 10 comandos reales y mantiene los
prerrequisitos fuera del conteo.

### Stack contenedorizado opcional

Si quieres probar la API y PostgreSQL por Docker, el compose ya construye la imagen automaticamente desde el repo:

```powershell
docker compose up -d --build
```

Servicios esperados:

- PostgreSQL: `adam-edu-postgres`
- API: `adam-edu-api`

Puertos por defecto:

- PostgreSQL: `localhost:5434`
- API: `localhost:8123`

Notas:

- Para esta opcion, `GEMINI_API_KEY` debe existir en tu shell o en un archivo `.env` de la raiz usado por Docker Compose.
- Esta ruta no sustituye el runbook canonico de auth local. El compose deja la API alineada con `DATABASE_URL`, pero el flujo recomendado sigue siendo backend/frontend locales + `supabase start`.
- Si quieres que la API en Docker use auth local, debes inyectar `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` y `SUPABASE_JWT_SECRET` de forma explicita. No se asume como happy path del repo.
- Dentro del contenedor, `SUPABASE_URL=http://localhost:54321` es incorrecto porque `localhost` apunta al propio contenedor. En Docker Desktop usa una URL alcanzable desde el contenedor, por ejemplo `http://host.docker.internal:54321`; en otros entornos Docker usa el hostname equivalente de tu host.
- Si solo necesitas base de datos para desarrollo, usa el runbook canonico; esa es la ruta principal recomendada.

### Apagar el entorno Docker

```powershell
docker compose down
```

Si necesitas eliminar tambien el volumen local de PostgreSQL:

```powershell
docker compose down -v
```

## Variables de entorno

- `DATABASE_URL`: DSN principal del Postgres local del repo. En local apunta a `localhost:5434`, no a `54322`.
- `SUPABASE_URL`: URL del plano de auth/session. En local via Supabase CLI apunta a `http://localhost:54321`.
- `SUPABASE_PROJECT_REF`: ref documental para tooling y validaciones. En local la convencion del repo es `local`.
- `SUPABASE_SERVICE_ROLE_KEY`: clave backend-only para activation/password y operaciones admin. Sale de `supabase status -o env`.
- `SUPABASE_JWT_SECRET`: fallback de desarrollo para JWT locales. Sale de `supabase status -o env`. No sustituye JWKS en produccion.
- `MICROSOFT_TENANT_ID`: placeholder para la configuracion local/remota de Azure en las siguientes issues.
- `INVITE_TEACHER_TTL_HOURS`: TTL de invitaciones de docentes.
- `INVITE_STUDENT_TTL_HOURS`: TTL de invitaciones de estudiantes.
- `GEMINI_API_KEY`: requerido para authoring real, `/api/suggest` y tests `live_llm`.
- `CORS_ALLOWED_ORIGIN`: origen extra permitido en produccion.
- `STORYTELLER_MODEL`: override opcional del modelo usado por `/api/suggest`.
- `VITE_SUPABASE_URL`: URL publica del plano auth/session. En local apunta a `http://localhost:54321`.
- `VITE_SUPABASE_ANON_KEY`: anon/publishable key usada por el frontend para leer la sesion actual. Sale de `supabase status -o env`.

Nunca expongas `SUPABASE_SERVICE_ROLE_KEY` en frontend, browser, ejemplos de Vite o docs de UI.

Base de ejemplo: [backend/.env.example](backend/.env.example)
Frontend base de ejemplo: [frontend/.env.example](frontend/.env.example)

### Nota para Issue 23

El sustrato de identidad de GitHub `#23` mantiene el bridge `users.id == auth.users.id`
como contrato de datos. El entorno local actual usa dos planos distintos y los dos son
obligatorios:

- Postgres del repo por Docker en `5434`
- Supabase CLI para auth local en `54321`

Eso significa:

- valida esquema y migraciones de la app contra el Postgres del repo
- valida auth/session local contra Supabase CLI
- no apuntes `DATABASE_URL` al Postgres interno de Supabase CLI en `54322`
- si tu base local vieja todavia tiene IDs fake como `teacher-123`, reseteala y reseedala antes de correr la migracion de Issue 23
- `backend/sql/rls_policies.sql` es un entregable separado de Alembic y no se aplica con `uv run alembic upgrade head`
- esas policies dependen de `auth.uid()`, asi que solo deben aplicarse en Supabase o en un entorno local que realmente exponga el schema Auth compatible

## Validacion

- Backend tests:
  `uv run --directory backend pytest -q`
- Type checking:
  `uv run --directory backend mypy src`
- Frontend build:
  `npm --prefix frontend run build`
- Frontend tests:
  `npm --prefix frontend run test`
- Live LLM:
  `RUN_LIVE_LLM_TESTS=1 uv run --directory backend pytest -m live_llm -q`

La suite default no debe tocar Gemini ni depender de side effects externos. Los tests `live_llm` quedan aislados detras de `RUN_LIVE_LLM_TESTS=1`.

La prueba de migracion de Issue 23 crea y elimina bases temporales para validar upgrade y downgrade de Alembic. Con los defaults locales funciona porque el usuario `postgres` tiene permisos amplios sobre el contenedor local. Si apuntas a otro Postgres, asegurate de tener permisos `CREATE DATABASE` y `DROP DATABASE` o esa prueba fallara aunque el codigo este bien.

## Nota historica

`docs/archive/MASTER_AUDIT_PLAN.md` se conserva solo como documento historico de auditoria y ya no define el alcance operativo del repo publicado.

## Para contributors

Lee [CLAUDE.md](CLAUDE.md) antes de abrir cambios grandes.
Lee [docs/adr/0001-auth-perimeter-fase1.md](docs/adr/0001-auth-perimeter-fase1.md) si vas a tocar auth, tenancy o trust boundaries de Fase 1.
Lee [docs/agent-workflow.md](docs/agent-workflow.md) si vas a trabajar con Codex, Claude o tooling de agentes.
