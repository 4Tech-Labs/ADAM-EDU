# Teacher · Vista de detalle/preview de la entrega del estudiante (preguntas, respuestas y solución esperada)

> **Iteración previa cerrada:** Issue #210 / PR #212 entregaron el listado `/teacher/cases/:assignmentId/entregas` y registraron la ruta placeholder `/teacher/cases/:assignmentId/entregas/:membershipId`.
> **Esta issue:** implementar dicha ruta como vista **de solo lectura** que el docente abre al pulsar **"Ver entrega y calificar"** en `TeacherCaseSubmissionsPage.tsx`. Debe mostrar, módulo por módulo, las **preguntas del caso**, la **respuesta del estudiante** y la **solución esperada** del caso.
> **Fuera de alcance (próxima issue):** captura de calificación, edición de feedback, persistencia de notas, panel de rúbrica. Esta issue **debe dejar reservado** el espacio visual y los contratos de datos para que la próxima iteración solo añada el formulario de calificación, sin rediseñar la página ni renombrar archivos.

---

## 0. Inventario de reuso (OBLIGATORIO antes de empezar)

Antes de crear cualquier símbolo nuevo, el implementador debe leer y reutilizar:

| Activo existente | Ruta | Uso esperado |
| --- | --- | --- |
| `Assignment.canonical_output` (JSONB) | `backend/src/shared/models.py` | Fuente del contenido del caso (preguntas + `solucion_esperada` por módulo). |
| `StudentCaseResponse` | `backend/src/shared/models.py` | Estado del intento del estudiante (`status`, `answers`, `submitted_at`, `version`). |
| `StudentCaseResponseSubmission` | `backend/src/shared/models.py` | Snapshot inmutable de la entrega (`answers_snapshot`, `submitted_at`, `canonical_output_hash`). **Es la fuente de verdad cuando existe.** |
| `CaseGrade` | `backend/src/shared/models.py` | Solo para resumen de estado (`status`, `score`, `max_score`, `graded_at`). **No exponer `feedback` aquí.** |
| `QUESTION_FIELD_TO_MODULE` | `backend/src/shared/student_reads.py` | Mapa `caseQuestions→M1`, `edaQuestions→M2`, `m3Questions→M3`, `m4Questions→M4`, `m5Questions→M5`. **Reusar; no duplicar.** |
| `sanitize_canonical_output_for_student` | `backend/src/shared/case_sanitization.py` | **No usar** para esta vista (oculta `solucion_esperada`). Crear hermano para docente (ver §3). |
| `_build_assignment_target_courses_subquery`, `_assignment_target_course_metadata` | `backend/src/shared/teacher_reads.py` | Para validar que el `assignment` pertenece al docente y el `membership` pertenece a un curso destino. |
| `_derive_grade_cell_status` | `backend/src/shared/teacher_reads.py` | Para derivar `status` (`not_started` / `in_progress` / `submitted` / `graded`) coherente con la vista padre. |
| `get_teacher_case_submissions` | `backend/src/shared/teacher_reads.py` | Patrón de referencia (auth chain, joins, mapping). El nuevo read debe seguir el mismo estilo. |
| `TeacherContext`, `require_teacher_context` | `backend/src/shared/teacher_context.py` | Cadena de auth (`verified_identity → profile → membership → password_rotation → role`). |
| `TeacherLayout` | `frontend/src/features/teacher-layout/TeacherLayout.tsx` | Shell de la página (no crear shell propio). |
| `formatTeacherCourseTimestamp`, `formatTeacherGradebookScore`, `formatTeacherGradebookCellStatus` | `frontend/src/features/teacher-course/teacherCourseModel.ts` | Formateadores. **Reusar idéntico para coherencia visual con el listado.** |
| `getTeacherCaseSubmissionsErrorMessage` (patrón) | `frontend/src/features/teacher-case-submissions/useTeacherCaseSubmissions.ts` | Patrón de helper de errores TanStack. Replicar idéntico estilo (`getTeacherCaseSubmissionDetailErrorMessage`). |
| Ruta placeholder `:/membershipId` | `frontend/src/app/App.tsx` | **Reemplazar el placeholder** por el componente real. No añadir nueva ruta. |
| Botón "Ver entrega y calificar" | `frontend/src/features/teacher-case-submissions/TeacherCaseSubmissionsPage.tsx` | Ya navega a la ruta correcta. **No tocar.** |

> **Regla DRY:** si una nueva utilidad supera 25 LOC y solo se usa una vez, mantenla local; si se usa ≥2 veces o pertenece al dominio del listado padre, extráela al módulo compartido (`teacher_reads.py` o `teacherCourseModel.ts`). Cualquier helper extraído debe tener tests propios.

---

## 1. Contexto y objetivo

El docente acaba de revisar la lista de entregas (`/teacher/cases/:assignmentId/entregas`). Al pulsar **"Ver entrega y calificar"** sobre la fila de un estudiante, navega a `/teacher/cases/:assignmentId/entregas/:membershipId`. Hoy esa ruta carga un placeholder.

**Objetivo de esta issue:** entregar la página real que permite al docente **leer**:

1. Metadatos del caso y del estudiante (título, curso, fecha de entrega, estado, fecha de envío).
2. Para cada uno de los módulos del caso (M1…M5), en orden:
   - Enunciado de la pregunta (texto del estudiante-facing).
   - **Respuesta del estudiante** (snapshot inmutable cuando exista; si no, draft con disclaimer).
   - **Solución esperada** (`solucion_esperada` del canonical output, **visible solo para docente**).
3. Resumen de calificación actual (estado y puntaje si ya fue calificado en una iteración anterior). **No exponer `feedback`.**
4. Área visual reservada para el formulario de calificación que entregará la próxima issue (ver §6).

**No-objetivos (próxima iteración):** capturar puntaje, validar rúbrica, escribir feedback, mutar `case_grades`, exponer `feedback`, actualizar el listado padre tras calificar.

---

## 2. Flujo (ASCII)

```
TeacherCaseSubmissionsPage
   │  click "Ver entrega y calificar" (membership.status ≠ not_started)
   ▼
React Router → /teacher/cases/:assignmentId/entregas/:membershipId
   │
   ▼
TeacherCaseSubmissionDetailPage (NUEVA)
   │  useTeacherCaseSubmissionDetail(assignmentId, membershipId)
   ▼
GET /api/teacher/cases/{assignment_id}/submissions/{membership_id}
   │  auth: verified_identity → profile → membership → password_rotation → teacher_role
   │  authz: assignment pertenece a curso del docente
   │         AND membership pertenece a un curso destino del assignment
   │  data:  Assignment.canonical_output (raw, sanitizado para teacher)
   │         StudentCaseResponse (estado del draft)
   │         latest StudentCaseResponseSubmission (snapshot inmutable)
   │         CaseGrade (status, score, graded_at) — sin feedback
   ▼
TeacherCaseSubmissionDetailResponse (Pydantic strict)
   │
   ▼
UI: header + módulo selector + panel pregunta(s) + footer "Calificación (próximamente)"
```

---

## 3. Backend

### 3.1 Sanitización para docente (NUEVO helper, ubicación crítica)

Crear, en `backend/src/shared/case_sanitization.py`, una función hermana de `sanitize_canonical_output_for_student`:

```python
def build_teacher_case_review_payload(canonical_output: dict[str, Any]) -> dict[str, Any]:
    """
    Whitelist canonical_output fields safe to expose to a TEACHER reviewing a submission.

    Expone:
      - content.{caseQuestions, edaQuestions, m3Questions, m4Questions, m5Questions}
        con TODOS los campos pedagógicos públicos del estudiante MÁS
        `solucion_esperada` y `m5QuestionsSolutions` cuando aplique.
      - content.teachingNote (nota docente).
    Omite (siempre):
      - Cualquier campo de telemetría LLM, prompts internos, IDs de jobs de authoring,
        trazas de tokens, hashes de validación, debug logs, o claves no whitelisteadas.
    """
```

Reglas:
- **No** devolver el `canonical_output` crudo. Aplicar whitelist explícita por campo (mismo patrón que `sanitize_canonical_output_for_student`).
- Reusar `_QUESTION_ARRAY_FIELDS` y constantes existentes en el módulo. Extraer un nuevo `_TEACHER_QUESTION_FIELD_WHITELIST` que extienda al de estudiante con `solucion_esperada` (y los campos pedagógicos faltantes que ya valida la suite del case_generator).
- Tests obligatorios: garantizar que el payload de docente nunca incluye campos no whitelisteados aunque el `canonical_output` los contenga (test con input sintético con `__internal_token`, `prompt_trace`, etc.).

> **No tocar `backend/src/case_generator/**`.** Esta sanitización vive en `shared/`.

### 3.2 Endpoint

```
GET /api/teacher/cases/{assignment_id}/submissions/{membership_id}
```

Definir en `backend/src/shared/teacher_router.py`:

```python
@router.get(
    "/cases/{assignment_id}/submissions/{membership_id}",
    response_model=TeacherCaseSubmissionDetailResponse,
)
def get_teacher_case_submission_detail_view(
    assignment_id: str,
    membership_id: str,
    context: Annotated[TeacherContext, Depends(require_teacher_context)],
    db: Session = Depends(get_db),
) -> TeacherCaseSubmissionDetailResponse:
    return get_teacher_case_submission_detail(db, context, assignment_id, membership_id)
```

### 3.3 Read function

En `backend/src/shared/teacher_reads.py`, nueva función `get_teacher_case_submission_detail(db, context, assignment_id, membership_id)`:

1. **Authz assignment:** cargar `Assignment` filtrando por `course_id ∈ teacher.course_ids` (o subquery equivalente que ya use el listado padre). Si no existe ni pertenece, **HTTP 404** con `{"detail":"assignment_not_found"}`.
2. **Authz membership:** validar que `membership_id` pertenece a un curso `course_id` que es **target** del assignment (vía `_build_assignment_target_courses_subquery` y join contra `memberships`/`course_memberships`). Si no, **HTTP 404** con `{"detail":"submission_not_found"}` (no filtrar por contenido para evitar enumeración).
3. **Cargar:**
   - `Assignment.canonical_output` (JSONB).
   - `StudentCaseResponse` por `(membership_id, assignment_id)` si existe.
   - **Última** `StudentCaseResponseSubmission` por `response_id` ordenada `submitted_at DESC` (`limit 1`).
   - `CaseGrade` por `(membership_id, assignment_id, course_id)` si existe.
   - `Profile` y `Membership` para `full_name` y `email`.
   - `Course` (id + code + name) destino para el chip de contexto.
4. **Sanitizar** `canonical_output` con `build_teacher_case_review_payload(...)`.
5. **Construir módulos:** iterar `QUESTION_FIELD_TO_MODULE` en el orden M1→M5. Para cada módulo presente en el sanitized output:
   - `module.id` = `"M1"`…`"M5"`.
   - `module.title` = título legible (constante en español: `"Módulo 1 · Comprensión del caso"`, etc., centralizada en `teacher_reads.py` o nuevo `teacher_modules.py`).
   - Para cada pregunta proyectada: copiar el id, statement, opciones/contexto pedagógico, y `solucion_esperada`.
   - `student_answer` = lookup por question id en `submission.answers_snapshot` (preferido) o `response.answers` (fallback con `is_draft=True`).
6. **Status derivation:** usar `_derive_grade_cell_status(response.status, grade.status if grade else None)` para coherencia con la vista padre.
7. **Versionado del payload:** añadir `payload_version: int = 1` para que el frontend pueda evolucionar sin breaking change. Documentar regla de bump.

### 3.4 Schemas (Pydantic strict)

En `backend/src/shared/teacher_gradebook_schema.py` (mismo módulo que el listado padre, para colocalizar tipos del flujo de entregas):

```python
class TeacherCaseSubmissionDetailQuestion(StrictModel):
    id: str
    order: int                       # 1-based dentro del módulo
    statement: str
    context: str | None = None       # campos pedagógicos públicos opcionales
    expected_solution: str           # solucion_esperada del canonical
    student_answer: str | None       # null si el estudiante no respondió esa pregunta
    student_answer_chars: int        # len(student_answer) o 0
    is_answer_from_draft: bool       # True si proviene del draft (no hay snapshot)

class TeacherCaseSubmissionDetailModule(StrictModel):
    id: Literal["M1","M2","M3","M4","M5"]
    title: str
    questions: list[TeacherCaseSubmissionDetailQuestion]

class TeacherCaseSubmissionDetailCase(StrictModel):
    id: str                          # assignment_id
    title: str
    deadline: datetime | None
    available_from: datetime | None
    course_id: str
    course_code: str
    course_name: str
    teaching_note: str | None        # canonical.content.teachingNote (solo docente)

class TeacherCaseSubmissionDetailStudent(StrictModel):
    membership_id: str
    full_name: str
    email: str
    enrolled_at: datetime

class TeacherCaseSubmissionDetailResponseState(StrictModel):
    status: Literal["not_started","in_progress","submitted","graded"]
    first_opened_at: datetime | None
    last_autosaved_at: datetime | None
    submitted_at: datetime | None
    snapshot_id: str | None          # id del StudentCaseResponseSubmission usado
    snapshot_hash: str | None        # canonical_output_hash del snapshot

class TeacherCaseSubmissionDetailGradeSummary(StrictModel):
    status: Literal["in_progress","submitted","graded"] | None
    score: Decimal | None
    max_score: Decimal
    graded_at: datetime | None
    # NO incluir feedback aquí — pertenece a la próxima issue.

class TeacherCaseSubmissionDetailResponse(StrictModel):
    payload_version: Literal[1] = 1
    case: TeacherCaseSubmissionDetailCase
    student: TeacherCaseSubmissionDetailStudent
    response_state: TeacherCaseSubmissionDetailResponseState
    grade_summary: TeacherCaseSubmissionDetailGradeSummary
    modules: list[TeacherCaseSubmissionDetailModule]
```

> Todos los modelos heredan de `StrictModel` (`extra="forbid"`, `from_attributes=True`).

### 3.5 Reglas de fuente de verdad para `student_answer`

| `response.status` en DB | ¿Existe snapshot? | Fuente usada | `is_answer_from_draft` |
| --- | --- | --- | --- |
| `submitted` o `graded` | sí | `submission.answers_snapshot` | `false` |
| `submitted` o `graded` | no (caso de inconsistencia) | `response.answers` | `true` (alertar en logs `WARN`) |
| `draft` (in_progress) | (irrelevante) | `response.answers` | `true` |
| no existe `response` | — | `null` por pregunta | `false` |

### 3.6 Performance y escala (cientos de usuarios)

- **Una sola consulta SQL** con joins explícitos (`joinedload` o `select_from`) para `Assignment + Profile + Membership + Course + StudentCaseResponse`.
- **Subconsulta independiente** acotada para el último `StudentCaseResponseSubmission` (`order by submitted_at DESC limit 1`).
- **Sin N+1**: prohibir loops que disparen lazy loads.
- Tamaño de respuesta acotado: el `canonical_output` ya está limitado por el authoring; añadir guardia: si `len(json.dumps(modules)) > 1_500_000` (1.5 MB), truncar `expected_solution` con `__truncated_at_chars` y registrar `WARN`. Esto evita degradar la UI con casos atípicos.
- Cache HTTP: responder con `Cache-Control: private, max-age=0, must-revalidate` (consistente con resto de endpoints docentes).
- Reusar el patrón `Supavisor :6543` por defecto. **No introducir SSE, websockets ni canales Realtime** para esta vista (es read-on-demand).

### 3.7 Errores y mensajes

| Caso | HTTP | `detail` |
| --- | --- | --- |
| Assignment no existe o no es del docente | 404 | `assignment_not_found` |
| Membership no pertenece a curso destino | 404 | `submission_not_found` |
| Membership existe pero estudiante nunca abrió el caso (`response is None`) | 200 | payload completo con `response_state.status="not_started"`, `modules[*].questions[*].student_answer=null`, `grade_summary.status=null` |
| `canonical_output` ausente o malformado | 500 | `case_canonical_output_invalid` (logueado) |
| `payload_version` desconocido | n/a (servidor controla) | — |

> El frontend debe poder navegar incluso a `not_started` para ver el caso vacío, **pero** el botón en la lista padre ya está deshabilitado para `not_started`. La vista funciona como defensa en profundidad si alguien escribe la URL a mano.

---

## 4. Frontend

### 4.1 Nueva feature folder

```
frontend/src/features/teacher-case-submission-detail/
├── TeacherCaseSubmissionDetailPage.tsx
├── useTeacherCaseSubmissionDetail.ts        # TanStack Query hook + error mapper
├── teacherCaseSubmissionDetailApi.ts        # fetcher tipado + zod o tipo TS de runtime
├── teacherCaseSubmissionDetailModel.ts      # tipos + helpers puros (orden módulos, derivar labels)
├── components/
│   ├── ModuleNavigator.tsx                  # tabs/sidebar M1..M5
│   ├── QuestionPanel.tsx                    # render de una pregunta (3 columnas o stacked)
│   ├── StudentAnswerBlock.tsx
│   ├── ExpectedSolutionBlock.tsx
│   ├── SubmissionMetaHeader.tsx
│   └── GradingPlaceholderPanel.tsx          # área reservada (ver §6)
└── __tests__/
    ├── TeacherCaseSubmissionDetailPage.test.tsx
    ├── useTeacherCaseSubmissionDetail.test.ts
    └── teacherCaseSubmissionDetailModel.test.ts
```

> **Prohibido** crear `frontend/src/components|pages|hooks|helpers|common|misc`. Mantener split `app/features/shared`.

### 4.2 Ruta

En `frontend/src/app/App.tsx`, **reemplazar** el placeholder de `/teacher/cases/:assignmentId/entregas/:membershipId` por:

```tsx
<TeacherCaseSubmissionDetailPage />
```

Con `lazy(() => import("@/features/teacher-case-submission-detail/TeacherCaseSubmissionDetailPage"))` siguiendo el patrón existente. Mantener guardas de auth idénticas a las del listado padre.

### 4.3 TanStack Query

```ts
queryKey: ["teacher", "case-submission-detail", assignmentId, membershipId]
staleTime: 30_000
refetchOnWindowFocus: true
gcTime: 5 * 60_000
```

- `enabled: Boolean(assignmentId && membershipId)`.
- Helper `getTeacherCaseSubmissionDetailErrorMessage(error, fallback)` espejo de `getTeacherCaseSubmissionsErrorMessage`. **Reusar el mismo cliente HTTP compartido** (`@/shared/api/...`) — no inventar otro fetch.
- En éxito: NO invalidar la query del listado padre (no hubo mutación). Si en el futuro se añade `prefetchQuery` desde el listado, dejar el `queryKey` listo para ello.

### 4.4 UX (descripción funcional, no pixel-perfect)

- **Header**: botón `Volver` (a `/teacher/cases/:assignmentId/entregas`), título `Entrega de {fullName}`, chips con `course_code`, `deadline`, `status` (mismo formateo que el listado), y `score` si `grade_summary.status === "graded"`.
- **Banner condicional** cuando `response_state.status === "not_started"`: copy "Este estudiante todavía no abrió el caso. Las respuestas aparecerán cuando lo entregue."
- **Banner condicional** cuando hay snapshot pero sus `is_answer_from_draft === true` (caso de inconsistencia): "Mostrando borrador del estudiante; no se encontró snapshot de entrega."
- **Navegador de módulos**: tabs `M1 … M5` (solo módulos presentes en `modules`). Persistir el módulo activo en `?modulo=M3` (URL param) para deep-linking.
- **Panel de preguntas**: para cada pregunta del módulo activo, layout de dos columnas en desktop:
  - Izquierda: enunciado + `Respuesta del estudiante` (si `null`, mostrar estado "Sin respuesta").
  - Derecha: `Solución esperada` (badge "Solo visible para docentes"; reuse de chip neutral).
  - En mobile: stack vertical, mismo orden.
- **Accesibilidad**: cada pregunta es una `<section aria-labelledby="...">`; navegación de módulos accesible por teclado (`role="tablist"`); `aria-live="polite"` para refresh; respetar foco al cambiar de módulo (`useEffect` que mueve foco al heading del módulo).
- **Estados visuales** (loading, error, empty, refreshing) deben replicar los patrones de `TeacherCaseSubmissionsPage` para consistencia.
- **Refresh manual** con el mismo botón `Actualizar` del listado padre.
- **Render seguro**: tratar `student_answer` y `expected_solution` como **texto plano** (no `dangerouslySetInnerHTML`). Preservar saltos de línea con `white-space: pre-wrap`.

### 4.5 Tipado + runtime guard

- Tipos TS en `teacherCaseSubmissionDetailApi.ts` que **coincidan exactamente** con `TeacherCaseSubmissionDetailResponse` del backend (mismos discriminantes literales). No usar `any`.
- Validar `payload_version === 1` en el cliente; si difiere, mostrar banner "Tu versión de la app está desactualizada. Recarga para continuar." (no romper).

### 4.6 Estilos

- Reusar tokens y clases ya disponibles (`teacher-course-page`, `teacher-gradebook-*`). Extender CSS solo si es indispensable; nuevos estilos dedicados van en `teacherCaseSubmissionDetail.css` colocalizado.
- **Sin** animaciones nuevas ni librerías nuevas.

---

## 5. Tests

### 5.1 Backend (≥8 tests)

Crear `backend/tests/test_teacher_case_submission_detail.py`:

1. `test_returns_full_payload_for_submitted_response_with_snapshot`
2. `test_uses_draft_when_no_snapshot_exists_and_marks_is_draft`
3. `test_returns_not_started_payload_when_no_response`
4. `test_404_when_assignment_does_not_belong_to_teacher`
5. `test_404_when_membership_not_in_assignment_target_courses`
6. `test_status_reflects_case_grade_when_present` (graded path)
7. `test_response_payload_omits_case_grade_feedback_field` (regresión: feedback nunca se serializa)
8. `test_payload_includes_solucion_esperada_for_each_question` (frente al sanitizer de estudiante)
9. `test_payload_excludes_internal_canonical_fields` (input sintético con `prompt_trace`, `__token`, `authoring_job_id` → no presentes)
10. `test_modules_ordered_M1_to_M5_and_skips_missing_modules`
11. `test_truncation_warning_when_expected_solution_exceeds_size_cap` (opcional, si se implementa la guardia)

Adicional para sanitizer en `backend/tests/test_case_sanitization.py` (extender):

- `test_build_teacher_case_review_payload_keeps_solucion_esperada`
- `test_build_teacher_case_review_payload_drops_unknown_root_fields`

### 5.2 Frontend (≥10 tests)

`TeacherCaseSubmissionDetailPage.test.tsx`:

1. Loading state (mock query `pending`).
2. Error state with retry button calls `refetch`.
3. Renders header con `course_code`, deadline formateado y status chip.
4. Renders M1 by default y permite cambiar a M3 vía teclado.
5. URL param `?modulo=M2` selecciona M2 al montar.
6. Banner "no abrió el caso" cuando `response_state.status === "not_started"`.
7. Banner draft fallback cuando `is_answer_from_draft === true` y status es `submitted`.
8. Render de `student_answer` preserva saltos de línea y NO interpreta HTML (regresión XSS).
9. `grade_summary.score` no se renderiza si `status !== "graded"`.
10. `Volver` navega a `/teacher/cases/:assignmentId/entregas`.
11. `payload_version !== 1` muestra banner "desactualizado".

`useTeacherCaseSubmissionDetail.test.ts`:

12. `enabled` es `false` cuando faltan params.
13. `getTeacherCaseSubmissionDetailErrorMessage` mapea 404 `submission_not_found` a copy localizado.

`teacherCaseSubmissionDetailModel.test.ts`:

14. Helper de orden de módulos descarta módulos vacíos.

---

## 6. Reserva para la próxima iteración (Calificación)

Esta issue **no** implementa calificación, pero **sí** debe dejar el terreno preparado para que la próxima issue solo añada el formulario:

- **Backend:**
  - El `grade_summary` ya expone `status/score/max_score/graded_at` (sin feedback). La próxima issue añadirá `feedback` en un payload separado o extenderá `payload_version → 2`.
  - **Documentar** en docstring del endpoint que mutaciones (`POST/PUT /api/teacher/cases/.../grade`) se entregarán en la siguiente issue.
- **Frontend:**
  - `GradingPlaceholderPanel.tsx` debe renderizarse en el lugar exacto donde irá el formulario (footer sticky en desktop, sección al final en mobile).
  - Copy: "La calificación estará disponible en una próxima actualización." (sin botones falsos).
  - El `data-testid="teacher-case-submission-detail-grading-slot"` debe estar presente para que la próxima issue inserte el form sin renombrar.
  - **No** crear hooks de mutación, **no** crear formularios disabled, **no** stub de endpoints de calificación. Mantener la deuda en cero.

---

## 7. Out of scope (rechazar en revisión)

- Persistencia de calificación, feedback, rúbrica.
- Comparación automática estudiante-vs-esperada (LLM grading).
- Exportar entrega a PDF.
- Comentarios inline en respuestas.
- Notificaciones al estudiante.
- Cualquier modificación a `backend/src/case_generator/**`.
- SSE / websocket / Supabase Realtime para esta vista.
- Cambios al listado padre (`TeacherCaseSubmissionsPage`) que no sean estrictamente necesarios.
- Invalidaciones de query en el listado padre (no hay mutación).

---

## 8. Criterios de aceptación

1. Pulsar "Ver entrega y calificar" desde la lista carga la nueva página sin pantallazos en blanco ni errores de consola.
2. La página muestra metadatos del caso, del estudiante, módulos M1..M5 con preguntas, respuestas del estudiante y soluciones esperadas.
3. La respuesta del estudiante proviene del **snapshot inmutable** cuando existe; si no, del draft con disclaimer.
4. La solución esperada es visible para docente y **nunca** se filtra al endpoint de estudiante (test de regresión en `case_sanitization`).
5. El payload **no** contiene `feedback` de `case_grades`.
6. Auth chain respeta `verified_identity → profile → membership → password_rotation → role` y devuelve 404 ambiguo para enumeraciones cruzadas.
7. Cobertura: ≥8 tests backend nuevos + ≥10 tests frontend nuevos, todos verdes.
8. `uv run --directory backend pytest -q`, `uv run --directory backend mypy src`, `npm --prefix frontend run lint`, `npm --prefix frontend run test`, `npm --prefix frontend run build` pasan en limpio.
9. No se modifica `backend/src/case_generator/**`.
10. No se introducen carpetas frontend genéricas (`components/pages/hooks/...`).
11. No hay `any`, `# type: ignore` sin justificación, ni `dangerouslySetInnerHTML`.
12. La UI deja **listo** el slot `teacher-case-submission-detail-grading-slot` para la siguiente issue.

---

## 9. Validación local

```powershell
docker compose up -d adam-edu-postgres
supabase start

cd backend
uv sync --dev
uv run alembic upgrade head
uv run --directory . pytest -q tests/test_teacher_case_submission_detail.py
uv run --directory . pytest -q
uv run --directory . mypy src

cd ../frontend
npm install
npm run lint
npm run test -- teacher-case-submission-detail
npm run test
npm run build
```

Smoke manual:

1. Login docente con seed o cuenta de pruebas.
2. Crear curso, publicar caso, simular entrega de un estudiante (snapshot).
3. Ir al listado de entregas y pulsar "Ver entrega y calificar".
4. Verificar que aparecen módulos, respuestas y soluciones esperadas.
5. Pegar la URL en otra pestaña con un `membership_id` ajeno → 404 limpio.
6. Forzar `?modulo=M4` → carga directa al módulo 4.

---

## 10. Guardrails (recordatorio)

- `backend/src/case_generator/**` es intocable.
- Auth precedence: `verified_identity → profile_state → membership_state → password_rotation → role/context → handler`.
- `case_grades.feedback` **no** se expone en esta vista.
- Nada de SSE / Realtime / colas para esta ruta.
- `Supavisor :6543` por defecto en prod.
- Mantener split frontend `app / features / shared`.
- Imports absolutos por dominio. Nada de `sys.path` hacks.
- Si cambia setup, contratos o flujo: actualizar `README.md`, `CONTRIBUTING.md`, `AGENTS.md`, `CLAUDE.md` en el mismo PR.
- Branch: `feature/issue-XXX-teacher-case-submission-detail` (XXX = número que GitHub asigne).
- Squash merge.

---

## 11. Definición de hecho

- [ ] Endpoint `GET /api/teacher/cases/{assignment_id}/submissions/{membership_id}` operativo y autenticado.
- [ ] Sanitizador `build_teacher_case_review_payload` con tests dedicados.
- [ ] `payload_version: 1` documentado.
- [ ] Página `TeacherCaseSubmissionDetailPage` reemplaza el placeholder.
- [ ] Slot reservado para calificación con `data-testid` estable.
- [ ] Suite verde: backend pytest + mypy, frontend lint + test + build.
- [ ] PR con descripción, screenshots (desktop + mobile) y referencia a esta issue.
- [ ] Review aprobada con foco en sanitización, auth chain y ausencia de `feedback`.
