# Handoff de Implementación: Issue #140 Teacher Course Management

## Contexto

- Issue principal: #140
- Sub-issue backend: #137
- Sub-issue frontend: #138
- Sub-issue authoring/IA: #139
- Repo: `4Tech-Labs/ADAM-EDU`

Esta iniciativa convierte la ruta docente `/teacher/courses/:courseId` en una pantalla real de gestión académica. La regla central sigue igual: el syllabus ya no es un mock de UI, es una entidad persistida y versionada que además alimenta el grounding de ADAM. La generación de casos no puede continuar si el syllabus del curso no existe o no está guardado.

## Estado actual después de #137

La base backend ya quedó implementada y validada en la sub-issue #137. Este handoff ya no debe tratar esa parte como trabajo pendiente.

### Lo que ya existe

1. Dominio `syllabuses` 1:1 con `courses`.
2. Historial append-only en `syllabus_revisions`.
3. Contrato canónico backend en [backend/src/shared/syllabus_schema.py](backend/src/shared/syllabus_schema.py).
4. Endpoint compuesto de detalle:
   - `GET /api/teacher/courses/{course_id}`
5. Endpoint de guardado:
   - `PUT /api/teacher/courses/{course_id}/syllabus`
6. Optimistic locking con `expected_revision` y conflicto explícito `409 stale_syllabus_revision`.
7. Derivación server-side de `ai_grounding_context` en el save del syllabus.
8. Ownership y tenant isolation filtrando por `teacher_membership_id` y `university_id`.

### Archivos backend ya resueltos en #137

- [backend/src/shared/models.py](backend/src/shared/models.py)
- [backend/src/shared/syllabus_schema.py](backend/src/shared/syllabus_schema.py)
- [backend/src/shared/teacher_reads.py](backend/src/shared/teacher_reads.py)
- [backend/src/shared/teacher_writes.py](backend/src/shared/teacher_writes.py)
- [backend/src/shared/teacher_router.py](backend/src/shared/teacher_router.py)
- [backend/alembic/versions/e1b3c4d5f6a7_issue137_teacher_syllabuses.py](backend/alembic/versions/e1b3c4d5f6a7_issue137_teacher_syllabuses.py)
- [backend/tests/test_issue88_teacher_courses.py](backend/tests/test_issue88_teacher_courses.py)
- [backend/tests/test_issue30_auth_perimeter.py](backend/tests/test_issue30_auth_perimeter.py)

### Restricciones reales que dejó #137

1. `courses` sigue siendo la fuente institucional para `title`, `code`, `semester`, `academic_level`.
2. `syllabuses` es un dominio separado 1:1 con `courses`.
3. El frontend no es autoridad de grounding. El backend deriva el contexto ADAM desde el syllabus persistido.
4. El save del syllabus no acepta campos institucionales. Si el cliente intenta mandar `title`, `code`, `semester` u otros campos fuera del contrato, la request debe fallar por validación.
5. El detalle docente devuelve configuración del access link, pero no expone un raw link reutilizable.
6. El runtime de authoring/generación es LangGraph-based. No introducir una capa paralela o un framing incorrecto de “LangChain graph” para la integración pendiente.

## Objetivo técnico remanente

Con #137 cerrado, el trabajo de #140 queda partido en dos frentes coordinados:

1. #138: consumir el contrato real del backend en la página docente `/teacher/courses/:courseId`.
2. #139: conectar el authoring flow con `course_id`, exigir syllabus persistido y reusar el `ai_grounding_context` canónico ya guardado.

## Principios que no se deben romper

1. No reabrir la separación de autoridades entre `Course` e `Syllabus`.
2. No portar el JavaScript demo del mockup a React.
3. Usar el patrón actual del repo: API explícita + TanStack Query + tipos manuales de contrato.
4. Unificar un solo shape frontend para `syllabus -> modules -> units` y retirarlo de mocks funcionales.
5. No inventar un contrato alterno de grounding dentro del authoring pipeline.
6. No introducir una solución frontend-only para copiar o regenerar access links sin soporte backend dedicado.

## Contrato backend vigente

### `GET /api/teacher/courses/{course_id}`

Devuelve un payload compuesto con cuatro bloques:

1. `course`
   - institucional, read-only
2. `syllabus`
   - editable por docente
3. `revision_metadata`
   - incluye revisión actual y último guardado
4. `configuration`
   - estado/configuración del access link

### `PUT /api/teacher/courses/{course_id}/syllabus`

Payload esperado:

```json
{
  "expected_revision": 1,
  "syllabus": {
    "department": "...",
    "knowledge_area": "...",
    "nbc": "...",
    "version_label": "...",
    "academic_load": "...",
    "course_description": "...",
    "general_objective": "...",
    "specific_objectives": ["..."],
    "modules": [],
    "evaluation_strategy": [],
    "didactic_strategy": {
      "methodological_perspective": "...",
      "pedagogical_modality": "..."
    },
    "integrative_project": "...",
    "bibliography": ["..."],
    "teacher_notes": "..."
  }
}
```

### Consecuencias para consumidores

1. El cliente debe leer `revision_metadata.current_revision` y reenviarlo como `expected_revision` al guardar.
2. Si el backend responde `409 stale_syllabus_revision`, el cliente no debe reintentar a ciegas ni sobrescribir silenciosamente.
3. La configuración actual no permite reconstruir ni copiar un raw invite link existente. Solo hay metadata en el bloque `configuration`.

## Estado de las fases del plan

## Fase 1: Modelos y migraciones backend

### Estado

Completada en #137, excepto la integración `Assignment.course_id`, que fue diferida de forma explícita a #139.

### Hecho en #137

1. `Syllabus` 1:1 con `Course`.
2. `SyllabusRevision` append-only.
3. Persistencia de `ai_grounding_context` como JSONB derivado server-side.
4. Migración Alembic conectada al head correcto.

### Pendiente para #139

1. Agregar `Assignment.course_id` como FK real.
2. Propagar `course_id` por el intake y el pipeline de authoring.

## Fase 2: Contratos y rutas teacher backend

### Estado

Completada en #137.

### Hecho en #137

1. `TeacherCourseDetailResponse`.
2. `GET /api/teacher/courses/{course_id}`.
3. `PUT /api/teacher/courses/{course_id}/syllabus`.
4. Ownership y tenant isolation.
5. Snapshot de revisión por save exitoso.

### Qué no reabrir

1. No mezclar escritura de campos institucionales por la ruta docente.
2. No fragmentar el detalle en múltiples llamadas si el endpoint compuesto ya cubre la pantalla.

## Fase 3: Contratos frontend y TanStack Query

### Objetivo

Preparar el consumo frontend sin inventar formas paralelas de datos.

### Archivos a modificar

- [frontend/src/shared/adam-types.ts](frontend/src/shared/adam-types.ts)
- [frontend/src/shared/api.ts](frontend/src/shared/api.ts)
- [frontend/src/shared/queryKeys.ts](frontend/src/shared/queryKeys.ts)

### Trabajo esperado

1. Agregar contratos manuales para:
   - `TeacherCourseDetailResponse`
   - `TeacherSyllabusPayload`
   - `TeacherSyllabusRevisionMetadata`
   - payload de save del syllabus
2. Agregar `api.teacher.getCourseDetail(courseId)`.
3. Agregar `api.teacher.saveCourseSyllabus(courseId, payload)`.
4. Agregar query key específica por `courseId`, idealmente algo como `queryKeys.teacher.course(courseId)`.
5. Mantener invalidación dirigida y evitar invalidar todo `teacher.*` si no hace falta.
6. Modelar explícitamente el conflicto `409 stale_syllabus_revision`.

## Fase 4: Página real de gestión de curso

### Objetivo

Reemplazar el placeholder y renderizar la pantalla real fiel al mockup.

### Archivos a modificar

- [frontend/src/app/App.tsx](frontend/src/app/App.tsx)
- [frontend/src/features/teacher-dashboard/TeacherCoursePlaceholderPage.tsx](frontend/src/features/teacher-dashboard/TeacherCoursePlaceholderPage.tsx)
- [frontend/src/features/teacher-layout/TeacherLayout.tsx](frontend/src/features/teacher-layout/TeacherLayout.tsx)
- [frontend/src/features/teacher-layout/TeacherUserHeader.tsx](frontend/src/features/teacher-layout/TeacherUserHeader.tsx)
- nuevos componentes en la zona docente del frontend, manteniendo la convención del repo

### Trabajo esperado

1. Sustituir el placeholder por una página real.
2. Reusar el layout/header docente existente.
3. Implementar tabs `Syllabus` y `Configuración` con persistencia por URL.
4. Mantener alta fidelidad al mockup en:
   - sidebar/card del curso
   - jerarquía visual de secciones
   - formularios y divisores
   - badges `✦ ADAM`
   - botón de guardado y metadata de último guardado
5. Traducir el mockup a JSX semántico y componentes del sistema actual.

### Restricción importante para #138

La tab `Configuración` no puede prometer copy/regeneration de un raw access link con el contrato actual. Debe renderizar estado/configuración real y no una UX ficticia basada en `access_link_id`.

### Qué excluir del mockup

1. modal de respuestas de estudiantes
2. dataset de estudiantes demo
3. lógica vanilla JS no relacionada con la pantalla real

## Fase 5: Unificación con el authoring flow

### Objetivo

Eliminar la duplicación entre la pantalla de syllabus y el authoring form.

### Archivos a modificar

- [frontend/src/features/teacher-authoring/AuthoringForm.tsx](frontend/src/features/teacher-authoring/AuthoringForm.tsx)
- [frontend/src/features/teacher-authoring/authoringFormConfig.ts](frontend/src/features/teacher-authoring/authoringFormConfig.ts)
- [frontend/src/features/teacher-authoring/useAuthoringJobProgress.ts](frontend/src/features/teacher-authoring/useAuthoringJobProgress.ts)
- [frontend/src/shared/adam-types.ts](frontend/src/shared/adam-types.ts)

### Trabajo esperado

1. Dejar de usar `professorDB` como fuente funcional del syllabus.
2. Reutilizar el mismo contrato de `modules -> units` proveniente del curso persistido.
3. Agregar `course_id` al request builder del authoring job.
4. Mantener el comportamiento actual del formulario, pero ya respaldado por datos reales.

## Fase 6: Guard de generación y grounding ADAM

### Objetivo

Hacer que la generación de casos dependa del syllabus guardado y que el contexto ADAM se resuelva desde el grounding persistido.

### Archivos a modificar

- [backend/src/shared/app.py](backend/src/shared/app.py)
- [backend/src/case_generator/orchestration/frontend_adapter.py](backend/src/case_generator/orchestration/frontend_adapter.py)
- [backend/src/case_generator/core/authoring.py](backend/src/case_generator/core/authoring.py)
- [backend/src/shared/models.py](backend/src/shared/models.py)
- [backend/alembic/versions](backend/alembic/versions)

### Trabajo esperado

1. Extender intake request con `course_id`.
2. Agregar `Assignment.course_id` como FK real.
3. Rechazar el create job si el curso seleccionado y owned no tiene syllabus guardado.
4. Resolver `ai_grounding_context` desde el row persistido en `syllabuses`.
5. Inyectar ese grounding persistido en el pipeline antes de ejecutar el grafo.
6. Ignorar o rechazar cualquier intento del cliente de mandar grounding autoritativo duplicado.

### Contrato de referencia para grounding

El contrato canónico ya implementado vive en [backend/src/shared/syllabus_schema.py](backend/src/shared/syllabus_schema.py):

1. `SyllabusGroundingContext`
2. `derive_syllabus_grounding_context(...)`

La integración de #139 debe tratar ese contrato como la fuente de verdad. Si se necesitan más `generation_hints`, se evoluciona ese contrato canónico y sus tests; no se crea un segundo esquema implícito dentro del pipeline.

### Regla práctica

Guardar el syllabus completo. Reusar el grounding compacto ya persistido. No mandar el syllabus entero al prompt si el objeto compacto ya cubre la personalización requerida.

### Qué no hacer en #139

1. No implementar el guard como SQL ad hoc estilo `SELECT count(*) ...` disperso por el codebase.
2. No reconstruir el grounding desde form fields del cliente si ya existe persistido.
3. No introducir un contrato paralelo “frontend-owned” para personalizar ADAM.

## Fase 7: Testing

### Backend

Archivos base:

- [backend/tests/test_issue88_teacher_courses.py](backend/tests/test_issue88_teacher_courses.py)
- tests nuevos o adyacentes para authoring intake, `course_id`, guard y grounding

Cobertura mínima remanente:

1. Guard de generación sin syllabus guardado.
2. Persistencia real de `Assignment.course_id`.
3. Traza de `course_id` en `authoring_jobs.task_payload`.
4. Selección del grounding persistido por `course_id`.
5. Resistencia a payload cliente stale o conflictivo de grounding.

### Frontend

Archivos base:

- tests nuevos de la route/page docente
- [frontend/src/features/teacher-authoring/useAuthoringJobProgress.test.ts](frontend/src/features/teacher-authoring/useAuthoringJobProgress.test.ts)

Cobertura mínima remanente:

1. La ruta carga el detalle.
2. El tab en URL persiste correctamente.
3. Save success.
4. Save validation failure.
5. Save conflict `409 stale_syllabus_revision`.
6. `course_id` se serializa en el create request.

## Secuencia recomendada desde hoy

1. #138: contratos frontend/API + query keys + página real.
2. #138: tests e integración visual/funcional de la ruta docente.
3. #139: `course_id` en authoring intake + migración `Assignment.course_id`.
4. #139: guard de syllabus persistido + grounding persistido en LangGraph.
5. #139: tests backend/frontend remanentes.
6. Validación final completa.

## Validación final

Backend:

```powershell
uv run --directory backend pytest -q
uv run --directory backend mypy src
```

Frontend:

```powershell
npm --prefix frontend run lint
npm --prefix frontend run test
npm --prefix frontend run build
```

Solo si se tocan prompts o builders de contexto LLM:

```powershell
$env:RUN_LIVE_LLM_TESTS="1"
uv run --directory backend pytest -m live_llm -q
```

## Riesgos que deben revisarse en code review

1. Drift entre syllabus guardado y payload cliente.
2. `course_id` faltante o parcial entre assignment, job y authoring intake.
3. Invalidación demasiado amplia o demasiado estrecha en TanStack Query.
4. Payload de grounding demasiado grande y costoso para prompts.
5. Fuga de datos si teacher detail/save o el authoring intake no filtran por ownership real.
6. UX falsa en frontend si se intenta “copiar link” sin raw token real del backend.