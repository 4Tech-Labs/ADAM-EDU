# MASTER AUDIT PLAN: PROTOCOLO PHOENIX (ADAM EDU)

> **ESTADO HISTORICO**: Este documento se conserva solo como registro de auditoria. No define el alcance operativo del repo publicado en GitHub. El alcance vigente esta documentado en `README.md` y `CLAUDE.md`.

> **Fecha**: 2026-03-31  
> **Auditor**: Claude Opus 4.6  
> **Repositorio**: `gemini-fullstack-langgraph-quickstart` (fork divergente: +11,694 / -2,762 líneas)  
> **Sistema objetivo**: ADAM EDU v8.0 - Sistema multi-agente para casos de negocio pedagógicos

---

## 0. DIAGNOSTICO DE ARQUITECTURA

### Estado actual

Todo el backend vive en un namespace plano `backend/src/agent/` con 22 módulos sin separación de dominio:

```
backend/src/agent/          <- NAMESPACE PLANO (anti-patrón)
  adapters/
    frontend_adapter.py          (input adapter legacy->canonical)
    frontend_output_adapter.py   (output adapter canonical->frontend)
  routers/
    runtime.py                   (endpoints Phase 4 student)
  services/
    artifact_manager.py          (upload + manifest persistence)
    authoring.py                 (orquestador pipeline LangGraph)
    chat.py                      (SSE streaming, thread lifecycle)
    enrollment.py                (matrícula estudiantes)
    grading.py                   (calificación módulos)
    storage.py                   (IStorageProvider, LocalStorageProvider)
  app.py                         (FastAPI entry, 423 líneas)
  blueprint_schema.py            (AssignmentBlueprint, contratos Pydantic)
  checkpoint.py                  (AsyncPostgresSaver para LangGraph)
  configuration.py               (config modelos LLM)
  database.py                    (SQLAlchemy engine, Cloud SQL pooling)
  dependencies.py                (FastAPI auth deps)
  graph.py                       (PIPELINE CENTRAL, 2,970 líneas)
  models.py                      (ORM: 10 modelos, 220 líneas)
  progress_bus.py                (pub/sub SSE in-memory)
  prompts.py                     (TODOS los prompts LLM, 2,042 líneas)
  state.py                       (ADAMState TypedDict)
  suggest_service.py             (sugerencias pedagógicas)
  tools_and_schemas.py           (schemas Pydantic output LLM, 302 líneas)
  twin_graph.py                  (LangGraph conversacional para twins)
```

Frontend con estructura plana de componentes:

```
frontend/src/
  pages/TeacherBuilderPage.tsx, StudentPlaceholder.tsx
  components/TeacherCaseForm.tsx, CasePreview.tsx, ActivityTimeline.tsx, ...
  hooks/useJobProgress.ts
  lib/api.ts
  types/adam.ts
```

### Stack técnico confirmado (manifiestos)

| Capa | Tecnología | Versión |
|------|-----------|---------|
| Backend runtime | Python | 3.12 |
| API framework | FastAPI | >=0.115 |
| Orquestación IA | LangGraph | >=1.0 |
| LLM provider | langchain-google-genai (Gemini) | >=4.0 |
| ORM | SQLAlchemy | >=2.0 |
| Migraciones | Alembic | >=1.13 (4 migraciones existentes) |
| DB | PostgreSQL | 16 (via docker-compose) |
| Frontend framework | React | 19 |
| Bundler | Vite | 6 |
| Tipado | TypeScript | 5.7 |
| Estilos | Tailwind CSS | 4 |
| Gráficos | Plotly.js | 3 |
| Contenedor | Docker multi-stage | node:20 -> langchain/langgraph-api:3.12 |

### Brechas arquitectónicas vs dominio objetivo

| Dominio ADAM EDU | Estado actual | Brecha |
|-----------------|---------------|--------|
| `/case-generator` | Lógica dispersa en graph.py, prompts.py, state.py, tools_and_schemas.py, services/authoring.py, services/artifact_manager.py | Sin módulo dedicado; todo bajo `agent/` |
| `/harvard-parser` | NO EXISTE como módulo. Lógica de parsing Harvard embebida en prompts.py | Dominio completamente ausente |
| `/tutor-engine` | twin_graph.py existe pero bajo `agent/` | Sin namespace propio |
| `/student-workspace` | routers/runtime.py + services/{chat,enrollment,grading}.py | Mezclado con el resto bajo `agent/` |
| `/auth-perimeter` | Solo dependencies.py con stub `get_current_student()` | Mínimo; sin middleware real |

---

## 1. SPRINT 0: THE PURGE & SECURITY

**Objetivo**: Limpiar artefactos muertos, cerrar brechas de seguridad y estabilizar el estado del repositorio antes de cualquier reestructuración.  
**Duración estimada**: 1 día

### 1.1 Hardening de `.gitignore`

El `.gitignore` actual (202 líneas) ya cubre `.env` (línea 163) y `.venv`/`venv/` (líneas 164-166). `.env` NO está en el índice de git (verificado). Faltan entradas específicas de ADAM:

```gitignore
# ADAM EDU - agregar al final de .gitignore
backend/.data/
.claude/
.python-version
backend/.python-version
```

### 1.2 Parametrizar credenciales de docker-compose.yml

`docker-compose.yml` líneas 10-14 tienen credenciales hardcodeadas:

```yaml
# ACTUAL (inseguro para cualquier entorno compartido)
POSTGRES_DB: postgres
POSTGRES_USER: postgres
POSTGRES_PASSWORD: postgres

# PROPUESTO
POSTGRES_DB: ${POSTGRES_DB:-postgres}
POSTGRES_USER: ${POSTGRES_USER:-postgres}
POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-postgres}
```

### 1.3 Eliminar virtual environment duplicado

Existen `backend/venv/` Y `backend/.venv/`. Verificar cuál referencia el `Makefile` o `runner.py`, eliminar el no usado. Convención: mantener `.venv/` (estándar moderno).

### 1.4 Reubicar test files mal ubicados

```
# MOVER: backend/src/ -> backend/tests/integration/
backend/src/test_e2e_baseline.py    -> backend/tests/integration/test_e2e_baseline.py
backend/src/test_t1_smoke.py        -> backend/tests/integration/test_t1_smoke.py
backend/src/test_t2_smoke.py        -> backend/tests/integration/test_t2_smoke.py
backend/src/test_t3_smoke.py        -> backend/tests/integration/test_t3_smoke.py
backend/src/test_t4_smoke.py        -> backend/tests/integration/test_t4_smoke.py
backend/src/validate_output_adapter.py -> backend/tests/validation/validate_output_adapter.py
```

### 1.5 Stage de archivos muertos del upstream

Archivos eliminados en working tree pero no staged (git status `D`):

```
# Imágenes obsoletas del quickstart original
agent.png
app.png

# Módulo legacy reemplazado
backend/src/agent/utils.py
backend/test-agent.ipynb

# Componentes frontend reemplazados por arquitectura ADAM
frontend/src/components/ChatMessagesView.tsx
frontend/src/components/InputForm.tsx
frontend/src/components/WelcomeScreen.tsx
frontend/src/components/ui/badge.tsx
frontend/src/components/ui/button.tsx
frontend/src/components/ui/card.tsx
frontend/src/components/ui/input.tsx
frontend/src/components/ui/scroll-area.tsx
frontend/src/components/ui/tabs.tsx
frontend/src/components/ui/textarea.tsx
```

**Acción**: `git add` todas las eliminaciones + commit `chore: remove dead upstream files replaced by ADAM architecture`.

### 1.6 Alerta de datos locales

`backend/.data/mock_gcs/` contiene 50+ archivos de artefactos de prueba (UUIDs con `v1_narrative_draft.md` y `v1_eda_report_draft.md`). NO eliminar - es storage local para `LocalStorageProvider`. Solo asegurar exclusión via `.gitignore` (ver 1.1).

### Checklist Sprint 0

- [x] `.gitignore` ampliado con entradas ADAM
- [x] `docker-compose.yml` parametrizado
- [x] venv duplicado eliminado
- [x] Test files reubicados y normalizados para `pytest` en `backend/tests/integration/` y `backend/tests/validation/`
- [x] Eliminaciones de archivos muertos staged y committed
- [x] `git status` limpio (sin secretos, sin artefactos huérfanos) - verificado al cierre de Sprint 0.5

### 1.7 Sprint 0.5: Hotfix de Calidad

- `docker-compose.yml` alineado con `POSTGRES_USER` también en el healthcheck de Postgres.
- Los smoke tests movidos a `backend/tests/integration/` fueron convertidos a tests recolectables por `pytest`, con bootstrap explícito a `backend/src`.
- `backend/tests/validation/validate_output_adapter.py` fue convertido a test real de `pytest` y validado contra estados HITL/finales.
- `pytest backend/tests/integration --collect-only -q` ahora recolecta 5 tests; sin `GEMINI_API_KEY`, `pytest backend/tests/integration -q` hace skip limpio y determinista.
- Sprint 0 queda formalmente cerrado a partir de este hotfix, sin modificar `backend/src/`.

---

## 2. SPRINT 1: THE BLUEPRINT (SCREAMING ARCHITECTURE)

**Objetivo**: Reestructurar `backend/src/agent/` en 5 paquetes de dominio + infraestructura compartida. Cada ruta de importación debe gritar el dominio de negocio al que pertenece.  
**Duración estimada**: 2-3 días

### 2.1 Estructura objetivo del backend

```
backend/src/
  case_generator/
    __init__.py
    graph.py
    prompts.py
    state.py
    tools_and_schemas.py
    suggest_service.py
    configuration.py
    core/
      __init__.py
      authoring.py
      artifact_manager.py
      storage.py
    orchestration/
      __init__.py
      frontend_adapter.py
      frontend_output_adapter.py

  harvard_parser/
    __init__.py
    parser.py
    schemas.py

  tutor_engine/
    __init__.py
    twin_graph.py

  student_workspace/
    __init__.py
    routers/
      __init__.py
      runtime.py
    core/
      __init__.py
      chat.py
      enrollment.py
      grading.py

  auth_perimeter/
    __init__.py
    dependencies.py
    middleware.py

  shared/
    __init__.py
    app.py
    database.py
    checkpoint.py
    models.py
    progress_bus.py
    blueprint_schema.py
```

### 2.2 Manifiesto de movimiento de archivos

| Ruta actual (`agent/`) | Ruta destino | Etapa |
|------------------------|-------------|-------|
| `database.py` | `shared/database.py` | shared_foundation |
| `checkpoint.py` | `shared/checkpoint.py` | shared_foundation |
| `models.py` | `shared/models.py` | shared_foundation |
| `progress_bus.py` | `shared/progress_bus.py` | shared_foundation |
| `blueprint_schema.py` | `shared/blueprint_schema.py` | shared_foundation |
| `graph.py` | `case_generator/graph.py` | case_generator |
| `prompts.py` | `case_generator/prompts.py` | case_generator |
| `state.py` | `case_generator/state.py` | case_generator |
| `tools_and_schemas.py` | `case_generator/tools_and_schemas.py` | case_generator |
| `suggest_service.py` | `case_generator/suggest_service.py` | case_generator |
| `configuration.py` | `case_generator/configuration.py` | case_generator |
| `services/authoring.py` | `case_generator/core/authoring.py` | case_generator |
| `services/artifact_manager.py` | `case_generator/core/artifact_manager.py` | case_generator |
| `services/storage.py` | `case_generator/core/storage.py` | case_generator |
| `adapters/frontend_adapter.py` | `case_generator/orchestration/frontend_adapter.py` | case_generator |
| `adapters/frontend_output_adapter.py` | `case_generator/orchestration/frontend_output_adapter.py` | case_generator |
| `routers/runtime.py` | `student_workspace/routers/runtime.py` | student_workspace |
| `services/chat.py` | `student_workspace/core/chat.py` | student_workspace |
| `services/enrollment.py` | `student_workspace/core/enrollment.py` | student_workspace |
| `services/grading.py` | `student_workspace/core/grading.py` | student_workspace |
| `twin_graph.py` | `tutor_engine/twin_graph.py` | tutor_engine |
| `dependencies.py` | `auth_perimeter/dependencies.py` | auth_perimeter |
| `app.py` | `shared/app.py` | composition_root |

**Total**: 23 archivos movidos según manifiesto.

### 2.3 Estrategia de reescritura de imports

Patrón actual: `from agent.X import Y`  
Patrón nuevo: `from {dominio}.X import Y`

**Orden obligatorio de ejecución**:
1. `refactor(structure): crear topología gritante base`
2. `refactor(domain): migrar shared_foundation a arquitectura gritante`
3. `refactor(domain): migrar case_generator a arquitectura gritante`
4. `refactor(domain): migrar student_workspace a arquitectura gritante`
5. `refactor(domain): migrar tutor_engine a arquitectura gritante`
6. `refactor(domain): migrar auth_perimeter a arquitectura gritante`
7. `refactor(domain): migrar composition_root a arquitectura gritante`
8. `chore(manifests): alinear entrypoints y package discovery`
9. `docs: completar Sprint 1`

**Reglas de ejecución**:
- Antes de cada etapa, usar `rg` en `backend/src`, `backend/tests/` y `backend/examples/` para localizar imports antiguos.
- Después de cada etapa de migración, ejecutar `python -m pytest backend/tests/integration --collect-only -q`.
- Si el gate falla con `ModuleNotFoundError` o `ImportError`, reparar inmediatamente antes del commit.
- `app.py` y `runner.py` se actualizan únicamente en `composition_root`.

### 2.4 Actualizaciones de configuración requeridas

- **`backend/pyproject.toml`**: Actualizar package discovery para `case_generator*`, `harvard_parser*`, `tutor_engine*`, `student_workspace*`, `auth_perimeter*`, `shared*`.
- **`Dockerfile`**: Cambiar entrypoints a `shared/app.py` y `case_generator/graph.py`.
- **`backend/langgraph.json`**: Cambiar file targets a `./src/shared/app.py:app` y `./src/case_generator/graph.py:graph`.
- **`backend/alembic/env.py`**: Importar `settings` desde `shared.database` y `Base` desde `shared.models`.
- **`backend/alembic/versions/`**: Reemplazo literal obligatorio de `agent.models` -> `shared.models` y `agent.database` -> `shared.database`.
- **`Makefile`**: Reemplazar `src.agent.app:app` por `shared.app:app`.
- **`backend/runner.py`**: Verificar y actualizar referencias antiguas solo en `composition_root`.

### 2.5 Dependencias cross-dominio válidas

```
shared/app.py --imports---> case_generator (AuthoringService)
shared/app.py --imports---> student_workspace (runtime router)
shared/app.py --imports---> auth_perimeter (dependencies)
student_workspace/core/chat.py --imports---> tutor_engine (twin_graph)
todos los dominios --imports---> shared (models, database, checkpoint, blueprint_schema)
```

**Regla**: Las flechas NUNCA van de `shared/` hacia un dominio, excepto `shared/app.py` como composition root.

### 2.6 Frontend - Alineación de dominio (documentación, no ejecución)

Estructura objetivo eventual (NO ejecutar en Sprint 1):

```
frontend/src/
  features/
    case-generator/
    student-workspace/
  shared/
    components/
    hooks/
    lib/
    types/
```

**Nota**: Reestructura del frontend diferida para evitar breakage simultáneo en ambos stacks.

### Checklist Sprint 1

- [x] Etapa 0: topología gritante base creada (`__init__.py`, stubs y plan V2 sincronizado)
- [x] Etapa 1: `shared_foundation` migrado y validado con `integration --collect-only`
- [x] Etapa 2: `case_generator` migrado y validado con `integration --collect-only`
- [x] Etapa 3: `student_workspace` migrado y validado con `integration --collect-only`
- [x] Etapa 4: `tutor_engine` migrado y validado con `integration --collect-only`
- [x] Etapa 5: `auth_perimeter` migrado y validado con `integration --collect-only`
- [x] Etapa 6: `composition_root` migrado y validado con `integration --collect-only`
- [x] Manifiestos alineados (`pyproject.toml`, `Dockerfile`, `langgraph.json`, `alembic`, `Makefile`)
- [x] Gate final `python -m pytest backend/tests --collect-only -q`
- [x] Barrido final sin referencias funcionales a `agent.*`

## SPRINT 1.1: QA HOTFIX (Ejecutado)

**Objetivo**: Convertir el cierre topológico del Sprint 1 en un cierre de ejecución reproducible para QA/SRE local, sin modificar la topología de dominios.  
**Estado**: Ejecutado

### Correcciones aplicadas

- Se agregó `pytest-asyncio` al grupo `dev` en `backend/pyproject.toml` y se configuró `asyncio_mode = "auto"` para permitir ejecución real de suites asíncronas.
- `backend/tests/test_phase2_fragmentation.py` quedó estabilizado bajo `pytest`: el caso de compatibilidad legacy sigue ejecutándose y los 4 escenarios que dependen de símbolos removidos tras Sprint 1 (`graph.interrupt` / `graph_v5`) quedaron marcados explícitamente como `skipped` con razón documentada.
- Se creó `backend/tests/conftest.py` con un fixture `db` real sobre SQLAlchemy para los tests de API, y `backend/tests/test_phase3_status_api.py` fue ajustado para no disparar `BackgroundTasks` reales durante la validación de estados.
- Se eliminaron hacks de `sys.path` en `backend/alembic/env.py`, `backend/runner.py`, `backend/tests/test_phase1a_smoke.py` y `backend/tests/test_phase3_status_api.py`, delegando la resolución de imports al package discovery ya configurado en Sprint 1.
- Se corrigió `Makefile`: `dev-backend` ahora levanta solo la API FastAPI (`uvicorn`) y `langgraph dev` quedó aislado en el nuevo target `dev-langgraph`, evitando comandos bloqueantes secuenciales en un mismo target.

### Gate de validación Sprint 1.1

- `uv run --group dev python -m pytest tests/test_phase2_fragmentation.py -q` -> `1 passed, 4 skipped`
- `uv run --group dev python -m pytest tests/test_phase3_status_api.py -q` -> `4 passed`
- `uv run --group dev python -m pytest tests/test_phase1a_smoke.py::test_database_connection -q` -> `1 passed`
- `uv run python runner.py` -> `ALL TESTS PASSED. PHASE 3 API VALIDATED.`
- `Makefile` fue validado de forma estática en este host Windows; no se pudo ejecutar `make` porque `make`, `mingw32-make` y `nmake` no están instalados en el entorno local actual.

---

## 3. SPRINT 2: HARDENING & CONTEXT SANITIZATION

**Objetivo**: Establecer convenciones de código, sanitizar fronteras de confianza con LLMs, agregar type safety, y crear la capa de documentación para desarrolladores.  
**Duración estimada**: 2-3 días

### 3.1 Creación de `CLAUDE.md` (Convenciones del proyecto)

Crear `CLAUDE.md` en la raíz del repositorio con:
- Descripción del proyecto y mapa de dominios
- Convenciones de import (`from {dominio}.{módulo} import {símbolo}`)
- Convenciones de naming (términos de dominio en español preservados en prompts, inglés en código)
- Convenciones de testing (unit en `backend/tests/unit_tests/`, integration en `backend/tests/integration/`)
- Patrones prohibidos (no queries ORM cross-dominio, no imports directos de modelos fuera de `shared/`)
- Reglas de higiene de prompts LLM (no API keys hardcodeadas en prompts, todo contexto via state injection)

### 3.2 Auditoría de fronteras de confianza LLM

**`case_generator/prompts.py`** (2,042 líneas):
- Revisar TODOS los templates de prompts buscando input controlado por usuario que fluya directamente a system prompts sin sanitización
- Verificar que variables inyectadas ({industry}, {scenario}, etc.) no permitan prompt injection

**`tutor_engine/twin_graph.py`**:
- Auditar la variable `full_system` que concatena system prompt con `context_payload`
- Verificar que `context_payload` está scoped a los datos del módulo del estudiante actual
- Confirmar que no se puede filtrar datos de otros estudiantes ni la rúbrica del profesor

**`case_generator/graph.py`** (2,970 líneas):
- Cada nodo que usa `.with_structured_output()` debe tener fallback handler para `ValidationError`
- Revisar manejo de errores "sentinel" en nodos para prevenir cascadas de fallos

### 3.3 Type safety

1. Agregar archivos `py.typed` a todos los paquetes de dominio
2. Configurar `mypy` en `pyproject.toml` (actualmente `graph.py` línea 1 desactiva mypy con `# mypy: disable-error-code="no-untyped-def,misc"`)
3. Objetivo: remover pragma y corregir errores de tipo subyacentes
4. Asegurar que todos los métodos de servicio tengan anotaciones de tipo de retorno
5. Validar consistencia de keys de `ADAMState` (TypedDict) con lo que los nodos de `graph.py` realmente leen/escriben

### 3.4 Anotación de ownership en ORM models

En `shared/models.py`, agregar separadores claros de dominio:

```python
# --- AUTHORING PLANE (owned by: case_generator) ---
# Tenant, User, Assignment, AuthoringJob, ArtifactManifest

# --- RUNTIME PLANE (owned by: student_workspace) ---
# StudentAssignment, ModuleAttempt, GradingResult, ChatThreadIndex
```

Extracción completa de modelos a archivos de dominio diferida para evitar complejidad con migraciones Alembic.

### 3.5 Correcciones puntuales

- **Version mismatch**: `app.py` línea 69 retorna `{"service": "adam-v7"}` pero el header de `graph.py` dice "ADAM v8/v9". Unificar a `adam-v8.0` (coincide con `pyproject.toml` version `8.0.0`)
- **sys.path hack**: `app.py` línea 12 tiene `sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))`. Después de Sprint 1 con proper package discovery, esta línea debería ser eliminable. Verificar y borrar.

### Checklist Sprint 2

- [x] `CLAUDE.md` creado y comprehensivo
- [x] Templates de prompts auditados para vectores de inyección
- [x] `twin_graph.py` context leakage verificado seguro
- [x] Configuración `mypy` agregada, pragma removido de `graph.py`
- [x] Modelos ORM anotados con ownership de dominio
- [x] Version string unificada en health check y graph header
- [x] `sys.path` hack removido y verificado funcional

**Estado de cierre consolidado**:
La auditoría posterior detectó deuda bloqueante y reabrió el cierre de Sprint 2 en Sprint 2.1.
Sprint 2 queda ahora formalmente cerrado porque Sprint 2.1 ya fue ejecutado, validado en verde y dejó habilitado el arranque de Sprint 3.

---

## 4. SPRINT 2.1: PRODUCTION READINESS GATE BEFORE GITHUB & CLOUD

**Objetivo**: Cerrar la deuda bloqueante detectada después del hardening inicial y dejar el repositorio en un estado realmente apto para GitHub, CI/CD y handoff a otros desarrolladores/agentes sin ambigüedad arquitectónica. Sprint 3 queda bloqueado hasta que este sprint cierre en verde.  
**Duración estimada**: 2-4 días

**Las cinco deudas bloqueantes que este sprint DEBE cerrar son**:
- contrato `authoring -> runtime`
- hardening real de fronteras de confianza LLM
- type safety real
- suite determinista apta para CI
- documentación de onboarding para GitHub y handoff a otros developers/agentes

### 4.1 Cierre del contrato Authoring -> Runtime

**Problema detectado**: el flujo real `authoring -> runtime` no está listo para producción. El authoring persiste un blueprint transicional con placeholders, mientras que enrollment/chat/grading operan correctamente solo cuando reciben fixtures manuales más ricos en tests. Esa brecha impide un CI serio y hace que el sistema no sea autoexplicativo para terceros.

**Acciones obligatorias**:

1. **Cerrar el blueprint productivo**:
   - `AssignmentBlueprint.version` debe pasar a `adam-v8.0` para el flujo productivo
   - `transitional_metadata` NO debe emitirse desde `AuthoringService` en el path normal
   - El blueprint persistido por authoring debe ser consumible directamente por runtime sin fixtures manuales

2. **Student artifacts**:
   - `student_artifacts.narrative_text` debe contener la narrativa M1 visible al estudiante
   - `student_artifacts.eda_summary` solo debe poblarse si la ruta realmente genera EDA
   - `eda_summary` debe ser resumen acotado, NO el reporte EDA completo ni artefactos docentes

3. **Artifact manifest projection**:
   - `artifact_manifest.artifact_ids` debe poblarse con los IDs publicados del job
   - La proyección debe reflejar el estado real persistido en `ArtifactManifest`, sin arrays vacíos por defecto al cerrar jobs exitosos

4. **Module manifests productivos**:
   - `module_manifests` deja de ser placeholder
   - El MVP runtime antes de Sprint 3 expone EXACTAMENTE 1 módulo interactivo: `doc1_narrativa`
   - Ese `ModuleManifest` debe tener:
     - `module_id = "doc1_narrativa"`
     - `isolated_memory = True`
     - `allowed_context_keys = ["student_artifacts.narrative_text", "student_artifacts.eda_summary"]`
   - M2-M5 permanecen como contenido de preview/docencia, sin crear nuevos `ModuleAttempt` en este sprint

5. **Runtime fail-closed**:
   - `EnrollmentService` deja de fabricar `doc1_narrativa` por defecto
   - Si `module_manifests` viene vacío o inconsistente, enrollment debe fallar cerrado con error explícito de blueprint inválido

6. **Validation contract explícito**:
   - El blueprint emitido por authoring debe dejar:
     - `passing_threshold_global = 0.6`
     - `required_modules_passed = 1`

7. **Grading contract explícito para MVP**:
   - `grading_contract` deja de ser vacío
   - Debe emitirse un contrato mínimo para `doc1_narrativa` con rubric keys:
     - `problem_framing`
     - `evidence_use`
     - `stakeholder_reasoning`
   - El contrato debe ser suficientemente explícito para que el runtime no dependa de placeholders silenciosos

### 4.2 Cierre de fronteras de confianza LLM

**Problema detectado**: Sprint 2 documentó el riesgo pero no lo cerró completamente. Persisten flujos de datos no confiables entrando a prompts del sistema y el twin runtime sigue mezclando contexto no confiable dentro del `SystemMessage`.

**Acciones obligatorias**:

1. **Helper central de sanitización**:
   - Crear un helper compartido para datos no confiables usados en prompts y contexto de twins
   - Debe remover caracteres de control, normalizar whitespace, truncar por campo y truncar payload total
   - Debe ser reusable, testeado y quedar documentado en `CLAUDE.md`

2. **Case generator prompt inputs**:
   - `teacher_input` y `architect_output` SOLO pueden construirse mediante ese helper
   - El sprint cierra con CERO `FIXME (Security)` remanentes en:
     - `case_generator/prompts.py`
     - `case_generator/graph.py`
     - `student_workspace/core/chat.py`
     - `tutor_engine/twin_graph.py`

3. **Context scoping del twin**:
   - `ChatService` debe construir `context_payload` exclusivamente desde `allowed_context_keys`
   - `grading_contract`, `validation_contract`, datos docente-only y datos de otros intentos/estudiantes quedan fuera del conjunto elegible
   - Si un `allowed_context_key` no existe, debe omitirse sin fallback implícito a otros campos

4. **Separación de canales confiables vs no confiables**:
   - `twin_graph` debe reservar `SystemMessage` solo para instrucciones confiables del twin
   - El contexto no confiable del caso debe viajar en un mensaje separado no-system
   - El bloque contextual debe seguir delimitado como datos, no instrucciones

### 4.3 Type safety real

**Problema detectado**: `mypy` pasa hoy apoyándose en `ignore_errors = true` precisamente en módulos críticos del sistema. Eso no constituye cierre real de Sprint 2 para un entorno de producción colaborativo.

**Acciones obligatorias**:

1. Eliminar los `mypy` module-wide ignores de:
   - `case_generator.graph`
   - `case_generator.core.authoring`
   - `student_workspace.core.grading`
   - `shared.models`

2. Migrar `shared.models` a estilo SQLAlchemy 2 tipado:
   - `Mapped[...]`
   - `mapped_column`
   - relaciones tipadas consistentes

3. Asegurar anotación de retorno en todas las funciones públicas del backend

4. Prohibir nuevos ignores amplios:
   - solo se permiten ignores puntuales y justificados en línea
   - cualquier ignore residual debe explicar el porqué y la estrategia de remoción

### 4.4 Suite determinista y entrada limpia a CI

**Problema detectado**: la suite actual no es apta todavía como base de CI. Algunos tests siguen disparando authoring real o dependen de LLM/BackgroundTasks sin aislamiento suficiente.

**Acciones obligatorias**:

1. **Separar suites**:
   - `tests/test_phase1b_real.py`
   - `backend/tests/integration/test_*_smoke.py`
   - `backend/tests/integration/test_e2e_baseline.py`
   Deben marcarse como `live_llm` y saltarse salvo `RUN_LIVE_LLM_TESTS=1`

2. **Cero red en tests por defecto**:
   - Ningún test HTTP de la suite default puede disparar Gemini real
   - Los tests que cubren `/api/authoring/jobs` deben patchar `AuthoringService.run_job` o `graph.astream` explícitamente

3. **Corregir deuda de tests desfasados**:
   - Alinear tests con el nuevo contrato de blueprint productivo
   - Corregir el typo de idempotencia
   - Remover expectativas legacy incompatibles con el flujo real actual

4. **Agregar contract test productivo**:
   - Crear un test e2e stubbed de contrato:
     - create job
     - persist blueprint generado
     - enroll
     - start attempt
     - stream twin
     - submit
     - grade
   - Debe correr sin fixtures manuales de blueprint y sin red

5. **Gate de limpieza**:
   - `pytest` default debe poder correr completo sin colgarse, sin depender de API keys y sin side effects externos

### 4.5 Documentación para GitHub/onboarding

**Problema detectado**: el repositorio todavía no está listo para publicarse y ser entendido rápidamente por otros developers/agentes porque el `README.md` está vacío y la separación entre flujos productivos y live-LLM no está suficientemente documentada.

**Acciones obligatorias**:

1. Crear un `README.md` raíz no vacío con:
   - overview del proyecto
   - mapa de dominios
   - setup local
   - variables de entorno
   - matriz de tests
   - límites del MVP
   - flujo `authoring -> runtime`

2. Referenciar `CLAUDE.md` desde el `README.md`

3. Documentar qué entra en la suite default y qué queda en la suite `live_llm`

### 4.6 Higiene de runtime y compatibilidad

**Problema detectado**: persiste al menos una deprecación real del stack (`LangGraphDeprecatedSinceV10`) en el path backend por defecto. Ese tipo de warning no debe trasladarse a Sprint 3 ni contaminar CI.

**Acciones obligatorias**:

1. Reemplazar `config_schema` por la API soportada actual de LangGraph
2. El sprint cierra sin warnings deprecados en la corrida backend por defecto

### Supuestos y defaults Sprint 2.1

- El runtime MVP antes de Sprint 3 sigue teniendo un solo módulo interactivo: `doc1_narrativa`
- M2-M5 permanecen como contenido de preview/docencia y NO deben abrir nuevos `ModuleAttempt` en este sprint
- El objetivo de "sin deuda antes de Sprint 3" se interpreta como cero deuda bloqueante en contrato authoring/runtime, seguridad de contexto LLM, tipado, tests deterministas y documentación de onboarding
- Sprint 3 arranca únicamente cuando este Sprint 2.1 quede cerrado con los gates anteriores en verde

### Checklist Sprint 2.1

- [x] Blueprint productivo no transicional y operativo para runtime MVP
- [x] Fronteras LLM saneadas y sin FIXME(Security)
- [x] `mypy` passing sin ignores de módulo
- [x] `pytest` por defecto passing sin red
- [x] Suite `live_llm` separada y documentada
- [x] `README.md` y `CLAUDE.md` listos para onboarding
- [x] Sin warnings deprecados en backend

### Gate de validación Sprint 2.1

- `uv run --directory backend mypy src`
- `uv run --directory backend pytest -q -W error`
- `npm --prefix frontend run build`
- `RUN_LIVE_LLM_TESTS=1 uv run --directory backend pytest -m live_llm -q` (gate manual, no bloqueante del CI por defecto)

### Cierre ejecutado Sprint 2.1

- [x] Blueprint productivo no transicional y operativo para runtime MVP
- [x] Fronteras LLM saneadas y sin `FIXME (Security)`
- [x] `mypy` en verde sin ignores de modulo
- [x] `pytest` default en verde sin red: `34 passed, 12 skipped`
- [x] Suite `live_llm` separada por marcador y `RUN_LIVE_LLM_TESTS=1`
- [x] `README.md` y `CLAUDE.md` listos para onboarding
- [x] Backend sin warnings deprecados del path por defecto

### Estado de cierre Sprint 2.1

- Cierre tecnico backend ejecutado con blueprint productivo, tipado estricto, sanitizacion LLM y runtime fail-closed.
- `uv run --directory backend mypy src` ejecutado en verde.
- `uv run --directory backend pytest -q -W error` ejecutado en verde.
- `npm --prefix frontend run build` ejecutado en verde.
- La suite `live_llm` queda separada; su gate sigue siendo manual y no bloquea el CI por defecto.
- Sprint 2.1 queda formalmente cerrado y habilita el arranque de Sprint 3.

---

## 5. SPRINT 3: GITHUB & CLOUD READINESS

**Estado**: habilitado para ejecucion tras el cierre de Sprint 2.1.

**Objetivo**: Establecer infraestructura CI/CD, gobernanza de PRs, y preparación para deployment en producción. Actualmente NO existe directorio `.github/`.  
**Duración estimada**: 2 días

### 5.1 Estructura `.github/`

```
.github/
  workflows/
    ci.yml                        # Lint + typecheck + test en cada PR
    deploy-staging.yml            # Deploy a Cloud Run staging en merge a develop
    deploy-prod.yml               # Deploy a Cloud Run prod en release tag
  PULL_REQUEST_TEMPLATE.md
  CODEOWNERS
  dependabot.yml
```

### 5.2 Pipeline CI (`ci.yml`)

```yaml
# Triggers: pull_request a main/develop
# Jobs:
#   1. lint: ruff check + ruff format --check
#   2. typecheck: mypy backend/src/
#   3. test-unit: pytest backend/tests/unit_tests/ -v
#   4. test-integration: pytest backend/tests/integration/ -v (requiere servicio postgres)
#   5. frontend-build: npm ci && npm run build (en frontend/)
#   6. docker-build: docker build . --no-cache (verificar Dockerfile)
```

### 5.3 CODEOWNERS

```
# Domain ownership
/backend/src/case_generator/       @adam-core-team
/backend/src/harvard_parser/       @adam-core-team
/backend/src/tutor_engine/         @adam-core-team
/backend/src/student_workspace/    @adam-runtime-team
/backend/src/auth_perimeter/       @adam-security-team
/backend/src/shared/               @adam-core-team
/frontend/                         @adam-frontend-team
/.github/                          @adam-devops
```

### 5.4 Hardening de Docker para producción

1. **`.dockerignore`** - Crear archivo (no existe):
   ```
   venv/
   .venv/
   .data/
   node_modules/
   .env
   __pycache__/
   .git/
   .claude/
   *.pyc
   backend/tests/
   ```

2. **HEALTHCHECK** - Agregar al Dockerfile:
   ```dockerfile
   HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
     CMD curl -f http://localhost:8000/health || exit 1
   ```

3. **Dockerfile línea 24** - Agregar `--no-install-recommends` a `apt-get install`:
   ```dockerfile
   RUN apt-get update && apt-get install -y --no-install-recommends curl && \
   ```

### 5.5 Cloud Run + Supabase roadmap

1. **Gestión de secretos**: Reemplazar `os.getenv("GEMINI_API_KEY")` (encontrado en `twin_graph.py` y `graph.py`) con un secret provider centralizado que lea de env vars localmente y de Secret Manager en producción
2. **`database.py`**: Verificar que el code path `ENVIRONMENT=production` usa Cloud SQL Python Connector con IAM authentication (no password)
3. **`docker-compose.yml`**: Documentar que es SOLO para desarrollo local

### 5.6 Gobernanza de migraciones Alembic

Las 4 migraciones existentes son:
1. `26812dc7bf5c_initial_phase_1a_data_layer.py`
2. `6185b1d0f91e_phase4a_runtime_models.py`
3. `1571dcf87c69_phase5_canonical_output_column.py`
4. `fab7ddd36c0c_add_artifactmanifest_idempotency.py`

**Acciones**:
1. Después de Sprint 1, actualizar `alembic/env.py` para importar `Base` desde nueva ruta
2. Agregar check CI que ejecute `alembic check` para detectar drift modelo/migración
3. Documentar convención de naming en `CLAUDE.md`: `{hash}_{sprintN}_{descripcion}.py`

### Checklist Sprint 3

- [ ] `.github/workflows/ci.yml` creado y passing
- [ ] `.github/PULL_REQUEST_TEMPLATE.md` creado
- [ ] `.github/CODEOWNERS` creado
- [ ] `.github/dependabot.yml` creado
- [ ] `.dockerignore` creado
- [ ] Dockerfile HEALTHCHECK agregado
- [ ] Dockerfile env vars actualizados para nuevas rutas
- [ ] `alembic/env.py` actualizado para nuevas rutas de import
- [ ] Estrategia de secret management documentada

---

## REGISTRO DE RIESGOS

| Riesgo | Severidad | Sprint | Mitigación |
|--------|-----------|--------|------------|
| `graph.py` (2,970 líneas) resiste extracción limpia | ALTA | 1 | Mover como monolito; refactoring interno es esfuerzo separado |
| Cascada de reescritura de imports rompe tests | ALTA | 1 | Mover un dominio a la vez; ejecutar tests después de cada uno |
| `alembic/env.py` se rompe tras mover archivos | MEDIA | 1 | Actualizar import path en el mismo commit que los file moves |
| `Dockerfile` build falla tras reestructura | MEDIA | 1 | Actualizar ENV lines en el mismo PR que los file moves |
| `twin_graph.py` context leakage entre estudiantes | MEDIA | 2 | Auditar construcción de `context_payload` en `chat.py` |
| Contrato `authoring -> runtime` inconsistente bloquea publicación del repo | ALTA | 2.1 | Cerrar blueprint productivo, module manifests, grading y validation contracts |
| `mypy` passing artificial por `ignore_errors` amplios | ALTA | 2.1 | Eliminar ignores de módulo y tipar `shared.models` + runtime crítico |
| Suite default dispara LLM real o se cuelga | ALTA | 2.1 | Separar `live_llm`, stubbear authoring y exigir `pytest -q -W error` limpio |
| Sin CI = regresiones no detectadas | MEDIA | 3 | Sprint 3 intencionalmente antes de cualquier feature work nuevo |
| `docker-compose.yml` credenciales hardcoded en entorno compartido | BAJA | 0 | Parametrizar con env vars + defaults |

---

## GRAFO DE DEPENDENCIAS

```
Sprint 0 (PURGE & SECURITY)
    |
    v
Sprint 1 (SCREAMING ARCHITECTURE)
    |
    v
Sprint 2 (HARDENING)
    |
    v
Sprint 2.1 (PRODUCTION READINESS GATE)
    |
    v
Sprint 3 (GITHUB/CLOUD)
```

- Sprint 0 DEBE completarse antes de cualquier otro trabajo
- Sprint 1 DEBE completarse antes de Sprint 2 (convenciones dependen de la nueva estructura)
- Sprint 2.1 DEBE completarse antes de Sprint 3
- Sprint 3 NO debe ejecutarse en paralelo con Sprint 2.1, salvo borradores aislados de documentación sin merge

---

> **NOTA HISTORICA**: Este bloque pertenecía a la auditoría original en modo solo-lectura. Ya no aplica como instrucción operativa porque Sprint 2.1 fue ejecutado y el documento pasó a ser un plan maestro vivo con registro de cierre.

> **ACTUALIZACION POSTERIOR**: La implementacion ya ejecuto y cerro Sprint 2.1. Este documento debe leerse ahora como plan maestro vivo y registro de cierre, no como una auditoria congelada en modo solo-lectura.

## CIERRE POSTERIOR (SPRINT 0.5)

Tras la auditoría original, Sprint 0 fue completado mediante un hotfix acotado de QA/SRE que:

- corrigió el healthcheck parametrizado de Postgres en `docker-compose.yml`,
- normalizó los tests reubicados para `pytest`,
- eliminó la deuda inmediata de ejecución manual en `backend/tests/integration/` y `backend/tests/validation/`,
- y dejó el working tree limpio al cierre de los commits del hotfix.
