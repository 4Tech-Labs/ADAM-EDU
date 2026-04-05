# TODOS

Deuda técnica y mejoras diferidas identificadas durante el desarrollo.

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
