# ADR 0001: Auth perimeter, trust boundaries y stack de acceso para Fase 1

- Status: Accepted
- Date: 2026-04-02
- GitHub tracking: `#24`
- Plan mapping: `Issue 1` en `docs/planPlataforma/fase0_y_fase1.md`
- Blocks: GitHub `#23` y el future issue del plan `Feature: auth perimeter backend y contratos body-only de activacion/redencion`

## Summary

Fase 1 no va a reescribir el producto ni a dividir servicios antes de tiempo. Va a cerrar
el auth perimeter del monolito actual, mantener FastAPI como application plane, mover la
identidad a Supabase Auth y resolver autorizacion real desde DB. El split
`public-api` / `authoring-worker` queda despues, no antes.

La autoridad de decisiones para trust boundaries y auth perimeter vive en este ADR. El
plan maestro sigue siendo la fuente de backlog y secuencia de issues.

## Current Insecure State

El repo publicado hoy es un MVP teacher-only con varios supuestos inseguros que Fase 1
debe retirar de forma explicita:

- El backend confia en `teacher_id` enviado por el cliente en
  [`backend/src/shared/app.py`](../../backend/src/shared/app.py).
- `POST /api/authoring/jobs` autocrea `Tenant` y `User` si no existen, en el mismo
  endpoint y sin identidad verificada.
- El shell funcional actual vive bajo `/app/teacher`, montado por
  [`frontend/src/app/App.tsx`](../../frontend/src/app/App.tsx) con
  `BrowserRouter basename="/app/"` en
  [`frontend/src/app/main.tsx`](../../frontend/src/app/main.tsx).
- El mismo proceso FastAPI expone `/api/*`, SSE y la SPA bajo `/app`, con el mount en
  [`backend/src/shared/app.py`](../../backend/src/shared/app.py).
- `/api/suggest` es hoy una superficie publica del monolito y sigue perteneciendo al
  `public-api` plane.
- Existe un seam interno preservado en `/api/internal/tasks/authoring_step`, pero hoy
  sigue conviviendo en el monolito.
- El frontend usa un cliente API centralizado y hoy no consulta dominio por PostgREST;
  habla con FastAPI via `/api/*` desde
  [`frontend/src/shared/api.ts`](../../frontend/src/shared/api.ts).

Esto sirve para authoring local. No sirve como auth perimeter multi-tenant.

## Context Diagram

```text
Browser SPA (/app/*)
        |
        v
   public-api (FastAPI)
        |
        +--> Supabase Auth
        |      - password auth
        |      - OAuth / Microsoft
        |      - JWT issuance
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
         authoring-worker
```

## Approved Trust Boundaries

| Boundary | Caller | Accepted credential / authority | Source of truth | Rejected input | Owner |
|---|---|---|---|---|---|
| Browser SPA | Human user | Supabase session only | UI state plus `public-api` responses | Domain authority in local state, Service Role, invite token in visible URL | Frontend |
| `public-api` | Browser, internal platform traffic | Bearer JWT verified locally, internal service auth where applicable | Supabase Postgres plus resolved `CurrentActor` | `teacher_id`, `student_id`, `role`, `auth_user_id`, `university_id` from request body | Backend |
| Supabase Auth | `public-api`, browser auth flows | Password / OAuth flows managed by Supabase | Auth identity and JWT issuance | Custom claims as critical business authority | Identity platform |
| Supabase Postgres | `public-api`, internal scripts | Server-side DB access | Access data, memberships, invites, bridge legacy | Browser direct domain queries via PostgREST | Backend / data layer |
| Cloud Tasks | `public-api` | Queue config plus OIDC when split happens | Task dispatch contract | Public internet invocation as steady-state worker access path | Platform |
| `authoring-worker` | Cloud Tasks only after split | Valid OIDC token with expected audience and service account | Authoring execution seam | Browser traffic, unauthenticated HTTP, actor identity from task body | Backend / platform |
| Service Role / CLI provisioning | Backend-only flows and operator CLI | `SUPABASE_SERVICE_ROLE_KEY` | Privileged auth administration | Browser access, logs, responses, analytics, client bundles | Backend / ops |

Notas de boundary:

- `public-api` puede exponer endpoints publicos puntuales, por ejemplo `/health` y
  `/api/suggest`.
- Esa excepcion no habilita endpoints de dominio ni de auth a confiar en identidad
  enviada por body o derivada de estado del frontend.

## Actor Resolution Contract

La ruta critica de autorizacion para Fase 1 queda cerrada asi:

```text
Browser
  -> Authorization: Bearer <JWT>
  -> public-api
       -> verify JWT locally with JWKS + issuer + audience
       -> map auth user id to DB records
       -> resolve CurrentActor from memberships / profiles / bridge legacy
       -> authorize by membership.role + resource ownership
       -> call domain logic

Browser -X-> actor identity from request body
Browser -X-> domain reads via PostgREST
Custom claims -X-> critical authorization
```

Reglas obligatorias:

- Supabase Auth es la source of truth de identidad.
- Supabase Postgres es el unico plano de datos para acceso.
- FastAPI sigue siendo el application plane. El frontend no usa PostgREST para datos de
  dominio.
- JWT de produccion se verifica localmente con `JWKS`, `issuer` y `audience`.
- `SUPABASE_JWT_SECRET` queda solo como fallback local controlado para desarrollo.
- No hay custom claims en la ruta critica para `role`, `university_id` o
  `must_rotate_password`.
- RLS es defensa secundaria. No reemplaza el auth perimeter del backend ni la
  autorizacion de SQLAlchemy.

## Explicitly Retired Assumptions

Fase 1 retira estos supuestos del MVP actual:

- Identidad del actor por `teacher_id`, `student_id`, `role`, `auth_user_id` o
  `university_id` en body.
- Autocreacion implicita de `Tenant/User` dentro de endpoints productivos.
- Token de invitacion en path params, query string, `state`, logs, analytics,
  breadcrumbs o headers reflejados.
- Uso de `SUPABASE_SERVICE_ROLE_KEY` fuera de backend o CLI.
- Dependencia de claims custom para negocio critico.
- Frontend leyendo dominio directamente desde Supabase/PostgREST.

## Secrets And Privileged Credentials

- `SUPABASE_SERVICE_ROLE_KEY` es backend-only y CLI-only. Nunca entra al browser, nunca
  a respuestas HTTP, nunca a logs, nunca a analytics.
- El frontend puede usar Supabase solamente para auth y session management. No para
  queries de dominio.
- Credenciales de operador para provisioning admin viven en runbooks y tooling
  server-side, no en endpoints publicos.
- Los links de invitacion usan fragmento, no path ni query:
  - `/app/teacher/activate#invite_token=<token>`
  - `/app/join#invite_token=<token>`

## Deferred Split And Exit Triggers

Fase 1 mantiene el monolito actual hasta cerrar el auth perimeter del backend. El split
`public-api` / `authoring-worker` no entra en este ADR como implementacion, pero si como
decision secuencial.

Reglas:

- La SPA sigue servida por `public-api`.
- Antes del split, `/api/internal/tasks/authoring_step` sigue como seam interno
  preservado por compatibilidad y continuidad de authoring.
- Despues del split, `authoring-worker` sera privado y validara OIDC de Cloud Tasks.
- Fase 1 modela `university_sso_configs`, pero el rollout habilita solo un tenant
  Microsoft activo por deployment.

Triggers de salida del stack:

- Drift operacional entre multiples universidades y un solo tenant Microsoft por
  deployment.
- `p95` de DB fuera del presupuesto operativo.
- Egress o latencia inaceptable entre Cloud Run y Supabase.
- Necesidad real de multi-provider SSO o de mas de un tenant Microsoft activo por
  deployment.

## Impact On Follow-Up Issues

| Decision | Impact on GitHub `#23` | Impact on future Issue 3 |
|---|---|---|
| `profiles.id == auth.users.id` y bridge legacy | Cierra el substrate de identidad sin tocar `backend/src/case_generator/**` | Permite resolver actor real sin reescribir authoring |
| JWT local con JWKS / issuer / audience | Evita dependencia de claims custom o secretos productivos en runtime | Define la entrada obligatoria del middleware / dependency de auth |
| FastAPI como perimeter y Postgres como source of truth de acceso | Mantiene el modelo de datos y RLS como defensa secundaria | Obliga a derivar autorizacion desde DB y no desde body |
| Split diferido de servicios | Evita mover infraestructura antes de tiempo | Deja Issue 3 enfocado en auth perimeter, no en deploy topology |

## NOT in Scope

- Implementar endpoints de auth o guards de frontend.
- Crear migraciones, tablas nuevas o `rls_policies.sql`.
- Hacer el split `public-api` / `authoring-worker`.
- Definir UX detallada de login, activation, join o admin dashboard.
- Migrar IDs legacy `TEXT` a `uuid` nativo.
- Abrir password reset self-serve, MFA obligatoria o multi-provider SSO.

## Consequences

Buenas:

- Issue `#23` y el future issue `Feature: auth perimeter backend y contratos body-only de activacion/redencion`
  quedan bloqueados por una decision explicita y no por memoria tribal.
- Se conserva el seam actual de authoring y se reduce riesgo de tocar
  `backend/src/case_generator/**` antes de tiempo.
- El equipo tiene una frontera clara entre identidad, autorizacion y deploy hardening.

Costos aceptados:

- Sigue existiendo una etapa transitoria donde el monolito concentra SPA, APIs y seam
  interno.
- Se acepta `SUPABASE_JWT_SECRET` solo como fallback local, no como camino productivo.
- Se difiere el split de infraestructura hasta despues de cerrar el perimeter backend.

## References

- Plan maestro: [`docs/planPlataforma/fase0_y_fase1.md`](../planPlataforma/fase0_y_fase1.md)
- GitHub `#24`: ADR: auth perimeter, trust boundaries y stack de acceso para Fase 1
- GitHub `#23`: Infra: schema de identidad, memberships, invites, RLS secundaria y bridge legacy
- Supabase JWT / JWKS: https://supabase.com/docs/guides/auth/jwts
- Supabase SQLAlchemy + transaction pooler: https://supabase.com/docs/guides/troubleshooting/using-sqlalchemy-with-supabase-FUqebT
- Cloud Tasks OIDC token: https://docs.cloud.google.com/tasks/docs/reference/rest/v2/OidcToken
