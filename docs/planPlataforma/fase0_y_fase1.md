# Plan de arquitectura e issue map para Fase 0 y Fase 1

Documento de planeacion para convertir el requerimiento fuente en un backlog ejecutable
sin modificar codigo de producto por accidente ni abrir huecos de seguridad durante la
migracion desde el MVP teacher-only actual. Este archivo es el single source of truth
para abrir issues de Fase 0 y Fase 1 sin tener que consultar otros documentos para
entender el alcance, los contratos y los criterios de aceptacion.

## Referencias

- Fuente funcional: [Parte1-Inicio-Registro.md](./Parte1-Inicio-Registro.md)
- Mockup docente: [LOGIN_PROFESOR.HTML](./Mockups/profesor/LOGIN_PROFESOR.HTML)
- Mockup estudiante: [LOGIN_ESTUDIANTE.html](./Mockups/estudiante/LOGIN_ESTUDIANTE.html)
- Mockup admin: [Dashboard_admin.html](./Mockups/admin/Dashboard_admin.html)
- Estado real del frontend: [frontend/src/app/App.tsx](../../frontend/src/app/App.tsx)
- Basename actual del frontend: [frontend/src/app/main.tsx](../../frontend/src/app/main.tsx)
- FastAPI app actual: [backend/src/shared/app.py](../../backend/src/shared/app.py)
- Modelos actuales: [backend/src/shared/models.py](../../backend/src/shared/models.py)
- Engine y pooling actual: [backend/src/shared/database.py](../../backend/src/shared/database.py)
- Variables backend actuales: [backend/.env.example](../../backend/.env.example)
- Stack local actual: [docker-compose.yml](../../docker-compose.yml)
- Onboarding y setup actual: [README.md](../../README.md)
- Flujo de contribucion actual: [CONTRIBUTING.md](../../CONTRIBUTING.md)
- Migracion inicial legacy: [backend/alembic/versions/26812dc7bf5c_initial_phase_1a_data_layer.py](../../backend/alembic/versions/26812dc7bf5c_initial_phase_1a_data_layer.py)

## Resumen ejecutivo

Este repo hoy publica un MVP docente funcional bajo `/app/teacher`. El backend acepta
`teacher_id` desde el cliente, autocrea `Tenant/User` si faltan y monta en un solo
proceso authoring, polling, SSE, `/api/suggest` y la SPA. Eso sirve para authoring
local, pero no sirve como perimeter de autenticacion multi-tenant.

La arquitectura aprobada para Fase 0 y Fase 1 mantiene una sola base de datos en
Supabase Postgres, usa Supabase Auth como sistema de identidad, conserva FastAPI como
application plane y deja el split `public-api` / `authoring-worker` para despues de
cerrar el auth perimeter del monolito actual.

No se depende de custom claims en la ruta critica. El backend verifica JWT localmente
con JWKS, resuelve actor por lookup a DB y trata RLS como defensa secundaria, no como
mecanismo principal de autorizacion para SQLAlchemy. Este backlog ya incorpora el issue
DevX faltante, el archivo SQL separado con las policies de RLS, el endurecimiento de
PKCE y callback OAuth, el contrato fail-closed del cambio de password admin y el
hardening operativo de deploy sin mover ninguna decision arquitectonica cerrada.

## What already exists

- Ya existe un monolito funcional con:
  - `POST /api/authoring/jobs`
  - `POST /api/internal/tasks/authoring_step`
  - `GET /api/authoring/jobs/{job_id}`
  - `GET /api/authoring/jobs/{job_id}/result`
  - `GET /api/authoring/jobs/{job_id}/progress`
  - `POST /api/suggest`
- Ya existen tablas legacy que sostienen el MVP actual: `tenants`, `users`,
  `assignments`, `authoring_jobs`, `artifact_manifests`, mas tablas runtime retenidas.
- Ya existe el shell frontend bajo `/app/*` con `BrowserRouter basename="/app/"`.
- Ya existe un seam probado para Cloud Tasks e idempotencia de authoring. No se debe
  re-plataformar ese tramo antes de resolver auth.
- El repo hoy usa `docker compose` para la base local del producto en host `5434`.
- `supabase start` todavia no es la ruta canonica del repo para auth local, pero queda
  fijado como parte del backlog de Fase 0.

## Decisiones cerradas

- La SPA sigue servida por `public-api` bajo `/app/*` en Fase 1.
- No se abre un frontend host separado ni se mete PostgREST en el flujo de producto.
- No hay `signUp` publico para docentes, estudiantes o admins.
- La alta por password ocurre solo via backend invite-gated con Service Role.
- Los links de invitacion usan fragmento, no path:
  - `/app/teacher/activate#invite_token=<token>`
  - `/app/join#invite_token=<token>`
- El token nunca viaja en path params ni en OAuth `state`.
- El frontend limpia el fragmento al montar y luego manda el token solo por `POST`.
- El callback OAuth no contiene token sensible. El frontend persiste contexto corto de
  activacion en `sessionStorage` y completa el flujo al volver.
- `profiles` es global por usuario. No tiene `university_id`.
- `memberships` representa pertenencia activa o suspendida a una universidad. La
  invitacion no vive dentro de `memberships`.
- `invites` es el unico artefacto pre-usuario o pre-membership.
- `courses` referencia `teacher_membership_id`.
- `course_memberships` referencia `membership_id`.
- Se conserva el bridge legacy `users.id == auth.users.id` como string UUID para no
  tocar `backend/src/case_generator/**` en esta fase.
- El backend no depende de custom claims para `role`, `university_id` ni
  `must_rotate_password`.
- La verificacion JWT usa JWKS, `issuer` y `audience`. `SUPABASE_JWT_SECRET` queda solo
  como fallback local controlado para desarrollo.
- El provisioning admin se fija por CLI/runbook, no por endpoint HTTP interno.
- No se promete atomicidad entre Supabase Auth y writes de aplicacion. Se exige
  idempotencia, compensacion y fail-closed.
- Microsoft SSO queda modelado por `university_id`, pero en Fase 1 solo se habilita un
  tenant Microsoft activo por deployment.
- RLS se mantiene como defensa secundaria.
- El split `public-api` / `authoring-worker` queda despues de cerrar Issue 3.

## No negociables

- No auto-registro publico para docentes ni admins.
- No enlaces de invitacion generados en frontend.
- No CTA de "Olvide mi contrasena" si el flujo no existe.
- No token de invitacion en URL path, query string, logs o `state`.
- No `teacher_id`, `student_id`, `role` ni `auth_user_id` en body de requests
  autenticados como fuente de verdad.
- No exposicion publica del `authoring-worker`.
- No dependencia de claims custom para guardar negocio critico.
- No dashboard admin "fake" usado como sustituto del login real.
- No documentar `5432` como puerto host local por defecto del repo.

## NOT in Scope

- Multi-university Microsoft SSO con mas de un proveedor activo en el mismo deployment
- Frontend consultando tablas de dominio via Supabase/PostgREST
- Migracion de IDs string UUID legacy a columnas nativas `uuid`
- Password reset self-serve
- MFA obligatoria
- Dashboard admin funcional completo
- Hosting frontend separado de `public-api`

## Arquitectura objetivo

```text
Browser SPA (/app/*)
        |
        v
   public-api (FastAPI)
        |
        +--> Supabase Auth (JWT issuance, OAuth, password auth)
        |
        +--> Supabase Postgres
        |      - profiles
        |      - memberships
        |      - invites
        |      - allowed_email_domains
        |      - courses
        |      - course_memberships
        |      - university_sso_configs
        |      - legacy bridge: users / assignments / authoring_jobs
        |
        +--> Cloud Tasks
               |
               v
         authoring-worker (private Cloud Run)
               |
               v
      backend/src/case_generator/**
```

## Modelo de datos aprobado

### Nuevas tablas de acceso

- `profiles`
  - `id TEXT PK`, mismo valor que `auth.users.id`
  - `full_name TEXT NOT NULL`
  - `created_at TIMESTAMPTZ NOT NULL`
  - `updated_at TIMESTAMPTZ NOT NULL`

- `memberships`
  - `id TEXT PK`
  - `user_id TEXT NOT NULL REFERENCES profiles(id)`
  - `university_id TEXT NOT NULL REFERENCES tenants(id)`
  - `role TEXT NOT NULL CHECK (role IN ('teacher', 'student', 'university_admin'))`
  - `status TEXT NOT NULL CHECK (status IN ('active', 'suspended'))`
  - `must_rotate_password BOOLEAN NOT NULL DEFAULT FALSE`
  - `created_at TIMESTAMPTZ NOT NULL`
  - `updated_at TIMESTAMPTZ NOT NULL`
  - `UNIQUE(user_id, university_id, role)`

- `invites`
  - `id TEXT PK`
  - `token_hash TEXT UNIQUE NOT NULL`
  - `email TEXT NOT NULL`
  - `university_id TEXT NOT NULL REFERENCES tenants(id)`
  - `course_id TEXT NULL`
  - `role TEXT NOT NULL CHECK (role IN ('teacher', 'student'))`
  - `status TEXT NOT NULL CHECK (status IN ('pending', 'consumed', 'expired', 'revoked'))`
  - `expires_at TIMESTAMPTZ NOT NULL`
  - `consumed_at TIMESTAMPTZ NULL`
  - `created_at TIMESTAMPTZ NOT NULL`

- `allowed_email_domains`
  - `id TEXT PK`
  - `university_id TEXT NOT NULL REFERENCES tenants(id)`
  - `domain TEXT NOT NULL`
  - `created_at TIMESTAMPTZ NOT NULL`
  - `UNIQUE(university_id, domain)`

- `courses`
  - `id TEXT PK`
  - `university_id TEXT NOT NULL REFERENCES tenants(id)`
  - `teacher_membership_id TEXT NOT NULL REFERENCES memberships(id)`
  - `title TEXT NOT NULL`
  - `created_at TIMESTAMPTZ NOT NULL`

- `course_memberships`
  - `id TEXT PK`
  - `course_id TEXT NOT NULL REFERENCES courses(id)`
  - `membership_id TEXT NOT NULL REFERENCES memberships(id)`
  - `created_at TIMESTAMPTZ NOT NULL`
  - `UNIQUE(course_id, membership_id)`

- `university_sso_configs`
  - `id TEXT PK`
  - `university_id TEXT NOT NULL REFERENCES tenants(id)`
  - `provider TEXT NOT NULL CHECK (provider IN ('azure'))`
  - `azure_tenant_id TEXT NOT NULL`
  - `client_id TEXT NOT NULL`
  - `enabled BOOLEAN NOT NULL DEFAULT FALSE`
  - `created_at TIMESTAMPTZ NOT NULL`
  - `updated_at TIMESTAMPTZ NOT NULL`
  - `UNIQUE(university_id, provider)`

### Legacy bridge obligatorio

- `users.id` se alinea a `auth.users.id`
- `users.role` se normaliza a lowercase
- `assignments.teacher_id` sigue apuntando a `users.id`
- Ningun cambio funcional entra a `backend/src/case_generator/**`

## Grafo de dependencias entre issues

```text
Issue 1 (ADR)                -> sin dependencias
Issue 2 (Identity substrate) -> depende de Issue 1
Issue 3 (Auth perimeter)     -> depende de Issue 2
Issue 4 (DevX local)         -> sin dependencias
Issue 5 (Frontend shell)     -> depende de Issue 3
Issue 6 (Teacher flow)       -> depende de Issue 5
Issue 7 (Student flow)       -> depende de Issue 5
Issue 8 (Admin flow)         -> depende de Issue 5
Issue 9 (Deploy hardening)   -> depende de Issue 3
Issue 10 (Security ops)      -> depende de Issue 6, Issue 7, Issue 8, Issue 9
Issue 11 (Tests and QA)      -> depende de Issue 6, Issue 7, Issue 8, Issue 9, Issue 10
```

## Paralelizacion recomendada

| Step | Issues | Modules touched | Depends on |
|------|--------|-----------------|------------|
| ADR y decisiones de perimeter | Issue 1 | docs de arquitectura y repo governance | - |
| Identity substrate | Issue 2 | `backend/alembic`, `backend/src/shared/models`, SQL RLS separado | Issue 1 |
| Auth perimeter | Issue 3 | `backend/src/shared` | Issue 2 |
| DevX local y convenciones | Issue 4 | `.env.example`, `README.md`, `CONTRIBUTING.md`, runbooks | - |
| Frontend auth shell | Issue 5 | `frontend/src/app`, `frontend/src/shared`, `frontend/src/features/*-auth` | Issue 3 |
| Teacher flow | Issue 6 | `frontend/src/features/teacher-auth`, `backend/src/shared` | Issue 5 |
| Student flow | Issue 7 | `frontend/src/features/student-auth`, `backend/src/shared` | Issue 5 |
| Admin flow | Issue 8 | `frontend/src/features/admin-auth`, `backend/src/shared`, `scripts/` | Issue 5 |
| Deploy hardening | Issue 9 | `backend/src/shared`, `backend/pyproject.toml`, infra config, docs | Issue 3 |
| Security ops | Issue 10 | auth backend, auditoria, runbooks, policy docs | Issue 6, Issue 7, Issue 8, Issue 9 |
| Tests y QA gate | Issue 11 | backend tests, frontend tests, browser QA | Issue 6, Issue 7, Issue 8, Issue 9, Issue 10 |

- Lane A: Issue 1 -> Issue 2 -> Issue 3
- Lane B: Issue 4
- Lane C: Issue 5 y Issue 9 salen despues de Issue 3 y pueden avanzar en paralelo
- Lane D: Issue 6 despues de Issue 5
- Lane E: Issue 7 despues de Issue 5
- Lane F: Issue 8 despues de Issue 5
- Issue 10 cierra cuando Issue 6, Issue 7, Issue 8 e Issue 9 esten completos
- Issue 11 cierra al final como gate de fase

## Mapa de issues

Los issues de abajo quedan listos para copiar a GitHub con backlog claro, dependencias
explicitas y criterios de aceptacion testeables.

---

## Fase 0

### Issue 1

**Titulo:** `ADR: auth perimeter, trust boundaries y stack de acceso para Fase 1`

**Tipo:** `Infra`

**Dependencias:** ninguna

**Descripcion:**
Formalizar la arquitectura base para pasar del MVP teacher-only actual a una plataforma
con auth real. El ADR debe fijar trust boundaries, aclarar por que el monolito actual se
mantiene hasta cerrar auth perimeter, y documentar que el split `public-api` /
`authoring-worker` ocurre despues, no antes.

**Tareas (Checklist):**

- [ ] Documentar el estado real del repo:
  - monolito FastAPI con authoring, SSE y SPA
  - frontend shell docente bajo `/app/teacher`
  - `teacher_id` enviado por el cliente
  - autocreacion de `Tenant/User` en `POST /api/authoring/jobs`
- [ ] Documentar que Supabase Auth es source of truth de identidad.
- [ ] Documentar que Supabase Postgres es el unico plano de datos para acceso.
- [ ] Documentar que FastAPI sigue siendo el application plane y que el frontend no usa
      PostgREST para datos de dominio.
- [ ] Fijar que JWT se verifica localmente con JWKS, `issuer` y `audience`.
- [ ] Dejar `SUPABASE_JWT_SECRET` solo como fallback local, nunca como camino primario de
      produccion.
- [ ] Fijar que no hay custom claims en la ruta critica.
- [ ] Fijar que RLS es defensa secundaria y no reemplaza el auth perimeter del backend.
- [ ] Fijar que la SPA sigue servida por `public-api`.
- [ ] Fijar que Fase 1 modela `university_sso_configs`, pero solo habilita un tenant
      Microsoft activo por deployment.
- [ ] Fijar que el split `public-api` / `authoring-worker` queda despues de cerrar Issue 3.
- [ ] Documentar triggers de salida del stack:
  - drift operacional entre universidades y un solo tenant Microsoft
  - p95 DB fuera de presupuesto
  - egress o latencia inaceptable entre Cloud Run y Supabase
  - necesidad real de multi-provider SSO
- [ ] Incluir seccion `NOT in Scope`.

**Criterios de Aceptacion:**

- Existe un ADR versionado que fija trust boundaries y limites de Fase 1.
- El ADR deja claro que el monolito actual se reutiliza primero y se divide despues.
- El ADR deja claro que JWKS es el mecanismo de verificacion JWT de produccion.
- El ADR deja claro que no hay token de invitacion en URL path ni `state`.
- El ADR deja claro que Microsoft SSO es tenant-scoped en modelo pero limitado en rollout.

**Notas Tecnicas:**

- Archivos a referenciar:
  - [backend/src/shared/app.py](../../backend/src/shared/app.py)
  - [backend/src/shared/models.py](../../backend/src/shared/models.py)
  - [frontend/src/app/App.tsx](../../frontend/src/app/App.tsx)
  - [frontend/src/app/main.tsx](../../frontend/src/app/main.tsx)
- Fuentes externas:
  - Supabase JWT/JWKS
  - Supabase SQLAlchemy + transaction pooler
  - Cloud Tasks OIDC token

---

### Issue 2

**Titulo:** `Infra: schema de identidad, memberships, invites, RLS secundaria y bridge legacy`

**Tipo:** `Infra`

**Dependencias:** Issue 1

**Descripcion:**
Crear el sustrato de datos para auth y multi-tenancy sin romper el authoring actual. Este
issue introduce las nuevas tablas de acceso, cierra el bridge con `users` legacy para
que `backend/src/case_generator/**` siga intacto durante Fase 1 y deja RLS secundaria
documentada en un archivo SQL separado fuera de Alembic.

**Tareas (Checklist):**

- [ ] Crear migracion Alembic para:
  - `profiles`
  - `memberships`
  - `invites`
  - `allowed_email_domains`
  - `courses`
  - `course_memberships`
  - `university_sso_configs`
- [ ] Crear un archivo SQL separado, por ejemplo `backend/sql/rls_policies.sql`, fuera
      de Alembic pero referenciado explicitamente como entregable del issue.
- [ ] Definir `profiles.id == auth.users.id`.
- [ ] Definir `users.id == auth.users.id` como bridge legacy.
- [ ] Normalizar `users.role` a lowercase y documentar el mapping:
  - `Teacher` -> `teacher`
  - `Student` -> `student`
  - `UniversityAdmin` o equivalente -> `university_admin`
- [ ] Crear backfill para `users.role` legacy si hay datos locales existentes.
- [ ] Eliminar del plan cualquier uso de `memberships.status = invited`.
- [ ] Dejar `invites` como unico estado pre-activacion.
- [ ] Fijar `memberships.status` a `active | suspended`.
- [ ] Fijar `must_rotate_password` como flag booleana leida desde DB.
- [ ] Fijar `courses.teacher_membership_id`.
- [ ] Fijar `course_memberships.membership_id`.
- [ ] Modelar `allowed_email_domains` por universidad, no por deployment.
- [ ] Modelar `university_sso_configs` por universidad aunque Fase 1 use un solo tenant
      Microsoft activo.
- [ ] Crear indices minimos para:
  - `invites.token_hash`
  - `memberships.user_id`
  - `memberships.university_id`
  - `allowed_email_domains.university_id`
  - `course_memberships.course_id`
  - `course_memberships.membership_id`
- [ ] Documentar que el compare de hashes fuera de SQL debe usar
      `hmac.compare_digest()`.
- [ ] Eliminar del documento cualquier dependencia critica de custom claims o hooks de
      Supabase.
- [ ] Mantener explicito que RLS es defensa secundaria y no sustituye el auth perimeter
      del backend.

**Criterios de Aceptacion:**

- Existe una migracion Alembic clara con todas las tablas nuevas.
- Existe `rls_policies.sql` como entregable separado y referenciado por el issue.
- `profiles`, `memberships` e `invites` no mezclan estados de negocio incompatibles.
- El bridge `users.id == auth.users.id` queda fijado y documentado.
- Las relaciones `courses -> memberships` y `course_memberships -> memberships` quedan
  cerradas.
- El issue deja explicito que no se toca `backend/src/case_generator/**`.

**Notas Tecnicas:**

- Archivos base:
  - [backend/src/shared/models.py](../../backend/src/shared/models.py)
  - [backend/alembic/versions/26812dc7bf5c_initial_phase_1a_data_layer.py](../../backend/alembic/versions/26812dc7bf5c_initial_phase_1a_data_layer.py)
- Variables de entorno relacionadas:
  - `SUPABASE_URL`
  - `SUPABASE_PROJECT_REF`
- El archivo `rls_policies.sql` debe incluir como minimo el SQL completo siguiente:

```sql
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE courses ENABLE ROW LEVEL SECURITY;
ALTER TABLE course_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE invites ENABLE ROW LEVEL SECURITY;
ALTER TABLE allowed_email_domains ENABLE ROW LEVEL SECURITY;
ALTER TABLE university_sso_configs ENABLE ROW LEVEL SECURITY;

CREATE POLICY profiles_self ON profiles
  FOR ALL
  USING (id = auth.uid()::text)
  WITH CHECK (id = auth.uid()::text);

CREATE POLICY memberships_self ON memberships
  FOR SELECT
  USING (user_id = auth.uid()::text);

CREATE POLICY courses_by_university ON courses
  FOR SELECT
  USING (
    university_id IN (
      SELECT m.university_id
      FROM memberships m
      WHERE m.user_id = auth.uid()::text
        AND m.status = 'active'
    )
  );

CREATE POLICY course_memberships_self ON course_memberships
  FOR SELECT
  USING (
    membership_id IN (
      SELECT m.id
      FROM memberships m
      WHERE m.user_id = auth.uid()::text
        AND m.status = 'active'
    )
  );

CREATE POLICY deny_all ON invites
  FOR ALL
  USING (false)
  WITH CHECK (false);

CREATE POLICY deny_all ON allowed_email_domains
  FOR ALL
  USING (false)
  WITH CHECK (false);

CREATE POLICY deny_all ON university_sso_configs
  FOR ALL
  USING (false)
  WITH CHECK (false);
```

- El cast `::text` es obligatorio porque el plan mantiene IDs `TEXT` por compatibilidad
  con el bridge legacy.

---
### Issue 3

**Titulo:** `Feature: auth perimeter backend y contratos body-only de activacion/redencion`

**Tipo:** `Feature`

**Dependencias:** Issue 2

**Descripcion:**
Introducir autenticacion real y resolucion de actor dentro del monolito actual. Este
issue elimina la confianza en IDs enviados por el cliente, protege las rutas existentes,
y define los endpoints body-only para activacion, resolve y redeem de invitaciones.

**Tareas (Checklist):**

- [ ] Agregar dependencias backend necesarias:
  - libreria de verificacion JWT con JWKS
  - `supabase` / `supabase-py`
- [ ] Crear `backend/src/shared/auth.py`.
- [ ] Implementar verificador JWT con:
  - fetch y cache de JWKS
  - validacion de `issuer`
  - validacion de `audience = authenticated`
  - soporte de rotacion por `kid`
- [ ] Dejar fallback local controlado con `SUPABASE_JWT_SECRET` solo para entornos de
      desarrollo donde JWKS no aplique.
- [ ] Definir `CurrentActor` con:
  - `auth_user_id`
  - `profile_id`
  - `memberships[]` o membership activa relevante
  - `must_rotate_password`
  - `primary_role` resuelto desde DB
- [ ] Resolver actor por lookup DB, no por claims custom.
- [ ] Implementar degradation ladder:
  - JWT invalido o expirado -> 401
  - JWT valido sin `profiles` -> 403 `profile_incomplete`
  - JWT valido sin membership activa -> 403 `membership_required`
  - JWT valido con membership suspendida -> 403 `account_suspended`
- [ ] Proteger en el mismo PR:
  - `POST /api/authoring/jobs`
  - `GET /api/authoring/jobs/{job_id}`
  - `GET /api/authoring/jobs/{job_id}/result`
  - `GET /api/authoring/jobs/{job_id}/progress`
  - `POST /api/suggest`
- [ ] Remover `teacher_id` de `IntakeRequest`.
- [ ] Eliminar la autocreacion implicita de `Tenant/User` en `POST /api/authoring/jobs`.
- [ ] Crear `GET /api/auth/me`.
- [ ] Crear `POST /api/invites/resolve` con body `{ invite_token }`.
- [ ] Crear `POST /api/invites/redeem` con body `{ invite_token }`.
- [ ] Crear `POST /api/auth/activate/password` con body
      `{ invite_token, full_name?, password, confirm_password }`.
- [ ] Crear `POST /api/auth/activate/oauth/complete` autenticado con body
      `{ invite_token }`.
- [ ] Para alta password invite-gated:
  - validar invite
  - crear usuario Auth por Service Role
  - crear `profiles` y `memberships` idempotentes
  - consumir invite
  - no abrir `signUp` publico
- [ ] Para OAuth complete:
  - leer `auth_user_id` desde JWT
  - comparar email del JWT contra invite
  - si mismatch, borrar usuario Auth y retornar 422
  - si match, crear `profiles` y `memberships` idempotentes
  - consumir invite
- [ ] Implementar redemption atomica de invite con `UPDATE ... RETURNING`.
- [ ] Registrar auditoria de:
  - invite resolve valido e invalido
  - activate password
  - activate oauth
  - redeem curso
  - mismatch con delete de usuario Auth

**Criterios de Aceptacion:**

- Ninguna ruta protegida depende de IDs enviados por el cliente.
- `POST /api/authoring/jobs` deriva actor desde sesion y no crea users sombra.
- Los endpoints con token usan body-only.
- La activacion password no expone `signUp` publico.
- OAuth complete falla cerrado cuando el email no coincide con el invite.
- `GET /api/auth/me` lee `must_rotate_password` desde DB.

**Notas Tecnicas:**

- Archivos base:
  - [backend/src/shared/app.py](../../backend/src/shared/app.py)
  - [backend/src/shared/database.py](../../backend/src/shared/database.py)
  - [backend/src/shared/models.py](../../backend/src/shared/models.py)
- Variables de entorno esperadas:
  - `SUPABASE_URL`
  - `SUPABASE_ANON_KEY`
  - `SUPABASE_SERVICE_ROLE_KEY`
  - `SUPABASE_PROJECT_REF`
  - `SUPABASE_JWT_SECRET`

---

### Issue 4

**Titulo:** `DevX: entorno local y convenciones de repo`

**Tipo:** `Task`

**Dependencias:** ninguna

**Descripcion:**
Alinear entorno local, `.env.example`, `CONTRIBUTING.md` y runbook de arranque para que
un dev nuevo pueda levantar auth local y authoring local sin ayuda externa, manteniendo
`docker compose` solo para Postgres de authoring y `supabase start` para auth local.

**Tareas (Checklist):**

- [ ] Documentar `supabase start` para auth local en `54321`.
- [ ] Documentar que `docker compose` sigue siendo solo para Postgres de authoring.
- [ ] Documentar el puerto host local real del repo para Postgres: `5434`.
- [ ] Aclarar en `.env.example` la diferencia entre:
  - local docker host port `5434`
  - session mode `5432` cuando aplique
  - transaction mode `6543` en produccion con Supavisor
- [ ] Agregar `MICROSOFT_TENANT_ID` a `backend/.env.example` y a la documentacion
      correspondiente.
- [ ] Agregar `INVITE_TEACHER_TTL_HOURS=72`.
- [ ] Agregar `INVITE_STUDENT_TTL_HOURS=168`.
- [ ] Actualizar `CONTRIBUTING.md` con un flujo de arranque en menos de 10 comandos.
- [ ] Alinear `README.md`, `CONTRIBUTING.md`, `.env.example` y runbook de arranque para
      que describan el mismo setup local.

**Criterios de Aceptacion:**

- Un dev nuevo puede levantar auth local y authoring local sin ayuda externa.
- La documentacion diferencia sin ambiguedad `5434`, `5432` y `6543`.
- Ningun documento del repo deja `5432` como puerto host local por defecto.

**Notas Tecnicas:**

- Archivos a tocar:
  - [README.md](../../README.md)
  - [CONTRIBUTING.md](../../CONTRIBUTING.md)
  - [backend/.env.example](../../backend/.env.example)
  - [docker-compose.yml](../../docker-compose.yml)
- Nota explicita de consistencia:
  - el gap original decia `5432` como host local
  - el repo vigente usa `5434` en `docker-compose.yml`, `README.md` y `backend/.env.example`
  - `5432` solo puede quedar como referencia a session mode interno o Supabase, nunca
    como default local del repo

---

## Fase 1

### Issue 5

**Titulo:** `Feature: shell frontend auth-aware y rutas reales por rol`

**Tipo:** `Feature`

**Dependencias:** Issue 3

**Descripcion:**
Extender el shell actual bajo `/app/*` para soportar auth real, callback OAuth, guards y
bootstrap de sesion sin romper el basename vigente ni contaminar `src/shared` con
logica de producto. Este issue deja bloqueados los prerequisitos manuales y tecnicos
para teacher, student y admin flows.

**Tareas (Checklist):**

- [ ] Instalar `@supabase/supabase-js` solo para auth flows.
- [ ] [PASO MANUAL - BLOQUEA ISSUES 6/7/8] Configurar en Supabase Dashboard ->
      Authentication -> Redirect URLs:
  - `https://<PROD_DOMAIN>/app/auth/callback`
  - `http://localhost:5173/app/auth/callback`
- [ ] Crear `frontend/src/shared/supabaseClient.ts` con comentario explicito:
      "solo auth, nunca queries de dominio".
- [ ] Fijar explicitamente `auth: { flowType: 'pkce' }` en `supabaseClient.ts`.
- [ ] Mantener `BrowserRouter basename="/app/"`.
- [ ] Crear `AuthContext` como unica fuente de verdad de:
  - `session`
  - `actor`
  - `loading`
  - `error`
- [ ] Implementar bootstrap:
  - `getSession()`
  - `onAuthStateChange`
  - `GET /api/auth/me` cuando exista sesion
- [ ] Agregar rutas reales:
  - `/teacher/login`
  - `/teacher/activate`
  - `/student/login`
  - `/join`
  - `/admin/login`
  - `/admin/change-password`
  - `/auth/callback`
- [ ] Crear helper cerrado de `sessionStorage` para contexto corto de activacion con la
      interfaz `{ flow, invite_token, role, expires_at }`.
- [ ] Fijar TTL del helper en `5 minutos`.
- [ ] Exportar `saveActivationContext`, `readActivationContext`, `clearActivationContext`.
- [ ] Limpiar siempre el contexto de activacion en `/auth/callback`, tanto en exito como
      en error.
- [ ] Implementar `/auth/callback` sin depender de token en `state`.
- [ ] Implementar guards por:
  - sesion
  - rol
  - `must_rotate_password`
- [ ] Crear placeholders reales para landing autenticada de teacher, student y admin.
- [ ] Eliminar cualquier dependencia de toggles de demo de los mockups.

**Criterios de Aceptacion:**

- Las nuevas rutas conviven con `/app/teacher` sin romper el shell actual.
- `AuthContext` es la unica fuente de verdad de sesion y actor.
- El callback OAuth funciona sin token en `state`.
- PKCE queda configurado explicitamente y no de manera implicita o ambigua.
- Un usuario con `must_rotate_password=true` no puede navegar fuera del flujo de cambio.
- No quedan rutas productivas dependientes de los botones `Alternar` o `Probar vista`.

**Notas Tecnicas:**

- Archivos base:
  - [frontend/src/app/App.tsx](../../frontend/src/app/App.tsx)
  - [frontend/src/app/main.tsx](../../frontend/src/app/main.tsx)
- Variables de entorno frontend:
  - `VITE_SUPABASE_URL`
  - `VITE_SUPABASE_ANON_KEY`
  - `VITE_AUTH_CALLBACK_URL`
  - `VITE_APP_BASE_URL`
- PKCE es obligatorio para SPA en este plan. No dejar la redaccion ambigua.
- El cliente debe quedar con una forma equivalente a esta:

```ts
createClient(url, anonKey, {
  auth: { flowType: 'pkce' },
})
```

---

### Issue 6

**Titulo:** `Feature: activacion e inicio de sesion docente hibrido`

**Tipo:** `Feature`

**Dependencias:** Issue 5

**Descripcion:**
Implementar el acceso docente con activacion por invitacion y login regular separados.
Microsoft es el camino principal, pero el fallback password sigue existiendo bajo control
invite-gated. No se abre `signUp` publico ni se filtra el token de invitacion.

**Tareas (Checklist):**

- [ ] Crear vista `/app/teacher/activate`.
- [ ] Leer `invite_token` desde `location.hash`.
- [ ] Limpiar el hash apenas se parsea.
- [ ] Guardar el contexto en `sessionStorage` usando el helper cerrado de Issue 5.
- [ ] Resolver la invitacion llamando `POST /api/invites/resolve`.
- [ ] Mostrar:
  - email enmascarado o bloqueado
  - universidad
  - curso si aplica
  - estado accionable si el invite no sirve
- [ ] Implementar activacion Microsoft:
  - iniciar OAuth con `redirectTo = VITE_AUTH_CALLBACK_URL`
  - guardar el token solo en `sessionStorage`
  - al volver, `/auth/callback` llama `POST /api/auth/activate/oauth/complete`
- [ ] Implementar activacion password:
  - formulario con `password` y `confirm_password`
  - si hace falta `full_name`, pedirlo
  - llamar `POST /api/auth/activate/password`
  - hacer `signInWithPassword` despues de activacion exitosa
- [ ] Crear `/app/teacher/login`.
- [ ] Login regular por Microsoft y password.
- [ ] Eliminar CTA de password reset.
- [ ] Redirigir al shell docente autenticado.

**Criterios de Aceptacion:**

- Activacion y login usan rutas y copys distintos.
- El invite token no aparece en path, query string ni `state`.
- El email invitado no se puede alterar manualmente como bypass.
- Microsoft activa solo si el email del JWT coincide exactamente con el invite.
- El fallback password funciona sin `signUp` publico.
- Un invite expirado, revocado o consumido muestra un error accionable.

**Notas Tecnicas:**

- Fuente funcional:
  - [Parte1-Inicio-Registro.md](./Parte1-Inicio-Registro.md)
  - [LOGIN_PROFESOR.HTML](./Mockups/profesor/LOGIN_PROFESOR.HTML)
- Dependencias de datos:
  - `invites`
  - `profiles`
  - `memberships`

---
### Issue 7

**Titulo:** `Feature: registro, login y matricula de estudiante`

**Tipo:** `Feature`

**Dependencias:** Issue 5

**Descripcion:**
Implementar el acceso estudiantil con dos experiencias reales: login regular y join por
invitacion. El join debe soportar usuario ya autenticado y usuario nuevo. El estudiante
nuevo solo puede entrar por invitacion valida.

**Tareas (Checklist):**

- [ ] Crear `/app/join`.
- [ ] Leer `invite_token` desde fragmento.
- [ ] Limpiar el hash apenas se parsea.
- [ ] Guardar contexto corto en `sessionStorage` usando el helper cerrado de Issue 5.
- [ ] Resolver invite via `POST /api/invites/resolve`.
- [ ] Mostrar contexto real del curso y docente.
- [ ] Si hay sesion activa:
  - llamar `POST /api/invites/redeem`
  - redirigir al shell estudiante
- [ ] Si no hay sesion:
  - mostrar camino "Ya tengo cuenta"
  - mostrar camino "Soy nuevo"
- [ ] Camino "Ya tengo cuenta":
  - login regular por Microsoft o password
  - luego `POST /api/invites/redeem`
- [ ] Camino "Soy nuevo":
  - alta password invite-gated via `POST /api/auth/activate/password`
  - o alta Microsoft con callback + `POST /api/auth/activate/oauth/complete`
  - crear membership de estudiante y `course_membership`
- [ ] Validar dominio institucional contra `allowed_email_domains`.
- [ ] Implementar cache in-process documentado para dominios:
  - TTL 5 min
  - invalidez aceptada solo mientras `max_instances = 1`
- [ ] Mostrar mensaje generico en credenciales invalidas.
- [ ] Crear `/app/student/login` como login regular sin token.

**Criterios de Aceptacion:**

- `/app/join` y `/app/student/login` tienen copys y formularios distintos.
- Un estudiante autenticado puede unirse a un curso sin reloguearse.
- Un estudiante nuevo solo entra via invitacion valida.
- No se aceptan dominios fuera de `allowed_email_domains`.
- Los errores de login no revelan existencia de email.
- El invite token no aparece en path, query string ni `state`.

**Notas Tecnicas:**

- Fuente funcional:
  - [Parte1-Inicio-Registro.md](./Parte1-Inicio-Registro.md)
  - [LOGIN_ESTUDIANTE.html](./Mockups/estudiante/LOGIN_ESTUDIANTE.html)
- Dependencias de datos:
  - `invites`
  - `memberships`
  - `courses`
  - `course_memberships`
  - `allowed_email_domains`

---

### Issue 8

**Titulo:** `Feature: aprovisionamiento CLI y login de administrador universitario`

**Tipo:** `Feature`

**Dependencias:** Issue 5

**Descripcion:**
Implementar el acceso admin sin auto-registro y sin endpoint HTTP de provisioning. El
admin se crea via script interno, recibe password temporal por canal operativo fuera del
sistema y debe cambiarla en el primer acceso.

**Tareas (Checklist):**

- [ ] Crear script `scripts/provision_admin.py`.
- [ ] El script debe:
  - crear usuario Auth via Service Role
  - crear `profiles`
  - crear `memberships` con `role = university_admin`
  - dejar `must_rotate_password = TRUE`
  - exigir `university_id`
- [ ] Crear `/app/admin/login`.
- [ ] Implementar login admin por email/password.
- [ ] Crear `/app/admin/change-password`.
- [ ] Implementar `POST /api/auth/change-password`.
- [ ] Implementar el flujo fail-closed de cambio de password en este orden exacto:
  1. llamar a la Admin API de Supabase con Service Role para actualizar el password
  2. solo si eso resulta exitoso, hacer `UPDATE memberships SET must_rotate_password=FALSE`
  3. si el update de DB falla despues del update Auth:
     - loguear como fallo parcial
     - no revertir el password remoto
     - permitir reintento idempotente
  4. nunca limpiar el flag antes del cambio remoto
- [ ] Redirigir a landing autenticada minima de admin.
- [ ] Registrar auditoria de:
  - provision
  - primer login
  - cambio de password
  - fallos de acceso
- [ ] Documentar explicitamente que la entrega de password temporal es un runbook manual
      fuera de la app en Fase 1.

**Criterios de Aceptacion:**

- No existe auto-registro admin.
- El provisioning ocurre solo por CLI/script.
- Ningun admin se crea sin `university_id`.
- Un admin con `must_rotate_password=true` no puede saltarse el flujo de cambio.
- `POST /api/auth/change-password` falla cerrado si la consistencia no queda garantizada.

**Notas Tecnicas:**

- Mockup de referencia visual:
  - [Dashboard_admin.html](./Mockups/admin/Dashboard_admin.html)
- Variables de entorno:
  - `SUPABASE_SERVICE_ROLE_KEY`
  - `APP_BASE_URL`
- El wording del issue debe hablar de la Admin API de Supabase o de
  `update_user_by_id` o equivalente server-side. No describir este paso como si fuera un
  metodo de cliente de usuario final.

---
### Issue 9

**Titulo:** `Infra: split public-api/authoring-worker, Secret Manager y hardening de Cloud Run`

**Tipo:** `Infra`

**Dependencias:** Issue 3

**Descripcion:**
Separar el monolito actual en dos servicios Cloud Run solo despues de tener auth
perimeter estable. Este issue endurece deploy, secretos, validacion OIDC de Cloud Tasks,
pooling DB, capacidad minima y observabilidad.

**Tareas (Checklist):**

- [ ] Separar entrypoints:
  - `public-api` sirve SPA y APIs publicas
  - `authoring-worker` expone solo el endpoint interno de tasks
- [ ] Mantener el seam actual de Cloud Tasks probado en el repo.
- [ ] Configurar `authoring-worker` con ingress privado.
- [ ] Validar OIDC token de Cloud Tasks en el worker:
  - Bearer token obligatorio
  - service account esperado
  - audience esperado
- [ ] Mover secretos a Secret Manager.
- [ ] Documentar mapa secreto -> env var.
- [ ] Extender `Settings` en [backend/src/shared/database.py](../../backend/src/shared/database.py)
      para exponer `environment` desde `ENVIRONMENT`.
- [ ] Cambiar `backend/src/shared/database.py` para soportar:
  - `NullPool` en production / transaction mode
  - pool clasico en dev local
- [ ] Definir `DATABASE_URL` de produccion contra Supavisor transaction mode.
- [ ] Mantener local dev documentado.
- [ ] Agregar `python-json-logger` al `pyproject.toml`.
- [ ] Implementar middleware FastAPI que cree `request_id` UUID por request.
- [ ] Despues de resolver `CurrentActor`, inyectar al contexto de logs:
  - `request_id`
  - `auth_user_id`
  - `membership_id`
  - `university_id`
  - `outcome`
  - `latency_ms`
- [ ] Emitir logs JSON a stdout para Cloud Logging.
- [ ] Capturar `cold_start: bool` en logs para medir p95.
- [ ] Configurar capacidad minima:
  - `public-api` con `min-instances=1`
  - `authoring-worker` con `min-instances=0`
- [ ] Documentar penalidad esperada de cold start de `5-15s`.
- [ ] Definir alertas minimas:
  - auth failures
  - 5xx
  - latency
  - queue backlog
  - OIDC validation failures
- [ ] Documentar rollback y degradacion segura.

**Criterios de Aceptacion:**

- El split ocurre sin romper el seam actual de authoring.
- `authoring-worker` no es invocable desde internet publica.
- El worker valida OIDC token, no solo headers cosmeticos.
- `database.py` soporta `NullPool` cuando `ENVIRONMENT=production`.
- Existe un test que verifica `NullPool` cuando `ENVIRONMENT=production`.
- Existe logging JSON util para auth y authoring con contexto suficiente para Cloud Logging.

**Notas Tecnicas:**

- Archivos base:
  - [backend/src/shared/app.py](../../backend/src/shared/app.py)
  - [backend/src/shared/database.py](../../backend/src/shared/database.py)
  - [backend/.env.example](../../backend/.env.example)
- El issue debe incluir explicitamente este snippet una vez `Settings.environment` exista:

```python
engine_kwargs = {"poolclass": NullPool} if settings.environment == "production" \
    else {"pool_size": 5, "max_overflow": 10, "pool_pre_ping": True}
engine = create_engine(settings.database_url, **engine_kwargs)
```

- Fuentes externas:
  - Supabase transaction pooler con SQLAlchemy
  - Cloud Tasks OIDC token

---

### Issue 10

**Titulo:** `Enhancement: seguridad operativa de auth y politicas de error`

**Tipo:** `Enhancement`

**Dependencias:** Issue 6, Issue 7, Issue 8, Issue 9

**Descripcion:**
Implementar los controles que evitan que auth "parezca lista" sin estar endurecida.
Incluye rate limiting, mensajes seguros, auditoria, checklist pre-PR y guardrails de
operacion.

**Tareas (Checklist):**

- [ ] Aplicar rate limiting a endpoints de auth propios:
  - `POST /api/invites/resolve`
  - `POST /api/invites/redeem`
  - `POST /api/auth/activate/password`
  - `POST /api/auth/activate/oauth/complete`
  - `POST /api/auth/change-password`
- [ ] Alinear estrategia con `max_instances`:
  - si `max_instances = 1`, rate limiting in-memory aceptable
  - si `max_instances > 1`, bloquear rollout hasta tener backend distribuido
- [ ] Definir mensajes de error que no revelen existencia de email ni estado interno.
- [ ] Registrar eventos auditables:
  - invite emitido
  - invite revocado
  - invite consumido
  - login exitoso
  - login fallido
  - activate password
  - activate oauth
  - redeem curso
  - password changed
  - provisioning admin
- [ ] Definir checklist de seguridad pre-PR:
  - no IDs de actor desde body
  - JWT verificado localmente
  - Service Role fuera de logs y responses
  - token scrubbing efectivo
  - Cloud Tasks OIDC validado
  - errores sin filtracion
- [ ] Documentar riesgo y trigger de migracion para rate limiting distribuido.

**Criterios de Aceptacion:**

- Los endpoints de auth propios tienen rate limiting coherente con el deploy real.
- Los mensajes de error no filtran informacion sensible.
- Existe auditoria util de principio a fin para invites y activaciones.
- Existe checklist reproducible para aprobar PRs de auth.

**Notas Tecnicas:**

- Archivos relacionados:
  - [backend/src/shared/app.py](../../backend/src/shared/app.py)
  - nuevos modulos de auth y logging

---
### Issue 11

**Titulo:** `Enhancement: suites de prueba, concurrencia y QA gate para auth`

**Tipo:** `Enhancement`

**Dependencias:** Issue 6, Issue 7, Issue 8, Issue 9, Issue 10

**Descripcion:**
Cerrar Fase 1 con una bateria de pruebas que cubra JWT, activacion, redencion, permisos,
deploy hardening y browser QA. Esto es gate de fase, no decoracion.

**Tareas (Checklist):**

- [ ] Definir estrategia de pruebas por nivel:
  - unit
  - integration con `supabase start`
  - concurrencia
  - frontend routing/guards
  - browser QA
- [ ] Cubrir JWT:
  - valido
  - expirado
  - issuer incorrecto
  - audience incorrecta
  - rotacion de `kid`
- [ ] Cubrir activacion password:
  - invite valido
  - invite expirado
  - invite reutilizado
  - retry idempotente
- [ ] Cubrir activacion oauth:
  - match exacto
  - mismatch con delete de usuario Auth
  - callback sin contexto de activacion
- [ ] Cubrir flujo estudiante:
  - sesion vigente + redeem
  - usuario nuevo + activate + enroll
  - dominio no permitido
  - doble redencion concurrente
- [ ] Cubrir admin:
  - login con password temporal
  - cambio de password
  - fallo parcial que no limpia `must_rotate_password`
- [ ] Cubrir authoring protegido:
  - teacher permitido
  - student denegado
  - admin denegado
- [ ] Cubrir deploy hardening:
  - Cloud Tasks OIDC valido
  - OIDC invalido
  - `NullPool` cuando `ENVIRONMENT=production`
  - fallback seguro
- [ ] Definir QA browser reproducible para:
  - teacher activation
  - teacher login
  - student join
  - student login
  - admin first login
  - admin change password

**Criterios de Aceptacion:**

- Existe matriz de pruebas por rol, estado y tipo de fallo.
- El test de redencion concurrente esta implementado.
- Los riesgos criticos no quedan sin test ni sin manejo de error.
- El equipo tiene un QA gate reproducible antes de cerrar Fase 1.

**Notas Tecnicas:**

- Validaciones base del repo:
  - `uv run --directory backend pytest -q`
  - `uv run --directory backend mypy src`
  - `npm --prefix frontend run lint`
  - `npm --prefix frontend run test`
  - `npm --prefix frontend run build`
- QA manual asistida por skills del repo:
  - `adam-orchestrator`
  - `qa`
  - `browse`
  - `review`

---

## Validacion transversal de la fase

- Verificar que no exista ningun flujo de auth que dependa de `teacher_id` enviado por el
  cliente.
- Verificar que ningun token de invitacion viaje en path, query string ni OAuth `state`.
- Verificar que la activacion password no abra `signUp` publico.
- Verificar que Microsoft mismatch elimine el usuario Auth y falle cerrado.
- Verificar que `GET /api/auth/me` lea desde DB el rol efectivo y
  `must_rotate_password`.
- Verificar que `authoring-worker` no sea publico y que valide OIDC.
- Verificar que `database.py` soporte transaction mode sin pool local inseguro.
- Verificar que no quede ninguna mencion de `5432` como puerto host local por defecto del
  repo.
- Verificar que Issue 2 incluya `rls_policies.sql` con el SQL completo y el cast
  `::text`.
- Verificar que Issue 5 incluya:
  - redirect URLs como paso manual bloqueante
  - PKCE explicito
  - helper de `sessionStorage` con interfaz cerrada y TTL de 5 minutos
- Verificar que Issue 8 deje el contrato fail-closed de cambio de password sin
  ambiguedad y contra la Admin API de Supabase.
- Verificar que Issue 9 incluya:
  - snippet `NullPool`
  - test de `ENVIRONMENT=production`
  - `python-json-logger`
  - middleware y contexto de logs
  - `min-instances`
  - `cold_start`
- Verificar que la tabla de deuda reemplace, y no duplique, la deuda anterior.
- Verificar que teacher, student y admin fallen cerrado contra endpoints de authoring
  ajenos.
- Verificar que el documento final quede autosuficiente para abrir issues sin consultar
  `README.md` ni `CONTRIBUTING.md`.

## Deuda aceptada y documentada

| Deuda | Trigger de resolucion |
|---|---|
| Un solo tenant Microsoft por deployment | Segundo cliente con MSO distinto |
| Bridge `users.id` como TEXT | Migracion de dominio post-Fase 1 |
| Rate limiting in-memory | Scale-out `max_instances > 1` |
| Cache in-process de `allowed_email_domains` | Scale-out `max_instances > 1` |
| Split `public-api` / `authoring-worker` diferido | Issues 1-3 en produccion |
| Password reset self-serve ausente | Peticion operativa o de usuarios |
| MFA admins ausente | Requisito de compliance |

## Fuentes externas validadas

- Supabase custom access token hook:
  - https://supabase.com/docs/guides/auth/auth-hooks/custom-access-token-hook
- Supabase JWT/JWKS:
  - https://supabase.com/docs/guides/auth/jwts
- Supabase SQLAlchemy + pooler transaction mode:
  - https://supabase.com/docs/guides/troubleshooting/using-sqlalchemy-with-supabase-FUqebT
- Cloud Tasks OIDC token:
  - https://cloud.google.com/tasks/docs/reference/rest/v2/OidcToken

## Cierre

Este documento deja el backlog criticado, secuenciado y listo para abrir issues sin que
el equipo tenga que improvisar decisiones de auth, tenancy o deploy a mitad de la
implementacion. Las reglas que no se pueden romper son estas: auth fuera de
`backend/src/case_generator/**`, actor derivado desde sesion y DB, invitaciones como
artefacto pre-usuario, tokens fuera de la URL visible, y split de servicios solo despues
de cerrar el perimeter del backend actual.
