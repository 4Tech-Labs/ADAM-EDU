# [Feature] Student case resolution view: respuestas, autosave y submit (epic execution-ready)

> **Reemplaza el cuerpo previo de #196.** El epic original quedaba a nivel de
> intención. Esta versión es ejecutable end-to-end por un agente sin
> ambigüedades, con contratos cerrados, esquema de DB cerrado, decisiones
> arquitectónicas tomadas y NOT-in-scope explícito. El follow-up de grading IA y
> chat socrático se trabaja en issues separadas referenciadas al final.

## Contexto

El estudiante ya tiene dashboard (#195) y onboarding (#39), pero los CTAs
"Resolver caso" / "Continuar" no llevan a ningún sitio porque no existe la
superficie de **resolución del caso**. Esta issue construye esa superficie con
paridad visual frente al preview del docente (`CasePreview.tsx`), persistencia
en DB para que respuestas autosaveadas y entregadas sean recuperables, y
preparación arquitectónica para que el grading LLM y el chatbot socrático
posteriores enchufen sin reescribir nada.

Diseño guía: la vista del estudiante debe verse **idéntica** al preview docente,
con dos diferencias estrictas:

1. El estudiante **no ve** las soluciones esperadas (`solucion_esperada`,
   `m5QuestionsSolutions`) ni el módulo M6 (`teachingNote`).
2. Los `<textarea>` de cada pregunta son **editables**, con autosave
   automático y submit final.

Todo lo demás (layout, sidebar de módulos, exhibits, charts, narrativa,
markdown, scroll-spy del rail derecho) es exactamente igual.

## Decisiones arquitectónicas tomadas (no re-discutir en el PR)

| Decisión | Elegido | Razón |
|---|---|---|
| Persistencia | Tabla nueva `student_case_responses` keyed en Membership + audit `student_case_response_submissions` | Alineada con identidad moderna (#23) y multi-curso (#180); no resucita las tablas legacy `student_assignments`/`module_attempts` (que siguen marcadas inactivas y usan `User.id`). |
| Reuse del componente | Extracción quirúrgica de `<CaseContentRenderer>` a `frontend/src/shared/case-viewer/` con slot `rightPanelSlot` reservado para futuro chat | Garantiza paridad teacher↔student por construcción y evita un god-component cuando llegue el chat socrático por módulo. |
| Submit | Único e irreversible. 409 si se reintenta. UI bloqueada después | El grading LLM futuro requiere snapshot inmutable; explicit > clever. |
| Concurrencia multi-pestaña | Optimistic locking con `version` (int) + 409 + modal de recarga | Evita pérdida silenciosa de trabajo del estudiante. |
| Notebook tasks (`task_type: "notebook_task"`) | Solo texto + disclaimer en este PR; upload `.ipynb` en follow-up | Sandboxing y eval de notebooks merece su propia issue. |
| Sanitización de soluciones | **Backend** (whitelist), no frontend | El filtrado solo en frontend es bypassable vía DevTools. |
| Realtime | No se usa Supabase Realtime aquí | Single-actor flow; TanStack Query invalidate basta. (Conforme a Supabase Infrastructure Guardrails de AGENTS.md.) |

## Diagrama de datos

```
┌─────────────────────────────┐         ┌─────────────────────────────────────┐
│  memberships                │         │  assignments                        │
│  - id (PK)                  │         │  - id (PK)                          │
│  - profile_id               │         │  - canonical_output (JSONB)         │
│  - university_id            │         │  - status, deadline, available_from │
└──────────┬──────────────────┘         └──────────────┬──────────────────────┘
           │                                           │
           └────────────┬──────────────────────────────┘
                        │
                ┌───────▼─────────────────────────────────┐
                │  student_case_responses    (NEW)        │
                │  - id (PK uuid)                         │
                │  - membership_id (FK NOT NULL)          │
                │  - assignment_id (FK NOT NULL)          │
                │  - answers (JSONB NOT NULL DEFAULT '{}')│
                │  - status: 'draft' | 'submitted'        │
                │  - version (int NOT NULL DEFAULT 0)     │
                │  - first_opened_at (timestamptz)        │
                │  - last_autosaved_at (timestamptz null) │
                │  - submitted_at (timestamptz null)      │
                │  - created_at, updated_at               │
                │  UNIQUE(membership_id, assignment_id)   │
                │  INDEX(assignment_id)                   │
                │  CHECK(status in ('draft','submitted')) │
                │  CHECK(version >= 0)                    │
                └─────────────┬───────────────────────────┘
                              │ 1:N (audit, append-only)
                              ▼
                ┌─────────────────────────────────────────┐
                │  student_case_response_submissions (NEW)│
                │  - id (PK uuid)                         │
                │  - response_id (FK)                     │
                │  - answers_snapshot (JSONB NOT NULL)    │
                │  - submitted_at (timestamptz NOT NULL)  │
                │  - canonical_output_hash (varchar 64)   │
                │  - created_at                           │
                │  INDEX(response_id)                     │
                └─────────────────────────────────────────┘
```

`canonical_output_hash` = `sha256(json.dumps(canonical_output_sanitized, sort_keys=True))`.
Permite detectar a futuro si el caso fue editado entre resolución y grading.

Estado mostrado en el dashboard del estudiante (derivado, no almacenado):

```
sin row                                        → "available"
row, status=draft, last_autosaved_at IS NULL   → "available"
row, status=draft, last_autosaved_at NOT NULL  → "in_progress"
row, status=submitted                          → "submitted"
deadline pasada y no submitted                 → "closed"
available_from futuro                          → "upcoming"
```

## State machine UX

```
                       ┌──────────────┐
   GET detail ────────▶│  loading     │
                       └──────┬───────┘
                              │ fetched + status=draft + deadline ok
                              ▼
                       ┌──────────────┐  edita  ┌──────────────┐
                       │  editable    │────────▶│  saving      │
                       └──────┬───────┘         └──────┬───────┘
                              │                        │ 200 → editable
                              │                        │ 409 → conflict modal → reload
                              │                        │ 5xx → backoff retry, banner "Sin conexión"
                              │ click "Enviar"
                              ▼
                       ┌──────────────┐
                       │  confirming  │  cancela → editable
                       └──────┬───────┘
                              │ confirma
                              ▼
                       ┌──────────────┐  200  ┌──────────────────────────┐
                       │  submitting  │──────▶│  submitted (read-only)   │
                       └──────┬───────┘       └──────────────────────────┘
                              │ 409 → "Ya entregado", reload
                              │ 403 → "Deadline vencido", reload
```

## Alcance — Backend

### Migración Alembic
Crear revisión nueva con:
- Tabla `student_case_responses` con columnas exactas del diagrama, incluyendo
  CHECKs y UNIQUE constraint.
- Tabla `student_case_response_submissions` con FK + ON DELETE CASCADE.
- `down_revision` apuntando al head actual; `downgrade()` borra ambas tablas.
- NO tocar tablas legacy `student_assignments`/`module_attempts`.
- Test de migración up/down (siguiendo el patrón de Issue 23).

### Modelos SQLAlchemy
En `backend/src/shared/models.py`:
- `StudentCaseResponse(Base)` con docstring que incluya un diagrama ASCII del
  state machine `draft → submitted` y los invariantes (UNIQUE, monotonic
  `version`).
- `StudentCaseResponseSubmission(Base)` append-only, sin método `update`.

### Sanitización (archivo nuevo)
`backend/src/shared/case_sanitization.py`:

```python
def sanitize_canonical_output_for_student(
    canonical_output: dict[str, Any],
) -> dict[str, Any]:
    """
    Strip teacher-only fields from a CanonicalCaseOutput before exposing it to a
    student. Implementation MUST use a whitelist of allowed paths, not a blacklist,
    so that any future addition to the contract is private-by-default.

    Removed:
      - content.caseQuestions[*].solucion_esperada
      - content.edaQuestions[*].solucion_esperada
      - content.m3Questions[*].solucion_esperada
      - content.m4Questions[*].solucion_esperada
      - content.m5Questions[*].solucion_esperada
      - content.m5QuestionsSolutions
      - content.teachingNote
    """
```

Acompañar con un docstring ASCII pipeline:

```
canonical_output ─▶ deepcopy ─▶ filter content.* by whitelist ─▶ for each
question array: project allowed fields ─▶ return
```

### Endpoints en `backend/src/shared/student_router.py`

```
GET    /api/student/cases/{assignment_id}
PUT    /api/student/cases/{assignment_id}/draft
POST   /api/student/cases/{assignment_id}/submit
```

Schemas Pydantic en el mismo archivo o `student_reads.py`:

```python
class StudentCaseDetailResponse(BaseModel):
    assignment: StudentCaseAssignmentMeta   # id, title, available_from, deadline,
                                            # course_codes, status (effective)
    canonical_output: dict[str, Any]        # SANITIZED — never includes solutions
    response: StudentCaseResponseState

class StudentCaseResponseState(BaseModel):
    status: Literal["draft", "submitted"]
    answers: dict[str, str]                 # {question_id: text}
    version: int
    last_autosaved_at: datetime | None
    submitted_at: datetime | None

class StudentCaseDraftRequest(BaseModel):
    answers: dict[str, str]
    version: int

class StudentCaseDraftResponse(BaseModel):
    version: int
    last_autosaved_at: datetime

class StudentCaseSubmitRequest(BaseModel):
    answers: dict[str, str]
    version: int

class StudentCaseSubmitResponse(BaseModel):
    status: Literal["submitted"]
    submitted_at: datetime
    version: int
```

`question_id` debe usar el `numero` (string) de cada pregunta tal como aparece
en el `canonical_output` (M1: `caseQuestions[].numero`, M2:
`edaQuestions[].numero`, etc.). Documentar formato `M{n}-Q{numero}` (ej.
`"M1-Q1"`) para evitar colisiones entre módulos.

Reglas de autorización (en orden, conforme a la Auth Error Precedence de
AGENTS.md):
1. `verified_identity` → `profile_state` → `membership_state` →
   `password_rotation` → `role/context` (ya cubierto por
   `require_student_context`).
2. Validar que el `assignment_id` está vinculado a uno de los cursos del
   estudiante vía `assignment_courses` (con fallback a `assignment.course_id`
   por compat #180).
3. `assignment.status == "published"` y `available_from <= now`. Si no, 404.
4. Para `PUT draft` y `POST submit`: si `deadline IS NOT NULL` y `now >
   deadline`, 403 con código `deadline_passed`.
5. Para `PUT draft`: si `response.status == "submitted"`, 403 con código
   `already_submitted`.
6. Optimistic locking: si `body.version != response.version`, 409 con código
   `version_conflict`.
7. Validación de payload: cada respuesta ≤ 10_000 chars, total JSON ≤ 200_000
   bytes serializado, → 422 con código `payload_too_large`.

Códigos de error como cuerpos `{"detail": {"code": "...", "message": "..."}}`,
consistentes con los routers actuales.

### Extender `student_reads.list_student_cases`

Hoy devuelve `status: "available" | "upcoming" | "closed"`. Extender a:
`"available" | "in_progress" | "submitted" | "upcoming" | "closed"`. Calcular
status efectivo con LEFT JOIN a `student_case_responses` por `(membership_id,
assignment_id)`. **No** romper consumidores actuales — el frontend del dashboard
debe manejar los nuevos valores en este mismo PR.

## Alcance — Frontend

### Refactor: extracción a `frontend/src/shared/case-viewer/`

Mover desde `frontend/src/features/case-preview/` los pedazos puramente de
renderizado de contenido. Estructura objetivo:

```
frontend/src/shared/case-viewer/
  CaseContentRenderer.tsx
  ModulesSidebar.tsx
  SectionRail.tsx
  PreguntaCard.tsx               // input controlado: value/onChange + readOnly
  SolucionEsperadaRenderer.tsx   // solo se renderiza si showExpectedSolutions=true
  modules/
    M1StoryReader.tsx
    M2Eda.tsx
    M3AuditSection.tsx
    M4Finance.tsx
    M5ExecutiveReport.tsx
    M6MasterSolution.tsx          // queda aquí pero solo se monta si está en visibleModules
    types.ts
  utils/
    markdownTable.ts
    sanitizeExhibit.ts
    renderMarkdownWithIds.ts
    stripDuplicatedM1ExhibitSections.ts
  index.ts
```

Contrato del renderer:

```ts
type CaseContentRendererProps = {
  result: CanonicalCaseOutput;       // si readOnly=true viene del payload backend
  visibleModules: ModuleId[];        // teacher: incluye M6; student: nunca M6
  activeModule: ModuleId;
  onActiveModuleChange: (id: ModuleId) => void;
  answers: Record<string, string>;          // por questionId formato "M{n}-Q{numero}"
  onAnswersChange: (next: Record<string, string>) => void;
  readOnly: boolean;                        // true para teacher y para student post-submit
  showExpectedSolutions: boolean;           // false siempre para student
  rightPanelSlot?: ReactNode;               // default: <SectionRail/>; futuro: <ChatPanel/>
  headerSlot?: ReactNode;                   // diferenciador: PublishBar vs SubmitBar
};
```

`CasePreview.tsx` (teacher) queda como wrapper delgado:

```tsx
<CaseContentRenderer
  result={result}
  visibleModules={teacherVisibleModules(result)}
  activeModule={...}
  onActiveModuleChange={...}
  answers={{}}                              // teacher no edita
  onAnswersChange={() => {}}                // no-op
  readOnly={true}
  showExpectedSolutions={true}
  headerSlot={<TeacherPublishBar ... />}
/>
```

**Regla del refactor:** el comportamiento del lado teacher debe ser
**bit-for-bit idéntico** después de mover el código. Asegurar con:
- Snapshot tests en el archivo `CasePreview.test.tsx` actual (ampliar fixtures
  si hace falta).
- QA visual manual del docente antes de merge.

### Páginas y rutas nuevas

`frontend/src/features/student-runtime/`:

```
StudentCaseResolutionPage.tsx
StudentCaseResolutionPage.test.tsx
useStudentCaseResolution.ts
useStudentCaseResolution.test.ts
StudentSubmitBar.tsx
StudentAutosaveIndicator.tsx
StudentDeadlineCountdown.tsx
StudentVersionConflictModal.tsx
index.ts
```

Ruta nueva en `frontend/src/app/App.tsx`:

```
/student/cases/:assignmentId/resolve  →  StudentCaseResolutionPage  (lazy)
```

`isStudentShellRoute` debe incluir `/student/cases/`.

### Hook `useStudentCaseResolution`

Diagrama ASCII a embeber en el archivo:

```
input (textarea) ─▶ setLocalAnswers ─▶ debounce 1500ms ─▶
       PUT /draft {answers, version}
                ├─ 200 ─▶ version=server.version, last_autosaved_at=now
                ├─ 409 ─▶ open VersionConflictModal → reload
                ├─ 403(deadline) ─▶ lock UI + banner
                └─ 5xx ─▶ retry exponential (max 3) + offline banner
```

Implementación:
- TanStack Query: `useQuery` para detail (queryKey
  `queryKeys.student.caseDetail(assignmentId)`).
- `useMutation` para draft, **debounce a nivel de hook** (no a nivel de
  mutationFn) usando un timer manejado en el hook; cancela mutaciones previas
  pendientes.
- `useMutation` para submit, con `onSuccess` que invalida
  `queryKeys.student.caseDetail`, `queryKeys.student.cases`,
  `queryKeys.student.courses`.
- LocalStorage backup `student-draft:{assignmentId}` con `{answers, version,
  ts}`. Al montar la página: si server tiene `version` mayor que local, server
  gana; si igual y local es más fresco, dispara autosave inmediato con local.
- Cleanup en `unmount`: flush pendiente de autosave.

### UI estados

- **Header sticky**: título del caso + countdown a deadline + indicador
  autosave (`Guardado hace 3s` / `Guardando…` / `Sin conexión, reintentando…` /
  `Entregado el 24/04 14:32`).
- **Submit bar sticky bottom** (solo en estado `editable`): botón "Enviar
  respuestas" → modal de confirmación con texto explícito "Esto es definitivo,
  no podrás editar".
- **Estado `submitted`**: banner verde superior "Entregado · esperando
  retroalimentación", textareas read-only, botón submit oculto.
- **Estado `closed` (deadline pasado sin submit)**: banner ámbar "Plazo
  cerrado", textareas read-only, banner explicativo, botón submit oculto.
- **Modal de conflicto** (`409 version_conflict`): "Tu trabajo fue editado en
  otra pestaña o dispositivo. Recarga para ver la última versión." Botón
  "Recargar" → invalida query y reabre.

### API client + queryKeys

`frontend/src/shared/api.ts`:

```ts
api.student.getCaseDetail(assignmentId: string)
api.student.saveDraft(assignmentId: string, body: {answers, version})
api.student.submitCase(assignmentId: string, body: {answers, version})
```

`frontend/src/shared/queryKeys.ts`:

```ts
student: {
  ...existing,
  caseDetail: (assignmentId: string) => ["student", "caseDetail", assignmentId] as const,
}
```

### Dashboard wiring

- Extender enum status renderizado en
  `frontend/src/features/student-dashboard/` para soportar `in_progress` y
  `submitted` (label, color, CTA).
- CTA por estado:
  - `available` → "Resolver caso" → `/student/cases/:id/resolve`
  - `in_progress` → "Continuar" → mismo destino
  - `submitted` → "Ver entrega" → mismo destino (UI read-only)
  - `closed` → "Ver caso" deshabilitado o navega read-only
  - `upcoming` → CTA deshabilitado con tooltip de fecha

## Tests

### Backend (`backend/tests/test_issue196_student_case_resolution.py`)

- **GET detail**
  - 200 happy path con membership válida y assignment publicada visible.
  - **Sanitization**: assert que el JSON serializado del response NO contiene
    los strings literales `"solucion_esperada"`, `"m5QuestionsSolutions"`,
    `"teachingNote"` (string-search defensivo, además de assertions de keys).
  - 403 si membership pertenece a otra universidad.
  - 403/404 si assignment no published o `available_from` futuro.
  - Crea row `student_case_responses` con status=draft si no existe (con
    `first_opened_at` poblado).
- **PUT draft**
  - 200 happy path: incrementa `version` en 1, actualiza `last_autosaved_at`,
    persiste `answers`.
  - 409 si version stale (concurrencia simulada).
  - 403 si status=submitted.
  - 403 si `now > deadline`.
  - 422 si una respuesta excede 10_000 chars.
  - 422 si JSON serializado total excede 200_000 bytes.
- **POST submit**
  - 200 happy path: cambia status a submitted, popula submitted_at, crea row en
    `student_case_response_submissions` con `canonical_output_hash`.
  - 409 si ya submitted.
  - 409 si version stale.
  - 403 si `now > deadline`.
  - Después de submit, GET detail devuelve status=submitted y answers
    inmutables.
- **Cross-tenant isolation**
  - Membership de Universidad A no puede leer ni escribir respuesta vinculada a
    Universidad B (mismo assignment cross-asignado por error de configuración →
    403).
- **Sanitization unit test** (archivo separado o mismo):
  - Función `sanitize_canonical_output_for_student` con fixture full → assert
    keys filtradas; whitelist behavior con campo desconocido futuro
    (campo extra en input → no aparece en output).
- **Migración up/down**: crea y borra tablas correctamente.
- **Dashboard status**:
  - Sin row → status `"available"`.
  - Row con `last_autosaved_at` poblado → `"in_progress"`.
  - Row submitted → `"submitted"`.

### Frontend (vitest)

- `CaseContentRenderer.test.tsx`:
  - Snapshot regression para teacher view (compara con baseline pre-extracción).
  - Render student (`readOnly=false`, `showExpectedSolutions=false`,
    `visibleModules` sin M6) NO contiene texto de soluciones esperadas ni del
    M6 teaching note.
  - `readOnly=true` deshabilita textareas.
  - `rightPanelSlot` custom se renderiza en lugar del rail por defecto.
- `StudentCaseResolutionPage.test.tsx`:
  - Render inicial con respuestas existentes.
  - Edita textarea → `useStudentDraftMutation` se llama con debounce
    (verificar timing con fake timers).
  - Click submit → modal de confirmación → submit dispara mutation → UI pasa a
    read-only.
  - 409 en autosave abre `StudentVersionConflictModal`.
  - 403 deadline pasado → banner "Plazo cerrado" + UI read-only.
- `useStudentCaseResolution.test.ts`:
  - Debounce timing.
  - Retry con backoff en 5xx.
  - LocalStorage backup escrito y leído.
  - Reconciliación: server más nuevo gana.
- Bundle isolation: confirmar que `frontend/scripts/assert-bundle-isolation.mjs`
  sigue pasando tras la extracción (Plotly issue #130).

### E2E (si existen)

Happy path: dashboard → "Resolver" → escribir → recargar página → respuestas
persisten → submit → confirmación → dashboard muestra "Entregado".

## Failure modes (con cobertura explícita)

| # | Codepath | Falla realista | Cubierto por |
|---|---|---|---|
| 1 | Sanitize backend | Nuevo campo de solución agregado al contrato fuga al estudiante | Test whitelist + assert string-search en JSON |
| 2 | GET detail | Asignación a curso al que el estudiante no pertenece | 403 + test cross-tenant |
| 3 | PUT draft | Deadline expira mientras el estudiante escribe | Backend re-check at write-time → 403 + UI lock |
| 4 | PUT draft | Pérdida de red intermitente | Retry exponencial (max 3) + indicador "Sin conexión" + localStorage backup |
| 5 | PUT draft | Race entre dos pestañas | Optimistic locking con `version` → 409 + modal |
| 6 | POST submit | Doble click rápido | Botón disabled mientras submitting + check de `status=submitted` en backend → 409 |
| 7 | POST submit | Backend acepta pero respuesta se pierde | Refetch detail tras error → estado server canonical |
| 8 | Sanitize bypass via DevTools | Estudiante intenta inspeccionar payload buscando soluciones | **Cubierto en backend**, no se confía en frontend |
| 9 | JSONB bloat | Estudiante pega texto enorme | Validación max 10k chars/respuesta, max 200k JSON total → 422 |
| 10 | Refactor frontend | Regresión visual en teacher preview | Snapshot tests + QA visual antes de merge |

## Criterios de aceptación

- [ ] Migración Alembic crea las dos tablas nuevas y `pytest -q` pasa con un
      test up/down dedicado.
- [ ] Endpoint `GET /api/student/cases/{id}` devuelve `canonical_output`
      sanitizado; test verifica que NO aparecen strings de soluciones ni M6.
- [ ] Endpoints `PUT /draft` y `POST /submit` cubren todas las reglas de
      autorización y los códigos de error definidos.
- [ ] Optimistic locking funciona: dos PUT con la misma `version` resultan en
      el segundo recibiendo 409.
- [ ] Submit es irreversible: segundo POST devuelve 409.
- [ ] `student_reads.list_student_cases` devuelve los nuevos status
      `in_progress` y `submitted` correctamente derivados.
- [ ] `<CaseContentRenderer>` extraído a `frontend/src/shared/case-viewer/`.
      `CasePreview.tsx` (teacher) sigue funcionando idéntico (snapshot tests
      verdes).
- [ ] Ruta `/student/cases/:assignmentId/resolve` montada y lazy-loaded.
- [ ] Estudiante puede: abrir caso → escribir → recargar → respuestas
      persisten → submit → estado dashboard cambia a "Entregado".
- [ ] Modal de conflicto se muestra ante 409 y modal de deadline ante 403.
- [ ] Indicador de autosave visible y honesto sobre el estado real.
- [ ] Suite completa pasa:
  - `uv run --directory backend pytest -q`
  - `uv run --directory backend mypy src`
  - `npm --prefix frontend run lint`
  - `npm --prefix frontend run test`
  - `npm --prefix frontend run build`
- [ ] Manual en DevTools: `GET /api/student/cases/{id}` no contiene
      `solucion_esperada`, `m5QuestionsSolutions`, `teachingNote`.

## NOT in scope (follow-up issues)

- Grading IA / feedback LLM sobre las respuestas del estudiante
  (consume `student_case_response_submissions.answers_snapshot` +
  `canonical_output_hash`).
- Chat socrático por módulo (slot `rightPanelSlot` ya reservado en
  `CaseContentRenderer`).
- Upload de notebooks `.ipynb` para preguntas con
  `task_type: "notebook_task"` (este PR las trata como texto con disclaimer).
- Vista del docente sobre las respuestas entregadas por sus estudiantes.
- Re-submit / unlock por parte del docente.
- Notificaciones (email / push) al submit o al aproximarse la deadline.
- Sunset definitivo de tablas legacy `student_assignments`/`module_attempts`
  (se decide cuando llegue grading).
- Realtime updates por Supabase Realtime (single-actor; no se justifica aquí).
- Versionado de drafts más allá del snapshot inmutable al submit.
- Telemetría tiempo-en-tarea por módulo (TODO en TODOS.md).

## Phasing del PR sugerido

1. **Backend**: migración + modelos + sanitization + 3 endpoints + tests.
2. **Frontend refactor zero-behavior-change**: extracción a `shared/case-viewer/`,
   `CasePreview.tsx` queda como wrapper teacher delgado, snapshot regression
   pasa.
3. **Frontend nuevo**: `StudentCaseResolutionPage` + hook + ruta + estados UX.
4. **Dashboard wiring**: extender enum + CTAs + invalidaciones post-submit.
5. **Docs**: AGENTS.md / CLAUDE.md mencionan `shared/case-viewer/` en
   Architecture Boundaries y `docs/runbooks/local-dev-auth.md` menciona ruta
   nueva si aplica.

Cada paso debe poder mergearse con tests pasando antes de pasar al siguiente.

## Referencias

- `frontend/src/features/case-preview/CasePreview.tsx` (referencia visual y
  funcional del docente)
- `frontend/src/features/case-preview/modules/types.ts`
- `backend/src/shared/student_router.py`
- `backend/src/shared/student_context.py`
- `backend/src/shared/student_reads.py`
- `backend/src/shared/models.py` (sección `StudentAssignment`/`ModuleAttempt` —
  documentadas como inactivas, NO tocar en este PR)
- `backend/alembic/versions/` (patrón de migración existente)
- `frontend/src/shared/api.ts`, `frontend/src/shared/queryKeys.ts`
- `AGENTS.md` (Auth Error Precedence, Supabase Infrastructure Guardrails,
  Architecture Boundaries)
- `CLAUDE.md` (mismas secciones)
- Issues relacionadas: `#23`, `#39`, `#180`, `#195`
