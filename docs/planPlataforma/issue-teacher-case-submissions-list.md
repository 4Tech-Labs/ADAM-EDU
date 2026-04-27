# Issue — Vista de entregas por caso (listado del docente)

> **Tipo:** Feature (frontend + backend, read-only)
> **Surface:** Teacher
> **Ruta:** `/teacher/cases/:assignmentId/entregas`
> **Tamaño estimado:** S–M (un endpoint nuevo + una página nueva, sin migraciones)
> **Estado actual:** la ruta existe como placeholder en [frontend/src/app/App.tsx](frontend/src/app/App.tsx#L151-L157)
> **Issue siguiente (NO en este scope):** vista de detalle por estudiante con módulos, respuestas, soluciones esperadas y formulario de calificación.

---

## 1. Contexto y objetivo

Hoy el docente ve sus casos activos en el dashboard ([CasosActivosSection.tsx](frontend/src/features/teacher-dashboard/CasosActivosSection.tsx#L118-L124)) y al hacer click en **"Entregas"** llega a una página vacía que dice *"El listado de entregas estará disponible en la próxima versión."*

Esta issue convierte ese placeholder en una vista funcional **de solo lectura** que muestra **una fila por estudiante asignado a ese caso**, con su estado de entrega y, si ya está calificado, su nota. Cada fila expone un botón **"Ver entrega y calificar"** que será cableado a la siguiente issue (vista de detalle + calificación). En esta issue el botón solo navega a una ruta placeholder.

**Por qué importa ahora:** sin esta vista, el docente no tiene forma de saber qué alumnos han enviado el caso ni quién falta. La data ya existe en backend (`student_case_responses` + `case_grades`). Lo único que falta es exponerla por `assignment_id`.

---

## 2. Step 0 — Scope challenge

### Qué ya existe (a reutilizar, NO reconstruir)

| Pieza | Ubicación | Cómo se reutiliza |
|---|---|---|
| Lógica de overlay alumno × caso (status, score, graded_at) | `get_teacher_course_gradebook` en [teacher_reads.py](backend/src/shared/teacher_reads.py#L545) | Extraer/parametrizar el join `memberships` × `student_case_responses` × `case_grades` para una nueva consulta filtrada por `assignment_id`. **No duplicar la lógica de mapeo de status.** |
| Schema de celda de calificación | `TeacherCourseGradebookCell` en [teacher_gradebook_schema.py](backend/src/shared/teacher_gradebook_schema.py) (`status`, `score`, `graded_at`) | Reusar literalmente el `Literal["not_started","in_progress","submitted","graded"]` y el formato `score`. |
| Guard de ownership del docente sobre el caso | `teacher_context.py` + endpoint `GET /api/teacher/cases/{assignment_id}` (línea 259 de teacher_router.py) | Reusar la misma dependencia de autorización. Cero código nuevo de auth. |
| Helpers de formato (status chip, score, fecha) | `formatTeacherGradebookCellStatus`, `formatTeacherGradebookScore`, `formatTeacherCourseTimestamp` (usados por [TeacherCourseStudentsTab.tsx](frontend/src/features/teacher-course/TeacherCourseStudentsTab.tsx)) | Importar tal cual. **No re-implementar.** |
| Cliente API + React Query setup | `frontend/src/shared/` | Crear el hook nuevo siguiendo el patrón de `useTeacherCases` / `useTeacherCourseGradebook`. |
| Ruta y botón ya cableados | `CasosActivosSection.tsx` línea 120 | Cero cambios. El botón ya navega a `/teacher/cases/${caso.id}/entregas`. |

### Mínimo viable de cambios

**Backend (3 archivos):**
- `backend/src/shared/teacher_gradebook_schema.py` — añadir 2 schemas nuevos (`TeacherCaseSubmissionRow`, `TeacherCaseSubmissionsResponse`).
- `backend/src/shared/teacher_reads.py` — añadir `get_teacher_case_submissions(db, *, teacher_membership_id, assignment_id)`.
- `backend/src/shared/teacher_router.py` — registrar `GET /cases/{assignment_id}/submissions`.

**Frontend (4 archivos nuevos + 2 modificados):**
- Nuevo: `frontend/src/features/teacher-case-submissions/TeacherCaseSubmissionsPage.tsx`
- Nuevo: `frontend/src/features/teacher-case-submissions/useTeacherCaseSubmissions.ts`
- Nuevo: `frontend/src/features/teacher-case-submissions/teacherCaseSubmissionsModel.ts` (tipos espejo del backend)
- Nuevo: `frontend/src/features/teacher-case-submissions/TeacherCaseSubmissionsPage.test.tsx`
- Modificado: `frontend/src/app/App.tsx` — reemplazar placeholder por `<TeacherCaseSubmissionsPage />`, **además** registrar nueva ruta placeholder para `/teacher/cases/:assignmentId/entregas/:membershipId` (destino del botón "Ver entrega y calificar"; será reemplazada por la siguiente issue).

**Pruebas (2 archivos):**
- Nuevo: `backend/tests/test_teacher_case_submissions.py`
- Nuevo: el test del frontend listado arriba.

**Total: 8 archivos nuevos/modificados, 0 migraciones, 0 cambios de schema en BD, 0 nueva infraestructura.**

---

## 3. Diseño backend

### 3.1 Endpoint

```
GET /api/teacher/cases/{assignment_id}/submissions
```

**Auth:** mismo guard que `GET /api/teacher/cases/{assignment_id}` — el docente debe ser owner de **al menos uno** de los cursos donde el assignment está publicado. Si no, `404 NOT_FOUND` (no `403`, para no filtrar existencia de assignments ajenos — alinea con el patrón actual del router).

**Response (`TeacherCaseSubmissionsResponse`):**

```python
class TeacherCaseSubmissionRow(StrictModel):
    membership_id: str
    full_name: str
    email: str
    course_id: str            # curso por el cual el alumno tiene asignado este caso
    course_code: str          # para mostrar en la tabla cuando el caso es multi-curso
    enrolled_at: datetime
    status: Literal["not_started", "in_progress", "submitted", "graded"]
    submitted_at: datetime | None
    score: float | None       # presente solo si status == 'graded'
    max_score: float          # del assignment (default 5.00)
    graded_at: datetime | None

class TeacherCaseSubmissionsResponse(StrictModel):
    case: TeacherCourseGradebookCase   # reusa el schema existente (assignment_id, title, deadline, max_score, etc.)
    submissions: list[TeacherCaseSubmissionRow]
```

**Por qué incluir `course_id` + `course_code` por fila:** un assignment puede estar publicado en varios cursos (`assignment_courses`). El mismo caso, distintas cohortes. Si solo devolvemos `membership_id`, el docente no distingue el grupo. Esto **no** crea filas duplicadas: cada `membership` pertenece a un solo `course_membership` activo del docente; el cross-enrollment está prohibido por el guard existente (Issue 205).

**Orden de filas:** `course_code ASC, full_name ASC, email ASC` — determinístico, evita flake en tests.

### 3.2 Query (en `teacher_reads.py`)

Una sola query SQL, sin N+1:

```
memberships m
  JOIN profiles p          ON p.membership_id = m.id   (LEFT — fallback a email)
  JOIN users u             ON u.id = m.user_id         (LEFT — bridge legado para email)
  JOIN course_memberships cm ON cm.membership_id = m.id AND cm.status = 'active'
  JOIN assignment_courses ac ON ac.course_id = cm.course_id AND ac.assignment_id = :assignment_id
  JOIN courses c           ON c.id = cm.course_id
  LEFT JOIN student_case_responses scr
        ON scr.membership_id = m.id AND scr.assignment_id = :assignment_id
  LEFT JOIN case_grades cg
        ON cg.membership_id = m.id AND cg.assignment_id = :assignment_id
WHERE m.role = 'student' AND m.status = 'active'
  AND <ownership guard: c.id IN (cursos del docente)>
```

**Reglas de derivación de `status` (idénticas a `get_teacher_course_gradebook` — extraer a helper privado compartido `_derive_grade_cell_status` para no duplicar):**

```
cg.status == 'graded'                       → 'graded'
cg.status == 'submitted' OR scr.status == 'submitted' → 'submitted'
scr.status == 'draft'                        → 'in_progress'
sin scr y sin cg                             → 'not_started'
```

**Score:** solo se expone cuando `status == 'graded'`. Si está `submitted` pero el docente aún no calificó, `score = None`.

### 3.3 Diagrama de flujo

```
                    ┌───────────────────────────┐
 GET /cases/        │ teacher_router.py         │
 {id}/submissions ─▶│  - resolve teacher        │
                    │  - assert ownership of    │
                    │    assignment via         │
                    │    assignment_courses     │
                    └────────────┬──────────────┘
                                 │
                                 ▼
                    ┌───────────────────────────┐
                    │ teacher_reads.py          │
                    │ get_teacher_case_         │
                    │ submissions(...)          │
                    │  one SQL, no N+1          │
                    └────────────┬──────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
        memberships +     student_case_       case_grades
        course_memberships  responses        (overlay score)
        + assignment_courses (state)
                                 │
                                 ▼
                    ┌───────────────────────────┐
                    │ TeacherCaseSubmissions    │
                    │ Response (Pydantic)       │
                    └───────────────────────────┘
```

---

## 4. Diseño frontend

### 4.1 Ruta

En [App.tsx](frontend/src/app/App.tsx):

```tsx
// Reemplazar el placeholder existente (líneas 151-157):
<Route
  path="/teacher/cases/:assignmentId/entregas"
  element={<RequireRole role="teacher"><TeacherCaseSubmissionsPage /></RequireRole>}
/>

// AÑADIR nuevo placeholder para el destino del botón "Ver entrega y calificar".
// La siguiente issue reemplaza este placeholder por la vista de detalle + calificación.
<Route
  path="/teacher/cases/:assignmentId/entregas/:membershipId"
  element={
    <RequireRole role="teacher">
      <div className="...">
        <h1>Ver entrega y calificar</h1>
        <p>Esta vista estará disponible en la próxima versión.</p>
      </div>
    </RequireRole>
  }
/>
```

**Por qué registrar el placeholder destino aquí:** el botón debe ser navegable en producción desde el momento en que esta issue se mergea. Si el destino no existe, el alumno hace click y ve un 404 del SPA. Inaceptable para producción.

### 4.2 Página `TeacherCaseSubmissionsPage.tsx`

Patrón calcado de [TeacherCourseStudentsTab.tsx](frontend/src/features/teacher-course/TeacherCourseStudentsTab.tsx):

- Header: título del caso, deadline, `max_score`, contador "X estudiantes asignados".
- Botón secundario "Volver" → `navigate(-1)` o explícito a `/teacher/dashboard`.
- Buscador por nombre o correo (mismo `searchQuery` + filtro client-side; reutiliza `teacher-gradebook-search` styles si quedan limpios — si requiere CSS específico, crear `teacherCaseSubmissionsPage.css` minimalista).
- Estados: `loading` (spinner + copy), `error` (alert-strip con retry), `empty` (alumnos = 0).
- Tabla con columnas:

| Estudiante | Correo | Curso | Estado | Enviado | Nota | Acciones |
|---|---|---|---|---|---|---|
| `full_name`<br>`Ingresó: ...` | email | chip con `course_code` | chip de status (mismo estilo que gradebook) | `submitted_at` formateado o `—` | `score / max_score` si graded, si no `—` | botón "Ver entrega y calificar" |

**Comportamiento del botón "Ver entrega y calificar":**
- Estilo: usar mismo gradient indigo del botón "Entregas" del dashboard (consistencia visual).
- Estado `not_started`: **deshabilitado** con tooltip "El estudiante aún no ha abierto el caso." Razón: no hay nada que ver.
- Estados `in_progress`, `submitted`, `graded`: habilitado.
- Cuando `graded`: el label cambia a **"Ver calificación"** (la nota ya se ve en la columna; el botón mantiene la acción de revisar).
- `onClick` → `navigate(\`/teacher/cases/${assignmentId}/entregas/${membershipId}\`)`.

### 4.3 Hook `useTeacherCaseSubmissions(assignmentId)`

- React Query, `queryKey: ['teacher', 'case-submissions', assignmentId]`.
- `staleTime` corto (30s) — el docente espera ver entregas frescas.
- Refetch on window focus: **on** (alinea con expectativa de "actualicé y veo si ya entregaron").
- Botón "Actualizar" en el header (mismo patrón que `teacher-gradebook-refresh-group`).

### 4.4 Tipos (`teacherCaseSubmissionsModel.ts`)

Espejo exacto del schema Pydantic. Reutilizar el tipo `status` del modelo del gradebook si ya está exportado; si no, declararlo aquí con el mismo `Literal` y dejar un TODO para deduplicar en una issue futura (no en este scope — sería refactor cross-feature).

---

## 5. Diagrama de UX y flujo de datos

```
Dashboard docente
  └─ tabla "Casos Activos"
       └─ click "Entregas"  ──▶  /teacher/cases/:assignmentId/entregas
                                        │
                                        ▼
                             ┌────────────────────────────────┐
                             │ TeacherCaseSubmissionsPage     │
                             │  GET /api/teacher/cases/       │
                             │      {id}/submissions          │
                             └──────────────┬─────────────────┘
                                            │
                       ┌────────────────────┼────────────────────┐
                       ▼                    ▼                    ▼
                  loading              error+retry            tabla con filas
                                                                   │
                                       ┌───────────────────────────┴───────┐
                                       ▼                                   ▼
                                  status chip                  botón "Ver entrega y calificar"
                                  + score (si graded)                    │
                                                                          ▼
                                                       /teacher/cases/:id/entregas/:membershipId
                                                                  (placeholder en esta issue;
                                                                   siguiente issue lo construye)
```

---

## 6. Plan de tests

### 6.1 Backend — `backend/tests/test_teacher_case_submissions.py`

**Marcadores:** los DB-tests siguen el contrato per-test (ver `AGENTS.md`); ningún marker especial necesario.

Casos a cubrir:

1. **Happy path single-course:** un caso publicado en un curso del docente, 3 alumnos en estados distintos (`not_started`, `in_progress`, `submitted`, `graded`). Verifica que cada fila trae el `status` correcto y que `score` solo aparece en `graded`.
2. **Multi-course assignment:** mismo caso publicado en dos cursos del docente. Verifica que aparecen alumnos de ambos cursos, cada uno con su `course_code` correcto, ordenados por `course_code, full_name`.
3. **Auth — docente sin ownership:** el docente B pide submissions de un assignment que solo pertenece al docente A. Espera `404`.
4. **Auth — assignment no existe:** id inventado → `404`.
5. **Auth — usuario no docente:** estudiante autenticado intenta el endpoint → `403` (o el código que ya devuelva `RequireRole` equivalente backend).
6. **Estudiantes suspendidos excluidos:** una matrícula `suspended` en el curso no debe aparecer en submissions.
7. **Email fallback:** alumno sin `profiles.full_name` cae al email como `full_name` (mismo comportamiento que gradebook — confirma que el helper compartido se aplicó).
8. **`graded` sin `score` (estado inválido en BD):** check constraint de `case_grades` ya lo previene; **no** test específico (se test-ea a nivel de migración existente). Documentar en el test file con un comentario.
9. **Snapshot determinismo de orden:** llamar dos veces y comparar — mismo orden.

### 6.2 Frontend — `TeacherCaseSubmissionsPage.test.tsx`

Casos a cubrir:

1. Renderiza spinner mientras carga.
2. Renderiza tabla con N filas para N submissions.
3. Botón "Ver entrega y calificar" deshabilitado para `not_started`, habilitado para los demás.
4. Botón con label "Ver calificación" cuando `graded`.
5. Score visible solo cuando `graded`; en otros estados muestra `—`.
6. Buscador filtra por nombre y por correo (case-insensitive).
7. Empty state cuando no hay alumnos asignados.
8. Error state con botón retry que dispara refetch.
9. Click en botón navega a `/teacher/cases/:assignmentId/entregas/:membershipId` con los IDs correctos (mock de `useNavigate`).
10. Refetch on window focus dispara nueva request (mock React Query o usar `refetch()` directo).

### 6.3 Diagrama de cobertura

```
Nuevo codepath                              ¿Test backend? ¿Test frontend?
─────────────────────────────────────────── ─────────────  ──────────────
GET /cases/{id}/submissions  happy single   ✅ (#1)         —
GET /cases/{id}/submissions  multi-course   ✅ (#2)         —
GET /cases/{id}/submissions  ownership      ✅ (#3,#4,#5)   —
status derivation per-row                   ✅ (#1)         ✅ (#3,#4,#5)
suspended exclusion                         ✅ (#6)         —
email fallback                              ✅ (#7)         —
sort determinism                            ✅ (#9)         —
Page render: loading                        —              ✅ (#1)
Page render: tabla                          —              ✅ (#2)
Botón disabled si not_started               —              ✅ (#3)
Botón label graded                          —              ✅ (#4)
Score visibility                            —              ✅ (#5)
Buscador                                    —              ✅ (#6)
Empty state                                 —              ✅ (#7)
Error+retry                                 —              ✅ (#8)
Navegación al placeholder                   —              ✅ (#9)
Refetch on focus                            —              ✅ (#10)
```

---

## 7. Failure modes y manejo de errores

| Modo de falla | ¿Tiene test? | ¿Tiene manejo? | ¿Visible al usuario? |
|---|---|---|---|
| Backend devuelve 404 (assignment ajeno o inexistente) | ✅ | ✅ — frontend muestra error con copy "No encontramos este caso o no tienes acceso." | Sí, claro. |
| Backend devuelve 500 | ❌ explícito (genérico) | ✅ — error state genérico + retry | Sí. |
| Network timeout / offline | ❌ | ✅ — React Query maneja retry, error state visible | Sí. |
| Lista enorme (>500 alumnos) | ❌ | ⚠️ — sin paginación en esta versión. Aceptable: cursos típicos ≤ 60 alumnos. **Documentar en TODOS.md**. | No bloquea uso. |
| `case_grades` con `score` sin `max_score` consistente | N/A — check constraint en BD lo impide | ✅ a nivel BD | N/A. |
| Estudiante sin `email` ni `full_name` | ⚠️ — backend usa email como fallback de full_name; si email también es null, queda string vacío | ⚠️ frontend debe mostrar `(sin nombre)` en vez de fila en blanco | Sí. **Añadir test.** |
| Botón "Ver entrega y calificar" navega a placeholder | N/A — esperado en esta issue | ✅ — placeholder explícito en App.tsx | Sí, mensaje "próximamente". |

**Critical gaps:** ninguno (todos los modos tienen test o manejo o son aceptables documentados).

---

## 8. NOT in scope (deferido)

| Item | Por qué se difiere |
|---|---|
| Vista de detalle por estudiante (módulos M1–M6, respuestas, soluciones esperadas) | Es la siguiente issue. Ruta destino `/teacher/cases/:assignmentId/entregas/:membershipId` queda como placeholder. |
| Formulario de calificación (score + feedback) | Bloqueado por la vista de detalle. |
| Calificación granular por pregunta o módulo (`case_question_grades`) | Decisión arquitectural pendiente. Requiere migración nueva. Se decide en la issue de detalle. |
| Sugerencias de calificación con IA (campos `ai_suggested_*`) | Fase posterior, requiere ADR. |
| Endpoint para que el alumno vea su nota | Fuera del flujo del docente. Issue separada. |
| Paginación / scroll virtualizado del listado de entregas | Aceptable hasta ~500 filas. **Añadir TODO.** |
| Exportar entregas a CSV/Excel | No solicitado. |
| Notificaciones al docente cuando un alumno entrega | No solicitado. |
| Reabrir/anular una calificación (con historial) | Decisión de la issue de detalle. |
| Filtrado por estado en la tabla (chips clickeables) | Mejora opcional, fácil de añadir después; no necesaria para el MVP. |

---

## 9. Acceptance criteria

- [ ] `GET /api/teacher/cases/{assignment_id}/submissions` devuelve `TeacherCaseSubmissionsResponse` con la forma especificada.
- [ ] Endpoint devuelve `404` para assignments donde el docente no es owner de ningún curso.
- [ ] Endpoint devuelve `403` para usuarios no docentes.
- [ ] Lógica de derivación de `status` es la misma que `get_teacher_course_gradebook` (extraída a helper compartido).
- [ ] Ruta `/teacher/cases/:assignmentId/entregas` reemplaza el placeholder por la nueva página funcional.
- [ ] Ruta `/teacher/cases/:assignmentId/entregas/:membershipId` queda registrada como placeholder explícito.
- [ ] Tabla muestra: nombre, correo, curso (chip), estado (chip), fecha de envío, nota (si graded), botón.
- [ ] Botón está deshabilitado para `not_started` con tooltip explicativo.
- [ ] Botón cambia a "Ver calificación" cuando `status == 'graded'`.
- [ ] Buscador filtra por nombre y correo (case-insensitive).
- [ ] Estados loading / error+retry / empty implementados.
- [ ] Refetch on window focus activado.
- [ ] Tests backend (≥7 casos listados) en verde.
- [ ] Tests frontend (≥10 casos listados) en verde.
- [ ] `uv run --directory backend pytest -q` verde.
- [ ] `uv run --directory backend mypy src` verde.
- [ ] `npm --prefix frontend run lint` verde.
- [ ] `npm --prefix frontend run test` verde.
- [ ] `npm --prefix frontend run build` verde.
- [ ] Sin nuevas migraciones, sin cambios en `case_generator/**`, sin `sys.path` hacks, sin `console.log` ni `print` colados.
- [ ] PR sigue [CONTRIBUTING.md](CONTRIBUTING.md): branch `feature/...`, squash merge.

---

## 10. Riesgos y guardrails (para el implementador)

1. **No duplicar `_derive_grade_cell_status`.** Si ya existe en `teacher_reads.py`, reutilizar; si no, extraer del bloque actual del gradebook como función privada y usarla desde ambos sitios. Es DRY no negociable: si la lógica de status diverge, el dashboard del curso y el listado por caso mostrarán cosas distintas para el mismo alumno.
2. **No tocar `case_generator/**`** (ver `AGENTS.md`).
3. **No reabrir folders genéricos del frontend** (`components`, `pages`, etc. — ver `AGENTS.md`). La nueva carpeta es `frontend/src/features/teacher-case-submissions/`.
4. **Auth precedence:** el endpoint nuevo es protegido. Respetar el orden `verified_identity → profile_state → membership_state → password_rotation → role/context → handler`. El guard de docente ya implementa esto vía dependencia compartida.
5. **No añadir `feedback` ni `score` writeable en esta issue.** Cero mutaciones.
6. **No exponer `case_grades.feedback`** en este endpoint — el feedback se renderiza en la vista de detalle (siguiente issue), no en la tabla.

---

## 11. Comandos de validación local

```powershell
# Backend
cd C:\Users\Juan Camilo Dorado\Downloads\ADAM-EDU
docker compose up -d adam-edu-postgres
cd backend
uv run alembic upgrade head
uv run pytest -q tests/test_teacher_case_submissions.py
uv run mypy src

# Frontend
cd ..\frontend
npm run lint
npm run test -- TeacherCaseSubmissionsPage
npm run build
```
