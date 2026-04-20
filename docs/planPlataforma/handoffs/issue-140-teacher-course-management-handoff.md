# Handoff de Implementación: Issue #140 Teacher Course Management

## Contexto

- Issue principal: #140
- Sub-issue backend: #137
- Sub-issue frontend: #138
- Sub-issue authoring/IA: #139
- Repo: `4Tech-Labs/ADAM-EDU`

Esta iniciativa convierte la ruta docente `/teacher/courses/:courseId` en una pantalla real de gestión académica. La regla central es simple: el syllabus ya no es un mock de UI, es una entidad persistida y versionada que además alimenta el grounding de ADAM. La generación de casos no puede continuar si el syllabus del curso no existe o no está guardado.

## Objetivo técnico

Implementar la pantalla fiel al mockup de `Pantalla_Curso_Profesor_mvp.html`, reutilizando el header docente existente, con persistencia en backend, versionado por snapshots, integración con el authoring flow vía `course_id`, y un `ai_grounding_context` derivado server-side.

## Principios que no se deben romper

1. `courses` sigue siendo la fuente institucional para `title`, `code`, `semester`, `academic_level`.
2. `syllabuses` es un dominio separado 1:1 con `courses`.
3. El frontend no es autoridad de grounding. El backend deriva el contexto ADAM desde el syllabus persistido.
4. No portar el JavaScript demo del mockup a React.
5. Usar el patrón actual del repo: API explícita + TanStack Query + tipos manuales de contrato.
6. Unificar un solo shape frontend para `syllabus -> modules -> units` y retirarlo de mocks funcionales.

## Fase 1: Modelos y migraciones backend

### Objetivo

Crear el dominio `syllabuses`, el historial de revisiones y la relación explícita `Assignment.course_id`.

### Archivos a modificar

- [backend/src/shared/models.py](backend/src/shared/models.py)
- [backend/alembic/versions](backend/alembic/versions)

### Trabajo esperado

1. Agregar modelo `Syllabus` 1:1 con `Course`.
2. Agregar modelo o tabla de snapshots de revisión, por ejemplo `syllabus_revisions`.
3. Agregar `course_id` a `Assignment` como FK real.
4. Agregar relaciones ORM necesarias:
   - `Course.syllabus`
   - `Syllabus.course`
   - `Syllabus.revisions`
   - `Assignment.course`
5. Mantener el syllabus completo persistido en una estructura clara.
6. Persistir también `ai_grounding_context` como JSON profundo y compacto derivado del syllabus.

### Estructura mínima sugerida para `Syllabus`

- `id`
- `course_id`
- `revision`
- `department`
- `knowledge_area`
- `nbc`
- `version_label`
- `academic_load`
- `course_description`
- `general_objective`
- `specific_objectives`
- `modules`
- `evaluation_strategy`
- `didactic_strategy`
- `integrative_project`
- `bibliography`
- `teacher_notes`
- `ai_grounding_context`
- `saved_at`
- `saved_by_membership_id`

### Definition of done

- Alembic migrates cleanly.
- ORM maps all new entities.
- `Assignment.course_id` is present and queryable.
- Revision snapshot table is append-only.

## Fase 2: Contratos y rutas teacher backend

### Objetivo

Exponer el detalle compuesto del curso y el guardado del syllabus con ownership y tenant isolation.

### Archivos a modificar

- [backend/src/shared/teacher_reads.py](backend/src/shared/teacher_reads.py)
- [backend/src/shared/app.py](backend/src/shared/app.py) o un módulo teacher dedicado coherente con la arquitectura actual
- [backend/src/shared/models.py](backend/src/shared/models.py)

### Trabajo esperado

1. Crear contrato `TeacherCourseDetailResponse`.
2. Exponer `GET /api/teacher/courses/{course_id}` con payload compuesto:
   - bloque institucional read-only
   - syllabus persistido
   - metadata de revisión
   - link de invitación / configuración
3. Exponer `PUT` o `PATCH /api/teacher/courses/{course_id}/syllabus`.
4. Validar ownership con `teacher_membership_id`.
5. Validar tenant isolation.
6. Crear snapshot de revisión en cada guardado exitoso.

### Qué no hacer

- No mezclar escritura de campos institucionales por la ruta docente.
- No devolver varias lecturas separadas si una respuesta compuesta cubre toda la pantalla.

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
4. Agregar query key específica por `courseId`, por ejemplo `teacher.course(courseId)`.
5. Mantener invalidación dirigida y evitar invalidar todo `teacher.*` si no hace falta.

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

### Qué excluir del mockup

- modal de respuestas de estudiantes
- dataset de estudiantes demo
- lógica vanilla JS no relacionada con la pantalla real

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

Hacer que la generación de casos dependa del syllabus guardado y que el contexto ADAM se derive en backend.

### Archivos a modificar

- [backend/src/shared/app.py](backend/src/shared/app.py)
- [backend/src/case_generator/orchestration/frontend_adapter.py](backend/src/case_generator/orchestration/frontend_adapter.py)
- [backend/src/case_generator/core/authoring.py](backend/src/case_generator/core/authoring.py)
- [backend/src/shared/models.py](backend/src/shared/models.py)

### Trabajo esperado

1. Extender intake request con `course_id`.
2. Rechazar el create job si el curso no tiene syllabus guardado.
3. Resolver `ai_grounding_context` desde el syllabus persistido.
4. Inyectar el grounding derivado en el pipeline antes de ejecutar el grafo.
5. Ignorar cualquier intento del cliente de mandar grounding autoritativo duplicado.

### Esquema de referencia para `ai_grounding_context`

```json
{
  "course_identity": {
    "course_id": "uuid-or-text-id",
    "course_title": "Gerencia Estratégica y Modelos de Negocio en Ecosistemas Digitales",
    "academic_level": "Especialización",
    "department": "Gestión de las Organizaciones",
    "knowledge_area": "Economía, Administración, Contaduría y afines",
    "nbc": "Administración"
  },
  "pedagogical_intent": {
    "course_description": "texto compacto derivado del syllabus",
    "general_objective": "objetivo general",
    "specific_objectives": ["objetivo 1", "objetivo 2"]
  },
  "instructional_scope": {
    "modules": [
      {
        "module_id": "m1",
        "module_title": "Fundamentos de estrategia en la era de la IA",
        "weeks": "1-3",
        "module_summary": "resumen compacto",
        "learning_outcomes": ["resultado 1"],
        "units": [
          {
            "unit_id": "1.1",
            "title": "Evolución estratégica digital",
            "topics": "tema compacto"
          }
        ],
        "cross_course_connections": "texto compacto"
      }
    ],
    "evaluation_strategy": [
      {
        "activity": "Primer parcial",
        "weight": 20,
        "linked_objectives": ["O1"],
        "expected_outcome": "texto compacto"
      }
    ],
    "didactic_strategy": {
      "methodological_perspective": "texto compacto",
      "pedagogical_modality": "texto compacto"
    }
  },
  "generation_hints": {
    "target_student_profile": "business",
    "scenario_constraints": ["constraint 1"],
    "preferred_techniques": ["SWOT"],
    "difficulty_signal": "advanced",
    "forbidden_mismatches": [
      "No generar un caso que ignore el módulo seleccionado"
    ]
  },
  "metadata": {
    "syllabus_revision": 1,
    "saved_at": "ISO-8601 timestamp",
    "saved_by_membership_id": "teacher-membership-id"
  }
}
```

### Regla práctica

Guardar el syllabus completo. Derivar un grounding compacto. No mandar el syllabus entero al prompt si el objeto compacto ya cubre la personalización requerida.

## Fase 7: Testing

### Backend

Archivos base:

- [backend/tests/test_issue88_teacher_courses.py](backend/tests/test_issue88_teacher_courses.py)
- nuevos tests adyacentes para syllabus detail/save/guard

Cobertura mínima:

1. Teacher detail happy path.
2. Teacher detail forbidden for student/admin/non-owner.
3. Tenant isolation.
4. Save syllabus happy path.
5. Revision snapshot creation.
6. Guard de generación sin syllabus guardado.
7. Derivación determinista de `ai_grounding_context`.
8. Resistencia a payload cliente stale o conflictivo.

### Frontend

Archivos base:

- tests nuevos de la route/page docente
- [frontend/src/features/teacher-authoring/useAuthoringJobProgress.test.ts](frontend/src/features/teacher-authoring/useAuthoringJobProgress.test.ts)

Cobertura mínima:

1. La ruta carga el detalle.
2. El tab en URL persiste correctamente.
3. Save success.
4. Save failure.
5. Copy invitation link.
6. `course_id` se serializa en el create request.

## Secuencia recomendada

1. Fase 1 backend modelado/migraciones.
2. Fase 2 backend endpoints teacher.
3. Fase 3 contratos frontend/API.
4. Fase 4 página de curso real.
5. Fase 5 unificación con authoring form.
6. Fase 6 guard + grounding.
7. Fase 7 tests y validación final.

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
2. `course_id` faltante o parcial entre assignment, job y detalle docente.
3. Invalidación demasiado amplia o demasiado estrecha en TanStack Query.
4. Payload de grounding demasiado grande y costoso para prompts.
5. Fuga de datos si teacher detail/save no filtra por ownership real.