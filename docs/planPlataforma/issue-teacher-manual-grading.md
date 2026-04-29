# Calificación manual de entregas (con schema forward-compatible para IA)

## Contexto

Hoy `TeacherSubmissionPreview.tsx` (PR #217 / Issue #216) renderiza el caso resuelto del estudiante reusando `CasePreview` y deja un slot reservado en el header (`data-testid="teacher-case-submission-detail-grading-slot"` en `frontend/src/features/teacher-case-submission-detail/components/GradingPlaceholderPanel.tsx`).

El backend ya expone `GET /api/teacher/courses/{courseId}/cases/{assignmentId}/submissions/{membershipId}` con el contrato `TeacherCaseSubmissionDetailResponse` (ver `backend/src/shared/teacher_gradebook_schema.py`, `payload_version: Literal[1]`), que entrega:

- `case` + `case_view` (vista canónica M1..M5 + EDA cuando aplique)
- `student` (membership_id, nombre, email)
- `response_state` (status, snapshot_id, snapshot_hash, timestamps)
- `grade_summary` (status, score, max_score=5.00 default, graded_at)
- `modules[].questions[]` con `expected_solution` y `student_answer`

La tabla `case_grades` ya existe (`backend/src/shared/models.py`, líneas ~390-465) con:
- `status ∈ {in_progress, submitted, graded}` (CHECK constraint)
- `score Numeric(5,2)`, `max_score Numeric(5,2) DEFAULT 5.00`
- `graded_at`, `graded_by_membership_id`, `feedback Text`
- Constraint `ck_case_grades_state_consistency`: graded ⇔ score+graded_at presentes

**No existe persistencia por módulo ni por pregunta**, ni mecanismo de borrador, ni rúbrica.

Esta issue agrega calificación manual end-to-end: rúbrica discreta, pesos por módulo, feedback en tres niveles (pregunta / módulo / global), borrador con autosave, publicación explícita, e inmutabilidad post-publicación con auditoría. **El schema queda forward-compatible para que en una issue futura la IA pueda pre-calificar usando el mismo endpoint y las mismas tablas, sin migración disruptiva.**

## Objetivo

Permitir al docente calificar de forma rigurosa, rápida y consistente cada entrega de un caso, con persistencia robusta, auditoría completa y experiencia de autoría tipo "review/grade toggle" sobre la preview existente. La calificación publicada alimenta el gradebook del estudiante (issue separada — fuera de este alcance).

## Alcance (in-scope)

### Backend
1. **Migración Alembic** que:
   - Crea `case_grade_module_entries` (1 fila por (`case_grade_id`, `module_id ∈ {M1..M5}`)).
   - Crea `case_grade_question_entries` (1 fila por (`case_grade_id`, `question_id`)).
   - Agrega columnas a `case_grades`: `graded_by` enum, `ai_model_version`, `ai_suggested_at`, `human_reviewed_at`, `version int NOT NULL DEFAULT 1`.
   - Agrega columna `weight_per_module Numeric(4,3)` configurable a `assignments` (NULL = pesos iguales = 1/N).
   - Mantiene el CHECK constraint actual de `case_grades.status` (no agregar `'draft'`).
2. **Servicio `case_grade_service`** con operaciones idempotentes:
   - `get_grade_draft_or_published(assignment_id, membership_id) → GradePayload`
   - `save_grade_draft(payload) → GradePayload` (PUT full-body, autosave-friendly)
   - `publish_grade(payload) → GradePayload` (transición atómica draft→published, calcula score final, escribe `case_grades.status='graded'`, `case_grades.score`, `case_grades.graded_at`, `case_grades.feedback`, snapshot-bound)
3. **Endpoint** en `backend/src/shared/teacher_router.py`:
   - `GET /api/teacher/courses/{courseId}/cases/{assignmentId}/submissions/{membershipId}/grade` → 200 con borrador o publicado, 404 si no existe entrega submitted.
   - `PUT /api/teacher/courses/{courseId}/cases/{assignmentId}/submissions/{membershipId}/grade` → idempotente, full-body, valida `snapshot_hash` contra el `response_state` actual (rechaza con 409 si el estudiante reabrió y modificó después).
4. **Schemas Pydantic v2 StrictModel** en `backend/src/shared/teacher_grading_schema.py` con `payload_version: Literal[1]`.
5. **Sanitización** de feedback (whitelist actual) antes de persistir.
6. **Headers de respuesta**: `Cache-Control: private, max-age=0, must-revalidate`.
7. **Guard de tamaño**: payload rechazado >1.5 MB.

### Frontend
1. **Reemplazar** `GradingPlaceholderPanel.tsx` por un panel real `GradingPanel.tsx` que vive en el header.
2. **Toggle Review ↔ Grade** en el header de `TeacherSubmissionPreview.tsx`:
   - **Review** (default): vista actual de PR #217, solo lectura.
   - **Grade**: muestra chips de rúbrica debajo de cada `PreguntaCard`, textarea de feedback por pregunta (colapsable), feedback por módulo en el header de cada módulo, feedback global + score live en el sidebar, botones "Guardar borrador" y "Publicar calificación".
3. **Autosave** con debounce de 1.5 s sobre cualquier cambio (chip, texto, peso). Indicador visual "Guardando…" / "Guardado HH:MM".
4. **Estados visuales claros**:
   - Sin calificación: "Sin calificar"
   - Borrador: "Borrador (no publicado)" + chip amarillo
   - Publicado: "Calificado · X.X / 5.0" + chip verde + botón "Editar y republicar" (disponible, crea nuevo `version`)
5. **Publicación**: modal de confirmación que muestra score final, advierte "El estudiante verá esta calificación".
6. **Bloqueo**: si todas las preguntas no tienen chip asignado, deshabilitar "Publicar" con tooltip "Faltan N preguntas por calificar".

## Fuera de alcance (out-of-scope explícito)

- ❌ Endpoint `POST /grade/ai-suggest` y cualquier llamada a LLM.
- ❌ Botón "Pre-calificar con IA" (solo el flujo manual).
- ❌ Polling/Realtime para job de IA.
- ❌ Visualización del badge "✨ sugerido por IA" en chips.
- ❌ Vista de "historial de versiones" (la columna `version` se incrementa pero no se expone aún).
- ❌ Notificación al estudiante en publicación (issue separada de gradebook).
- ❌ Mobile/tablet (desktop-only MVP, ≥1280px).
- ❌ Exportar calificaciones a CSV.

## Decisiones de diseño (no negociables)

### Rúbrica discreta de 5 niveles

Enum único en backend y frontend (no usar números libres):

| Nivel | Score normalizado | Color UI |
|---|---|---|
| `excelente` | 1.00 | green |
| `bien` | 0.80 | blue |
| `aceptable` | 0.60 | yellow |
| `insuficiente` | 0.30 | orange |
| `no_responde` | 0.00 | gray |

`null` = sin calificar (estado válido en borrador, inválido en publicado).

### Score final

- Internamente todo se almacena como `score_normalized ∈ [0, 1]` (Float).
- **Score por módulo** = promedio simple de `score_normalized` de sus preguntas (preguntas sin chip cuentan como 0 al publicar; en borrador se omiten del cálculo live).
- **Score final del caso** = Σ (`score_modulo[i]` × `weight_modulo[i]`), donde Σ pesos = 1.0.
- **Pesos por defecto**: `1/N` para cada módulo presente. Configurables por assignment (columna `weight_per_module` JSON, NULL = iguales). Edición de pesos NO está en este MVP, pero el schema los soporta.
- **Display**: `score_final × 5.0` redondeado a 1 decimal. La columna `case_grades.score Numeric(5,2)` almacena el valor display (ya existe).

### Tres niveles de feedback

- `feedback_question` (opcional, por pregunta): texto libre ≤2000 chars sanitizado.
- `feedback_module` (opcional, por módulo): texto libre ≤2000 chars sanitizado.
- `feedback_global` (semi-requerido en publicación, ≥20 chars recomendado pero no bloqueante; si vacío se permite con warning): texto libre ≤4000 chars sanitizado. **Se persiste en la columna existente `case_grades.feedback`** (que pasa a ser serializada SOLO cuando `status='graded'` — el rule histórico "no serializar feedback" se levanta para publicado).

### Estados y autosave

- `case_grade_question_entries.state` y `case_grade_module_entries.state` ∈ `{draft, published}`. Autosave escribe `draft`. Publicar reemplaza atómicamente las filas a `published` y promueve a `case_grades`.
- `case_grades.status` permanece `submitted` mientras todo es draft. Al publicar pasa a `graded` (transición existente, respeta `ck_case_grades_state_consistency`).
- Re-publicación: se incrementa `case_grades.version`, se sobrescriben las filas `published` previas. No se mantiene historial completo en este MVP (solo `version`, `last_modified_at`, `published_at`).

### Snapshot binding

Toda calificación va atada a `response_state.snapshot_hash` del momento en que se inició la calificación. Si el estudiante reabre y modifica (caso edge — el flujo normal es submitted=inmutable), el `PUT /grade` devuelve `409 Conflict` con `{ error: "snapshot_changed", current_snapshot_hash }` y el frontend muestra modal "El estudiante modificó su entrega. Recargar para ver cambios."

### Forward-compatibilidad para IA (schema only)

Las siguientes columnas se agregan ahora con defaults sensatos para no migrar dos veces cuando se implemente IA:

```python
# case_grades
graded_by: Mapped[GradedBy] = mapped_column(
    String(16), nullable=False, server_default="human"
)  # Enum: 'human' | 'ai' | 'hybrid'
ai_model_version: Mapped[str | None]      # NULL en MVP
ai_suggested_at: Mapped[datetime | None]  # NULL en MVP
human_reviewed_at: Mapped[datetime | None]
version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

# case_grade_question_entries y case_grade_module_entries
source: Mapped[FeedbackSource] = mapped_column(
    String(24), nullable=False, server_default="human"
)  # Enum: 'human' | 'ai_suggested' | 'ai_edited_by_human'
ai_confidence: Mapped[float | None]       # 0..1, NULL en MVP
```

**Regla**: en este MVP el frontend NUNCA envía `graded_by != 'human'` ni `source != 'human'`. El backend valida que solo se acepten esos valores en este `payload_version=1`. Cuando se agregue IA en una issue futura, se bumpea a `payload_version=2` y se aceptan los demás valores.

## Contrato de API

### Request body (`PUT /grade`)

```json
{
  "payload_version": 1,
  "snapshot_hash": "sha256:abc123...",
  "intent": "save_draft" | "publish",
  "modules": [
    {
      "module_id": "M1",
      "weight": 0.20,
      "feedback_module": "Texto sanitizado o null",
      "questions": [
        {
          "question_id": "q-uuid",
          "rubric_level": "excelente" | "bien" | "aceptable" | "insuficiente" | "no_responde" | null,
          "feedback_question": "Texto sanitizado o null"
        }
      ]
    }
  ],
  "feedback_global": "Texto sanitizado o null"
}
```

### Response body (200, ambos endpoints)

```json
{
  "payload_version": 1,
  "snapshot_hash": "sha256:...",
  "publication_state": "draft" | "published",
  "version": 1,
  "score_normalized": 0.84,
  "score_display": 4.2,
  "max_score_display": 5.0,
  "modules": [ /* ... como request ... */ ],
  "feedback_global": "...",
  "graded_at": "2026-04-27T...",
  "published_at": "2026-04-27T..." | null,
  "last_modified_at": "2026-04-27T...",
  "graded_by": "human"
}
```

### Errores

- `400` payload_version inválido / valores fuera de enum / `graded_by != 'human'` en v1.
- `403` el docente no tiene membership de teacher en el curso del assignment.
- `404` no existe entrega `submitted` para (assignment_id, membership_id).
- `409` `snapshot_changed` (ver sección snapshot binding).
- `413` payload >1.5 MB.
- `422` validation error de Pydantic.

## Reglas duras (must-not-break)

1. **NO** tocar `backend/src/case_generator/**`.
2. **NO** romper el endpoint actual `GET …/submissions/{membershipId}` ni su `payload_version=1`.
3. **NO** modificar el componente `CasePreview` ni rutas de `case-preview/**`.
4. **NO** introducir SSE, WebSocket, ni progress bus para el flujo de grading (es síncrono).
5. **NO** auto-publicar bajo ninguna condición; siempre requiere acción explícita del docente.
6. **NO** persistir feedback sin pasar por sanitización whitelist.
7. **NO** permitir que el frontend envíe `graded_by`, `source`, `ai_*` distintos de los defaults humanos en `payload_version=1`.
8. **NO** registrar un solo CHECK constraint sin nombre explícito (`ck_…`).
9. **NO** usar `sys.path` hacks ni imports relativos profundos.
10. **NO** agregar tests live LLM ni dependencias de red.

## Validaciones obligatorias antes del PR

```powershell
uv run --directory backend pytest -q
uv run --directory backend mypy src
npm --prefix frontend run lint
npm --prefix frontend run test
npm --prefix frontend run build
```

Más:
- Migración Alembic: `uv run --directory backend alembic upgrade head` y `alembic downgrade -1` ambos limpios sobre Postgres local (`5434`).
- Test de migración (existente, marca `ddl_isolation`) debe seguir verde.

## Cobertura de tests requerida

### Backend (`backend/tests/test_teacher_manual_grading.py`)
- `test_get_grade_returns_404_when_no_submission`
- `test_get_grade_returns_empty_draft_initially`
- `test_save_draft_persists_per_question_and_per_module`
- `test_save_draft_is_idempotent_full_body`
- `test_save_draft_sanitizes_feedback_html`
- `test_save_draft_rejects_payload_over_1_5mb`
- `test_save_draft_rejects_invalid_rubric_level`
- `test_save_draft_rejects_graded_by_ai_in_v1`
- `test_publish_requires_all_questions_rated`
- `test_publish_computes_normalized_and_display_score`
- `test_publish_uses_equal_weights_when_assignment_weights_null`
- `test_publish_promotes_case_grades_to_graded_status`
- `test_publish_writes_feedback_global_to_case_grades_feedback`
- `test_publish_increments_version_on_republish`
- `test_snapshot_hash_mismatch_returns_409`
- `test_only_teacher_membership_can_grade` (403 para student/admin/otro curso)
- `test_score_consistency_check_constraint_holds`

### Frontend
- `TeacherSubmissionPreview.test.tsx`: review/grade toggle visible, chips renderizan en grade mode, autosave dispara PUT con debounce, score live actualiza, "Publicar" deshabilitado con preguntas faltantes, modal de confirmación, manejo de 409 con modal de recarga.
- `GradingPanel.test.tsx`: cada nivel de feedback respeta su límite, chips son accesibles por teclado (`role="radiogroup"`), estado "Borrador" vs "Publicado" visualmente diferenciado.
- `useGradeDraft.test.ts`: TanStack Query mutation con optimistic update, rollback en error, invalidate de query del detail al publicar.

## Definición de "Done"

- [ ] Migración Alembic up/down limpia.
- [ ] Backend pytest verde, mypy strict verde sin nuevos `# type: ignore`.
- [ ] Frontend lint + test + build verdes.
- [ ] Endpoint manual probado con `curl` o Thunder Client en stack local (Docker `5434` + `supabase start`).
- [ ] QA visual desktop (≥1280px) con browser skill: review→grade→chips→autosave→publish→re-edit, evidencia con screenshots.
- [ ] Cero regresiones en `test_issue205_teacher_course_gradebook.py` ni en `test_teacher_case_actions.py`.
- [ ] `AGENTS.md` y `CLAUDE.md` actualizados si se introducen patterns nuevos (esperado: añadir línea sobre `case_grade_*_entries` ownership en `shared/`).
- [ ] PR descriptiva con: diagrama de estados, screenshots before/after, lista de columnas nuevas, plan de rollback.

## Plan de rollback

1. La migración debe tener `downgrade()` que dropee tablas hijas y columnas nuevas en orden inverso.
2. El frontend cae a comportamiento previo (`GradingPlaceholderPanel`) si el endpoint devuelve 404 con `feature_disabled` flag (no requerido en MVP, pero el componente debe degradar elegante si el endpoint falla con 5xx).
3. Feature flag opcional `TEACHER_MANUAL_GRADING_ENABLED` env var (default true) para apagar el endpoint sin redeploy.

## Referencias en el código

- Tabla existente: [backend/src/shared/models.py](backend/src/shared/models.py) líneas ~390-465 (`CaseGrade`).
- Schema actual de detail: [backend/src/shared/teacher_gradebook_schema.py](backend/src/shared/teacher_gradebook_schema.py) líneas ~77-145.
- Router: [backend/src/shared/teacher_router.py](backend/src/shared/teacher_router.py).
- Frontend preview: [frontend/src/features/teacher-case-submission-detail/TeacherSubmissionPreview.tsx](frontend/src/features/teacher-case-submission-detail/TeacherSubmissionPreview.tsx).
- Slot reservado: [frontend/src/features/teacher-case-submission-detail/components/GradingPlaceholderPanel.tsx](frontend/src/features/teacher-case-submission-detail/components/GradingPlaceholderPanel.tsx).
- Hook actual: [frontend/src/features/teacher-case-submission-detail/useTeacherCaseSubmissionDetail.ts](frontend/src/features/teacher-case-submission-detail/useTeacherCaseSubmissionDetail.ts).

## Issue futura (no abrir hasta cerrar esta)

> **#TBD — Calificación asistida por IA**: implementa `POST /grade/ai-suggest`, integra LangGraph en `case_generator/`, agrega botón "Pre-calificar con IA", expone badges de `source` en la UI, bumpea `payload_version=2`. El schema ya está listo desde esta issue.
