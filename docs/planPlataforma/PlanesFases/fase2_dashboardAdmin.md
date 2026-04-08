# Fase 2 - Dashboard Admin por Issues

Documento de planeacion para ejecutar la Fase 2 del portal admin sin ambiguedades
de arquitectura, sin romper el auth perimeter de Fase 1 y sin permitir que varios
developers o agentes implementen contratos incompatibles entre si.

Este archivo es la fuente unica de verdad para abrir y ejecutar los issues de la fase.
No debe asumirse nada fuera de lo que aqui queda cerrado.

## Objetivo

La Fase 2 introduce el dashboard operativo del administrador universitario bajo la URL
real de navegador `/app/admin/dashboard` y la ruta React `/admin/dashboard`.

Esta vista deja de ser placeholder y pasa a ser el centro real de gestion academica del
tenant:

- metricas del tenant
- catalogo de cursos
- asignacion docente activa o pendiente
- archivado seguro de cursos
- generacion y rotacion de links seguros de ingreso de estudiantes

La condicion no negociable de esta fase es doble:

- La UI final debe quedar visualmente igual al mockup `Dashboard_admin.html`.
- La semantica backend no puede copiar de forma ingenua los comportamientos inseguros del
  HTML demo.

## Referencias

- Mockup obligatorio: [Dashboard_admin.html](../Mockups/admin/Dashboard_admin.html)
- Plan anterior cerrado: [fase0_y_fase1.md](./fase0_y_fase1.md)
- Shell frontend actual: [frontend/src/app/App.tsx](../../../frontend/src/app/App.tsx)
- Auth frontend actual: [frontend/src/app/auth/AuthContext.tsx](../../../frontend/src/app/auth/AuthContext.tsx)
- Join estudiantil actual: [frontend/src/features/student-auth/StudentJoinPage.tsx](../../../frontend/src/features/student-auth/StudentJoinPage.tsx)
- OAuth callback actual: [frontend/src/features/auth-callback/AuthCallbackPage.tsx](../../../frontend/src/features/auth-callback/AuthCallbackPage.tsx)
- Activation context actual: [frontend/src/shared/activationContext.ts](../../../frontend/src/shared/activationContext.ts)
- Backend FastAPI actual: [backend/src/shared/app.py](../../../backend/src/shared/app.py)
- Modelos actuales: [backend/src/shared/models.py](../../../backend/src/shared/models.py)
- Contratos auth actuales: [backend/src/shared/auth.py](../../../backend/src/shared/auth.py)

## What Already Exists

- `CurrentActor` ya resuelve JWT + memberships activas desde Supabase y es la base correcta
  para tenant isolation. No se debe inventar otro contexto auth paralelo.
- `RootRedirect`, `GuestOnlyRoute` y `RequireRole` ya contemplan `university_admin` y ya
  redirigen a `/admin/dashboard`. Falta la pantalla real, no el concepto de ruta.
- El frontend ya tiene flujo de tokens en fragmento y limpieza del hash para
  `invite_token`. Eso se debe extender, no reescribir con query params o `state`.
- `StudentJoinPage`, `AuthCallbackPage`, `api.ts` y `activationContext.ts` hoy estan
  diseñados alrededor de `invite_token` email-bound. Eso sirve como patron de seguridad,
  pero no sirve tal cual para un `course_access_token` reutilizable.
- `Course.teacher_membership_id` hoy es obligatorio y el modelo `Course` no soporta docente
  pendiente. El schema debe cambiar primero.
- `Invite` hoy es el artefacto pre-activacion activo en auth. El plan no debe forzar a
  reutilizar `Invite` como si fuera el link publico y revocable de curso.

## NOT in Scope

- Pagina completa de "Gestion de Docentes". En esta fase solo existe el quick action con
  toast placeholder.
- Modulo real de "Reportes Globales". En esta fase solo existe el quick action con toast
  `Proximamente`.
- Proveedor real de email, templates, retries, webhooks o runbook de envio. El backend
  solo crea la invitacion y devuelve el activation link.
- Tenant switcher admin en UI. Si una cuenta tiene multiples memberships activas de
  `university_admin`, el backend debe fallar cerrado con error explicito hasta que exista
  UX dedicada.
- Student runtime completo. Esta fase solo cubre el join/enrollment por link de curso.
- Hard delete o restore de cursos. "Archivar" significa `inactive`, nada mas.

## Decisiones Cerradas de Producto, Seguridad e Implementacion

- El dashboard es tenant-scoped y solo lo usa `university_admin`.
- La URL real de navegador es `/app/admin/dashboard`. La ruta React interna es
  `/admin/dashboard`.
- El header del dashboard admin no reutiliza `SiteHeader`. Debe renderizar su propia
  version exacta al mockup.
- El mockup HTML es el oracle visual. Si el sistema de diseño actual choca con el mockup,
  gana el mockup en esta pantalla.
- El dashboard admin puede usar componentes locales propios bajo
  `frontend/src/features/admin-dashboard/*` si eso es necesario para mantener la paridad
  visual exacta.
- Todos los endpoints admin deben resolver el tenant desde una unica membership activa de
  `university_admin`.
  - Si el actor no tiene ninguna membership admin activa: `403 admin_role_required`.
  - Si tiene mas de una membership admin activa: `409 admin_membership_context_required`.
  - No se acepta `university_id` desde query, path o body como fuente de verdad.
- La asignacion docente de un curso se modela como union exclusiva:
  - `teacher_membership_id` para docente activo
  - `pending_teacher_invite_id` para docente invitado pendiente
  - exactamente uno de los dos debe existir
- El pending teacher invite usado por cursos solo puede ser:
  - `role = teacher`
  - del mismo tenant del curso
  - `status = pending`
  - no expirado, no revocado, no consumido
- El endpoint de crear invitacion docente debe devolver `invite_id` y `activation_link`.
  No basta con devolver solo el link porque create/edit course necesita un identificador
  estable para persistir `pending_teacher_invite_id`.
- El directorio de cursos debe devolver no solo `teacher_display_name`, sino tambien la
  seleccion estructurada usada por el modal de editar:
  - `teacher_assignment.kind = membership | pending_invite`
  - `teacher_assignment.membership_id | invite_id`
- `course_access_links` guarda solo `token_hash`. El token raw existe unicamente:
  - al crear link inicial
  - al regenerarlo
  - al serializar el link de admin para mostrar/copiar en el dashboard
- El token de acceso de curso:
  - viaja solo en fragmento `#course_access_token=...`
  - no vive en path, query, OAuth state, breadcrumbs o logs
  - no reemplaza el auth perimeter
  - no da acceso directo al contenido del curso
- El flujo de course access no puede reutilizar los endpoints actuales
  `/api/auth/activate/*` ni `/api/invites/*` como si fueran equivalentes.
  La fase debe agregar endpoints especificos para `course_access_token`.
- `StudentJoinPage` debe soportar ambos caminos en convivencia:
  - `invite_token` actual
  - `course_access_token` nuevo
- `activationContext` y `AuthCallbackPage` tambien deben soportar ambos caminos. No basta
  con tocar `StudentJoinPage`.

## Contratos Publicos e Interfaces

### Backend Schema

Cambios requeridos:

- `courses`
  - agregar `code`
  - agregar `semester`
  - agregar `academic_level`
  - agregar `max_students`
  - agregar `status`
  - agregar `pending_teacher_invite_id`
  - volver `teacher_membership_id` nullable para permitir la union exclusiva
- `invites`
  - agregar `full_name`
- nueva tabla `course_access_links`
  - `id`
  - `course_id`
  - `token_hash`
  - `status`
  - `created_at`
  - `rotated_at`

Constraints obligatorios:

- `courses.status IN ('active', 'inactive')`
- `courses.max_students > 0`
- `UNIQUE (university_id, code, semester)` para evitar codigos duplicados dentro del mismo
  periodo academico
- check exclusivo en `courses`:
  - o hay `teacher_membership_id`
  - o hay `pending_teacher_invite_id`
  - pero no ambos ni ninguno
- `pending_teacher_invite_id` referencia `invites.id`
- `course_access_links.status IN ('active', 'rotated', 'revoked')`
- unicidad operacional del link activo por curso

Normalizacion obligatoria:

- `semester` usa formato canonico `YYYY-I` o `YYYY-II`
- `academic_level` reutiliza la misma taxonomia ya usada por frontend; no inventar una
  segunda vocabulario paralela

### Nuevos Endpoints

- `GET /api/admin/dashboard/summary`
- `GET /api/admin/courses`
- `GET /api/admin/teacher-options`
- `POST /api/admin/courses`
- `PATCH /api/admin/courses/{course_id}`
- `POST /api/admin/teacher-invites`
- `POST /api/admin/courses/{course_id}/access-link/regenerate`
- `POST /api/course-access/resolve`
- `POST /api/course-access/enroll`
- `POST /api/course-access/activate/password`
- `POST /api/course-access/activate/oauth/complete`

### Frontend Surface

- nueva feature `frontend/src/features/admin-dashboard/*`
- nueva ruta protegida `/admin/dashboard`
- ajuste de `RootRedirect` y `GuestOnlyRoute` para apuntar al dashboard real
- render condicional del layout para que `/admin/dashboard` no use el header global
- extension de:
  - `frontend/src/features/student-auth/StudentJoinPage.tsx`
  - `frontend/src/features/auth-callback/AuthCallbackPage.tsx`
  - `frontend/src/shared/activationContext.ts`
  - `frontend/src/shared/api.ts`
  - `frontend/src/shared/adam-types.ts`

## Paridad Visual Obligatoria con el Mockup

La implementacion de React debe respetar exactamente estos invariantes visibles del
mockup `Dashboard_admin.html`:

- header oscuro con gradiente, icono ADAM, texto "Portal Administrador", avatar circular y
  bloque de nombre + rol
- grid de 4 KPI cards con icono a la izquierda y metrica principal grande
- grid de 3 quick actions con:
  - `Crear Nuevo Curso`
  - `Gestion de Docentes`
  - `Reportes Globales`
- barra de filtros con:
  - input de busqueda
  - select de semestre
  - select de estado
  - select de nivel
- tabla con columnas, en este orden:
  - `Asignatura / Codigo`
  - `Docente Asignado`
  - `Estado`
  - `Capacidad`
  - `Link de Invitacion`
  - `Acciones`
- footer de tabla con contador y paginacion
- modal crear curso
- modal editar curso
- modal archivar curso
- modal invitar docente
- toast flotante oscuro abajo a la derecha

Reglas de implementacion visual:

- No sustituir esta pantalla por una variante "mas simple", "mas moderna" o "parecida".
- No rehacer copy, jerarquia o layout sin que el mockup lo respalde.
- La paridad visual se valida con screenshots lado a lado en desktop y mobile.
- Si un componente compartido impide la fidelidad del mockup, se crea la variante local en
  la feature admin.

## Diagramas

### Flujo del dashboard admin

```text
/app/admin/dashboard
        |
        v
  AuthContext + /api/auth/me
        |
        v
  RequireRole(university_admin)
        |
        +--> GET /api/admin/dashboard/summary
        +--> GET /api/admin/courses?filters&page&page_size
        +--> GET /api/admin/teacher-options
        |
        +--> POST /api/admin/courses
        +--> PATCH /api/admin/courses/{id}
        +--> POST /api/admin/teacher-invites
        +--> POST /api/admin/courses/{id}/access-link/regenerate
        |
        v
  courses / invites / memberships / course_memberships / course_access_links
```

### Flujo de ingreso por course access token

```text
Admin copia /app/join#course_access_token=<raw>
                    |
                    v
         StudentJoinPage parsea fragmento
                    |
                    v
    guarda token corto en activationContext y limpia hash
                    |
                    v
     POST /api/course-access/resolve  (publico, sin query/path token)
                    |
         +----------+-----------+
         |                      |
         v                      v
 estudiante ya autenticado   estudiante sin sesion
         |                      |
         v                      +--> password:
 POST /api/course-access/       |    POST /api/course-access/activate/password
 enroll                         |
         |                      +--> Microsoft:
         |                           OAuth -> /app/auth/callback
         |                           -> POST /api/course-access/activate/oauth/complete
         v
 enrollment creado o idempotente, siempre tenant-scoped y fail-closed
```

## Grafo de Dependencias

```text
Issue 1 (schema y contratos base)
  -> Issue 2 (lecturas admin)
  -> Issue 3 (mutaciones admin)
  -> Issue 4 (course access / join)

Issue 2 + Issue 3 + contratos cerrados de Issue 4
  -> Issue 5 (frontend dashboard exacto)

Issue 2 + Issue 3 + Issue 4 + Issue 5
  -> Issue 6 (QA gate)
```

## Paralelizacion Recomendada

| Lane | Issues | Comentario |
|---|---|---|
| Lane A | Issue 1 | Base obligatoria. Nadie implementa contratos antes de esto |
| Lane B | Issue 2 | Puede arrancar al cerrar Issue 1 |
| Lane C | Issue 3 | Puede correr en paralelo con Issue 2 tras Issue 1 |
| Lane D | Issue 4 | Puede correr en paralelo con Issue 2 y 3, pero debe reutilizar el mismo helper/servicio de token que Issue 3 |
| Lane E | Issue 5 | Arranca cuando los contratos backend ya no cambian |
| Lane F | Issue 6 | Gate final de fase |

Conflicto esperado:

- Issue 3 e Issue 4 tocan el dominio `course_access_links` y no deben divergir en formato
  del link, helper de hashing ni semantica de rotacion.

## Mapa de Issues

---

## Issue 1

**Titulo:** `Infra: sustrato de datos para catalogo admin, asignacion diferida y links de acceso por curso`

**Tipo:** `Infra`

**Dependencias:** ninguna

**Objetivo**

Dejar el schema y el ORM capaces de representar el dashboard real sin hacks en frontend y
sin sobrecargar el modelo actual de invites.

**Tareas**

- Crear migracion Alembic para ampliar `courses` con:
  - `code`
  - `semester`
  - `academic_level`
  - `max_students`
  - `status`
  - `pending_teacher_invite_id`
- Cambiar `teacher_membership_id` para soportar la union exclusiva con
  `pending_teacher_invite_id`
- Crear tabla `course_access_links`
- Extender `invites` con `full_name`
- Agregar constraints de:
  - estado del curso
  - capacidad positiva
  - unicidad `(university_id, code, semester)`
  - union exclusiva docente activo vs docente pendiente
  - unicidad operacional del link activo por curso
- Alinear `models.py` con la migracion
- Backfill obligatorio de cursos existentes para no romper data ya sembrada
- Actualizar fixtures backend para soportar:
  - cursos activos e inactivos
  - cursos con docente activo
  - cursos con docente pendiente
  - links activos, rotados y revocados

**Criterios de aceptacion**

- El modelo soporta todos los datos visibles y editables del dashboard.
- Crear curso con docente pendiente es valido.
- Rotar link invalida el anterior a nivel de modelo.
- No existe hard delete como contrato funcional del curso.
- El ORM queda alineado con migracion y tests de schema.

**Failure modes que este issue debe cubrir**

- curso legado sin backfill y con columnas nuevas nulas
- curso con ambos campos de docente informados
- codigo duplicado en mismo tenant + semestre
- max_students `<= 0`

---

## Issue 2

**Titulo:** `Backend: lecturas admin para KPIs, directorio y selectores del dashboard`

**Tipo:** `Feature`

**Dependencias:** Issue 1

**Objetivo**

Exponer las lecturas necesarias para poblar el dashboard sin mocks y sin calculos
duplicados en el cliente.

**Tareas**

- Implementar `GET /api/admin/dashboard/summary`
- Implementar `GET /api/admin/courses`
- Implementar `GET /api/admin/teacher-options`
- Requerir actor con rol activo `university_admin`
- Resolver tenant desde la unica membership admin activa
- En `summary`, devolver:
  - `active_courses`
  - `active_teachers`
  - `enrolled_students`
  - `average_occupancy`
- En `courses`, soportar:
  - `search`
  - `semester`
  - `status`
  - `academic_level`
  - `page`
  - `page_size`
- En `courses`, devolver por fila:
  - metadatos del curso
  - conteos de estudiantes
  - porcentaje de ocupacion
  - `access_link`
  - `teacher_display_name`
  - `teacher_state`
  - `teacher_assignment`
- Orden por defecto del directorio:
  - `created_at DESC`
- En `teacher-options`, devolver dos grupos:
  - docentes activos registrados
  - invitaciones docentes pendientes
- `teacher-options` debe excluir invites expirados, consumidos o revocados

**Criterios de aceptacion**

- El dashboard puede cargar sin datos mock.
- Filtros y paginacion salen del backend.
- Un admin nunca ve cursos, metricas o docentes de otro tenant.
- El directorio soporta cursos con docente activo y cursos con invitacion pendiente.
- Edit Course tiene ids estructurados suficientes para preseleccionar la opcion correcta.

**Failure modes que este issue debe cubrir**

- actor con multiples memberships admin activas
- join entre cursos y docentes de otro tenant
- curso con pending invite ya consumida
- division por cero en `average_occupancy`

---

## Issue 3

**Titulo:** `Backend: mutaciones admin para crear, editar, archivar cursos e invitar docentes`

**Tipo:** `Feature`

**Dependencias:** Issue 1

**Objetivo**

Implementar las acciones del dashboard admin que mutan estado real del sistema.

**Tareas**

- Implementar `POST /api/admin/courses`
- Implementar `PATCH /api/admin/courses/{course_id}`
- Implementar `POST /api/admin/teacher-invites`
- Implementar `POST /api/admin/courses/{course_id}/access-link/regenerate`
- Cerrar payload de create/edit con union explicita:
  - `teacher_assignment.kind = membership`
  - `teacher_assignment.kind = pending_invite`
- Reglas de creacion:
  - puede asignar docente activo
  - puede asignar invitacion pendiente valida
  - genera link activo inicial del curso
- Reglas de edicion:
  - actualiza campos visibles del mockup
  - puede cambiar entre docente activo y docente pendiente
  - si el pending invite seleccionado ya no es valido, responde `409 stale_pending_teacher_invite`
- Reglas de archivado:
  - cambia a `inactive`
  - no borra curso
  - el acceso por link falla cerrado para cursos inactivos
- Reglas de invitacion docente:
  - crea `Invite` tipo `teacher`
  - persiste `full_name`
  - devuelve `invite_id`
  - devuelve `activation_link`
  - no promete ni dispara envio por email
- Reglas de regeneracion de link:
  - invalida el anterior
  - devuelve el nuevo link listo para copiar
- Agregar auditoria minima:
  - `admin.course.created`
  - `admin.course.updated`
  - `admin.course.archived`
  - `admin.teacher.invited`
  - `admin.course_link.regenerated`

**Criterios de aceptacion**

- El modal Crear Curso funciona punta a punta contra backend real.
- El modal Editar Curso puede modificar curso, docente, estado y link.
- Archivar solo cambia estado a `inactive`.
- Invitar docente devuelve `invite_id` y link consistente.
- Regenerar link revoca el anterior.

**Failure modes que este issue debe cubrir**

- pending invite invalida entre el fetch de options y el submit
- curso de otro tenant en PATCH/regenerate/archive
- regeneracion concurrente del mismo link
- create/edit con union docente mal formada

---

## Issue 4

**Titulo:** `Auth/Enrollment: ingreso de estudiantes por link de curso sin romper el perimetro`

**Tipo:** `Feature`

**Dependencias:** Issue 1

**Objetivo**

Introducir el flujo seguro de ingreso de estudiantes por link de curso sin reinterpretar
el sistema actual de invites email-bound como si fuera un link publico reutilizable.

**Tareas**

- Introducir `course_access_token` como artefacto independiente de `Invite`
- Implementar `POST /api/course-access/resolve`
- Implementar `POST /api/course-access/enroll`
- Implementar `POST /api/course-access/activate/password`
- Implementar `POST /api/course-access/activate/oauth/complete`
- Definir que el link copiable usa fragmento:
  - `/app/join#course_access_token=...`
- En `resolve`, devolver:
  - curso
  - universidad
  - docente visible
  - estado del curso
  - estado del link
  - metodos de auth permitidos
- En `enroll`, exigir:
  - sesion valida
  - membership `student` del mismo tenant
  - dominio permitido por `allowed_email_domains`
  - curso activo
  - link activo
- En `activate/password`:
  - crear o reutilizar usuario auth
  - crear/activar membership `student`
  - validar dominio permitido
  - matricular en el curso de forma atomica
- En `activate/oauth/complete`:
  - validar identidad OAuth
  - crear/activar membership `student`
  - matricular en el curso de forma atomica
- Extender:
  - `StudentJoinPage`
  - `AuthCallbackPage`
  - `activationContext`
  - `api.ts`
  - `adam-types.ts`
- Mantener convivencia completa con el flujo actual por `invite_token`

**Criterios de aceptacion**

- Un estudiante nuevo puede entrar por el link del curso y quedar matriculado sin bypass
  inseguro.
- Un estudiante autenticado puede entrar por el link y quedar matriculado de forma
  idempotente.
- Un curso inactivo falla cerrado.
- Un link rotado o revocado falla cerrado.
- El flujo nuevo convive con `invite_token` sin regresiones.

**Failure modes que este issue debe cubrir**

- `course_access_token` no soportado por `activationContext`
- OAuth callback que sigue intentando leer solo `invite_token`
- usuario autenticado con dominio invalido
- doble click o carrera en enrollment

---

## Issue 5

**Titulo:** `Frontend: implementacion exacta del mockup admin en React`

**Tipo:** `Feature`

**Dependencias:** Issue 2, Issue 3, Issue 4

**Objetivo**

Implementar la pantalla admin exacta al mockup y conectarla a contratos backend reales.

**Tareas**

- Crear `frontend/src/features/admin-dashboard/*`
- Crear la ruta protegida `/admin/dashboard`
- Ajustar `RootRedirect` y `GuestOnlyRoute`
- Evitar `SiteHeader` global en esta ruta
- Maquetar exactamente:
  - header oscuro propio
  - 4 KPI cards
  - 3 quick actions
  - barra de filtros
  - tabla/directorio
  - modales Crear, Editar, Archivar, Invitar Docente
  - toast flotante
- Conectar KPIs, directorio, filtros, paginacion y modales a backend real
- `Gestion de Docentes`:
  - mostrar toast placeholder
  - no navegar
- `Reportes Globales`:
  - mostrar toast `Proximamente`
  - no navegar
- `Invitar Docente`:
  - usar endpoint real
  - mostrar y permitir copiar el link devuelto
- `Link de Invitacion` por curso:
  - copiar el link real generado por backend
- Si backend responde `admin_membership_context_required`, mostrar error explicito y no
  inventar un tenant por defecto
- Mantener equivalencia visual desktop y mobile con el mockup

**Criterios de aceptacion**

- `/admin/dashboard` existe y esta protegida por rol.
- La pantalla es visualmente igual al mockup.
- No queda el header global encima del dashboard.
- No quedan datos demo en la implementacion final.
- Los modales y toasts conservan la jerarquia visual del mockup.

**Failure modes que este issue debe cubrir**

- reuso de componentes compartidos que rompa el layout del mockup
- header global visible encima del dashboard
- diferencias entre labels/columnas/modales respecto al HTML de referencia
- UX silenciosa frente a error de contexto admin o stale pending invite

---

## Issue 6

**Titulo:** `QA Gate: pruebas funcionales, de seguridad y de paridad visual para dashboard admin`

**Tipo:** `Enhancement`

**Dependencias:** Issue 2, Issue 3, Issue 4, Issue 5

**Objetivo**

Cerrar la fase con un gate explicito de calidad para contrato, seguridad, aislamiento y
paridad visual.

**Tareas**

- Backend:
  - tests de schema y migracion
  - tests de filtros y paginacion
  - tests de aislamiento por tenant
  - tests de actor admin con multiples memberships
  - tests de curso con docente pendiente
  - tests de stale pending invite
  - tests de rotacion de link
  - tests de `course_access_token`
  - tests de curso inactivo
  - tests de enrollment idempotente
- Frontend:
  - tests de routing `/admin/dashboard`
  - tests de quick actions placeholder
  - tests de create/edit/archive/invite
  - tests de filtros
  - tests de paginacion
  - tests de empty state
  - tests de `course_access_token` en `StudentJoinPage`
  - tests de `AuthCallbackPage` con flow de course access
  - tests de `activationContext` extendido
- Browser QA:
  - comparacion visual con mockup
  - desktop
  - mobile
  - copy link
  - regenerate link
  - toast `Proximamente`
  - verificacion explicita de que no aparece el header global

**Criterios de aceptacion**

- Pasa:
  - `uv run --directory backend pytest -q`
  - `uv run --directory backend mypy src`
  - `npm --prefix frontend run lint`
  - `npm --prefix frontend run test`
  - `npm --prefix frontend run build`
- Existe evidencia visual de paridad con el mockup.
- No se aprueba la fase si el dashboard cae en diseño basico.
- No se aprueba la fase si el link del curso rompe seguridad o aislamiento.

## Contratos de Request/Response Recomendados

Para reducir decisiones durante implementacion paralela, los payloads deben seguir esta
forma minima.

### `GET /api/admin/dashboard/summary`

```json
{
  "active_courses": 4,
  "active_teachers": 3,
  "enrolled_students": 89,
  "average_occupancy": 74
}
```

### `GET /api/admin/courses`

```json
{
  "items": [
    {
      "id": "course-id",
      "title": "Gerencia Estrategica y Modelos de Negocio",
      "code": "GTD-GEME-01",
      "semester": "2026-I",
      "academic_level": "Especializacion",
      "status": "active",
      "teacher_display_name": "Julio Cesar Paz",
      "teacher_state": "active",
      "teacher_assignment": {
        "kind": "membership",
        "membership_id": "membership-id"
      },
      "students_count": 24,
      "max_students": 30,
      "occupancy_percent": 80,
      "access_link": "/app/join#course_access_token=..."
    }
  ],
  "page": 1,
  "page_size": 8,
  "total": 4,
  "total_pages": 1
}
```

### `POST /api/admin/courses`

```json
{
  "title": "Gerencia Estrategica y Modelos de Negocio",
  "code": "GTD-GEME-01",
  "semester": "2026-I",
  "academic_level": "Especializacion",
  "max_students": 30,
  "status": "active",
  "teacher_assignment": {
    "kind": "pending_invite",
    "invite_id": "invite-id"
  }
}
```

### `PATCH /api/admin/courses/{course_id}`

```json
{
  "title": "Gerencia Estrategica y Modelos de Negocio",
  "code": "GTD-GEME-01",
  "semester": "2026-I",
  "academic_level": "Especializacion",
  "max_students": 35,
  "status": "inactive",
  "teacher_assignment": {
    "kind": "membership",
    "membership_id": "membership-id"
  }
}
```

### `GET /api/admin/teacher-options`

```json
{
  "active_teachers": [
    {
      "membership_id": "membership-id",
      "full_name": "Julio Cesar Paz",
      "email": "julio.paz@univ.edu"
    }
  ],
  "pending_invites": [
    {
      "invite_id": "invite-id",
      "full_name": "Diana Lopez",
      "email": "diana.lopez@univ.edu",
      "status": "pending"
    }
  ]
}
```

### `POST /api/admin/teacher-invites`

```json
{
  "invite_id": "invite-id",
  "full_name": "Diana Lopez",
  "email": "diana.lopez@univ.edu",
  "status": "pending",
  "activation_link": "/app/teacher/activate#invite_token=..."
}
```

### `POST /api/course-access/resolve`

```json
{
  "course_id": "course-id",
  "course_title": "Gerencia Estrategica y Modelos de Negocio",
  "university_name": "Universidad Demo",
  "teacher_display_name": "Julio Cesar Paz",
  "course_status": "active",
  "link_status": "active",
  "allowed_auth_methods": ["microsoft", "password"]
}
```

### `POST /api/course-access/enroll`

```json
{
  "status": "enrolled"
}
```

### `POST /api/course-access/activate/password`

```json
{
  "status": "activated",
  "next_step": "sign_in",
  "email": "estudiante@universidad.edu"
}
```

### `POST /api/course-access/activate/oauth/complete`

```json
{
  "status": "activated"
}
```

## Failure Modes Obligatorios

| Codepath | Falla realista | Test obligatorio | Error handling | UX esperada |
|---|---|---|---|---|
| Admin API | actor con multiples memberships admin activas | backend | `409 admin_membership_context_required` | error explicito, nunca tenant implicito |
| Create/Edit course | pending invite queda stale antes del submit | backend + frontend | `409 stale_pending_teacher_invite` | toast/error y refetch de options |
| Course access resolve | token rotado o revocado | backend + frontend | fail-closed | mensaje claro, no pantalla vacia |
| Course access enroll | curso archivado entre resolve y enroll | backend + frontend | fail-closed | mensaje claro, sin enrollment silencioso |
| Enrollment | doble click o carrera | backend | idempotencia | `already_enrolled` o exito equivalente |
| Frontend join | token queda en URL o state | frontend | tests de hash cleanup y context corto | nunca visible tras mount |

## Supuestos y Defaults

- La fase toca backend, schema, frontend y flujo de join estudiantil.
- No es una fase solo de maquetacion.
- El dashboard solo pertenece al `university_admin`.
- El nombre del docente pendiente se guarda en backend y se muestra antes de activacion.
- El envio real de correo queda fuera de la fase hasta tener proveedor, secretos,
  templates y runbook.
- `Gestion de Docentes` y `Reportes Globales` no escalan dentro de esta fase.
- El sistema debe quedar listo para trabajo paralelo, pero la secuencia de dependencias
  del documento no se debe violar.

## Riesgos a Vigilar

- Que frontend implemente el mockup con datos mock y no con contratos reales.
- Que backend convierta el link del curso en bypass inseguro.
- Que se rompa tenant isolation al listar cursos o docentes.
- Que se simplifique el diseño del mockup para "terminar mas rapido".
- Que se interprete `archivar` como delete.
- Que Issue 4 toque solo `StudentJoinPage` y deje roto `AuthCallbackPage` o
  `activationContext`.

## Cierre

Esta fase no es "hacer una pantalla admin". Es cerrar un dashboard operativo,
multi-tenant, compatible con el auth perimeter ya aprobado y visualmente identico al
mockup obligatorio.

Cualquier implementacion que cumpla solo una de esas dos dimensiones queda incompleta:

- si se ve igual pero rompe seguridad, esta mal
- si es segura pero se aparta del mockup, tambien esta mal

El trabajo de implementacion debe seguir este documento issue por issue y respetar sus
dependencias, contratos y criterios de aceptacion.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | not run | No requerido para cerrar arquitectura de esta fase |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | not run | No requerido para este gate |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR | 6 gaps cerrados: contexto admin, union docente, endpoints de course access, archivos frontend a tocar, contratos mutables y gate visual del mockup |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | not run | Recomendable solo si se quiere un segundo gate visual antes de codificar |

- **UNRESOLVED:** 0
- **VERDICT:** ENG CLEARED - listo para implementacion. La paridad visual exacta con el mockup sigue siendo obligatoria y debe validarse en Issue 6.
