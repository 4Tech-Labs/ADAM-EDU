# TODOS

Deuda técnica y mejoras diferidas identificadas durante el desarrollo.

---

## TODO-NORM-A: Actualizar RENAME_MAP en _normalize_ml_ds_columns para el schema de 18 columnas

**What:** En `_normalize_ml_ds_columns()` en `backend/src/case_generator/graph.py` (~línea 1930),
la entrada `"feature_adoption_pct" → ("categoria", "str")` del `RENAME_MAP` quedó obsoleta
tras la especialización del prompt de clasificación. Si el LLM ignora parcialmente el nuevo
prompt y emite `feature_adoption_pct`, la función lo renombra a `categoria` con `type="str"`
y borra la `dependency` — deshaciendo silenciosamente la corrección del target binario.

**Why:** Cierra el último camino de corrupción silenciosa del tipo de `categoria`. Después de
este TODO, una respuesta LLM no conforme con el nuevo prompt ya no puede producir un target
de texto sin señal a través de la vía de legado.

**Pros:** Elimina la posibilidad de que una respuesta LLM parcialmente incumplidora resulte
en AUC ~0.50 en el notebook M3, incluso tras el rename de seguridad.

**Cons:** Requiere decidir si `feature_adoption_pct` se mapea a `("categoria", "int")` con
una dependencia stub en `churn_rate`, o si simplemente se descarta. La opción más segura es:
si aparece `feature_adoption_pct`, renombrar a `categoria` Y forzar `type="int"`,
`range_min=0`, `range_max=1`, `dependency={"depends_on": "churn_rate", "relationship": "linear", "noise_factor": 0.30}`.

**Context:** Ver `_normalize_ml_ds_columns()` en `graph.py`. La función corre después de
validación Pydantic como red de seguridad post-LLM. La entrada `feature_adoption_pct` del
RENAME_MAP fue añadida cuando el prompt genérico permitía ese nombre de columna. Tras este
PR, el prompt de clasificación emite `categoria: int` directamente, por lo que este camino
no debería activarse en operación normal. Sin embargo, permanece como trampa para replays
de `task_payload` legacy y para LLMs con respuestas parcialmente no conformes.

**Depends on / blocked by:** PR de especialización del dataset de clasificación (M2) ya mergeado.

---

## TODO-CONFUSION-MULTICLASS: Extender confusion_matrix a casos multiclase

**What:** La sección `# === SECTION:confusion_matrix ===` que se agrega en Issue #246 está
protegida detrás de `if not is_binary or not can_model_binary: ...` — es decir, solo se
ejecuta para clasificación binaria. Los casos multiclase (3+ clases) omiten la sección por
completo con un `print(f"Bloque omitido: {modeling_skip_reason}")`.

**Why:** La `ConfusionMatrixDisplay` es especialmente informativa en multiclase (matriz N×N
con tasas de confusión entre clases). La restricción binaria actual cubre ~90% del catálogo
Harvard ml_ds pero deja un gap pedagógico real para datasets como clasificación de tipos de
crédito o segmentación de productos con 3+ categorías de respuesta.

**Pros:** Elimina el mensaje de `Bloque omitido` para alumnos que trabajen con targets
multiclase; los gráficos N×N normalizados por fila son didácticamente valiosos.

**Cons:** Requiere redeseñar `comparison_table` y `cost_matrix` para multiclase (actualmente
también binarias). La `cost_matrix` usa un sweep de thresholds que solo tiene sentido con
probabilidades de clase positiva — en multiclase no hay un threshold único.

**Context:** Esto NO se puede resolver solo en `confusion_matrix`: `cost_matrix` necesita ser
rediseñada primero para multiclase, porque el notebook quedaría incoherente si se muestra
una matriz multiclase pero la cost_matrix sigue asumiendo binario. La restricción actual es
la posición correcta hasta que `cost_matrix` tenga un modo multiclase explícito.

**Depends on / blocked by:** Rediseño de `cost_matrix` para multiclase (no existe aún).
Una vez desbloqueado, quitar el guard `if not is_binary` en `confusion_matrix` y añadir
`normalize="true"` para matrices N×N.

---

## TODO-M2-B: Añadir dispatch de dataset para la familia regresión

**What:** Crear `backend/src/case_generator/prompts/regresion/dataset.py` con
`SCHEMA_DESIGNER_PROMPT_REGRESSION` y extender `SCHEMA_DESIGNER_PROMPT_BY_FAMILY`
con la clave `"regresion"`.

**Why:** Completa el patrón de separación por familia para regresión (target continuo,
features numéricas correladas, sin columna de clase). Sigue el mismo patrón de 5 pasos
establecido en `feat/m2-dataset-family-dispatch` para clasificación.

**Pros:** Habilita especialización futura del schema de regresión sin afectar otras
familias; la carpeta `prompts/regresion/` no existe aún — este TODO la crea.

**Cons:** Requiere crear la carpeta, el módulo y el `__init__.py` de regresión antes
de poder especializar el prompt. La estructura es idéntica a la de clasificación.

**Context:** El dispatch en `schema_designer()` ya usa `.get(primary_family, SCHEMA_DESIGNER_PROMPT)`
como fallback, por lo que la ausencia de la clave `"regresion"` no rompe nada hoy.
Cuando se cree el prompt, sólo hay que añadir la clave al dict en `prompts/__init__.py`.
Ver `prompts/clasificacion/dataset.py` como template exacto.

**Depends on / blocked by:** Independiente — puede hacerse sin bloqueantes.

---

## TODO-M2-C: Añadir dispatch de dataset para la familia clustering

**What:** Crear `backend/src/case_generator/prompts/clustering/dataset.py` con
`SCHEMA_DESIGNER_PROMPT_CLUSTERING` y extender `SCHEMA_DESIGNER_PROMPT_BY_FAMILY`
con la clave `"clustering"`.

**Why:** Completa la cobertura de las 3 familias activas del catálogo (clasificacion,
regresion, clustering). Clustering no tiene target column — el prompt debe reforzar
eso explícitamente para evitar que el LLM genere una columna `label` o `categoria`.

**Pros:** Cierra la brecha de calidad de dataset para jobs de clustering (K-Means);
elimina el riesgo de que el prompt genérico genere un target innecesario.

**Cons:** Mismos que TODO-M2-B. Tercera iteración del mismo patrón — bajo riesgo.

**Context:** `serie_temporal` está retirada del catálogo activo y no necesita un
prompt especializado en este ciclo. Cuando clustering esté hecho, las 3 familias
activas tendrán su propio prompt de dataset, completando la arquitectura de dispatch.

**Depends on / blocked by:** TODO-M2-B (regresion) y branch `feat/m2-dataset-family-dispatch`
mergeado.

---

## TODO-244-A: Test unitario React para badge `learning_type` en `AlgorithmSelector`

**What:** Agregar un test Vitest + React Testing Library que renderice `AlgorithmSelector` con un catálogo mockeado y verifique que el badge "Supervisado" / "No Supervisado" se renderiza correctamente según el campo `learning_type` de cada ítem.

**Why:** El componente `AlgorithmSelector` no tiene tests unitarios de componente. La badge se valida actualmente sólo de forma end-to-end implícita (frontend build + lint).

**Scope:** Crear `frontend/src/features/teacher-authoring/AlgorithmSelector.test.tsx` con al menos 2 assertions: badge "Supervisado" para `Logistic Regression`, badge "No Supervisado" para `K-Means`.

**Blocked by:** Setup de Vitest + RTL para el componente (actualmente no existe test file). No bloquea el rollout del feature.

---

## TODO-M5-A: Evaluar contrato dedicado `m5Memo` para memorándum final

**What:** Evaluar si M5 debe evolucionar desde el contrato compatible actual `m5Questions[0]` / `m5QuestionsSolutions[0]` hacia un artefacto explícito `m5Memo` con UI y grading propios.

**Why:** El cambio actual mantiene el contrato de preguntas para minimizar riesgo de despliegue y compatibilidad con casos históricos. Si el memorándum final se vuelve una experiencia de evaluación distinta, un contrato dedicado podría expresar mejor el dominio.

**Pros:** Permitiría una UI de memo más rica, validaciones semánticas específicas y un flujo de calificación diseñado para documentos ejecutivos largos en vez de tarjetas de pregunta.

**Cons:** Requiere migración o compatibilidad dual, tocar backend output adapters, sanitización, student runtime, teacher submission detail y frontend preview. Aumenta la superficie de QA.

**Context:** La implementación de M5 memo en este PR conserva `m5_questions` como lista de longitud 1 porque `frontend_output_adapter`, sanitizers, student/teacher reads y `renderPreguntas` ya soportan ese shape. Empezar por `m5_questions_generator`, `frontend_output_adapter`, `M5ExecutiveReport` y los fallbacks de teacher submission detail.

**Depends on / blocked by:** Decisión de producto de que el memo final necesita UI/grading distinto al flujo actual de preguntas. No bloquea el rollout de M5 como una sola consigna tipo memo.

---

## TODO-M5-B: Suite eval/golden para calidad del memorándum M5

**What:** Diseñar una suite de evaluación para el prompt de M5 memo en casos `business`, `ml_ds + clasificacion` y al menos un caso sin M2/M3 ejecutado.

**Why:** Los tests determinísticos protegen schema, copy y no filtrado de soluciones, pero no juzgan si el memorándum generado toma una decisión fuerte, usa evidencia real, responde al riesgo principal y mantiene calidad pedagógica.

**Pros:** Daría una señal de calidad antes de futuros cambios de prompt; ayudaría a comparar baselines y evitar regresiones sutiles de coherencia ejecutiva.

**Cons:** Requiere fixtures, criterios de scoring y mantenimiento de baselines. Si usa live LLM, añade costo, latencia y potencial flakiness.

**Context:** El prompt M5 ahora pide una consigna única de memorándum y una `solucion_esperada` modelo con decisión, evidencia, riesgo, implementación y criterio académico. La suite debería verificar que no invente cifras, no reintroduzca rúbricas ni términos que disparen falsos positivos conocidos del grounding narrativo.

**Depends on / blocked by:** Definir harness de eval/golden estable y confirmar si la suite será puramente fixture-based o marcada como `live_llm` opt-in.

---

## TODO-HYGIENE-A: Sanitizador post-generación de referencias de tickets

**What:** Añadir un guard de runtime en los nodos de `graph.py` que procesan la salida
del LLM para M2 (EDA narrative) y M3 (notebook content): después de recibir el texto
del modelo, aplicar `re.sub(r"\(Issue #\d+[^)]*\)", "", text)` como paso de limpieza
antes de persistir en el estado del job.

**Why:** Los prompts ya están limpios (fix en rama `fix/strip-issue-refs-from-prompts`),
pero los LLMs tienen memoria: un modelo puede haber sido entrenado con contenido interno
o puede alucinar etiquetas del estilo `(Issue #XXX)` espontáneamente si ve patrones
similares en el prompt. El sanitizador garantiza que ninguna referencia de ese tipo
llegue jamás al output visible por docentes o estudiantes, incluso en ese escenario.

**Scope:** ~10–15 líneas en los nodos relevantes de `graph.py`. Aplicar después del
`_validate_notebook_family_consistency` / grounding checks. Sin afectar sentinelas
(`# === SECTION:... ===`) ni la lógica de reprompt.

**Pros:** Defensa en profundidad. Cierra el riesgo de regresión aunque el LLM alucine
las etiquetas sin haberlas visto en el prompt.

**Cons:** Regex post-proceso añade una pasada sobre el texto generado (muy bajo costo).
Debe aplicarse ANTES de la validación de grounding narrativo para no interactuar con ella.

**Context:** El PR `fix/strip-issue-refs-from-prompts` elimina las referencias de los
prompts (causa raíz). Este TODO es la capa de defensa adicional runtime. Se puede
implementar de forma independiente en un PR posterior de bajo riesgo.

**Depends on / blocked by:** PR `fix/strip-issue-refs-from-prompts` mergeado.

---

## TODO-243-A: Excepción estrecha para umbrales prospectivos en grounding narrativo

**What:** Evaluar si `validate_narrative_grounding` debe permitir números técnicos dentro de contextos explícitamente prospectivos, como "Condición mínima de éxito", "target futuro" o recomendaciones de monitoreo, sin tratarlos como métricas ejecutadas del notebook.

**Why:** El hotfix de M4 evita pedir umbrales numéricos aspiracionales en el prompt, pero a largo plazo podría ser pedagógicamente útil permitir cortes futuros controlados (por ejemplo, un umbral de deploy) sin fallar la generación del caso.

**Pros:** Permitiría recomendaciones de producción más específicas cuando el equipo quiera umbrales técnicos explícitos; reduce dependencia de que el LLM siempre reformule en lenguaje cualitativo.

**Cons:** Una excepción amplia podría ocultar métricas de modelo inventadas y debilitar el guardrail de Issue #243. Requiere regex/contexto muy estrecho y pruebas negativas fuertes para que `El AUC fue 87%` siga fallando si no está anclado.

**Context:** El fallo de producción vino de M4 `ml_ds + clasificacion`: el prompt pedía una condición mínima de éxito y Gemini emitió `AUC de 0.70`; el validador lo rechazó como `UNANCHORED` porque no estaba en `m3_metrics_summary`. La corrección inmediata cambió el prompt para pedir una condición cualitativa o anclada, dejando intacto el validador.

**Depends on / blocked by:** Telemetría de M4 después del hotfix y plan-eng-review dedicado si se decide relajar el validador.

---

## TODO-239-A: Two-pass M3-content grounding con métricas ejecutadas

**What:** Evaluar un rediseño two-pass donde M3-content pueda recibir métricas ejecutadas del notebook, no solo M4/M5.

**Why:** Issue #239 ejecuta el notebook después de `m3_content_generator` porque el notebook depende del contenido M3. M4/M5 ya pueden usar `m3_metrics_summary`, pero M3-content necesitaría una segunda pasada o un grafo distinto.

**Pros:** M3-content también podría citar resultados reales del experimento y cerrar completamente el ciclo narrativo-ejecutable.

**Cons:** Rompe la simplicidad actual del flujo M3 y puede duplicar llamadas LLM; requiere plan de arquitectura dedicado.

**Context:** El orden actual queda `m3_content_generator -> m3_notebook_generator -> m3_notebook_executor -> m3_sync`. Cambiarlo para retroalimentar M3-content debe evitar ciclos implícitos y métricas inventadas.

**Depends on / blocked by:** Issue #239 estabilizado en producción y métricas ejecutadas confiables.

---

## TODO-239-B: Ejecución y métricas para familias no-clasificación

**What:** Extender ejecución/parseo de notebooks a `regresion`, `clustering` y `serie_temporal`, con schemas de métricas específicos por familia.

**Why:** Issue #239 limita ejecución real a `ml_ds + clasificacion` para no romper contratos de prompts ni validar métricas incorrectas en familias con semánticas distintas.

**Pros:** Grounding narrativo real para todos los perfiles técnicos; QA ejecutable más amplio.

**Cons:** Requiere diseñar métricas, sentinelas y gates por familia sin reintroducir el prompt monolítico.

**Context:** El dispatcher M3 ya es per-family. La extensión debe mantener `PROMPT_BY_FAMILY` con 4 familias canónicas y no añadir `{computed_metrics_block}` a business.

**Depends on / blocked by:** Telemetría de Issue #239 y plan-eng-review específico para métricas no-clasificación.

---

## TODO-239-C: Aislamiento OS/proceso más fuerte para notebooks ejecutados

**What:** Evaluar una capa de aislamiento adicional para el runner de notebooks: límites de memoria/proceso, bloqueo de red a nivel OS/container o ejecución en worker dedicado.

**Why:** Issue #239 usa subprocess, entorno mínimo, `-I`, `TemporaryDirectory`, AST scrub y timeouts. Eso es suficiente para el MVP, pero no equivale a sandbox OS completo.

**Pros:** Reduce riesgo residual ante código generado inesperado y mejora postura de producción a escala.

**Cons:** Cambia despliegue/infra y puede afectar latencia/costo; requiere ADR si modifica arquitectura operativa.

**Context:** No introducir colas/orquestadores nuevos ni fanout manual sin ADR. Cualquier cambio debe respetar Supabase Realtime como infraestructura de progreso.

**Depends on / blocked by:** Métricas de operación de Issue #239 y definición de presupuesto de latencia/costo.

---

## TODO-230-A: Curar `challenger` para perfil `business` en `ALGORITHM_CATALOG`

**What:** Hoy `get_algorithm_catalog("business", "harvard_with_eda")` devuelve solo baselines (4 entradas: 1 por familia). El frontend ya degrada el toggle "2 algoritmos" cuando esto pasa, pero el contrato ideal es exponer al menos 1-2 challengers seguros para business (p. ej. `Random Forest interpretable + SHAP`).

**Why:** Permitir el modo contraste también en cursos de negocio sin forzar perfil `ml_ds`.

**Pros:** Mejora la cobertura del modo contrast; mantiene el catálogo corto y curado.

**Cons:** Cambio de catálogo afecta UX inmediatamente; requiere consenso pedagógico.

**Context:** Issue #233 (`ALGORITHM_CATALOG` 4×2) preserva la decisión de #230 de mantener business solo con baselines. La curación de challengers para business se puede hacer en cualquier PR posterior tocando solo `ALGORITHM_CATALOG` (campo `profile_visibility`) y los tests asociados.

---

## TODO-230-B: Consumir `algorithm_mode == "contrast"` en narrativa M3 (`m3_content_generator`)

**What:** Cuando `task_payload["algorithm_mode"] == "contrast"` y `len(algoritmos) == 2`, la narrativa de M3 debe comparar explícitamente baseline vs challenger (trade-off, métricas, interpretabilidad). El notebook M3 ya tiene routing de variantes separado; este TODO es solo para `m3_content_generator` y textos narrativos.

**Why:** Hoy el grafo solo recibe `algoritmos: list[str]` y los prompts no diferencian. Para entregar el "deep contrast" prometido en la UI, M3 necesita branching consciente del modo.

**Pros:** Cierra el ciclo del feature #230; entrega el valor pedagógico real al docente.

**Cons:** Toca `case_generator/graph.py` y prompts sensibles → requiere review eng + diseño.

**Context:** El payload ya viaja con `algorithm_mode` y el notebook de clasificación lo consume para elegir `lr_only`, `rf_only` o `lr_rf_contrast`. Crear como issue separada con plan de prompts contrast-aware para narrativa.

---

## TODO-230-D: Hacer mode-aware la narrativa de clasificación single

**What:** Ajustar los prompts/ensamble narrativos de M3/M4/M5 para que `algorithm_mode == "single"` y un único algoritmo de clasificación no emitan narrativa de contraste LR baseline / RF challenger ni secciones como "Por qué RF challenger".

**Why:** El notebook M3 ya enruta variantes `lr_only`, `rf_only` y `lr_rf_contrast`, pero los textos narrativos de M3/M4/M5 aún pueden contener lenguaje de contraste heredado.

**Pros:** Alinea el contenido generado con la intención del docente y evita ruido pedagógico cuando el caso pide foco en un solo algoritmo.

**Cons:** Requiere tocar lógica/prompt assembly sensible y validar grounding narrativo sin debilitar Issue #243. Debe hacerse en PR dedicado con review de `graph.py`.

**Context:** Issue #230 notebook variants ya cubre el notebook M3 y mantiene el prompt público de clasificación como contraste por compatibilidad. Este TODO queda para el contenido visible de M3/M4/M5.

---

## TODO-230-E: Suite eval/golden para notebooks de clasificación por variante

**What:** Diseñar una suite de evaluación/golden para comparar salidas reales de notebook `lr_only`, `rf_only` y `lr_rf_contrast` con criterios de calidad pedagógica, runtime y ausencia de fugas del modelo no seleccionado.

**Why:** Los tests determinísticos protegen exports, sentinelas, chart budget, scrubber y validator, pero no juzgan si el notebook generado por LLM mantiene buen razonamiento, celdas ejecutables completas y explicaciones útiles para distintos datasets.

**Pros:** Daría una señal fuerte antes de futuros cambios de prompt; permitiría detectar regresiones sutiles en single-mode sin depender solo de unit tests estructurales.

**Cons:** Requiere fixtures estables, criterios de scoring y mantenimiento de baselines. Si usa live LLM, debe quedar marcado como `live_llm` opt-in por costo y flakiness.

**Context:** Issue #230 introduce builders determinísticos desde el prompt legacy y routing en `m3_notebook_generator`. La eval debe cubrir al menos Logistic Regression single, Random Forest single y contraste LR/RF sobre un contrato de dataset binario pequeño y otro con edge cases de clases raras.

---

## TODO-230-C: Deprecar `SuggestResponse.suggestedTechniques` cuando todos los consumidores migren a `algorithmPrimary` / `algorithmChallenger`

**What:** Mantener el campo `suggestedTechniques` como espejo legacy mientras dura la transición; planificar su remoción una vez que todos los consumidores (frontend + tooling externo) hayan migrado a los campos canónicos `algorithmPrimary` y `algorithmChallenger` introducidos por #230.

**Why:** Evitar dos fuentes de verdad para la sugerencia de algoritmos.

**Pros:** Limpia la API pública de `/api/suggest`.

**Cons:** Requiere coordinación si el endpoint es llamado fuera del frontend del repo.

**Context:** El frontend ya usa los campos canónicos; el espejo se conserva por compat de tests y posibles consumidores externos no auditados.

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

## TODO-M5-clasificacion-A: Mover `M5_PROMPT_CLASSIFICATION` a subcarpeta `M5_clasificacion/`

**What:** Crear `backend/src/case_generator/prompts/clasificacion/M5_clasificacion/__init__.py`, `narrative.py`, `questions.py` y `charts.py` siguiendo el patrón de `M4_clasificacion/`. Mover `M5_PROMPT_CLASSIFICATION` desde `clasificacion/narrative.py` hacia `M5_clasificacion/narrative.py`. Mantener alias backward-compat `M5_PROMPT_CLASSIFICATION` en `clasificacion/narrative.py`.

**Why:** El PR `feat/m4-clasificacion-prompt-subfolder` establece el patrón de subcarpetas por módulo para la familia clasificación. `M5_PROMPT_CLASSIFICATION` es actualmente el único prompt de clasificación M5 que vive en `clasificacion/narrative.py` sin su propia subcarpeta. Moverlo completa el patrón y prepara el terreno para prompts M5 de questions/charts separados por familia.

**Pros:** Consistencia de arquitectura con M1/M2/M3/M4; facilita añadir `M5_QUESTIONS_PROMPT_CLASSIFICATION` y `M5_CHART_PROMPT_CLASSIFICATION` en el futuro sin tocar archivos de nivel superior; mantiene `clasificacion/narrative.py` como coordinador liviano.

**Cons:** Requiere tocar `clasificacion/narrative.py`, `clasificacion/__init__.py`, `prompts/__init__.py` y actualizar imports. Bajo riesgo si se sigue el mismo patrón quirúrgico de este PR.

**Context:** El stub `# TODO(M5_clasificacion): M5_PROMPT_CLASSIFICATION moves to M5_clasificacion/ in next PR.` ya existe en `clasificacion/narrative.py` como recordatorio explícito. Este TODO no bloquea ningún feature activo — `M5_PROMPT_CLASSIFICATION` ya funciona en su ubicación actual.

**Depends on / blocked by:** PR `feat/m4-clasificacion-prompt-subfolder` mergeado en main.

---

## TODO-M4-clasificacion-B: Evaluar variantes lr_only/rf_only/contrast para prompts M4 questions/charts

**What:** Después de despliegue en staging, evaluar si el único `M4_QUESTIONS_PROMPT_CLASSIFICATION` y `M4_CHART_PROMPT_CLASSIFICATION` es suficiente para todos los valores de `algorithm_mode` (`single`/`contrast`), o si se necesitan variantes dedicadas similares al patrón `M3_CLASSIFICATION_QUESTIONS_BY_VARIANT` (`lr_only`, `rf_only`, `lr_rf_contrast`).

**Why:** M4 questions/charts reciben `algorithm_mode` como placeholder pero el prompt actual no tiene branching explícito por variante — el LLM debe inferir el comportamiento correcto. Si la calidad pedagógica difiere materialmente entre modes (especialmente en el gráfico de escenarios del Tornado), puede valer la pena introducir variantes.

**Scope:** Revisar outputs generados en staging para al menos 3 casos: `clasificacion + lr_only`, `clasificacion + rf_only`, `clasificacion + lr_rf_contrast`. Si la calidad es aceptable en los 3, este TODO se cierra como no necesario. Si hay regresión en uno o más, crear `M4_clasificacion/questions_by_variant.py` y `M4_clasificacion/charts_by_variant.py` siguiendo el patrón de `M3_clasificacion/`.

**Pros:** Evita over-engineering si el prompt actual es suficiente; si no lo es, el patrón de dispatch por variante ya está establecido en M3 y es directo de replicar.

**Cons:** Añade 2 dicts de variantes y más superficie de test si se decide implementar. Requiere eval con LLM real (no solo tests determinísticos).

**Context:** El `m4_chart_generator` ya usa `_extract_state_algorithm_mode(state)` y pasa `algorithm_mode` al prompt. El Tornado chart en `M4_CHART_PROMPT_CLASSIFICATION` tiene una nota `(adapta el eje si es single-mode vs contrast)` para guiar al LLM, pero sin branching duro.

**Depends on / blocked by:** PR `feat/m4-clasificacion-prompt-subfolder` mergeado en main y al menos 1 semana de telemetría de jobs M4-clasificacion en staging.

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

---

## TODO-ADR0002-A: Suite de evaluación offline para coherencia escenario↔familia

**What:** Construir un eval set de N (target ~200) prompts sintéticos por familia (`clasificacion` / `regresion` / `clustering` / `serie_temporal`) y medir la tasa con la que el LLM genera un escenario cuyo `problemType` coincide con la familia anclada.

**Why:** ADR 0002 ancla el escenario al algoritmo vía prompt + coherence-check post-LLM. Sin un eval suite no hay forma defendible de saber si refuerzos del prompt mejoran o regresan la coherencia. Hoy solo tenemos un live LLM smoke test (Prophet→serie_temporal) bajo `RUN_LIVE_LLM_TESTS=1`.

**Context:** Ver `docs/adr/0002-suggest-scenario-anchored-by-algorithm.md`. Reusar el mock pattern de `backend/tests/test_suggest_scenario_anchor.py::_patch_llm` y exponer una métrica agregada en el reporte del eval. Considerar correr el eval en CI nightly, no por PR.

---

## TODO-ADR0002-B: Telemetría de `coherenceWarning` y de banner stale

**What:** Emitir métricas (counter + tasa por familia) cuando `SuggestResponse.coherenceWarning` se activa en producción y cuando el frontend renderiza el `ScenarioStaleBanner` variant `stale`. Threshold inicial sugerido: alerta si la tasa de warning supera ~5% en una familia durante 7 días.

**Why:** Sin telemetría no podemos saber si el LLM ignora el anchor en producción ni si los profesores realmente cambian el algoritmo después de generar el escenario (señal de UX para refinar el orden o agregar un confirm step).

**Context:** El campo `coherenceWarning` ya viaja en el contrato de respuesta. Falta wiring de telemetría server-side (endpoint protegido o log estructurado) y client-side (event al render del banner). No bloquea el ship de ADR 0002.


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

## TODO-014: Paginación o virtualización para el listado docente de entregas por caso

**What:** Evaluar y aplicar paginación server-side o virtualización de filas en la vista docente `GET /api/teacher/cases/{assignment_id}/submissions` y su tabla en frontend cuando el volumen por caso crezca más allá del rango cómodo del render actual.

**Why:** La implementación de Issue #210 entrega el listado completo en una sola respuesta y lo renderiza íntegro en el cliente. Eso mantiene el diff mínimo y cubre el caso actual, pero en cursos grandes puede degradar tiempo de respuesta, costo de serialización y rendimiento del DOM.

**Pros:** Mejor escalabilidad para cursos grandes, menor costo de render en frontend y un contrato más explícito para navegación incremental del docente.

**Cons:** Añade complejidad de contrato compartido (cursor o page params), estados extra en TanStack Query y decisiones de UX sobre búsqueda local vs remota, ordenamiento y preservación de filtros.

**Context:** Diferido explícitamente durante la implementación de Issue #210 para cerrar primero la vista read-only con el contrato mínimo reutilizando la capa de gradebook de Issue #205. Antes de implementarlo conviene medir tamaños reales por curso y decidir si basta con virtualización en frontend o si hace falta paginación backend.

**Depends on / blocked by:** Señales reales de volumen en producción o staging, decisión de producto sobre búsqueda/ordenamiento cross-page y definición del contrato incremental compartido entre backend y frontend.

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

---

## TODO-LR-GATE-UNIFY: Unificar el gate business+clasificación de M3 con el helper de M4/M5

**What:** Refactorizar el gate inline de `m3_content_generator` (`graph.py`, inyección de
`M3_AUDIT_LR_BUSINESS_BLOCK` vía `context["lr_business_block"]`) para que comparta el mismo origen
de verdad que `_maybe_business_classification_prompt` (Issue #306), de modo que la condición
`profile=="business" AND family=="clasificacion"` se defina UNA sola vez para M3/M4/M5.

**Why:** Hoy la condición del gate está duplicada: inline en M3 y dentro del helper para M4/M5.
Tres copias del mismo predicado de negocio derivan con el tiempo (p. ej. al añadir una familia o
cambiar la normalización de `profile`).

**Pros:** Una única definición del gate business-LR en los tres módulos del arco.

**Cons:** Toca `m3_content_generator` (código ya mergeado, área sensible) para un refactor no
funcional; además los MECANISMOS de inyección difieren — M3 rellena un placeholder
(`{lr_business_block}`) mientras M4/M5 sustituyen el prompt completo (variante por concatenación),
así que un helper único probablemente necesite una segunda forma. La CONDICIÓN es idéntica; el
mecanismo no.

**Context:** Introducido en Issue #306. `_maybe_business_classification_prompt` vive junto a
`_resolve_generation_focus` en `graph.py`. M3 usa el idiom placeholder; M4/M5 usan swap de prompt.

**Depends on / blocked by:** Issue #306 mergeado (este PR).

---

## TODO-MLDS-M4M5-FROZEN-HASH: Frozen-hash invariante para los prompts ml_ds de M4/M5

**What:** Añadir tests con digest SHA256 congelado para los prompts ml_ds ensamblados de M4/M5,
espejo de `_MLDS_ARCHITECT_PROMPT_SHA256` en `tests/test_issue301_pr2b_architect.py`.

**Why:** Hoy solo el prompt ml_ds del ARQUITECTO está congelado por hash. Los prompts ml_ds de
M4/M5 no tienen guard byte-level, así que una futura edición del lado business podría filtrarse al
path ml_ds y solo lo detectarían los tests de ausencia-de-sentinela (más débiles).

**Pros:** Tripwire explícito y fuerte de que el output ml_ds de M4/M5 nunca deriva por un cambio
del lado business.

**Cons:** Los hashes congelados son fricción de mantenimiento — toda edición intencional del prompt
ml_ds de M4/M5 debe actualizar el digest; alcance más amplio que #306.

**Context:** El approach 1B de Issue #306 ya mantiene el base byte-idéntico y el test
`test_lr_business_block_m4m5_absent_from_ml_ds_prompts` cubre el riesgo inmediato de filtración. El
frozen-hash es defensa-en-profundidad para cambios FUTUROS. Referencia:
`tests/test_issue301_pr2b_architect.py:71-102`.

**Depends on / blocked by:** Ninguno (hardening independiente).

---

## TODO-EDA-FAMILIES: Builder Python-determinista para regresión/clustering business

**What:** Extender el path Python de charts EDA (hoy solo `clasificacion`) a `business+regresion` y
`business+clustering`, reusando `datagen/eda_charts_common.py`.

**Why:** Tras el PR de business+LR, solo clasificación tiene charts honestos deterministas para
business; las otras familias siguen usando el path LLM-JSON (mismo riesgo de overclaim/charts malos).

**Pros:** Calidad de charts uniforme en todas las familias del perfil business.

**Cons:** Más builders + tests; fuera del caso de uso actual (clasificación/LR).

**Context:** El dispatch en `graph.py::eda_chart_generator` gatea `primary_family == "clasificacion"`
para enrutar a `_eda_business_python_path`. Replicar para regresión y clustering con sus charts
propios (p. ej. real-vs-predicho para regresión; PCA 2D / elbow para clustering), reusando los
helpers de `eda_charts_common.py` y el patrón de `eda_charts_business.py`.

**Depends on / blocked by:** `eda_charts_common.py` y `eda_charts_business.py` introducidos en el PR
de business+LR.

---

## TODO-297-A: El de-sawtooth de `financial_mirage` es solo de presentación (causa raíz intacta)

**What:** Dejar registrado que el fix de Issue #297 (agregación temporal anual/trimestral en
`_build_financial_mirage`) suaviza la sierra del margen SOLO en ese chart, vía display-aggregation.
La causa raíz de la varianza por fila del margen sigue intacta: `costs` `noise_factor: 0.12`
(`SCHEMA_DESIGNER_PROMPT`) + el recálculo `(rev-cost)/rev` en `_generate_dataset_from_schema`.

**Why:** Cualquier futuro chart business que muestre el `margin_pct` MENSUAL crudo (sin agregar)
volverá a verse como sierra. El fix no es un cambio de datos a propósito (cohortes, correlaciones
y ml_ds quedan byte-idénticos), así que la deuda es consciente, no un descuido.

**Pros:** Si más adelante se decide que el margen mensual crudo importa, hay un punto único documentado
para reconsiderar bajar el `noise_factor` o suavizar en el data-gen (con su propio plan-eng-review).

**Cons:** Mantener una nota de deuda que quizá nunca se accione. Bajo costo.

**Context:** El grano se elige en `_detect_period_grain` (eda_charts_business.py): business genera
80–120 meses → SIEMPRE cae en "annual" (~7–10 puntos). La rama "quarterly" (25–48 meses) es
actualmente **inalcanzable en producción** (el clamp `n_rows` business es 80–120 mensual); existe por
robustez y queda cubierta por test `test_financial_mirage_aggregates_quarterly_for_mid_horizon`. Si en
el futuro el schema designer pudiera emitir granularidad más gruesa o se cambia el clamp, revisitar.

**Depends on / blocked by:** Independiente. No bloquea nada; cerrar solo si se decide atacar la causa
raíz de la varianza del margen en el data-gen (área sensible, requiere regresión de notebooks ml_ds).

---

## TODO-OUTLIER-SCHEMA-AWARE: Inyección de outliers schema-aware (global, cross-profile)

**What:** Reemplazar la heurística "primera columna numérica no-revenue × 3.5" de
`_generate_dataset_from_schema` (graph.py, bloque `Fix B-05`) por una inyección de outliers
controlada/declarada en el schema (qué columna, magnitud, cuántas filas).

**Why:** La heurística "primera columna" es ciega y puede caer en una columna donde el outlier
engaña la lectura (p. ej. `costs` → margen roto). El PR de business+LR solo mitiga el síntoma en
business (excluye columnas financieras del target del outlier); ml_ds sigue con la heurística ciega.

**Pros:** Outliers intencionales y pedagógicamente coherentes; menos artefactos engañosos en cualquier
perfil; elimina la inconsistencia cost/margin latente en ml_ds.

**Cons:** Toca el generador de datos compartido (afecta ml_ds — área sensible); requiere tests de
regresión sobre notebooks ml_ds (AUC) que dependen de la distribución del dataset.

**Context:** Ver el bloque `Fix B-05` en `_generate_dataset_from_schema` (graph.py). El PR de
business+LR añadió un parámetro `profile` y excluye columnas financieras (revenue/cost/margin/ebitda)
solo para business. La solución global declararía la inyección en el contrato del schema
(`SCHEMA_DESIGNER_PROMPT`) en vez de inferirla por posición de columna.

**Depends on / blocked by:** Coordinar con la reconciliación introducida en el PR de business+LR
(parámetro `profile` en `_generate_dataset_from_schema`).

---

## TODO-EDA-BUILDER-POLISH: Pulido cosmético de los builders EDA Python (DRY + tono business)

**What:** Dos nits cosméticos surgidos en la review adversarial del PR business+LR, diferidos por
tocar el path de clasificación (sensible) para beneficio estético: (1) extraer un factory
`chart_spec(...)` en `eda_charts_common.py` que colapse las 5 claves boilerplate del camino de
éxito (library/description/notes/data_source/template), hoy repetidas en 7 dicts (4 business + 3
clasificación); (2) suavizar la frase "qué riesgo de modelado anticipa" en
`prompts/clasificacion/M2_clasificacion/eda_annotate.py:41` a un encuadre neutral de perfil
(p. ej. "qué riesgo de decisión o de los datos anticipa"), o crear un
`EDA_ANNOTATE_ONLY_PROMPT_BUSINESS` con tono gerencial coherente con `M3_AUDIT_LR_BUSINESS_BLOCK`.

**Why:** (1) elimina duplicación residual (preferencia DRY del equipo); (2) el path business
reutiliza el alias del prompt de clasificación, cuyo único rastro DS ("riesgo de modelado") riñe
levemente con la regla "sin jerga DS" del perfil business.

**Pros:** Builders más DRY y tono de anotaciones business 100% coherente.

**Cons:** El factory refactoriza el builder de clasificación (ml_ds), que está verde y es sensible;
la frase del annotate es compartida con ml_ds. Ambos son nits sin impacto de runtime.

**Context:** Review adversarial del PR business+LR (verdict ship, 0 blockers). El factory es la
duplicación que `eda_charts_common.py` aún no cubrió (solo extrajo `empty_chart`/`source_label`).
La opción más limpia para (2) es un prompt business dedicado, pero añade superficie.

**Depends on / blocked by:** Ninguno. Independiente; hacerlo cuando se toque el área de charts EDA.

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



---

## TODO-237-A: Migrar familia `regresion` a builder Python-determinista

**What:** Replicar el patrón de Issue #237 (`datagen/eda_charts_classification.py` + dispatch en `eda_chart_generator`) para la familia `regresion`. Charts: histograma del target, scatter target vs top-3 numéricas, residuales OLS, QQ-plot, heatmap de correlación, missingness.

**Why:** Cerrar el gap de `zero LLM-fabricated numbers` para el resto de familias ml_ds.

**Pros:** Misma garantía de determinismo. Cons: requiere snapshot tests adicionales y annotate-only prompt afinado para regresión.

**Context:** El builder reutiliza `_resolve_primary_family` y `EDA_ANNOTATE_ONLY_PROMPT` ya extraídos.

---

## TODO-237-B: Migrar familia `clustering` a builder Python-determinista

**What:** Builder con: silhouette por k, elbow (inertia), PCA 2D coloreado por cluster predicho con KMeans random_state=42, distribución por cluster, distancia intra-cluster, missingness.

**Why:** Mismo objetivo de #237 para clustering ml_ds.

**Context:** Importante: la elección de k debe venir de `dataset_schema_required` o un default conservador (k=3) — NO del LLM.

---

## TODO-237-C: Migrar familia `serie_temporal` a builder Python-determinista

**What:** Charts: serie cruda, descomposición STL (trend/seasonal/residual), ACF/PACF, missingness temporal, rolling mean, distribución del target.

**Why:** Cerrar #237 para todas las familias ml_ds.

**Context:** Necesita `statsmodels` como nueva dep o cálculo manual con scipy/numpy. Decidir en planning antes de empezar.

---

## TODO-237-D: Renderizar `anchored_question` en el preview del docente

**What:** El schema `EDAChartSpec` ahora expone `anchored_question: Optional[str]` (Issue #237). El builder Python aún no lo puebla para los 6 charts de clasificación. Falta: (1) escribir las 6 preguntas socráticas ancladas como constantes en `datagen/eda_charts_classification.py`, (2) agregarlas al payload, (3) renderizarlas en `PlotlyChartsRenderer.tsx` debajo de `description`.

**Why:** Cerrar la pieza pedagógica del DoD original de #237.

**Context:** El campo es Optional y back-compat — no rompe charts existentes que no lo populen.

---

## TODO-237-E: Telemetría `data_source` en logs de jobs

**What:** Emitir un log estructurado por job con la distribución `data_source` final del array `doc2_eda_charts` (cuántos `python_builder` vs `llm_json`). Permite verificar en producción que el path Python se activa solo para ml_ds + clasificación y NO se cae al fallback LLM por bugs silenciosos.

**Why:** Observabilidad del switch del path determinista.

**Context:** Hoy logueamos via `logger.info` en `_eda_classification_python_path`. Falta consolidarlo a un campo del job en `authoring_jobs.task_payload` o en un campo dedicado del snapshot final.

---

## TODO-M2-CLSF-EDA-TEXT: Customizar EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION

**What:** Rellenar EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION en M2_clasificacion/eda_text.py con framing de target binario, enfasis en desbalance de clases y vocabulario de churn. Actualizar EDA_TEXT_ANALYST_PROMPT_BY_FAMILY[clasificacion] en prompts/__init__.py.

**Depends on / blocked by:** PR feature/m2-clasificacion-prompt-subfolder mergeado.

---

## TODO-M2-CLSF-EDA-QUESTIONS: Customizar EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION

**What:** Rellenar EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION en M2_clasificacion/eda_questions.py con preguntas socraticas sobre trade-offs recall/precision y desbalance de clases. Actualizar EDA_QUESTIONS_PROMPT_BY_FAMILY[clasificacion].

**Depends on / blocked by:** PR feature/m2-clasificacion-prompt-subfolder mergeado.

---
## TODO-M2-OTHER-FAMILIES: Aplicar patron M2_<familia>/ a regresion, clustering, serie_temporal

**What:** Crear prompts/regresion/M2_regresion/, prompts/clustering/M2_clustering/, prompts/serie_temporal/M2_serie_temporal/ siguiendo el patron de 4 archivos (dataset.py, eda_text.py, eda_questions.py, __init__.py) de clasificacion. Un PR independiente por familia.

**Depends on / blocked by:** PR feature/m2-clasificacion-prompt-subfolder mergeado. Cada familia es independiente.

---

## ~~TODO-M2-CLSF-DATASET-SHIM~~: ✅ DONE — Eliminar shim prompts/clasificacion/dataset.py

**What:** Borrar backend/src/case_generator/prompts/clasificacion/dataset.py (shim) una vez confirmado que ningun importador directo lo referencia. Ejecutar grep exhaustivo en todo backend/ antes de borrar.
**Depends on / blocked by:** PR feature/m2-clasificacion-prompt-subfolder mergeado. Requiere auditoria de importadores directos.
**Status: DONE** — Cerrado por `chore/m2-clsf-dataset-shim-cleanup` (Issue #270). Los 2 importadores directos (tests) migrados a `M2_clasificacion.dataset`. Shim eliminado. Guard negativo `test_shim_deleted_raises_module_not_found` agregado.

---

## TODO-M3-CLSF-A: Crear M4_clasificacion/ subfolder (narrativa M4)

**What:** Crear `backend/src/case_generator/prompts/clasificacion/M4_clasificacion/` como paquete propio, mirroring el patrón `M3_clasificacion/`. Mover el prompt `M4_PROMPT_CLASSIFICATION` (actualmente en `narrative.py`) a `M4_clasificacion/content.py`. Exportar como antes a través de `clasificacion/__init__.py`.

**Why:** Completa la consolidación por módulo dentro de `clasificacion/`. Permite que M4 tenga variantes de algoritmo propias sin saturar `narrative.py`.

**Pros:** Simetría estructural con M1/M2/M3_clasificacion; facilita añadir variantes LR/RF en M4 si se necesitan.

**Cons:** Cambio puro de estructura; no hay lógica nueva. Requiere actualizar imports y `__all__` en `clasificacion/__init__.py` y `narrative.py`.

**Context:** PR `feat/m3-clasificacion-prompt-subfolder` dejó `M4_PROMPT_CLASSIFICATION` y `M5_PROMPT_CLASSIFICATION` en `narrative.py` para no ampliar scope. Este TODO es el siguiente paso natural.

**Depends on / blocked by:** PR `feat/m3-clasificacion-prompt-subfolder` mergeado.

---

## TODO-M3-CLSF-B: Crear M5_clasificacion/ subfolder (narrativa M5)

**What:** Crear `backend/src/case_generator/prompts/clasificacion/M5_clasificacion/` como paquete propio, mirroring `M3_clasificacion/`. Mover `M5_PROMPT_CLASSIFICATION` de `narrative.py` a `M5_clasificacion/content.py`.

**Why:** Mismo razonamiento que TODO-M3-CLSF-A para M5. Permite añadir variantes de memo ejecutivo por perfil de algoritmo sin tocar `narrative.py`.

**Pros:** Simetría con M1–M4; `narrative.py` queda vacía y puede eliminarse en limpieza posterior.

**Cons:** Cambio estructural sin lógica nueva; requiere actualizar imports.

**Depends on / blocked by:** TODO-M3-CLSF-A completado primero (o ambos en el mismo PR).

---

## TODO-M3-CLSF-C: Eliminar M3 content de narrative.py (cleanup de residuos)

**What:** Una vez confirmado que ningún importador externo consume `M3_CONTENT_PROMPT_CLASSIFICATION_*` directamente desde `narrative.py` (ya que son canónicos en `M3_clasificacion/content.py`), eliminar esas definiciones de `narrative.py` para evitar duplicación silenciosa.

**Why:** `narrative.py` aún define `M3_CONTENT_PROMPT_CLASSIFICATION_LR_ONLY`, `_RF_ONLY` y `M3_CONTENT_PROMPT_CLASSIFICATION` por compatibilidad hacia atrás. Una vez el sistema esté estabilizado en producción, esta duplicación es deuda técnica.

**Pros:** Elimina la fuente de verdad duplicada; `narrative.py` queda solo con M4/M5 hasta TODO-M3-CLSF-A/B.

**Cons:** Requiere audit de importadores directos. Si algún código importa desde `narrative.py` directamente (no a través de `clasificacion/__init__.py`), fallará — el audit debe ejecutarse antes.

**Context:** El `__all__` de `narrative.py` ya fue acotado a `["M4_PROMPT_CLASSIFICATION", "M5_PROMPT_CLASSIFICATION"]` en PR `feat/m3-clasificacion-prompt-subfolder`. Las definiciones de M3 aún existen como variables privadas-de-facto (sin `__all__`). Un `grep -r "from.*narrative import" backend/` confirmará si hay importadores directos.

**Depends on / blocked by:** PR `feat/m3-clasificacion-prompt-subfolder` mergeado. Audit de importadores directos.


---

## ~~TODO-M5-A~~: Mover M5_QUESTIONS_GENERATOR_PROMPT de prompts/__init__.py a prompts/_shared.py ✅ DONE (PR #277 — refactor/m5-questions-generator-prompt-to-shared)

**What:** M5_QUESTIONS_GENERATOR_PROMPT (el prompt base de M5 para familias regresion/clustering/serie_temporal)
actua hoy como fallback generico en M5_QUESTIONS_PROMPT_BY_FAMILY y esta definido directamente en
ackend/src/case_generator/prompts/__init__.py. Moverlo a prompts/_shared.py junto con otros
prompts base (M1_QUESTIONS_GENERATOR_PROMPT, M2_SCHEMA_DESIGNER_PROMPT, etc.) mejora la consistencia
arquitectonica del modulo.

**Why:** Siguiendo el patron de M1-M4 donde los prompts base viven en _shared.py y el dispatch
table en __init__.py. _shared.py ya importa desde familias especializadas; este cambio lo
simetria con el resto de la columna de prompts base.

**Pros:** Reduce la longitud de __init__.py (que ya tiene muchas definiciones inline); la fuente
de verdad del prompt base queda en _shared.py junto al resto; facilita tests directos del prompt base.

**Cons:** Requiere actualizar la importacion en __init__.py (de definicion inline a import desde _shared).
Bajo riesgo de rotura si solo __init__.py es el importador canonico.

**Context:** Diferido de Phase 2 de PR feat/m5-clasificacion-subfolder (Decision 4A). El dispatch
M5_QUESTIONS_PROMPT_BY_FAMILY permanece en __init__.py y continua funcionando con el fallback
sin cambios visibles desde el exterior.

**Depends on / blocked by:** PR feat/m5-clasificacion-subfolder mergeado. Independiente despues.

---

## TODO-M3-REF-A: Extender `NOTEBOOK_HEADING_REFS` a otros encabezados M3 de análisis clave

**What:** Añadir entradas adicionales en la constante `NOTEBOOK_HEADING_REFS` de
`frontend/src/shared/case-viewer/CaseContentRenderer.tsx` para anotar otros encabezados
del narrativo M3 que correspondan a celdas numeradas del notebook (por ejemplo, ROC/PR
curves en `§3.0.4`, matriz de confusión en `§3.0.7`, sección de tuning en `§3.0.8`).

**Why:** Si `§3.0.6` es útil para que el estudiante localice la matriz de costos, la misma
mecánica beneficia otras secciones analíticas clave del módulo M3.

**Pros:** Añadir una entrada es exactamente una línea en el lookup table — el mecanismo ya
existe. Zero nuevas abstracciones.

**Cons:** Requiere auditar qué encabezados del narrativo LLM corresponden a qué celdas
numeradas en cada variante (lr_only / rf_only / lr_rf_contrast), ya que algunos análisis
(tuning, interpretabilidad) tienen celdas distintas por variante. Un solo número de sección
no aplica a todos los casos.

**Context:** El mecanismo `injectNotebookRefs()` fue introducido en
`feat/m3-cost-matrix-notebook-ref`. Los números de sección de todas las celdas de
clasificación están hardcodeados en `notebooks/_shared.py` y `notebook.py`.
`§3.0.6 — Matriz de costos` es idéntico en las tres variantes, por lo que era seguro como
primer caso. Otras secciones requieren verificar si el número es estable entre variantes.

**Depends on / blocked by:** `feat/m3-cost-matrix-notebook-ref` mergeado. Independiente después.

---

## TODO-M3-REF-B: Assertion de CI sobre el texto exacto del encabezado en `content.py`

**What:** Añadir un test de string literal en `backend/tests/` que verifique que los tres
bloques de coherencia en `backend/src/case_generator/prompts/clasificacion/M3_clasificacion/content.py`
contienen exactamente `## Cómo leer la matriz de costos` (con tilde, capitalización y
espaciado correctos).

**Why:** El único modo de fallo silencioso de `injectNotebookRefs()` es que el LLM reciba
una instrucción con un encabezado distinto (por drift del prompt) y genere un ID diferente
al que el frontend espera (`seccion-como-leer-la-matriz-de-costos`). Un assert de string
en CI lo detectaría en el momento del cambio del prompt.

**Pros:** Cierra el único modo de fallo silencioso del sistema. Costo casi nulo — es un
`assert "## Cómo leer la matriz de costos" in BLOCK` en un archivo de test existente.

**Cons:** La assertion es un test de string literal sobre un prompt — si el encabezado se
renombra intencionalmente, el desarrollador debe actualizar dos archivos (prompt + assertion).
Riesgo de falso positivo si se renombra el encabezado con buena razón.

**Context:** Ver `_M3_CLASSIFICATION_COHERENCE_BLOCK_LR_ONLY`, `_RF_ONLY`, y
`_LR_RF_CONTRAST` en `content.py`. El ID generado por `renderMarkdownWithIds()` depende de
la normalización NFD + eliminación de diacríticos de ese texto exacto.

**Depends on / blocked by:** `feat/m3-cost-matrix-notebook-ref` mergeado. Independiente después.

---

## TODO-REALTIME-TELEMETRY: Instrumentar la tasa de CHANNEL_ERROR en producción post-fix

**What:** Agregar telemetría estructurada (Sentry, Datadog, o evento de analytics propio) en
el sitio donde `console.warn('[authoring-progress] realtime subscription failed', ...)` se
ejecuta en `frontend/src/shared/api.ts`. Capturar `jobId`, `subscriptionStatus`, y contexto
de red/browser.

**Why:** Tras el fix del JWT race condition (Issue #248), la expectativa es que `CHANNEL_ERROR`
prácticamente desaparezca en cold start. Sin telemetría no hay evidencia directa de que el
fix funcionó. Si aparece una nueva causa de CHANNEL_ERROR (token expirado en escenarios
inesperados, cambio de infraestructura Supabase), solo se sabría por tickets de soporte.

**Pros:** Verificación directa post-deploy. Permite detectar regresiones de transporte
Realtime con datos duros, no con reportes anecdóticos. Habilita alertas si la tasa supera
un umbral (p.ej. >2% de jobs en una ventana de 1h).

**Cons:** Requiere elegir e instalar una herramienta de telemetría client-side que actualmente
no está configurada en ADAM-EDU. Pequeño overhead de red por evento de error. No bloquea
el despliegue.

**Context:** El punto exacto de instrumentación es en `api.ts`, bloque
`subscriptionStatus === "CHANNEL_ERROR" || subscriptionStatus === "TIMED_OUT" || subscriptionStatus === "CLOSED"`, después del
`console.warn`. La llamada debe incluir `{ jobId, subscriptionStatus }` como propiedades
del evento. No loguear tokens ni PII.

**Depends on / blocked by:** Deploy de `fix/realtime-subscription-jwt-race` primero; luego
este TODO como follow-up independiente en una rama separada.

---

## TODO-REALTIME-EXPIRED-TOKEN-TEST: Test de cobertura para path de token expirado

**What:** Agregar Test D en `frontend/src/shared/api.test.ts`: `getBearerToken()` devuelve
un token no-nulo pero expirado → `setAuth(expiredToken)` es llamado → subscribe resulta en
`CHANNEL_ERROR` (simulado) → el fallback a polling toma el control → el job completa via
polling.

**Why:** La decision 1A en la revisión del plan aceptó el path de token expirado como un
edge case manejado por el fallback existente. Sin un test explícito, un cambio futuro a
`getBearerToken()` (p.ej. añadir `forceRefresh`) podría romper la cadena de degradación
silenciosamente.

**Pros:** Cierra el único gap de cobertura restante del fix. Previene regresiones en el
camino de degradación `CHANNEL_ERROR → polling` cuando el token es no-nulo pero inválido.

**Cons:** El setup del mock es ligeramente más complejo que los tres tests añadidos en el PR
(requiere simular `CHANNEL_ERROR` en `.subscribe()` después de que `setAuth()` fue llamado
con un token non-null). Aproximadamente 40 líneas de test.

**Context:** `getBearerToken()` llama `auth.getSession()` que retorna la sesión cacheada en
localStorage tal como está, sin verificar expiración activamente. El token puede ser
non-null pero expirado si el usuario reabrió una pestaña inactiva y `autoRefreshToken` no
había disparado todavía. La RLS `auth.uid() = NULL` con un token expirado produce
`CHANNEL_ERROR` idéntico al bug original, pero es manejado por el fallback.

**Depends on / blocked by:** `fix/realtime-subscription-jwt-race` mergeado. Independiente
después.

---

## TODO-TOC-A: Drift validator — sección TOC vs headers reales por variante

**What:** Añadir un test pytest (sin LLM, sin DB) en `test_issue230_classification_notebook_variants.py` que parsee el texto assembled de cada variante de clasificación y cruce los números de sección del `TOC_MARKDOWN_CELL_BY_VARIANT` contra los headers `# %% [markdown]` reales presentes en el `_shared.py` de cada variante. Reutilizar `_section_bounds()` para extraer el rango ejecutable de cada sección.

**Why:** Las TOC son strings estáticos — pueden desincronizarse de los headers reales si se añade o renombra una sección en `_shared.py` sin actualizar el dict. Un test de drift barato captura esto antes de merge.

**Pros:** Sin dependencias externas; se ejecuta en el suite unitario normal; protege la consistencia TOC↔headers como un constraint continuo.

**Cons:** Requiere que los headers de sección en los prompts sigan un patrón parseable (por ejemplo, `## X.Y.Z Título`) para poder extraer los números de sección programáticamente.

**Context:** Actualmente los TOC se validan solo por contenido de string (qué sección "3.0.5.2" está o no está). El drift validator cierra el loop: compara los índices declarados en la TOC contra los índices realmente presentes en el prompt de la variante.

**Depends on / blocked by:** Independiente — puede implementarse en cualquier PR posterior sin impacto en runtime.

---

## TODO-TOC-B: Convertir índices TOC en anchor links (Jupyter anchor scheme)

**What:** Una vez estabilizado el entorno de despliegue (JupyterLab vs Google Colab), convertir los números de sección de la TOC en links de anchor markdown (`[3.0.5.2 Pipeline LR](#3052-pipeline-reproducible--logistic-regression)`) para navegación clickable dentro del notebook.

**Why:** En JupyterLab/JupyterHub los anchor links funcionan en celdas markdown; en Colab el scheme es diferente. La feature es de alta UX pero requiere confirmar el target antes de usar un scheme incorrecto que quede roto.

**Pros:** Navegación rápida por el notebook para el alumno — clic directo a cada sección desde la TOC.

**Cons:** El scheme de anchor links no es estándar entre Jupyter, JupyterLab y Colab. Un anchor mal formado produce un link roto sin error visible.

**Context:** La TOC estática actual es legible pero no clickable. La conversión a anchors es trivial una vez decidido el entorno canónico. Los headers de las secciones en `_shared.py` deben convertirse al mismo scheme para que los destinos existan.

**Depends on / blocked by:** Confirmación del entorno de despliegue de notebooks (JupyterHub/Lab vs Colab). No bloquea el rollout de la TOC estática.

---

## TODO-TOC-C: Extender TOC a familias regresión, clustering y serie_temporal

**What:** Una vez que el placeholder `{toc_cell}` existe en `M3_NOTEBOOK_BASE_TEMPLATE`, añadir entradas de `TOC_MARKDOWN_CELL_BY_VARIANT` (o un `TOC_CELL_BY_FAMILY` nuevo) para las familias `regresion`, `clustering` y `serie_temporal`.

**Why:** La infraestructura de placeholder ya está. El único trabajo restante es escribir los strings estáticos de TOC para cada familia una vez que los prompts de esas familias estén estabilizados.

**Pros:** Cero cambios a `graph.py` — la lógica de resolución `TOC_MARKDOWN_CELL_BY_VARIANT.get(notebook_variant, "")` ya devuelve `""` para familias no listadas, por lo que la ausencia no rompe nada. Añadir una familia es puramente aditivo.

**Cons:** Requiere estabilización previa de los prompts por familia para que los números de sección de la TOC sean definitivos.

**Context:** `feat/classification-notebook-toc` implementa el mecanismo completo y los TOC para `lr_only`, `rf_only` y `lr_rf_contrast`. Extender a otras familias es trivial una vez aprobadas las secciones definitivas de sus prompts.

**Depends on / blocked by:** Estabilización de los prompts de regresión, clustering y serie_temporal.

---

## TODO-COST-A: Reducir la FRECUENCIA de reprompts de validación (prompt tuning de 1ª pasada)

**What:** Afinar los prompts de primera pasada para que disparen menos los reprompts de
validación: grounding narrativo (`validate_narrative_grounding` en M3/M4/M5), decision-matrix
(`_validate_m5_decision_matrix`), family-consistency (`_validate_notebook_family_consistency`)
y la corrección de ejecución de `m3_notebook_executor`. Cada reprompt es una llamada LLM extra
sobre un nodo Pro.

**Why:** Es el driver #2 de costo del diagnóstico de reducción de costos (los reprompts pueden
añadir ~6-8 llamadas Pro extra en el peor caso). Reducir la tasa de reprompt baja costo sin
debilitar las compuertas de corrección.

**Pros:** Ataca el costo sin tocar el tier de modelo ni eliminar las validaciones; las compuertas
siguen intactas como red de seguridad.

**Cons:** Es prompt-engineering en los archivos más sensibles (`prompts/**`, `graph.py`); requiere
su propio eval (golden-set) para confirmar que el ajuste no degrada calidad. Alto cuidado.

**Context:** El `CostCallbackHandler` (Fase 0, `cost_metrics.py`) persiste `cost_breakdown` en
`task_payload` con tokens/USD por nodo; usar esa telemetría para medir la tasa real de reprompt
por nodo ANTES de tocar prompts. Sin datos de Fase 0 no se sabe qué reprompt domina.

**Depends on / blocked by:** Datos de Fase 0 (reprompt-rate por nodo) en producción/staging.
Debe ir en un PR dedicado con eval, no junto al PR de reducción de costos.

---

## TODO-COST-B: Gemini explicit context caching (`cached_content`) para prefijos estáticos

**What:** Cachear explícitamente los prefijos de prompt estáticos grandes
(`prompts/__init__.py` ~28K tokens, `prompts/clasificacion/notebooks/_shared.py` ~12K tokens)
con la API de context caching de Gemini, para pagarlos a la tarifa reducida de cache en vez de
reenviarlos completos en cada llamada.

**Why:** Hoy cada `.invoke` reenvía el prompt estático completo como input. El caching corta
input-tokens transversalmente en todos los nodos.

**Pros:** Reducción de input-tokens sin tocar la lógica del grafo ni la calidad de salida.

**Cons:** El reuso DENTRO de un job es limitado (cada nodo usa un template distinto, una sola vez),
así que el beneficio real depende del caching IMPLÍCITO entre jobs y del soporte de caching en los
modelos `-preview`. Agrega complejidad de gestión de TTL/handles de cache.

**Context:** El `CostCallbackHandler` ya separa `cached_input_tokens` (lee `input_token_details.cache_read`)
y los factura a `cached_input_per_1m` en `cost_metrics.PRICE_MAP`, así que el ahorro es medible una
vez activado. Confiar primero en el caching implícito de Gemini (gratis, sin código) y reevaluar con
datos de Fase 0 antes de construir infra de cache explícito.

**Depends on / blocked by:** Datos de Fase 0 (cuánto del costo es input estático) + confirmar
soporte de context caching en `gemini-3.x-preview`.

---

## TODO-294-A: Investigar el origen aguas arriba de columnas numéricas constantes en el dataset sintético

**What:** Rastrear por qué `_generate_dataset_from_schema` (`backend/src/case_generator/graph.py:2720`)
emite una columna numérica de varianza cero en un dataset `business` de ~95 filas. Empezar por el
loop de `independent_cols` (~línea 2778) y `_generate_independent_values`: la causa probable es una
columna `int` con `range_min`/`range_max` muy próximos (o iguales, donde el guard `if low >= high:
high = low + 1.0` deja un rango de 1) que tras el redondeo a entero produce todas las filas con el
mismo valor. Prevenir la columna constante en el generador, o marcarla en `data_gap_warnings`.

**Why:** El fix de Issue #294 (PR `fix/issue-294-eda-constant-column-corr`) trata el SÍNTOMA en el
EDA (excluye las columnas constantes de la correlación para matar el `RuntimeWarning` de
`np.corrcoef` y la "0 correlación" engañosa). Un dataset sintético de ~95 filas no debería tener
una columna numérica de varianza cero en primer lugar — el origen del dato sigue abierto.

**Pros:** Elimina el smell en la fuente; mejora el realismo del dataset para TODOS los casos, no solo
el heatmap del EDA.

**Cons:** Edita la lógica de generación del archivo más sensible del repo (`graph.py`, shape del
schema), con mayor riesgo de regresión; requiere su propio repro y un schema de prueba que reproduzca
el rango degenerado.

**Context:** Detectado durante la implementación de Issue #294. El repro confirmó que el
`RuntimeWarning` real venía de `Series.corr` (= `np.corrcoef`) en `graph.py:1239`, no de
`DataFrame.corr` en 1183. El fix de EDA ya contiene el síntoma, así que este trabajo es
independiente y de baja urgencia.

**Depends on / blocked by:** PR de Issue #294 mergeado (síntoma ya contenido). Sin otros bloqueantes.

---

## TODO-294-B: Registrar columnas constantes excluidas en `data_gap_warnings`

**What:** Cuando el fix de Issue #294 en `_calculate_eda_regressions` excluye una columna numérica
constante, dejar una traza (p. ej. un append a `data_gap_warnings`) en vez de descartarla en
silencio, para que docentes/devs vean el smell de datos.

**Why:** La exclusión silenciosa oculta el mismo problema de calidad de datos que ataca
[TODO-294-A]. Un breadcrumb hace visible la recurrencia sin reintroducir el `RuntimeWarning`.

**Pros:** Señal barata de calidad de datos; conecta el síntoma (EDA) con su origen (generador).

**Cons:** `_calculate_eda_regressions` hoy solo devuelve métricas precalculadas; cablear un warning
implica confirmar la ruta de escritura de `data_gap_warnings` desde este nodo del grafo — un toque
de contrato algo más amplio que el fix puramente local.

**Context:** Diferido en la plan-eng-review de Issue #294 (TODO 2, decisión "A: add"). Conviene
emparejarlo con [TODO-294-A] una vez confirmada la ruta de escritura de `data_gap_warnings`.

**Depends on / blocked by:** Confirmar cómo se persiste `data_gap_warnings` desde el nodo de EDA.
Idealmente junto con [TODO-294-A].

---

## TODO-301-A: Aplicar el guard `_ensure_both_classes` también a `categoria` (ml_ds)

**What:** Extender el guard anti-degeneración de clases `_ensure_both_classes` (hoy
business-only, en el branch int dependiente de `_generate_dataset_from_schema`) al target
binario `categoria` de ml_ds + clasificación.

**Why:** El guard se introdujo en Issue #301 gateado a `profile == "business"` para no
alterar el output de ml_ds (invariante "ml_ds intacto / golden sin cambios"). Pero
`categoria` tiene el MISMO riesgo probabilístico de colapsar a una sola clase
(`round(parent_norm + noise)` con `churn_rate` sesgado), lo que produciría un notebook M3
con AUC indefinido sin aviso.

**Pros:** Cierra el bug latente en el perfil de alto valor; un solo guard en todas partes.

**Cons:** Cambia el output de `categoria` en el seed degenerado → exige re-baseline del
golden/snapshot de ml_ds, que el invariante de #301 prohíbe tocar ahora.

**Context:** El guard vive junto a `_generate_dataset_from_schema` en `graph.py`; `categoria`
se define inline en `_build_fallback_schema` (~L2018-2027). Aplicarlo a ml_ds requiere mover
el gate y regenerar el golden en un PR dedicado.

**Depends on / blocked by:** PR1 de Issue #301 (el guard) mergeado. Re-baseline del golden ml_ds.

---

## TODO-301-B: Eliminar la duplicación verbatim de `CASE_ARCHITECT_PROMPT` [RESUELTO por #305]

**What:** Extraer el cuerpo genérico de `CASE_ARCHITECT_PROMPT` a una constante compartida y
componer `CASE_ARCHITECT_PROMPT_CLASSIFICATION = _BASE + _ANCHOR`, eliminando la copia
verbatim en `prompts/clasificacion/M1_clasificacion/architect.py` (L67-276).

**Why:** Hoy cada cambio al prompt base debe replicarse a mano en dos archivos (el header del
módulo lo admite explícitamente). El test de sincronización de #301 PR2 DETECTA el drift pero
no lo previene; este refactor lo elimina en la raíz.

**Pros:** DRY real; futuros edits del architect tocan un solo lugar; el test guard se vuelve
redundante.

**Cons:** Reestructura el módulo sensible de ensamblaje de prompts; riesgo de romper variables
`.format()`; fuera del alcance de #301.

**Context:** Detectado en la plan-eng-review de Issue #301 (issue 5, opción 5B diferida).
Depende de que PR2 (condicionamiento de la "regla 7" por perfil) aterrice primero para partir
del texto corregido. Requiere snapshot de prompts para verificar.

**Depends on / blocked by:** PR2 de Issue #301 mergeado.

---

## TODO-301-C: Consumir `min_signal_strength` en el umbral del chart + validador suave

**What:** Cablear `min_signal_strength` del contrato al umbral "sin driver fuerte" de
`churn_drivers` (`_DRIVERS_MIN_ABS_CORR`, hoy fijo en 0.10) y añadir un validador SUAVE que
avise (no falle el job) cuando `|corr|` alcanzada < `min_signal_strength`.

**Why:** #301 PR1 usa `min_signal_strength` solo como objetivo de síntesis (deriva el
`noise_factor` del driver). Leerlo también en display + validación lo vuelve un campo del
contrato totalmente load-bearing en vez de medio decorativo.

**Pros:** El campo pasa a ser la única fuente de verdad para "señal suficiente"; umbral
ajustable por caso.

**Cons:** Acopla el display del chart al contrato; un validador DURO podría fallar casos de
señal débil honestos (por eso 8A lo difirió).

**Context:** Detectado en la plan-eng-review de Issue #301 (issue 8, opción 8B diferida).
Toca `eda_charts_business.py` (`_DRIVERS_MIN_ABS_CORR`) + un validador en `graph.py`.

**Depends on / blocked by:** PR1 de Issue #301 mergeado.

---

## TODO-301-D: Chart 3 dedicado para clasificación (tasa de evento / balance en el tiempo)

**What:** Construir un tercer chart hecho a medida para casos de clasificación binaria — p. ej.
tasa del evento por período, o balance de clases en el tiempo — en vez del `class_balance`
(barra de conteo) que #301 PR1 reutiliza en el slot de cohorte.

**Why:** 4A reutiliza el slot de cohorte con una barra simple de balance de clases (diff
mínimo). Un chart dedicado podría contar una historia pedagógica más rica para un target
binario (tendencia de la tasa del evento, desglose por segmento).

**Pros:** Mejor pedagogía del M2 para clasificación no-churn; completa la familia de charts
business.

**Cons:** Nuevo builder + dispatch + tests en el módulo datagen sensible; requiere diseño.

**Context:** Detectado en la plan-eng-review de Issue #301 (issue 4, opción 4B diferida).
`eda_charts_business.py` + dispatch en `eda_chart_generator`.

**Depends on / blocked by:** PR1 de Issue #301 (títulos/fallback) mergeado.

---

## TODO-301-PR2a-A: Anunciar el flip legítimo del target en `data_gap_warnings`

**What:** Cuando `_ensure_both_classes` balancea un target binario degenerado en
`_generate_dataset_from_schema` (`backend/src/case_generator/graph.py`), emitir una nota en
`data_gap_warnings` con el conteo de filas volteadas (p. ej. "target binario degenerado:
N filas sintéticas inyectadas para garantizar ambas clases").

**Why:** Honestidad #296/#298 — un flip sintético sobre el target hoy es SILENCIOSO. PR2a
detuvo los flips sobre features no-target (Fix 1), pero el flip legítimo del target sigue sin
anunciarse. El docente debería ver que el dataset tuvo intervención determinista.

**Pros:** Cierra el último flip silencioso del generador; coherente con el resto de avisos de
honestidad que ya alimentan M2/M3.

**Cons:** `_generate_dataset_from_schema` hoy devuelve solo `rows`; los warnings se ensamblan
aguas arriba en `schema_designer` (graph.py:2941-2947, 2975-2981). Anunciar el flip exige
cambiar la forma de retorno (p. ej. `(rows, notes)`) y enhebrarlo por `data_generator`
(graph.py:3383) → fuera de la "tajada segura" de PR2a.

**Context:** Detectado en la verificación adversarial de PR #302 ("8 filas volteadas, flip
sintético no anunciado") y registrado en la plan-eng-review de PR2a. `_ensure_both_classes`
(graph.py) ya conoce cuántas filas voltea (`k`); solo falta propagar esa señal.

**Depends on / blocked by:** Empareja naturalmente con PR2b (que ya toca el camino del target
y del architect). Independiente del resto de PR2b — puede hacerse en su propio PR de honestidad.

---

## TODO-301-PR2b-A: Deduplicar el prompt del architect (copia verbatim base→clasificación) [RESUELTO por #305]

**What:** `CASE_ARCHITECT_PROMPT_CLASSIFICATION`
(`backend/src/case_generator/prompts/clasificacion/M1_clasificacion/architect.py`) es una **copia
verbatim** de ~200 líneas del `CASE_ARCHITECT_PROMPT` base (`prompts/__init__.py`) con el ancla
`_M1_CLASSIFICATION_ANCHOR_ARCHITECT` concatenada. El docstring del módulo declara una regla manual
de "mirror changes". Componer el prompt como `base + ancla` (en vez de copiarlo) elimina la
duplicación.

**Why:** Cualquier edición futura al prompt base debe hacerse dos veces o las copias divergen
silenciosamente — exactamente la clase de bug que PR2b evitó tocando solo un bloque añadido.

**Pros:** Una sola fuente de verdad para el prompt del architect; el snapshot ml_ds de PR2b
(`tests/test_issue301_pr2b_architect.py`, hash + differential) hace el refactor seguro de verificar.

**Cons:** Tocar el ensamblado de un prompt compartido con ml_ds es sensible; necesita su propio PR
con el snapshot vigilando y revisión de `graph.py`/`prompts`.

**Context:** PR2b (#301) eligió el bloque `M1_CLASSIFICATION_BUSINESS_TARGET_BLOCK` añadido en
ensamblado (`graph._assemble_architect_prompt`) precisamente para NO tocar el texto duplicado y
mantener el prompt ml_ds byte-idéntico. La deuda de duplicación queda intacta (ni peor ni mejor).

**Depends on / blocked by:** Snapshot ml_ds de PR2b mergeado (ya disponible tras este PR).

---

## TODO-301-PR2b-B: Limpiar las líneas stale "business puede emitir null/continuo" [RESUELTO por #305]

**What:** En el prompt de clasificación, la rule 7 (~L263-265) y la prosa de
`## dataset_schema_required` (~L195-198) todavía dicen que business puede emitir `null` o un target
continuo. Para business+clasificación eso ya está contradicho por el ancla y por el bloque business
de PR2b. Condicionarlas por familia/perfil (o eliminarlas del prompt de clasificación) cierra la
contradicción textual.

**Why:** Un prompt auto-contradictorio es deuda de honestidad/claridad y puede subir la tasa de
fallo crudo del LLM (más dependencia del net determinista que cae a `target_event_flag`).

**Pros:** Prompt coherente para business+clasificación; menos ruido para el modelo → mejor tasa de
nombre de dominio (medida por las evals multi-dominio 9A).

**Cons:** Editar esas líneas cambia el string del prompt ml_ds → rompe la garantía byte-idéntica de
PR2b a menos que se haga junto con la composición del prompt (TODO-301-PR2b-A).

**Context:** PR2b dejó estas líneas intactas a propósito (decisión 2A: bloque business añadido en
ensamblado, sin tocar texto compartido). El ancla ya las sobreescribe en runtime, así que la
contradicción es cosmética hoy.

**Depends on / blocked by:** TODO-301-PR2b-A (un prompt compuesto permite condicionar estas líneas
sin duplicar la edición ni romper el snapshot ml_ds).

---

## TODO-305-A: Deduplicar `CASE_WRITER_PROMPT_CLASSIFICATION` / `CASE_QUESTIONS_PROMPT_CLASSIFICATION`

**What:** Igual que el architect en #305: `CASE_WRITER_PROMPT_CLASSIFICATION`
(`prompts/clasificacion/M1_clasificacion/writer.py`) y `CASE_QUESTIONS_PROMPT_CLASSIFICATION`
(`.../questions.py`) son copias verbatim de sus bases (`CASE_WRITER_PROMPT` /
`CASE_QUESTIONS_PROMPT` en `prompts/__init__.py`) + un ancla. Componerlas como `base + ancla`
extrayendo las bases a módulos leaf (patrón `prompts/_architect_base.py` de #305).

**Why:** Misma deuda de duplicación que el architect: cualquier edición a la base hay que
replicarla a mano y el header del módulo declara una regla manual de "mirror changes".

**Pros:** DRY consistente en las tres copias M1 de clasificación; un solo lugar por prompt base.

**Cons:** No son auto-contradictorias hoy (a diferencia del architect), así que NO hay bug
funcional — es limpieza. Cada copia es su propia superficie de snapshot; conviene un guard
de identidad por prompt como el de #305 antes de tocar.

**Context:** #305 dedupló SOLO el architect (era el único con la contradicción rule-7) y extrajo
`CASE_ARCHITECT_PROMPT` a `prompts/_architect_base.py` para romper el ciclo de import. Usar ese
PR como plantilla exacta: leaf module + import en `__init__.py` (bloque top, evita E402) + import
en el módulo de familia + test de identidad `X_CLASSIFICATION == BASE + ANCHOR`.

**Depends on / blocked by:** #305 mergeado (provee la plantilla de extracción + import ordering).

---

## TODO-305-B: Ampliar la cobertura de `_TITLE_TO_TARGET_TOKENS` (blind spots del detector de mismatch)

**What:** Añadir keywords de dominio que el detector `_validate_target_semantic_coherence`
(`graph.py`) no cubre hoy — p. ej. logística/incumplimiento/socios/SLA. El caso FastRoute que
motivó #301 ni siquiera dispara el warning porque su título no matchea ningún keyword del mapa.

**Why:** El enforcement de mismatch de #305 Gate 2 (reprompt) SOLO se dispara cuando la heurística
detecta el mismatch. Los blind spots = passthrough silencioso de un target con nombre desalineado.

**Pros:** Más casos business+clasificación reciben el reprompt de corrección de nombre.

**Cons:** #301 de-enfatiza explícitamente el keyword-matching (no escala — por eso la síntesis
determinista y el reprompt son la red). Más keywords también amplían la superficie de FALSOS
positivos del detector, justo ahora que es accionable (reprompt). Prioridad baja.

**Context:** El mapa `_TITLE_TO_TARGET_TOKENS` mapea sustantivos de título (es/en) a tokens
esperados de target. El reprompt de #305 es false-positive-safe (acepta cualquier target de
clasificación válido en el reprompt), así que ampliar tokens es seguro pero de bajo retorno.

**Depends on / blocked by:** #305 mergeado (Gate 2 enforcement). Independiente por lo demás.

---

## TODO-319-A: Auditar coherencia gráfico↔narrativa en M2 EDA charts para business+clasificación

**What:** Verificar si los gráficos EDA de M2 (`eda_chart_generator`) para business+clasificación
reflejan el framing gerencial (probabilidad de evento × valor en riesgo) o siguen genéricos como
estaban los de M4 antes de #319.

**Why:** #318 ajustó el *texto* EDA business y #237 hizo los *charts* EDA para ml_ds clasificación,
pero el framing de los charts EDA business quedó sin verificar; #319 solo cierra M4. Si el desfase
es simétrico, los gráficos de M2 razonarían en ROI/financiero genérico mientras el texto EDA ya
habla en lenguaje de priorización.

**Pros:** Cierra un gap probablemente simétrico al de #319; UX coherente entre módulos M2 y M4.

**Cons:** Investigación separada + posible nuevo bloque de prompt; puede resultar que los charts de
M2 business ya estén bien y el TODO se cierre como no necesario.

**Context:** Mirar `eda_chart_generator` en `backend/src/case_generator/graph.py` y los prompts EDA;
superficie de test en `backend/tests/test_eda_charts_business.py` y
`backend/tests/test_issue237_eda_charts_classification.py`. Si hay desfase, replicar el patrón
exacto de #306/#319: bloque estático placeholder-free + `_maybe_business_classification_prompt`.

**Depends on / blocked by:** Independiente de #319.

---

## TODO-320-A: Test de snapshot/regresión visual frontend para el chart de drivers divergente

**What:** Añadir un test automatizado de frontend que cubra el render del chart `churn_drivers`
divergente de M2 business: que el encoding con signo (x ∈ [-1,1]), el `marker.color` por barra y
el `xaxis.range=[-1,1]` sobreviven a `sanitizeTraces` y llegan intactos a Plotly.

**Why:** Hoy **no existe ninguna cobertura de test de frontend** para estos charts Plotly; el fix de
#320 se apoya en verificación manual del JSON de la traza (e inspección visual) para confirmar que
`sanitizeTraces` no descarta `marker` ni recorta valores negativos. Un cambio futuro en
`sanitizeTraces`/`buildLayout` podría romper el encoding direccional sin que ningún test lo detecte.

**Pros:** Cierra el gap de cero cobertura FE para los charts EDA; bloquea regresiones silenciosas del
encoding con signo y del color por barra (modo de fallo F2 del plan-eng-review de #320).

**Cons:** No existe aún harness de test para componentes de chart en `frontend/` — es infraestructura
net-new (Vitest/RTL + setup de Plotly mock). Mayor que un test puntual.

**Context:** Render en `frontend/src/shared/case-viewer/PlotlyChartsRenderer.tsx` +
`plotlyChartUtils.ts` (`sanitizeTraces`, `buildLayout`). Verificado en #320 que `sanitizeTraces` solo
normaliza heatmaps y `null→0` en x/y (no toca `marker`, no recorta negativos) y que el tipo TS
`Data`/`PlotMarker` ya admite `Color[]`. Punto de partida sugerido: un snapshot de la salida de
`sanitizeTraces` para una spec de barra divergente con `marker.color` por barra y x con signo.

**Depends on / blocked by:** Ninguno. El fix backend de #320 es independiente; este TODO es hardening
de cobertura FE.
