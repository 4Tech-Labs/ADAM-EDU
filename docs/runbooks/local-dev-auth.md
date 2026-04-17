# Local Dev Auth Runbook

Este runbook fija el setup local canonico para auth y authoring despues de Issue 30.
Hay dos planos locales distintos. No los mezcles.

## Antes de empezar

- Docker Desktop o Docker Engine con Compose funcionando
- Supabase CLI instalada
- `uv` instalado
- Node.js 22 + npm

Opcional:

- `npx supabase ...` como fallback si no quieres una instalacion global

## Plano 1: authoring y app DB local

Este repo mantiene su base principal local fuera de Supabase CLI.

- Servicio: `adam-edu-postgres`
- Comando: `docker compose up -d adam-edu-postgres`
- Host: `localhost`
- Puerto host del repo: `5434`
- DSN backend local:
  `postgresql+psycopg://postgres:postgres@localhost:5434/postgres`

`DATABASE_URL` siempre apunta a este Postgres del repo cuando trabajas localmente.
No lo apuntes al Postgres interno de Supabase CLI.
El launcher `uv run --directory backend python -m shared.app` ahora valida esto en startup y rechaza hosts remotos de Supabase cuando corres en `development`.

## Plano 2: auth local y tooling de Supabase

Supabase CLI se usa para auth/session local y para obtener claves del stack local.

- Comando: `supabase start`
- API URL: `http://localhost:54321`
- DB URL interna del stack Supabase: `postgresql://postgres:postgres@localhost:54322/postgres`
- Studio: `http://localhost:54323`
- Mailpit: `http://localhost:54324`

El Postgres de Supabase CLI en `54322` no reemplaza la base principal del repo. Sirve
para el stack local de Supabase, no para `DATABASE_URL`.

El `supabase/config.toml` incluye redirects del shell auth-aware de Issue 5:
`/app/`, `/app/teacher` (compatibilidad), `/app/auth/callback`, `/app/teacher/activate`, `/app/join`. Para que los cambios de
`config.toml` tengan efecto local, reinicia Supabase: `supabase stop && supabase start`.

## Puertos remotos y de produccion

- `5432`: Supavisor session mode o conexion remota equivalente. No es el default local del repo.
- `6543`: Supavisor transaction mode remoto/serverless. No es setup local.

## Matriz runtime canonica

La fuente de verdad del perfil runtime de la API es el launcher:
`uv run --directory backend python -m shared.app`.

Resolucion de entorno efectivo:

- si `APP_ENV` esta definido y no vacio, tiene prioridad
- si `APP_ENV` no esta definido, usa `ENVIRONMENT`
- si ninguna variable esta definida, el default es `development`

| Entorno efectivo | Politica de reload | Evidencia operativa |
| --- | --- | --- |
| `development` | permitido, con watch scope solo en `backend/src` y exclusiones explicitas (`.venv`, `site-packages`, `node_modules`, `.git`, `build`, `dist`) | log `runtime_profile` con `reload_enabled=true` |
| cualquier valor distinto de `development` (por ejemplo `staging`, `production`) | deshabilitado; cualquier intento explicito de `--reload` falla en startup | error `Reload is forbidden...` + `reload_enabled=false` |

## Flujo recomendado en menos de 10 comandos

Los prerrequisitos anteriores no cuentan dentro de este flujo.

1. `docker compose up -d adam-edu-postgres`
2. `supabase start`
3. `supabase status -o env`
4. preparar `backend/.env` y `frontend/.env` desde sus ejemplos, con el mapping local correcto
5. `uv sync --directory backend --dev`
6. `uv run --directory backend alembic upgrade head`
7. `uv run --directory backend python -m shared.app`
8. `npm --prefix frontend install`
9. `npm --prefix frontend run dev`

Si usas el atajo opcional del root en entornos Unix-like, `make dev-backend` ya fuerza `DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5434/postgres` para evitar arrancar accidentalmente contra un pooler remoto.

## Traduccion de `supabase status -o env`

Usa `supabase status -o env` como fuente de verdad local para extraer los valores del
stack Supabase. Traducelos al naming del repo asi:

| Output Supabase CLI | Repo backend/frontend |
| --- | --- |
| `API_URL` | `SUPABASE_URL` y `VITE_SUPABASE_URL` |
| `ANON_KEY` | `VITE_SUPABASE_ANON_KEY` |
| `SERVICE_ROLE_KEY` | `SUPABASE_SERVICE_ROLE_KEY` |
| `JWT_SECRET` | `SUPABASE_JWT_SECRET` |

Convencion local del repo:

- `SUPABASE_PROJECT_REF=local`

## Variables a completar

Backend:

- `DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5434/postgres`
- `SUPABASE_URL=http://localhost:54321`
- `SUPABASE_PROJECT_REF=local`
- `SUPABASE_SERVICE_ROLE_KEY=<SERVICE_ROLE_KEY desde supabase status -o env>`
- `SUPABASE_JWT_SECRET=<JWT_SECRET desde supabase status -o env>`
- `MICROSOFT_TENANT_ID=`
- `INVITE_TEACHER_TTL_HOURS=72`
- `INVITE_STUDENT_TTL_HOURS=168`

Frontend:

- `VITE_SUPABASE_URL=http://localhost:54321`
- `VITE_SUPABASE_ANON_KEY=<ANON_KEY desde supabase status -o env>`
- `VITE_AUTH_CALLBACK_URL=http://localhost:5173/app/auth/callback`
- `VITE_APP_BASE_URL=http://localhost:5173/app`

Nunca lleves `SUPABASE_SERVICE_ROLE_KEY` al browser ni a ejemplos frontend.

## Smoke minimo

- `GET /health` responde `200`
- `GET /api/auth/me` sin bearer responde `401`
- `http://localhost:5173/app/` sin sesion muestra la landing con 3 entrypoints por rol
- `http://localhost:5173/app/teacher` redirige a `http://localhost:5173/app/teacher/case-designer`
- `http://localhost:5173/app/teacher/dashboard` sin sesion redirige a `http://localhost:5173/app/teacher/login`
- `http://localhost:5173/app/teacher/case-designer` sin sesion redirige a `http://localhost:5173/app/teacher/login`
- `http://localhost:5173/app/auth/callback` muestra spinner de "Completando inicio de sesion"

## Prerequisito manual para produccion

En Supabase Dashboard → Authentication → URL Configuration, agregar:

- `https://<TU-DOMINIO>/app/auth/callback`

Para Microsoft OAuth (Issue #6), agregar ademas en Azure AD la Redirect URI:

- `https://<TU-SUPABASE-PROJECT>.supabase.co/auth/v1/callback`

No incluir secretos de provider en el frontend ni en este runbook.

## Microsoft OAuth local

El scaffold local de `supabase/config.toml` deja preparado el bloque Azure, pero no lo
habilita en esta issue.

- usa `localhost`, no `127.0.0.1`, para redirect URIs locales
- las rutas funcionales actuales del shell docente son `/app/teacher/dashboard` y `/app/teacher/case-designer`; `/app/teacher` se mantiene como redirect de compatibilidad
- completa client id/secret y activa el provider antes de Issue 5
- callback local esperado: `http://localhost:54321/auth/v1/callback`

## Nota sobre RLS separada

`backend/sql/rls_policies.sql` no forma parte del happy path local de este repo. Alembic
no aplica ese archivo y solo debe usarse como paso separado cuando el entorno realmente
exponga helpers compatibles como `auth.uid()`.
