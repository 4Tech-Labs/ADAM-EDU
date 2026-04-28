# Teacher · Rediseño de la vista de entrega usando el shell de `CasePreview` (sin mutarlo)

> **Iteración previa cerrada:** Issue #213 / PR #215 entregaron una primera versión funcional de la vista de detalle de la entrega en `/teacher/cases/:assignmentId/entregas/:membershipId`, con backend (`build_teacher_case_review_payload`, `get_teacher_case_submission_detail`, `GET /api/teacher/cases/{assignmentId}/submissions/{membershipId}`), schemas (`TeacherCaseSubmissionDetail*`, `payload_version: Literal[1]`), guard de tamaño (1.5 MB), `Cache-Control: private, max-age=0, must-revalidate`, fallback snapshot↔draft con `is_answer_from_draft`, y un layout pregunta-por-pregunta con dos columnas (Solución esperada | Respuesta del estudiante) + sidebar de módulos paralelo.
>
> **Problema UX detectado al revisar la pantalla en producción:** la vista actual rompe el modelo mental que el docente ya tiene del **preview del caso**. Inventa una segunda navegación de módulos, repite el badge "Borrador vigente" en tres lugares, ocupa el primer scroll completo con 4 KPI cards, y separa visualmente la pregunta de su contexto pedagógico (exhibits, datos EDA, narrativa M1→M5).
>
> **Esta issue:** rediseñar la página del detalle de entrega para que **reuse el shell visual de `frontend/src/features/case-preview/CasePreview.tsx`** (sidebar oscuro 280px + módulos M1..M5 + `CaseContentRenderer` con respuestas y solución esperada inline), añadiendo **solo** lo que el contexto profesor↔entrega exige (identidad del estudiante, estado de la entrega, snapshot↔draft, slot de calificación reservado).
>
> **Fuera de alcance (próxima issue):** captura de calificación, edición de feedback, persistencia de notas, panel de rúbrica. Esta issue **debe dejar reservado** el espacio visual y los contratos de datos para que la próxima iteración solo añada el formulario de calificación, sin rediseñar la página.

---

## 0. Hard rules (cualquier violación = bloqueo)

1. **No mutar `frontend/src/features/case-preview/CasePreview.tsx`.** Cero líneas modificadas en ese archivo. Verificable con `git diff main -- frontend/src/features/case-preview/CasePreview.tsx`.
2. **No mutar `frontend/src/shared/case-viewer/**`** salvo cambios estrictamente aditivos y retro-compatibles (props nuevos opcionales con default seguro). Cualquier cambio aditivo debe llevar test propio. Si dudas, **no toques** y crea un wrapper local.
3. **No tocar `backend/src/case_generator/**`.**
4. **No tocar la página padre** `frontend/src/features/teacher-case-submissions/**` (la lista). El botón "Ver entrega y calificar" sigue navegando a la misma ruta.
5. **No tocar el endpoint backend** `GET /api/teacher/cases/{assignment_id}/submissions/{membership_id}` ni los schemas `TeacherCaseSubmissionDetail*` salvo cambios aditivos retro-compatibles necesarios para soportar el render reusado (ver §3). Si se añade un campo, debe ser opcional, llevar default seguro y bumpear `payload_version` solo si se rompe contrato.
6. **No exponer `case_grades.feedback`.** La whitelist de `build_teacher_case_review_payload` no se relaja.
7. **No añadir dependencias** (frontend ni backend).
8. **No SSE / WebSockets / Realtime / queues** nuevas.
9. **No `dangerouslySetInnerHTML`** en código nuevo. El render de markdown del caso ya está canalizado por los componentes compartidos de `case-viewer`.
10. **No `: any`, `as any`, `// @ts-ignore`, `// @ts-expect-error`, `# type: ignore`** sin justificación inline.
11. **Reservar el slot de calificación** con `data-testid` estable (ver §4). Cero lógica de calificación.
12. **Mantener el contrato actual** del payload del backend: las respuestas del estudiante se siguen entregando con la misma forma. El frontend las adapta a `Record<string, string>` para `CaseContentRenderer`.

---

## 1. Inventario de reuso (OBLIGATORIO antes de empezar)

| Activo existente | Ruta | Uso esperado |
| --- | --- | --- |
| `CasePreview` | `frontend/src/features/case-preview/CasePreview.tsx` | **Referencia visual y estructural.** Replicar shell (sidebar 280px `bg-[#0f172a]`, header h-16, `CaseContentRenderer` con `readOnly={true}` + `showExpectedSolutions={true}`). **No importar como componente; copiar el patrón a un wrapper propio del feature.** |
| `CASE_VIEWER_STYLES` | `frontend/src/shared/case-viewer/index.ts` | Reusar `<style>{CASE_VIEWER_STYLES}</style>` igual que `CasePreview`. |
| `CaseContentRenderer` | `frontend/src/shared/case-viewer/CaseContentRenderer.tsx` | Render real de módulos + preguntas + soluciones esperadas. Ya acepta `answers: Record<string, string>`, `readOnly`, `showExpectedSolutions`. **Reusar tal cual.** |
| `ModulesSidebar` | `frontend/src/shared/case-viewer/ModulesSidebar.tsx` | Sidebar de módulos M1..M5 idéntico al preview. |
| `getModuleConfig` | `frontend/src/shared/case-viewer/caseViewerConfig.ts` | Derivar módulos visibles según `studentProfile` y `caseType`. |
| `PORTAL_SHELL_HEIGHT_VH_CLASSNAME` | `frontend/src/shared/ui/layout` | Altura de viewport del shell. |
| `PreguntaCard` | `frontend/src/shared/case-viewer/PreguntaCard.tsx` | Renderiza la pregunta + textarea (en modo `readOnly` muestra el texto). **No tocar.** |
| `useTeacherCaseSubmissionDetail` (hook) | `frontend/src/features/teacher-case-submission-detail/useTeacherCaseSubmissionDetail.ts` | Hook TanStack ya existente del PR #215. Reusar sin cambios; solo se cambia el render. |
| `getTeacherCaseSubmissionDetailErrorMessage` | mismo feature | Reusar idéntico. |
| Backend payload (`TeacherCaseSubmissionDetail*`) | `backend/src/shared/teacher_gradebook_schema.py` | Reusar. Ver §3 si se necesita un campo aditivo opcional para mapear preguntas → `questionId` consumible por `CaseContentRenderer`. |
| `CanonicalCaseOutput`, `ModuleId` | `frontend/src/shared/adam-types` | Tipos del caso. **`CaseContentRenderer` requiere un `CanonicalCaseOutput`.** Hay que reconstruirlo desde el payload sanitizado del docente (ver §3.2). |

> **Regla DRY:** si una utilidad nueva supera 25 LOC y solo se usa una vez, mantenla local en el feature; si se usa ≥2 veces o pertenece al dominio compartido del case-viewer, propón el cambio aditivo correspondiente con su test. **No cambies firmas existentes.**

---

## 2. Objetivo

Cuando el docente pulsa "Ver entrega y calificar" sobre una fila de `/teacher/cases/:assignmentId/entregas`, debe llegar a una pantalla **visualmente equivalente al preview del caso que ya conoce**, con tres diferencias mínimas:

1. **Identidad del estudiante** y **estado de la entrega** visibles en el header (no en 4 KPI cards).
2. **Cada pregunta muestra la respuesta del estudiante inline**, justo donde el preview muestra el textarea editable, pero en modo solo-lectura (`readOnly={true}`, `showExpectedSolutions={true}`).
3. **Slot de calificación reservado** dentro del shell (sidebar inferior o header derecho), con `data-testid` estable, sin lógica.

El docente nunca debe sentir que está en una pantalla distinta del preview. Solo siente que "ahora ve la respuesta del estudiante donde antes había un cuadro de texto vacío".

---

## 3. Diseño técnico

### 3.1 Frontend — nuevo componente `TeacherSubmissionPreview`

Ubicación: `frontend/src/features/teacher-case-submission-detail/TeacherSubmissionPreview.tsx`.

- **No importar** `CasePreview`. **Copiar el patrón estructural** (sidebar 280px + header h-16 + `<CaseContentRenderer ... readOnly showExpectedSolutions />`) a un wrapper propio.
- Recibe como props el payload del hook `useTeacherCaseSubmissionDetail` (ya tipado por el schema del backend).
- Construye internamente:
  - `caseData: CanonicalCaseOutput` desde `payload.case` (ver §3.2 sobre adaptación).
  - `answers: Record<string, string>` mapeando `payload.questions[].studentAnswer.text` → keyed por `questionId`.
  - `visibleModuleIds` con `getModuleConfig(caseData.studentProfile ?? "business", caseData.caseType)`.
- Renderiza `<CaseContentRenderer ... readOnly={true} showExpectedSolutions={true} answers={answers} onAnswersChange={noop} />`.
- **Bloquea `body.overflow`** igual que `CasePreview` (mismo `useEffect`).

#### Diferencias mínimas con `CasePreview`:

- **Sidebar superior (donde `CasePreview` muestra "Volver y rehacer" / logo):** muestra botón **"← Volver al listado"** que navega a `/teacher/cases/:assignmentId/entregas`.
- **Sidebar bloque "Caso activo":** se sustituye por **dos líneas**:
  - L1 (uppercase tracking): `ENTREGA DE`
  - L2 (texto blanco semibold): nombre completo del estudiante.
  - Debajo, sub-línea en `text-slate-500`: `<courseName> · <caseTitle>`.
- **Sidebar bloque inferior (donde `CasePreview` muestra "Harvard Only"):** se sustituye por **bloque de estado de entrega**:
  - Badge de status: `EN PROGRESO` / `ENVIADO` / `CALIFICADO` (mapeado desde `payload.submission.status`).
  - Línea: `Respondidas: X/Y` (calculado en cliente desde `answers`).
  - Línea: `Snapshot: <enviado | borrador vigente>` derivada de `is_answer_from_draft`.
  - Si calificado: `Calificación: <score>/<max_score>` (sin feedback).
- **Header h-16 (donde `CasePreview` muestra acciones de envío):** muestra:
  - Izquierda: título del caso (igual que preview).
  - Derecha: botón `Actualizar entrega` (refetch del query) + **slot de calificación reservado** (ver §4).
  - Cero botones de envío, descarga PDF/HTML, ni continuación de EDA.
- **Cuerpo:** `<CaseContentRenderer ... />` con `readOnly={true}` y `showExpectedSolutions={true}`. Sin overrides visuales.

### 3.2 Adaptación de payload → `CanonicalCaseOutput`

`CaseContentRenderer` requiere un `CanonicalCaseOutput`. El backend ya devuelve la versión sanitizada del caso vía `build_teacher_case_review_payload`. Hay dos caminos aceptables; elegir el más conservador con el contrato:

**Opción A (preferida si el payload actual ya contiene el shape completo del caso sanitizado):** mapear directamente `payload.case` → `CanonicalCaseOutput`. El frontend define un adapter local `toCanonicalCaseOutput(payload): CanonicalCaseOutput` con tests unitarios.

**Opción B (si el payload del PR #215 quedó plano por preguntas y no tiene los exhibits/contexto):** ampliar el backend de forma **aditiva y opcional** para incluir `case_view: CanonicalCaseOutputForTeacher` en el response (whitelist estricta, **sin `feedback`**, sin campos del case_generator interno). En ese caso:
- El backend reusa `build_teacher_case_review_payload` y añade el bloque `case_view` documentado en el schema.
- Se bumpea `payload_version` de `Literal[1]` → `Literal[2]` solo si se rompe el shape; si es aditivo opcional, se mantiene `1` y se documenta.
- Se añaden tests backend que verifican: (a) `case_view` no contiene `feedback`, (b) no contiene llaves arbitrarias del JSONB, (c) los exhibits/datasets/notebook van por la misma whitelist que ya usa el preview de docente del case-generation flow (referencia, no import desde `case_generator`).

> El implementador decide entre A y B tras leer el PR #215 y el schema actual. **Documentar la decisión en la descripción del PR** con cita de archivo:línea.

### 3.3 Frontend — página

`frontend/src/features/teacher-case-submission-detail/TeacherCaseSubmissionDetailPage.tsx` deja de renderizar el layout antiguo y pasa a renderizar `<TeacherSubmissionPreview payload={...} />`. Mantiene exactamente el mismo hook, mismo manejo de loading/error, mismo mapping de errores. **No se cambia la ruta** ni el `App.tsx`.

### 3.4 Limpieza

Los componentes del layout antiguo del PR #215 (header con 4 KPI cards, sidebar paralelo "Módulos del caso", cards pregunta-por-pregunta a dos columnas) se **borran** del feature porque quedan reemplazados. El `GradingPlaceholderPanel` se conserva pero se reubica al nuevo slot del header/sidebar (ver §4).

---

## 4. Slot de calificación reservado

- **Componente:** `GradingPlaceholderSlot` (puede reusar el `GradingPlaceholderPanel` ya existente del PR #215, renombrado o envuelto).
- **Ubicación:** dentro del header h-16, a la derecha del botón "Actualizar entrega". En viewport pequeño, colapsa al final del sidebar.
- **`data-testid` estable:** `teacher-case-submission-detail-grading-slot`.
- **Contenido placeholder:** un botón deshabilitado `Calificar entrega` con tooltip "Próximamente". Sin lógica.
- **Por pregunta (opcional, no requerido):** si se quiere preparar también el slot por pregunta, exponer `data-testid="teacher-case-submission-detail-grading-slot-{questionId}"` dentro de cada `PreguntaCard` mediante un nuevo prop opcional `gradingSlot?: ReactNode` en `PreguntaCard` (cambio aditivo, default `null`, con test). **Solo si no se rompe ningún snapshot existente.**

---

## 5. Tests

### Frontend (mínimo 10 tests nuevos en `frontend/src/features/teacher-case-submission-detail/__tests__/`)

1. Render: el shell tiene sidebar 280px `bg-[#0f172a]`, header h-16, `CaseContentRenderer` con `readOnly` y `showExpectedSolutions`.
2. Render: el botón "← Volver al listado" navega a `/teacher/cases/:assignmentId/entregas`.
3. Render: el bloque del sidebar muestra "ENTREGA DE" + nombre del estudiante.
4. Render: bloque inferior del sidebar muestra el badge de status correcto para `submitted`, `in_progress`, `graded`, `not_started`.
5. Render: cuando `is_answer_from_draft=true`, el sidebar muestra `Snapshot: borrador vigente`; cuando `false`, muestra `Snapshot: enviado`.
6. Render: cuando `submission.status="graded"`, el sidebar muestra `Calificación: X/Y` y **NUNCA** renderiza la palabra `feedback`.
7. Render: el botón "Actualizar entrega" dispara el `refetch` del query.
8. Render: el slot `data-testid="teacher-case-submission-detail-grading-slot"` existe en el DOM.
9. Render: `CaseContentRenderer` recibe `answers` con las respuestas del estudiante mapeadas por `questionId`, en el orden M1→M5.
10. Render: `CaseContentRenderer` se invoca con `readOnly={true}` y `showExpectedSolutions={true}` (assert sobre props o sobre DOM resultante).
11. Snapshot test del adapter `toCanonicalCaseOutput` (o equivalente Opción A/B).
12. Test de regresión: el componente **no** renderiza la palabra `feedback` aunque el payload incluya un campo así por error.

Los tests del PR #215 que validaban el layout antiguo (4 KPI cards, sidebar paralelo, cards pregunta-por-pregunta) se **borran** en el mismo PR.

### Backend (solo si se eligió Opción B en §3.2)

Sumar tests a `backend/tests/test_teacher_case_submission_detail.py`:

- `case_view` presente en el response, sanitizado con whitelist.
- `case_view` **no contiene** `feedback` aunque el JSONB upstream lo tenga.
- `case_view` **no contiene** llaves arbitrarias del JSONB.
- `payload_version` se mantiene en `Literal[1]` si el cambio es aditivo opcional, o sube a `Literal[2]` con razonamiento documentado.

### Tests existentes que **deben seguir verdes sin modificarse**

- Suite completa de `case-preview` (verifica el no-mutate de `CasePreview.tsx`).
- Suite completa de `teacher-case-submissions` (verifica el no-mutate de la lista padre).
- Suite completa de `case-viewer` shared (verifica retro-compatibilidad).
- Backend `test_teacher_case_submission_detail` original.

---

## 6. Validación local

```powershell
git diff main -- frontend/src/features/case-preview/CasePreview.tsx
# debe imprimir: (vacío)

git diff main -- frontend/src/features/teacher-case-submissions/
# debe imprimir: (vacío)

git diff main -- backend/src/case_generator/
# debe imprimir: (vacío)

uv run --directory backend pytest -q
uv run --directory backend mypy src
npm --prefix frontend run lint
npm --prefix frontend run test
npm --prefix frontend run build
```

Los cinco comandos deben terminar con `exit 0`.

---

## 7. Acceptance criteria

- [ ] La pantalla `/teacher/cases/:assignmentId/entregas/:membershipId` se ve y se navega como `CasePreview`, con sidebar oscuro 280px, header h-16, módulos M1..M5 en el body, exhibits/datasets/notebook visibles según el caso.
- [ ] Cada pregunta muestra la respuesta del estudiante inline (donde el preview muestra el textarea), en modo solo-lectura, con `white-space: pre-wrap` (heredado de `PreguntaCard`).
- [ ] La solución esperada se muestra inline igual que en `CasePreview` con `showExpectedSolutions={true}`.
- [ ] El sidebar inferior muestra estado de la entrega + snapshot/draft + calificación (si aplica), sin duplicar info del header.
- [ ] El header tiene "Actualizar entrega" + slot de calificación con `data-testid` reservado.
- [ ] `CasePreview.tsx` **no** aparece en el diff del PR.
- [ ] La página padre **no** aparece en el diff del PR.
- [ ] `case_generator/**` **no** aparece en el diff del PR.
- [ ] `feedback` **no** aparece serializado en ningún test ni en el DOM.
- [ ] Los cinco comandos de validación pasan en local.
- [ ] PR description incluye: decisión Opción A vs B (§3.2), screenshots de antes/después, evidencia de validación, mención del slot reservado y su `data-testid`.

---

## 8. Out of scope (próxima issue)

- Captura de calificación (formulario, validaciones, persistencia).
- Edición o lectura de `case_grades.feedback`.
- Mutación del listado padre tras calificar.
- Rúbrica visual.
- Comparación entre intentos (versions).
- Export de la entrega a PDF/HTML.
