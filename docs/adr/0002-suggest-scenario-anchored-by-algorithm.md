# ADR 0002: Anclar la sugerencia de escenario al algoritmo elegido

- Status: Accepted
- Date: 2026-05-?? (post Issue #233)
- Related: GitHub `#230` (canonical algorithm catalog), `#233` (M3 per-family dispatch)
- Branch: `feature/authoring-scenario-anchored-to-algorithm`

## Contexto

Con la consolidación del catálogo canónico 4×2 (Issue #230 + #233) la elección de
algoritmo dejó de ser texto libre y pasó a ser una decisión de **familia**
(`clasificacion`, `regresion`, `clustering`, `serie_temporal`). Sin embargo, la
sugerencia de escenario y dilema (`POST /api/suggest` con `intent ∈ {scenario, both}`)
seguía generándose **antes** de elegir el algoritmo y sin recibir esa elección como
contexto. El profesor podía terminar con un caso de pronóstico de demanda y un
algoritmo de clasificación, exigiendo tirar y reescribir el escenario manualmente —
la peor experiencia para el formulario más crítico del producto.

## Decisión

1. **Picker-first en el formulario.** Cuando `caseType === harvard_with_eda` o
   `studentProfile === ml_ds`, el `AlgorithmSelector` se renderiza **antes** de la
   `Descripción del Escenario`. El botón "Sugerir Caso y Dilema" queda
   `disabled` (con tooltip explicativo en español) hasta que la pareja
   `algorithm_mode + algorithm_primary [+ algorithm_challenger]` sea válida.
2. **Anclaje en el prompt.** `case_generator.suggest_service._build_prompt` añade,
   **al final** del prompt y solo cuando hay picks resueltos en el catálogo, un
   bloque `# Anclaje del Algoritmo Elegido por el Docente` con la familia, el algoritmo, el
   modo y un *target hint* específico de la familia. Si los picks están ausentes o
   son off-catalog, el bloque se omite y el prompt es **byte-equivalente** al
   anterior — garantía de no romper flujos legacy.
3. **Coherence check post-LLM.** Tras la respuesta del modelo,
   `_check_scenario_family_coherence` compara `resp.problemType` contra
   `family_of(req.algorithmPrimary)` y, si difieren, escribe un advisory en
   `resp.coherenceWarning` (string en español, no bloqueante).
4. **Banners no bloqueantes en el frontend.** `ScenarioStaleBanner` cubre dos casos:
   - `variant="stale"` (ámbar, con botón **Regenerar**) cuando el profesor cambia el
     algoritmo después de generar un escenario. El fingerprint
     `{mode, primary, challenger}` se snapshot a la hora del **request**, no del
     success, para no enmascarar carreras.
   - `variant="warning"` (naranja) cuando el backend devuelve `coherenceWarning`.
   La edición manual del textarea limpia el banner stale (el profesor reconoce el
   cambio).
5. **Catalog drift contrato.** `FORM_STATE_SESSION_KEY` se sube de `v2` a `v3` para
   invalidar formularios persistidos que pudieran traer algoritmos eliminados (mismo
   patrón que la remoción de LSTM). El `AlgorithmSelector` ya valida picks contra el
   catálogo en mount.

## Garantías de compatibilidad

- El backend **acepta** payloads sin `algorithmPrimary` / `algorithmChallenger` (campos
  opcionales). En ese caso el anchor se omite y el comportamiento es el legacy.
- En el modo legacy `harvard_only + business` el picker no se renderiza y el botón de
  sugerencia no se gatea (verificado por test `does NOT gate the scenario button in
  legacy harvard_only + business mode`).
- `extra="forbid"` se preserva en `SuggestRequest` — los campos nuevos están
  declarados explícitamente.
- `coherenceWarning` es **opcional** en `SuggestResponse`; clientes existentes que
  ignoren el campo siguen funcionando.

## Por qué NO bloquear el submit ante un coherenceWarning

El profesor tiene autoridad final sobre el caso. La IA es consultiva. Bloquear el
submit por una verificación heurística (string-matching de `problemType` ↔ family)
generaría falsos positivos y fricción inaceptable. El banner orange comunica el
riesgo; la decisión queda con el humano.

## Por qué el anchor va al **final** del prompt

Recency bias documentado en LLMs: la información más cercana al final tiene mayor
peso en la generación. El anchor es el constraint duro; el contexto pedagógico de
arriba sigue siendo necesario pero secundario al algoritmo elegido.

## Tests

- Backend: `backend/tests/test_suggest_scenario_anchor.py` (13 tests + 1 live LLM
  smoke), cubre schema accept/reject, byte-equality del prompt sin picks, inclusión
  del anchor con picks, salto seguro ante algoritmos off-catalog, coherence-check
  unit y dos escenarios end-to-end mockeados.
- Frontend: `AuthoringForm.test.tsx` Task 4 (6 tests) — DOM order picker→textarea,
  gating del botón, payload `algorithmPrimary`, banner warning, banner stale +
  clear-on-edit, modo legacy intacto.

## Telemetría futura (no en esta PR)

Medir tasa de `coherenceWarning` por familia y tasa de regeneración tras stale
banner. Si la tasa de warning supera ~5% conviene fortalecer el prompt o introducir
un suite de evaluaciones offline. Anotado en `TODOS.md`.
