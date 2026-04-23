# TODOS

Deuda técnica y mejoras diferidas identificadas durante el desarrollo.

---

## TODO-004: Mover `usePublishCase` a `shared/` para eliminar import cross-feature

**What:** Extraer `usePublishCase` de `frontend/src/features/teacher-dashboard/useTeacherDashboard.ts` hacia un archivo en `shared/` (ej: `shared/usePublishCase.ts`).

**Why:** `CasePreview` (feature `case-preview`) importa `usePublishCase` desde `teacher-dashboard`, cruzando el límite de features. Si otros features necesitan publicar casos, el hook quedaría en un lugar incorrecto.

**Pros:** Limpia el grafo de dependencias entre features; sigue el principio "absolute imports by domain" de AGENTS.md.

**Cons:** Requiere tocar `useTeacherDashboard.ts` (fuera del scope de #154) y actualizar imports en todos los consumidores actuales (solo `CasePreview.tsx` y el propio dashboard).

**Context:** El import cross-feature fue aceptado explícitamente en la eng review de #154 para mantener el diff mínimo. El comentario TODO ya existe en `CasePreview.tsx` (línea ~15). Puede hacerse en cualquier PR de limpieza de arquitectura frontend.

**Depends on / blocked by:** #154 mergeado. Nada más bloquea esto.

---

## TODO-005: Inicializar `sendState` desde `TeacherCaseDetailResponse.status` para persistir estado "sent" entre remounts

**What:** En `CasePreview.tsx`, inicializar `sendState` como `"sent"` si `TeacherCaseDetailResponse.status === "published"` (u otro valor equivalente), en lugar de siempre comenzar en `"idle"`.

**Why:** Actualmente, si el docente recarga la vista de un caso ya enviado, el botón aparece de nuevo en estado `idle`, invitando a un doble envío. El backend rechazará el segundo publish, pero la UX es confusa.

**Pros:** UX consistente — el botón nunca aparece disponible para casos ya publicados; elimina el riesgo de double-submit.

**Cons:** Requiere que el componente reciba o consulte `TeacherCaseDetailResponse` (actualmente no lo recibe). Necesita coordinar el tipo de `status` con el backend (confirmar el valor exacto del campo).

**Context:** `CasePreview` solo recibe `CanonicalCaseOutput` (que no tiene `status`). Para inicializar correctamente habría que agregar un prop opcional `assignmentStatus?: string` o consultar `useCaseDetail(caseId)` dentro del componente. Decisión de diseño a tomar en el PR de implementación.

**Depends on / blocked by:** #154 mergeado. Requiere acuerdo sobre si agregar prop o usar query interna.

---

## TODO-001: Extraer `useActivationFlow` hook compartido

**What:** Crear un custom hook `useActivationFlow(flow, redirectTo)` que encapsule la lógica común entre `TeacherActivatePage` y `StudentJoinPage`: parse de hash → save context → resolveInvite → estados loading/error/resolvedInvite.

**Why:** `TeacherActivatePage` y `StudentJoinPage` comparten ~80% de la lógica de activación. Cuando se agregue un tercer flujo de activación (ej: admin o co-docente), el patrón sin hook implicaría un tercer componente con la misma lógica.

**Pros:** Elimina duplicación, punto único de corrección para bugs en el flujo de activación, tests más simples.

**Cons:** Introduce una abstracción nueva en `shared/`, aumenta el diff de la PR donde se implemente, requiere refactorizar `TeacherActivatePage` (ya mergeada).

**Context:** La decisión de NO hacer el hook en Issue #39 fue explícita (eng review Issue 7A): copiar/adaptar para minimal diff. Las diferencias reales entre los dos flujos (full_name requerido, teacher_name display, mensajes distintos) son suficientes para justificar componentes separados en el corto plazo.

**Depends on / blocked by:** Esperar a que aparezca un tercer flujo de activación para que la abstracción valga la pena. No bloquea nada ahora.

---

## TODO-002: Tests de pytest para B3 (domain validation en `activate_oauth_complete`)

**What:** Agregar casos de test en `backend/tests/test_student_activation.py` para el endpoint `POST /api/auth/activate/oauth/complete` cuando `invite.role == "student"` y hay dominios configurados en `allowed_email_domains`.

**Why:** La Tarea B3 (domain validation en OAuth complete) está implementada en `shared/app.py`, pero los tests actuales solo cubren el path password (B2). Un refactor futuro de `activate_oauth_complete` podría romper B3 silenciosamente.

**Pros:** Cierra el gap de cobertura en el segundo path de activación de estudiante. Requiere mock de `require_verified_identity` (inyectar un `VerifiedIdentity` fake con email controlado).

**Cons:** `activate_oauth_complete` usa `require_verified_identity` que lee el JWT directamente. Requiere usar el `token_factory` del conftest para generar un JWT con el email correcto. Moderadamente complejo de mockear.

**Context:** En Issue #39 eng review, el usuario eligió diferir estos tests a TODOS.md (respuesta al TODO candidato 2). El código B3 existe y está cubierto por el test de integración manual, pero no por pytest automatizado.

**Depends on / blocked by:** No bloquea nada. Puede hacerse en cualquier PR de hardening del auth perimeter.

---

## TODO-003: Propagación de `request_id` end-to-end en logs

**What:** Propagar el `request_id` generado por `structured_logging_middleware` (en `app.py`) a los logs de `shared/auth.py` y `case_generator/` para correlación end-to-end en Cloud Logging.

**Why:** Actualmente el `request_id` solo aparece en el log de request del middleware. Los logs de auth events (`audit_log`, `login_failed`, etc.) y los de `AuthoringService` no tienen correlación con el request que los originó, lo que hace el debugging en producción más difícil.

**Pros:** Permite filtrar todos los logs de un request específico en Cloud Logging con un solo query. Detecta latencias anómalas en pasos individuales. Sin esto, debuggear un 5xx en producción requiere correlacionar por timestamp.

**Cons:** Requiere `contextvars.ContextVar` para propagar sin pasar `request_id` como parámetro explícito por toda la cadena de llamadas. Toca `auth.py` (sensible) y potencialmente `case_generator/` (muy sensible). Scope mayor que un issue de infra.

**Context:** Identificado en Issue #44 (plan-eng-review TODO item 2). El middleware ya genera el `request_id` y lo guarda en `request.state.request_id`, pero ningún logger downstream lo lee. La infraestructura de JSON logging ya existe — solo falta el ContextVar bridge.

**Depends on / blocked by:** Issue #44 (completado). Puede hacerse en Issue #11 (Tests y QA gate) o como un issue independiente de observabilidad.

---

## TODO-004: PyJWKClient async para Cloud Tasks OIDC

**What:** Reemplazar la llamada síncrona `_google_jwks_client.get_signing_key_from_jwt(token)` en `shared/internal_tasks.py` con una versión async via `asyncio.get_event_loop().run_in_executor()` o una librería async equivalente.

**Why:** El endpoint `process_authoring_job_task` es `async def`. `PyJWKClient.get_signing_key_from_jwt()` hace I/O de red de forma síncrona cuando la caché expira (~1 vez cada 5 min), bloqueando el event loop durante ese tiempo (~100-200ms).

**Pros:** Elimina el bloqueo del event loop durante el fetch de JWKS. Correcto para un endpoint async con potencial concurrencia alta.

**Cons:** `PyJWKClient` no tiene API async nativa. Requiere wrapping manual con `run_in_executor` o migrar a `python-jose` / `authlib` que soportan async. Con `lifespan=300` y el worker de baja concurrencia actual, el impacto real es despreciable — el bloqueo ocurre ~1 vez cada 5 min.

**Context:** Identificado en Issue #44 (plan-eng-review TODO item 3, decisión 10A: aceptar bloqueo síncrono hoy). La misma restricción existe en `shared/auth.py` con `JwtVerifier`. Resolver ambos juntos tiene más sentido que resolver solo el worker.

**Depends on / blocked by:** Issue #44 (completado). Solo prioritario si el worker escala a alta concurrencia (>10 req/s simultáneos). Post-Fase 1.

---

## TODO-005: Rate limiting distribuido en endpoints de auth públicos

**What:** Implementar rate limiting en los 5 endpoints de auth públicos con `fastapi-limiter>=0.1.6` + `redis>=5.0` contra Cloud Memorystore:
- `POST /api/invites/resolve` → 10 req/min por IP
- `POST /api/invites/redeem` → 5 req/min por IP
- `POST /api/auth/activate/password` → 5 req/min por IP
- `POST /api/auth/activate/oauth/complete` → 10 req/min por IP
- `POST /api/auth/change-password` → 3 req/min por auth_user_id

**Why:** Sin rate limiting, los endpoints de activación e invitación son vulnerables a brute-force y enumeración de tokens. In-memory no protege nada porque `public-api` tiene `max-instances=10` — cada instancia mantiene contadores independientes, permitiendo hasta 10× el límite configurado.

**Pros:** Protección real contra brute-force en tokens de invitación y activación. Cierra el único control de seguridad operativa diferido del Plan Issue #10.

**Cons:** Requiere aprovisionar Cloud Memorystore (Redis) en el proyecto GCP — cambio de infra fuera del alcance de Issue #46. Añade `fastapi-limiter` y `redis` como dependencias de runtime.

**Context:** Identificado en Issue #46 (Plan Issue #10, plan-eng-review decisión 1A). La decisión de diferir fue explícita: no hay Redis disponible en la infra actual, y `slowapi` in-memory da falsa seguridad con max-instances=10. Ver sección "Rate Limiting Strategy" en `docs/runbooks/cloud-run-deploy.md` para los límites target y el contexto de la decisión.

**Depends on / blocked by:** Aprovisionamiento de Cloud Memorystore en el proyecto GCP, o reducción de `maxInstances` a 1 en `public-api`. No bloquea Issue #11.

---

## TODO-006: Migración total de contrato runtime a `APP_ENV`

**What:** Migrar el contrato de entorno runtime para que `APP_ENV` sea la variable única en todo el stack (código, runbooks, compose, CI y despliegue), retirando gradualmente `ENVIRONMENT`.

**Why:** Issue #110 introduce `APP_ENV` como override para aplicar guardrails de runtime sin romper compatibilidad. Mantener dos variables de entorno a largo plazo aumenta ambigüedad operativa y riesgo de configuraciones inconsistentes.

**Pros:** Contrato único y explícito para perfil runtime, menos drift documental, menor riesgo de errores de despliegue por variables cruzadas.

**Cons:** Toca múltiples superficies (docker-compose, Cloud Run env bindings, tests, `.env.example`, runbooks y validaciones), requiere coordinación de rollout para no romper entornos existentes.

**Context:** En la implementación de Issue #110 se decidió mantener `ENVIRONMENT` como canónico temporal y soportar `APP_ENV` con prioridad para minimizar riesgo inmediato. Esta deuda se registra para cerrar la dualidad una vez estabilicen los guardrails.

**Depends on / blocked by:** Plan de migración coordinado por fases, validación de todos los entornos activos y ventana de despliegue para cortar compatibilidad con `ENVIRONMENT`.

---

## TODO-007: Watchdog de progreso en frontend para fallback de stream

**What:** Implementar un watchdog en `useAuthoringJobProgress` que detecte silencio prolongado del stream (sin snapshots ni eventos realtime durante una ventana configurable) y ejecute fallback controlado: re-fetch del snapshot, reintento de suscripción y señalización explícita de estado degradado en UI.

**Why:** Aunque la PR actual mejora la rehidratación y normalización de pasos, todavía existe el riesgo de "stream zombie" cuando el canal realtime se degrada sin error hard. Sin watchdog, el usuario puede quedar viendo un progreso congelado sin feedback.

**Pros:** Mejora percepción de confiabilidad, reduce casos de estancamiento silencioso, y limita dependencia de reconexión manual (F5).

**Cons:** Añade complejidad de estado en el hook (timers + debounce + estados degradados), requiere cuidado para no generar polling excesivo ni ruido visual.

**Context:** Diferido explícitamente para mantener el scope de esta PR en contrato canónico + rehidratación. El síntoma principal (0% -> 100%) ya quedó resuelto; este ítem apunta a hardening operativo adicional.

**Depends on / blocked by:** Definir política final de timeout/retry por entorno (local/staging/prod) y métricas mínimas de reconexión aceptables.

---

## TODO-008: Pool sizing de LangGraph checkpointer para concurrencia bajo Supavisor

**What:** Evaluar y ajustar el pool sizing `(1,1)` del `AsyncConnectionPool` de LangGraph cuando corre sobre Supavisor transaction mode, para soportar 2-5 teachers concurrentes sin serialización innecesaria.

**Why:** Con `max_size=1`, jobs concurrentes de authoring compiten por la misma conexión del checkpointer. Bajo carga, esto serializa operaciones que podrían ser paralelas.

**Pros:** Desbloquea concurrencia real en authoring sin cambiar arquitectura. Mejora latencia percibida cuando múltiples teachers generan casos simultáneamente.

**Cons:** Requiere entender los límites de conexión de Supavisor y el comportamiento de transaction mode con pools más grandes. Riesgo de agotar connection slots si se sobredimensiona.

**Context:** Identificado en la revisión de eng-review de Issues #117-#120. La configuración actual en `_langgraph_checkpointer_pool_bounds()` (database.py:242-246) fue correcta para MVP single-teacher. Ver Issue #121.

**Depends on / blocked by:** Issues #118/#120 (alineación de schema y hardening de pool). Puede implementarse después o en paralelo.

---

## TODO-009: Ceremonia de upgrade de `langgraph-checkpoint-postgres`

**What:** Documentar y seguir una ceremonia explícita cada vez que se actualice la versión de `langgraph-checkpoint-postgres` en `pyproject.toml`: verificar nuevas migraciones en `MIGRATIONS`, crear migración Alembic que siembre versiones adicionales en `checkpoint_migrations`, alinear DDL nuevo con nombres de LangGraph.

**Why:** El root cause del bootstrap timeout (#117) fue la desalineación entre Alembic y el ledger de migraciones de LangGraph. Si se actualiza la dependencia sin verificar migraciones nuevas, el mismo problema puede reaparecer.

**Pros:** Previene regresión del bootstrap timeout en futuras actualizaciones. Formaliza un proceso que hoy es implícito.

**Cons:** Añade un paso manual al upgrade de dependencias. Requiere que quien actualice la dependencia conozca la estructura de `MIGRATIONS` en el paquete.

**Context:** Identificado en la revisión de eng-review de Issue #118. La ceremonia debe incluir: (1) diff de `MIGRATIONS` list, (2) nueva migración Alembic si hay versiones nuevas, (3) alineación de nombres DDL, (4) actualización del pin exacto en `pyproject.toml`.

**Depends on / blocked by:** Issue #118 (establece la línea base de alineación Alembic/LangGraph). No bloquea nada inmediato.

---

## TODO-010: Monitoreo y alertas de salud del stream de authoring

**What:** Agregar telemetría estructurada y tableros/alertas para el flujo realtime de authoring: tasa de suscripción fallida, reconexiones por job, latencia entre persistencia backend y render frontend, y porcentaje de jobs que llegan a `completed` sin eventos intermedios.

**Why:** Hoy hay logs de suscripción en frontend y resiliencia en backend, pero falta observabilidad agregada para detectar regresiones antes de que lleguen como reportes manuales.

**Pros:** Detección temprana de incidentes, baseline para SLO de progreso en tiempo real y diagnóstico más rápido de problemas de red/realtime/publicación.

**Cons:** Requiere definir pipeline de ingestión (frontend + backend), cardinalidad de etiquetas y umbrales de alerta para evitar fatiga por ruido.

**Context:** Registrado como follow-up de hardening después de estabilizar el contrato canónico de pasos y la persistencia resiliente introducidos en esta entrega.

**Depends on / blocked by:** Alineación con la estrategia de observabilidad de la plataforma (métricas, logs y alerting) y disponibilidad del destino de métricas en ambientes compartidos.

---

## TODO-011: Política de retención y purge de checkpoints LangGraph

**What:** Definir e implementar una política explícita de retención para tablas de checkpoints (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`) con purge seguro por antigüedad/estado terminal y guardrails para no borrar sesiones activas.

**Why:** La persistencia stateful de Issue #112 agrega crecimiento continuo de datos de checkpoint. Sin retención, la base acumula payloads JSONB/BYTEA y degrada costo/operación a mediano plazo.

**Pros:** Control de crecimiento de almacenamiento, mejor performance operacional, y ciclo de vida claro de datos transitorios de ejecución.

**Cons:** Requiere definir ventana de retención por entorno, estrategia de borrado incremental y observabilidad para evitar borrados agresivos.

**Context:** Reconfirmado en la corrección async de Issue #112. La decisión explícita es mantener Fase 2 enfocada en `AsyncPostgresSaver` + resume funcional y diferir la política de retención hasta que el flujo durable esté estable.

**Depends on / blocked by:** Estabilizar primero el flujo de resume con el wiring async lazy/fail-closed y acordar política de compliance para retención de trazas de ejecución.

---

## TODO-012: Recuperación de casos en estado borrador (Draft Case Recovery)

**What:** Agregar una sección "Borradores" en el dashboard del docente que liste los `Assignment` con `status='draft'` que tienen `canonical_output` generado pero no han sido publicados. Requiere un endpoint `GET /api/teacher/cases?status=draft` y una UI separada de "Casos Activos".

**Why:** Si un docente cierra el navegador después de que el caso fue generado pero antes de presionar "Enviar Caso", el borrador queda huérfano en la base de datos. La recuperación por `sessionStorage` solo funciona en la misma sesión. El usuario no tiene forma de encontrar el caso generado desde el dashboard.

**Context:** Identificado en la revisión de eng-review de Issue #149. La implementación de "Enviar Caso" (Issue #156) y el dashboard de casos activos (Issue #157) filtran explícitamente `status='published'`, lo que significa que los borradores quedan ocultos por diseño. La solución mínima viable es un endpoint filtrado por `status='draft'` + `canonical_output IS NOT NULL` y una tabla colapsable "Borradores" en el dashboard.

**Depends on / blocked by:** Issue #149 (Case Management foundation). Los endpoints y la lógica de ownership helper (`get_owned_assignment_or_404`) definidos en Issue #151 son el punto de partida natural para el endpoint de borradores.

---

## TODO-012: Utilidad de reconciliación de artefactos huérfanos legacy

**What:** Crear una utilidad operativa para reconciliar artefactos huérfanos históricos (manifest en DB vs blob en storage) y aplicar remediación controlada (marcar, limpiar o re-vincular según reglas).

**Why:** Aunque el pipeline actual maneja orphaning/publish por job, existen escenarios legacy y fallos previos donde pueden quedar inconsistencias entre DB y storage.

**Pros:** Reduce deuda de datos históricos, mejora integridad de inventario de artifacts y simplifica troubleshooting de casos antiguos.

**Cons:** Tiene riesgo de limpieza incorrecta si la heurística no es conservadora; requiere modo dry-run y auditoría de cambios.

**Context:** Reconfirmado en la revisión de corrección de Issue #112. La Fase 2 queda checkpoint-first; la reconciliación histórica sigue fuera de alcance para no mezclar cleanup legado con el fix del blocker async.

**Depends on / blocked by:** Definir criterios de reconciliación por tipo de artifact y ventana temporal, más aprobación operativa para ejecutar limpieza en ambientes compartidos después de estabilizar el resume durable.

---

## TODO-013: Política de retry budget y circuit breaker para authoring

**What:** Diseñar una política de presupuesto de reintentos por job/tenant y un circuit breaker para fallos transientes repetidos del proveedor LLM, con telemetría y mensajes de fallback consistentes.

**Why:** El estado `failed_resumable` habilita reintentos manuales, pero sin límites puede generar loops costosos de reintento y mala experiencia bajo incidentes prolongados.

**Pros:** Control de costo/estabilidad, prevención de tormentas de retry y comportamiento predecible durante degradaciones externas.

**Cons:** Requiere calibración fina por tipo de error y coordinación entre backend, UX y métricas para no bloquear reintentos legítimos.

**Context:** Reconfirmado durante la corrección async de Issue #112. La decisión explícita fue no diseñar budget/circuit breaker antes de tener baseline determinístico y `live_llm` del flujo de resume desde M4.

**Depends on / blocked by:** Baseline de métricas de fallos transientes en producción, validación del resume durable con `AsyncPostgresSaver`, y definición de política de producto sobre reintentos permitidos por usuario/curso.

---

## TODO-027: Hardening del `CASE_WRITER_PROMPT` para prohibir exhibits completos en `doc1_narrativa`

**What:** Ajustar `backend/src/case_generator/prompts.py` para que `CASE_WRITER_PROMPT` prohíba explícitamente reproducir tablas completas de `Exhibit 1`, `Exhibit 2` o `Exhibit 3` dentro de `doc1_narrativa`, limitando su uso a citas y referencias narrativas.

**Why:** El fix frontend del issue de duplicación en M1 ya evita que el preview muestre exhibits repetidos, pero el payload todavía puede contaminarse si el LLM vuelve a incrustar anexos completos dentro de la narrativa. Endurecer el prompt reduce la probabilidad de reintroducir el problema aguas arriba.

**Pros:** Refuerza el contrato semántico entre narrativa y exhibits, reduce ruido en payloads generados y baja la dependencia de guardrails correctivos en frontend.

**Cons:** Toca una superficie sensible de `backend/src/case_generator/prompts.py`, puede requerir recalibrar ejemplos/instrucciones del writer y debería validarse con suites/evals antes de aterrizarlo.

**Context:** Detectado durante el gap analysis del bug de duplicación visual de exhibits en M1 después del cambio de `sanitizeExhibitMarkdown` del issue #173. La investigación mostró que el frontend renderiza exhibits por un canal dedicado (`financialExhibit` / `operatingExhibit` / `stakeholdersExhibit`) y que la duplicación visible puede reaparecer si `doc1_narrativa` vuelve a incluir secciones `### Exhibit ...` completas. Se decidió mantener el fix actual frontend-only y registrar este hardening como follow-up separado.

**Depends on / blocked by:** Mantener verde el baseline actual del preview M1. Requiere definir el alcance de validación de prompts/evals antes de tocar `CASE_WRITER_PROMPT`.

---

## TODO-014: Lifecycle explícito para el singleton async de checkpoints

**What:** Evaluar si el singleton async lazy de `AsyncConnectionPool` + `AsyncPostgresSaver` + grafo compilado debe migrarse a ownership explícito por `lifespan` en `shared.app` y `shared.worker_app`.

**Why:** La Fase 2 de Issue #112 eligió el patrón lazy async por minimal diff. Si aparecen problemas de cleanup en shutdown, churn de event loops en tests o necesidad de teardown más predecible, conviene promover estos recursos a lifecycle explícito.

**Pros:** Cierre determinístico de recursos, menos ambigüedad en tests/multi-loop, ownership operacional más obvio.

**Cons:** Amplía scope a `shared.app` y `shared.worker_app`, añade más superficie sensible y no desbloquea el bug actual por sí mismo.

**Context:** Esta fue la alternativa 1B considerada en la revisión de corrección de Issue #112. Se rechazó para el fix inicial por preferencia de diff mínimo, pero queda capturada como hardening posterior si el patrón lazy muestra límites reales.

**Depends on / blocked by:** Observar primero el comportamiento del wiring async lazy en validación local, tests y worker real después de que el blocker quede resuelto.

---

## TODO-015: Aislamiento por worker para habilitar pytest-xdist

**What:** Diseñar aislamiento de base por worker para la suite backend, de modo que `pytest-xdist` pueda habilitarse sin compartir la misma DB entre workers.

**Why:** Issue #128 deja la suite serial determinística con `SAVEPOINT` por test, pero no resuelve paralelización. Mientras todos los workers apunten a la misma base, `xdist` sigue siendo inseguro.

**Pros:** Desbloquea paralelización real del backend, reduce tiempo de CI y elimina la restricción operativa de correr siempre en serie.

**Cons:** Requiere crear o aprovisionar una DB por worker, coordinar bootstrap de Alembic por worker y revisar tests con carve-outs (`ddl_isolation`, `shared_db_commit_visibility`). Es cambio de infraestructura de harness, no un patch chico.

**Context:** Diferido explícitamente durante Issue #128 para mantener el diff enfocado en la causa raíz de la contaminación cruzada: commits opacos, ausencia de transacción externa por test y teardown global insuficiente.

**Depends on / blocked by:** Mantener estable el harness serial con `SAVEPOINT` durante varias corridas de CI y definir estrategia de naming/bootstrap para DBs temporales por worker.

---

## TODO-016: Documentar el contrato operativo de clean-room para Authoring

**What:** Documentar el contrato operativo canonico del clean-room de Authoring: ownership de teardown, simbolos reutilizables, politica de purge de checkpoints y evidencia minima de logs para diagnostico de fugas o contencion.

**Why:** La estabilizacion de Authoring depende de una frontera precisa entre el harness de pytest, el runtime de `AuthoringService` y el lifecycle de LangGraph. Si esa frontera queda solo implícita en el codigo o en una PR, es facil reintroducir residuos de pools, tareas o checkpoints en cambios futuros.

**Pros:** Preserva el razonamiento operativo, reduce regresiones por drift entre tests y runtime, y acelera debugging cuando reaparezcan sintomas como `LockNotAvailable` o leaks de pools.

**Cons:** Añade trabajo de documentacion fuera del fix principal y exige mantener sincronizado el texto cuando cambie el contrato de cleanup.

---

## TODO-017: Consolidar tokens visuales y adapters de formularios docentes

**What:** Extraer y consolidar los tokens visuales, helpers de listas dinámicas y adapters explícitos de payload usados en la pantalla de gestión de curso docente y el authoring, una vez que ambos flujos queden respaldados por contratos reales estables.

**Why:** Issue #138 introduce una página docente nueva con estilos y adapters locales por minimal diff, mientras el authoring todavía mantiene su propio bundle visual y mocks históricos. Si #139 también aterriza sobre contratos reales, quedará una deuda clara de convergencia.

**Pros:** Reduce duplicación, baja el costo de mantenimiento de cambios visuales o contractuales y deja un lenguaje docente más consistente sin depender de mocks legados.

**Cons:** Hacerlo antes de cerrar #139 sería prematuro: aumenta el scope, fuerza abstracciones antes de tiempo y puede cristalizar un API compartido incorrecto.

**Context:** En la revisión de ingeniería de Issue #138 se decidió explícitamente mantener los estilos y adapters locales al feature para preservar minimal diff, evitar acoplar la nueva pantalla al authoring actual y no mezclar la deuda de `professorDB` con la integración fiel del contrato backend #137.

**Depends on / blocked by:** Esperar a que Issue #139 estabilice el consumo real de `course_id` y `syllabus -> modules -> units` en authoring. No bloquea el release de #138.

---

## TODO-018: Habilitar acciones docentes reales sobre access links cuando exista soporte backend

**What:** Agregar acciones reales en la vista docente para copiar o regenerar el access link del curso únicamente cuando exista un endpoint backend canónico que exponga ese contrato de forma segura.

**Why:** Issue #138 solo puede mostrar metadata (`access_link_status`, `access_link_id`, `access_link_created_at`, `join_path`). Cualquier UX que pretenda reconstruir o reutilizar un raw link a partir de esos campos sería falsa y riesgosa.

**Pros:** Cuando el backend exista, desbloqueará una UX docente completa y honesta para la gestión de acceso estudiantil desde la misma pantalla del curso.

**Cons:** Requiere trabajo coordinado de backend, permisos y UX; meterlo antes introduciría fake UX o drift contractual.

**Context:** Durante la revisión de Issue #138 se decidió explícitamente renderizar solo metadata real en la tab `Configuración` y agregar tests negativos para impedir botones de copy/regenerate sin soporte backend. Este TODO captura la necesidad futura con el contexto correcto para retomarla sin ambigüedad.

**Depends on / blocked by:** Nuevo alcance de producto y endpoint backend dedicado para exponer y/o regenerar access links de forma autorizada. No bloquea #138.

**Context:** Aceptado durante la revision de rediseño de Issue #127. El objetivo es que la solucion de clean-room sea invisible para quien escriba nuevos tests, pero explicita para quien mantenga el runtime. La documentacion debe referenciar el contrato centralizado una vez exista como superficie canonica.

**Depends on / blocked by:** Depende de cerrar primero la implementacion de Issue #127 y de fijar cuales helpers quedan como API operativa estable para clean-room y diagnostico.

## TODO-020: Endpoint docente para gestionar access link del curso

**What:** Crear un endpoint docente dedicado para visualizar o regenerar el access link vigente del curso, con auditoría y reglas explícitas de exposición del raw token.

**Why:** En Issue #137 el detalle docente devuelve solo metadata y `access_link_status`, porque el modelo actual persiste hashes y no puede reconstruir un link bruto existente de forma segura.

**Pros:** Hace accionable la pestaña Configuración sin degradar el modelo de secretos del endpoint de detalle; separa claramente lectura de estado y emisión/regeneración de links.

**Cons:** Añade una nueva superficie de escritura sensible, implica definir ownership docente, UX de one-time display y política de rotación para no filtrar tokens sin control.

**Context:** La revisión de arquitectura de Issue #137 eligió fail-closed en el detalle compuesto: no exponer raw links en `GET /api/teacher/courses/{course_id}` y dejar la gestión activa del link como follow-up deliberado.

**Depends on / blocked by:** Alineación de producto para self-service docente en la pestaña Configuración y decisión explícita sobre si la acción debe regenerar el token o solo mostrar un token recién emitido.

---

## TODO-017: Stress harness post-fix para contencion de checkpoints y churn de event loops

**What:** Evaluar un stress harness diferido que repita secuencias de bootstrap, retry, teardown y cambio de event loop para el path de checkpoints de LangGraph mas alla de `test_authoring_progress_resilience.py` y `test_phase3_status_api.py`.

**Why:** Issue #127 debe resolver la inestabilidad determinista actual con el menor diff posible. Un soak test o stress harness mas amplio puede ser valioso despues, pero mezclarlo ahora convertiria un fix de integracion Authoring en una epica de validacion de carga.

**Pros:** Captura una siguiente capa de hardening para detectar contencion intermitente, churn multi-loop y regresiones de lifecycle antes de que aparezcan en CI o staging.

**Cons:** Puede inflar scope y tiempo de mantenimiento; si se adelanta demasiado, corre el riesgo de probar comportamientos todavia no estabilizados por el fix principal.

**Context:** Aceptado como follow-up durante la revision de la nueva especificacion de Issue #127. La evidencia actual apunta a dos modulos pesados concretos; el stress harness seria una fase posterior una vez el clean-room de Authoring quede estable y reusable.

**Depends on / blocked by:** Bloqueado por la implementacion y validacion completa de Issue #127, incluyendo el contrato de clean-room, la reproduccion determinista del path de locks y tres corridas full-suite consecutivas en verde.

---

## TODO-018: Guardrail de bundle budget en CI para frontend post-Issue #130

**What:** Agregar un guardrail automatizado en CI que compare el tamano de los artefactos principales del build de frontend contra una baseline post-optimización de Issue #130 y falle o alerte cuando el bundle inicial o el chunk aislado de Plotly regresen por encima del presupuesto acordado.

**Why:** Issue #130 apunta a adelgazar el critical path del preview y aislar Plotly en un chunk dedicado. Sin un control automatizado despues del fix, futuras PRs pueden reintroducir bytes en el entry bundle o volver a acercar dependencias de case preview a rutas como login sin que nadie lo note hasta que reaparezca el warning de Vite o la degradacion en dispositivos lentos.

**Pros:** Convierte la mejora de #130 en un guardrail durable, detecta regresiones temprano en PR/CI y da una señal objetiva cuando cambie el tamano del bundle inicial o del chunk `vendor-plotly`.

**Cons:** Requiere fijar primero una baseline estable despues de implementar #130, decidir si el control debe bloquear o solo alertar, y mantener el presupuesto alineado cuando haya cambios legitimos de producto en el preview.

**Context:** Aceptado como follow-up durante la refinacion tecnica de Issue #130. La decision explicita fue no mezclar el guardrail de CI con la issue de aislamiento de Plotly para mantener #130 enfocada en el critical path y no convertirla en una iniciativa general de performance governance.

**Depends on / blocked by:** Bloqueado por la implementacion de Issue #130 y por una corrida de build post-fix que deje una baseline confiable para `index` y el chunk `vendor-plotly`. Tambien depende de decidir si el guardrail vivira en GitHub Actions, otro pipeline de CI, o una verificacion local reutilizable por ambos.

---

## TODO-021: Poblar `active_cases_count` en listado de cursos del docente

**What:** Implementar el conteo de casos activos por curso en `list_teacher_courses` (`backend/src/shared/teacher_reads.py`). Actualmente `active_cases_count` se hardcodea a `0` en `TeacherCourseItemResponse` y en `get_teacher_course_detail`.

**Why:** El dashboard del docente muestra el número de casos activos por curso. Con el valor siempre en `0`, el profesor no puede saber cuántos casos activos tiene en cada materia sin entrar a cada curso individualmente.

**Pros:** Completa la información visible en el listado de cursos; habilita UX de resumen en el dashboard sin round-trips adicionales.

**Cons:** Requiere que `Assignment` tenga una FK a `Course` (`course_id`) para que el join sea posible. Sin esa FK, cualquier implementación sería un proxy no confiable (p.ej. join por `teacher_id` + `course_id` en payload de metadata). Introducir la FK es un cambio de schema que requiere migración Alembic.

**Context:** El `TODO(#90)` en el código fue registrado explícitamente durante Issue #90 con la nota: `# TODO(#90): populate once Assignment gains course_id FK`. El campo existe en el contrato API (`TeacherCourseItemResponse.active_cases_count`) pero siempre retorna `0`. El fix de Issue #150 (null deadline) dejó expuesto que `Assignment` ya soporta `deadline=None`; el siguiente gap visible es este conteo. No bloquea ningún flujo actual.

**Depends on / blocked by:** Bloqueado por la adición de una FK `Assignment.course_id` + migración Alembic correspondiente. Ese cambio de schema debe coordinarse con el authoring job intake (`/api/authoring/jobs`) para que el `course_id` del payload se persista en la fila de `Assignment`.

---

## TODO-022: Guard en PATCH publish contra `canonical_output = null`

**What:** Antes de transicionar `status → "published"` en `PATCH /api/teacher/cases/{id}/publish`, verificar que `assignment.canonical_output is not None`. Si es `None`, lanzar 422 con `detail="cannot_publish_without_output"`.

**Why:** Un docente que presione publicar sobre un caso con generación fallida (`status="failed"`, `canonical_output=null`) obtendrá un estado `published` con contenido vacío. El preview mostrará una página en blanco sin ningún mensaje de error — fallo silencioso desde la perspectiva del usuario.

**Pros:** Previene el estado incoherente `published + canonical_output=null`. La guardia es 2 líneas y no agrega dependencias.

**Cons:** Añade una restricción de negocio en el endpoint de publicación que podría querer relajarse si en el futuro se admiten publicaciones parciales (e.g., preview con módulos incompletos).

**Context:** Identificado en la revisión de ingeniería de Issue #152. El spec de ese issue solo exige chequear `status == "published"` para el 409; el caso `canonical_output=null` quedó fuera de scope por minimal diff. El path `PATCH /publish` en `teacher_router.py` (función `patch_teacher_case_publish`) es el lugar exacto donde añadir el guard.

**Depends on / blocked by:** No bloquea nada. Puede incluirse en la PR de tests del Issue #159 o en un PR de hardening independiente.



---

## TODO-023: CI guard para aislar fallos de pool regression en frontend tests

**What:** Agregar un step en .github/workflows/ci.yml que ejecute AuthoringForm.test.tsx y TeacherCoursePage.test.tsx en aislado (itest run src/features/teacher-authoring/AuthoringForm.test.tsx src/features/teacher-course/TeacherCoursePage.test.tsx) si el full-suite falla, para distinguir regresiones de pool config de bugs reales.

**Why:** AuthoringForm.test.tsx y TeacherCoursePage.test.tsx son los tests m�s pesados (MSW + jsdom + timers extensivos). Pasaban 32/32 en isolated run pero fallaban con timeouts en el full-suite por resource contention. Con pool: "forks" + maxForks: 3 + testTimeout: 10000 el full-suite pasa, pero si alguien remueve maxForks o aumenta 	estTimeout en el futuro, la regresi�n volver�a silenciosamente.

**Pros:** Feedback r�pido y preciso cuando la causa es contenci�n de workers vs. bug real en el c�digo. Evita falsos positivos que bloqueen el merge de PRs leg�timas.

**Cons:** A�ade complejidad al workflow de CI. El step condicional requiere if: failure() en GitHub Actions, que tiene algunas limitaciones de contexto.

**Context:** Identificado en PR fix/flaky-tests-vitest-pool-config como riesgo futuro si se revierten los par�metros de pool. El fix actual (pool forks, maxForks 3, testTimeout 10s) es suficiente para el estado actual del suite (38 archivos, 276 tests). Si el suite crece significativamente, puede necesitar ajuste.

**Depends on / blocked by:** No bloquea nada. Mejora de observabilidad de CI independiente.

---

## TODO-024: Deadline-edit y re-publish UI en TeacherCaseViewPage

**What:** Añadir controles de edición de deadline (`useUpdateDeadline`) y un CTA de re-publicación (`usePublishCase`) en `frontend/src/features/teacher-authoring/TeacherCaseViewPage.tsx`.

**Why:** La página TeacherCaseViewPage (#155) es actualmente read-only. Los hooks `useUpdateDeadline` y `usePublishCase` ya existen en `useTeacherDashboard.ts` y los endpoints backend están implementados, pero la vista no expone estas acciones.

**Pros:** Permite al docente gestionar el ciclo de vida del caso (publicar, ajustar deadline) directamente desde la vista de detalle, sin tener que volver al dashboard. El backend ya soporta las operaciones.

**Cons:** Requiere diseñar la UX para deadline-edit (date picker inline vs. modal) y para re-publicación (¿permitir re-publicar un caso ya publicado?). Puede solaparse con flujos futuros del dashboard.

**Context:** Issue #155 especificó explícitamente "read-only" para mantener el diff mínimo. Los hooks existen desde PR #166. La página actual pasa `isAlreadyPublished={data.status === "published"}` para suprimir el botón de envío en `CasePreview`, pero no expone ningún CTA de gestión propio. El punto de partida es `TeacherCaseViewPage.tsx` tras el merge de #155.

**Depends on / blocked by:** Merge de Issue #155. Requiere decisión de producto sobre si el re-publish desde la vista de detalle está en scope.

---

## TODO-025: Exponer `available_from` en el endpoint de lista de casos del docente [RESUELTO por #175]

**Status:** Cerrado por el fix de la Issue #175. `GET /api/teacher/cases` ya expone `available_from` en el contrato de lista, alineado con `TeacherCaseItem` en frontend y con el pre-fill de `DeadlineEditModal`.

**What:** Agregar el campo `available_from` a la respuesta del endpoint `GET /api/teacher/cases`, de forma que `TeacherCaseItem` lo incluya en el payload de lista.

**Why:** `DeadlineEditModal` (Issue #158) pre-rellena el input "Disponible desde" con `caseItem.available_from`. Actualmente el endpoint de lista no devuelve ese campo — solo `TeacherCaseDetailResponse` lo incluye. Sin este campo en la lista, el modal siempre abre el input de disponibilidad vacío y el docente debe introducir la fecha manualmente aunque ya estuviera configurada.

**Pros:** UX coherente: el modal muestra el valor actual en lugar de campo vacío. Alineación entre vista de lista y vista de detalle para el mismo campo. No requiere un fetch adicional del caso específico antes de abrir el modal.

**Cons:** Cambio de backend en el serializador de la respuesta de lista. Requiere alinear el schema Pydantic de `TeacherCaseItem` en el backend con el tipo TypeScript del frontend. Necesita test de endpoint para verificar que `available_from` aparece en la lista.

**Context:** Registrado en la eng review de Issue #158. La decisión explícita fue no tocar el backend en esa issue y aceptar el pre-fill vacío como comportamiento degradado aceptable. El campo ya existe en la tabla `assignments` y en `TeacherCaseDetailResponse`; solo falta exponerlo en la query/serializer de lista.

**Depends on / blocked by:** Issue #158 mergeado. Alineación con el tipo `TeacherCaseItem` en `adam-types.ts` (campo ya agregado como opcional en #158).

---

## TODO-026: Manejo explícito de error de `db.commit()` en PATCH /cases/{id}/deadline y PATCH /cases/{id}/publish

**What:** Envolver los `db.commit()` en `patch_teacher_case_deadline` y `patch_teacher_case_publish` (en `backend/src/shared/teacher_router.py`) en un bloque `try/except` que eleve un 500 explícito cuando el commit falla.

**Why:** Si `db.commit()` lanza una excepción (por ejemplo, tras un reset de conexión bajo Supavisor transaction mode), el endpoint actualmente puede devolver 200 con datos pre-mutación porque el `db.refresh()` lee desde el rollback. El resultado es un 200 silencioso con stale data — el llamante cree que la mutación fue exitosa.

**Pros:** Convierte un fallo silencioso en un error observable. El frontend puede distinguir entre éxito real y fallo de persistencia y mostrar un mensaje claro al docente.

**Cons:** SQLAlchemy típicamente lanza en `commit()` antes de que el control regrese al handler, por lo que en la práctica este escenario es raro. El wrapping añade boilerplate al handler.

**Context:** Identificado como critical gap en la revisión de failure modes de Issue #159. El test harness (SAVEPOINT + outer transaction) oculta este escenario en pruebas. Afecta a ambos endpoints de mutación en `teacher_router.py`. Sin el wrap, la cobertura de fallo es: sin test, sin handler, fallo silencioso.

**Depends on / blocked by:** Nada. Puede implementarse en cualquier PR de hardening de los endpoints de caso docente.

