# ADR 0003: M4 agnóstico al caso vía un Impact Lens cross-módulo

- Status: **Proposed** (decisiones §11 pendientes de ratificar — sin código aún)
- Date: 2026-06-25
- Related: auditoría del Módulo 4 "Arquitecto Financiero"; ADR `0002` (anclaje por algoritmo); GitHub `#243`/`#337` (grounding de métricas), `#330` (variantes M4/M5), `#360`/`#361` (coherencia M1/P3), `#370`/`#377` (moneda USD), `#430` (grounding de charts M4)
- Branch: `claude/nervous-colden-091c9d`

## Contexto

El Módulo 4 modela el "impacto" de una intervención analítica como un **sinónimo
hardcodeado de ROI financiero**, sembrado en M1 y forzado en M4, con una instrucción
explícita de **fabricar** cifras cuando faltan datos. Un caso de salud, manufactura o
educación recibe un Exhibit P&L y un veredicto ROI/Payback/NPV forzado, sea o no
pertinente al dominio.

### Veredicto de la auditoría (verificado contra fuente)

La teoría *"M4 corre siempre con ROI/Payback/NPV/$ hardcodeados y fuerza un marco
financiero que el LLM debe inventar para dominios no comerciales"* es **CIERTA**:

- M4 es literalmente "el **Arquitecto Financiero**" (`prompts/_shared.py:166-173`); la
  tabla KPI §4.5 fuerza ROI/Payback/NPV para ambos perfiles (`_shared.py:230-235,266-271`);
  los charts son "EXACTAMENTE 2 gráficos financieros" (`prompts/__init__.py:917-955`).
- **Cero ramificación por dominio.** El routing (`route_master`, `_resolve_generation_focus`
  en `graph.py`) resuelve la familia solo desde los algoritmos; nunca lee `industria`. El
  `industry` de intake es `str` libre sin validación (`shared/app.py:654`).
- El daño concreto es la **fabricación sancionada**: los prompts ordenan
  *"Valores estimados basados en benchmarks de {industria}"* cuando faltan números
  (`prompts/__init__.py:960-962`, `prompts/_shared.py:190-194`).
- El marco se **siembra en M1**: Exhibit 1 P&L (`prompts/_architect_base.py:125-128`),
  regla de inversión (`:35-44`), USD-only (`:74-76`), y la regla de balance de opciones
  "A=mayor ROI" (`:61-65`) — todo bajo el lock `_MLDS_ARCHITECT_PROMPT_SHA256`. Por eso un
  cambio solo-M4 produciría un caso **incoherente**.

### Severidades corregidas (verificadas; otras superficies son menos profundas)

`M6` verdicts están atados por drift-test y son verbos neutros
(`teaching_note/module_guide_block.py:55-56`, `test_m4_verdict_literals_bound_to_source`);
la matriz de `M5` ya admite framing no-financiero
(`clasificacion/M5_clasificacion/narrative.py:57-64`); el label del frontend ya es
"Impacto", no "Finanzas" (`shared/case-viewer/caseViewerConfig.ts:43-45`); `M3` **no** está
acoplado. El conjunto real en lockstep es **M1 architect + M4**.

### Riesgo verdadero para los cohortes de clasificación (verificado, 7 agentes + red-team)

El eje del riesgo es el **DOMINIO, no el cohorte** — clasificación es de hecho la familia
mejor blindada:

- **Eje dominio (MEDIO, sistemático):** un caso clf en salud/educación/manufactura recibe
  el mismo §4.5 ROI/NPV forzado + la P2 *"¿El ROI justifica la inversión?"*
  (`M4_clasificacion/questions.py:87`). Ningún guard lo detecta porque el grounding vigila
  el anclaje de números, no la pertinencia del marco al dominio. Afecta a **ambos cohortes
  por igual**.
- **Eje fabricación (BAJO/medio):** la fabricación *peligrosa* — una métrica de modelo
  inventada — sí está blindada para clf (anclaje vía `validate_narrative_grounding` +
  chart grounding `#430`). Pero los **números de negocio** ($/ROI/NPV) no los valida nadie
  en ningún cohorte, **por diseño explícito** (`narrative_grounding.py:152-158` exime las
  cifras de negocio). Severidad baja: convención de caso de enseñanza, revisada por el
  docente, acotada por #360/#361 upstream.
- **Asimetría:** `business+clf` tiene menos red que `ml_ds+clf` — su narrative grounding
  está deshabilitado (business nunca ejecuta notebook M3, `graph.py:7529-7531` →
  `grounding_enabled=False`; anclaje de métricas y leak guard no-op).
- **Grieta concreta:** la invitación a fabricar "benchmarks de {industria}" sigue viva en
  el prompt BASE de narrativa (`_shared.py:190-194`, fallback `harvard_only`); la
  prohibición solo se añadió a charts + bloque business. `ml_ds+clf` usa esa base.

**Resultado:** clf en dominio comercial (retail/fintech/telecom) = riesgo BAJO; clf en
dominio no comercial = riesgo MEDIO y sistemático. El riesgo no es inherente al cohorte;
es `dominio-no-comercial × marco-financiero-forzado`, y clf no está exento.

## Decisión

Introducir un **Impact Lens** de primera clase: el *marco de valor* (métrica primaria,
filas KPI, semántica de charts, framing del veredicto) pasa a ser una variable ortogonal
tanto al **dominio** como a la **familia de algoritmo**, mientras se conserva la
*estructura* reutilizable de M4 (5 secciones, opciones A/B/C con trade-offs, veredicto,
tabla KPI, 2 charts).

- **DD1 — Una lente, resuelta una vez, consumida en todas partes.** La lente es un único
  valor canónico en el estado del grafo, resuelto por un helper `_resolve_impact_lens(state)`
  (espejo de `_resolve_primary_family` / `_resolve_generation_focus`) e inyectado en las
  opciones de M1, los 3 nodos M4, el ejemplo de M5 y los labels de M6. Es el invariante que
  evita la incoherencia *M4-habla-clínico / M5-habla-ROI*. Una sola fuente de verdad.
- **DD2 — Resolver la lente desde el valor CONSTREÑIDO de intake, no del `industria` libre.**
  El architect reescribe `industria` a un sustantivo libre, inseguro de parsear. El
  `industry` de intake (dropdown de 7 valores, persistido en `task_payload`) es
  determinista. Mapear esos 7 → lente vía dict estático; `"General"`/desconocido →
  `financial_roi`. Sin NLP difuso, sin dependencia del LLM para el default.
- **DD3 — Los costos siguen en USD; la lente reencuadra solo el lado del VALOR.** Salud,
  educación y operaciones usan **cost-effectiveness** ($/outcome) — el dinero no
  desaparece, cambia la métrica titular. La lente intercambia la métrica de valor primaria
  y las filas KPI (ROI/NPV → outcome-por-costo), pero el lado costo sigue en USD,
  preservando la decisión USD-only (#370/#377), `business_cost_matrix` y los financieros de
  Exhibit. **Unidades de valor puramente no monetarias quedan fuera de alcance (requieren
  ADR aparte).** Esta decisión elimina lo más rompible de cualquier intento naïf de "hacerlo
  no financiero".
- **DD4 — Conservar la estructura, variar solo el marco.** Opciones A/B/C, esqueleto
  §4.1–4.5, veredicto, tabla KPI y el contrato de 2 charts se mantienen. El renderer del
  frontend, el schema y el allowlist de `case_sanitization` no cambian.
- **DD5 — `financial_roi` es byte-idéntico a hoy.** El bloque de lente `financial_roi`
  reproduce el texto de prompt actual verbatim (patrón `*_LEGACY` probado), y el dispatch es
  identidad para business/comercial. Un diff main↔branch sobre un caso financiero business y
  ml_ds+clf es un **gate de aceptación duro**.

### Catálogo de lentes (`IMPACT_LENS_CATALOG`, espejo de `ALGORITHM_CATALOG`)

| Lente | Dominios de intake | Métrica de valor primaria | Filas KPI (reemplazan ROI/Payback/NPV) |
|---|---|---|---|
| `financial_roi` *(default; = hoy)* | retail, fintech, telecomunicaciones, General | valor USD, ROI | Payback, ROI, NPV |
| `operational_efficiency` | manufactura, logistica | tasa de defecto/scrap, downtime, throughput | Δ tasa, Δ downtime/OEE, $/unidad evitada |
| `clinical_outcomes` | salud | eventos/readmisiones evitadas, $/outcome | outcomes evitados, cost-effectiveness $/outcome, riesgo de seguridad |
| `learning_outcomes` | educacion | retención/graduación %, ganancia de aprendizaje | Δ retención, $/estudiante-retenido, equidad |

Regla transversal a **toda** lente (incl. `financial_roi`): sin benchmarks externos
fabricados; derivar de Exhibits/M2/M3 o aritmética declarada; si no hay dato, la sección es
**cualitativa** (patrón ya usado en `M4_CHART_LR_BUSINESS_BLOCK` y el bloque de costo P3 #361).

### Resolución, contrato y modos de fallo

- **Resolver:** `_resolve_impact_lens(state)` → clave de catálogo. Orden: `impact_lens`
  explícito del docente (si §11 D-A lo adopta) → `value_model.lens` emitido por el architect
  → mapa estático del `industry` de intake → `financial_roi`.
- **Contrato del architect (Fase 2):** objeto opcional `value_model` en `CaseArchitectOutput`
  (`tools_and_schemas.py:271`): `{ lens, primary_metric_name, unit, kpi_rows }`. Un
  normalizador determinista (espejo de `_validate_business_cost_matrix` / `_normalize_currency`)
  coacciona una lente inválida/ausente al default de intake — **coerce, nunca reject** (la
  disciplina #370; un `raise` nulificaría toda la salida del architect).
- **Modos de fallo:** architect omite `value_model` → default de intake; `industry`
  desconocido → `financial_roi`; el LLM ignora el bloque de lente → el detector de
  fabricación sigue corriendo y el mismatch de filas KPI es señal **logger-only** (nunca falla
  el job); nueva familia de algoritmo → la lente es ortogonal, hereda con cero trabajo de marco.

### Fases (cada una shipea y se revierte sola, con gate de tests)

0. **Matar la fabricación forzada.** Quitar/neutralizar la instrucción "benchmarks de
   {industria}" en los prompts genéricos de chart + narrativa; degradar a cualitativo si
   faltan números. Extender el detector puro `m4_grounding.detect_benchmark_fabrication` (hoy
   solo charts clf) a charts + narrativa genéricos para todos los perfiles/familias. Kill-switch
   + golden oracle. **Independiente de las 4 decisiones; máximo valor, mínimo riesgo, shipea
   sola.**
1. **Catálogo de lentes + dispatch en M4 (sin tocar el architect).** `IMPACT_LENS_CATALOG`,
   `_resolve_impact_lens`, default desde el dropdown, bloques de lente cortos y aditivos en los
   3 nodos M4. Kill-switch `IMPACT_LENS` (default-on). *Limitación honesta:* hasta la Fase 2 el
   Exhibit 1 P&L y las opciones "A=mayor ROI" siguen financieras, así que el reencuadre es
   parcial — pero nunca fabricado, y `financial_roi` byte-idéntico.
2. **El architect emite `value_model` + Exhibit 1 / dimensiones de opción acordes a la lente.**
   Toca el architect SHA-locked — deliberado, con el diff-lock actualizado y el diferencial tipo
   `test_mlds_architect_prompt_unchanged_by_business_gate` verde primero.
3. **Override del docente + parametrización del ejemplo M5/labels M6 + generalización del
   grounding + golden gates por lente.**

## Garantías de compatibilidad

- `financial_roi` default = byte-idéntico para business + dominios comerciales actuales (DD5,
  gate de diff).
- Nueva clave de estado resuelta `impact_lens` (y `value_model` en Fase 2) — solo prompt-side;
  **no** es clave canónica visible al estudiante → sin entrada en `case_sanitization`, sin
  migración de DB, sin fuga al estudiante. Tolerada por resume (`_is_resumable_state_value`),
  live preview y `regenerate-notebook`.
- Casos ya generados no se reprocesan (precedente de todo cambio M4 en CLAUDE.md).
- Kill-switches (Fase 0 y Fase 1) son campos `Settings`, default-on, documentados en
  `backend/.env.example` (patrón `MLDS_DECHURN_SIGNAL` / `M4_CHART_GROUNDING`).

## Registro de riesgos

| # | Riesgo | Mitigación |
|---|---|---|
| R1 | El refactor rompe la identidad byte del cohorte financiero dominante | DD5 bloque verbatim + diff test main↔branch como gate duro; kill-switch |
| R2 | Incoherencia cross-módulo (M4 lente ≠ M5/M6) | DD1 una sola lente resuelta consumida por todos; test cross-módulo |
| R3 | La lente se resuelve mal desde un industry libre | DD2 resolver desde el dropdown constreñido; default seguro `financial_roi` |
| R4 | El cambio SHA-lock desestabiliza M1 | Fase 2 aislada; diff-lock + diferencial business-gate verde primero; normalizador coerce-no-reject |
| R5 | El LLM ignora el bloque de lente | señal logger-only de mismatch (nunca falla el job); el detector de fabricación sigue activo |
| R6 | Conflicto matriz de costos / USD-only para lentes "no financieras" | **Neutralizado por DD3**: los costos siguen en USD; solo reencuadra el valor |
| R7 | La generalización del grounding causa tormenta de falsos positivos | mantener grounding prompt-led + el `detect_benchmark_fabrication` zero-FP; no construir anclas numéricas por-unidad |
| R8 | Tokens extra degradan la fiabilidad de los nodos Pro | bloques de lente cortos + aditivos; monitorear `cost_breakdown` |
| R9 | Cobertura golden por lente cara | fasear el eval; un golden por lente + `live_llm` opt-in |
| R10 | "Más algoritmos" aún requiere trabajo M4 por familia | la ortogonalidad reduce pero no elimina; documentado |

## Decisiones abiertas (a ratificar antes de implementar P1+)

- **D-A — Señal de la lente:** recomendado híbrido — default determinista del dropdown de
  intake, con override opcional `impact_lens` del docente y `value_model` del architect como
  señal secundaria.
- **D-B — Set inicial de lentes:** recomendadas las 4 de arriba. Alternativa: lanzar Fase 1 con
  `financial_roi` + `operational_efficiency` + una lente genérica `non_financial_outcomes`.
- **D-C — Blast radius del architect (Fase 2):** aceptar la regeneración de
  `_MLDS_ARCHITECT_PROMPT_SHA256` para arreglar el seed Exhibit-1/opciones, o que M4 reencuadre
  los exhibits financieros existentes (más barato; coherencia parcial).
- **D-D — Unidades de costo:** confirmar DD3 (costos en USD, framing cost-effectiveness). Si
  alguna vez se requieren unidades de valor puramente no monetarias, es un ADR aparte.

## Fuera de alcance (ADR aparte)

Unidades de valor puramente no monetarias / multi-moneda; retirar o reestructurar
`business_cost_matrix`; cambiar la metodología de M3 (no acoplada); cualquier salida de la
decisión USD-only o de la infraestructura Supabase-native.

## Verificación (para la implementación eventual)

- **Por fase, todo verde:** `uv run --directory backend pytest -q`,
  `uv run --directory backend mypy src`, `npm --prefix frontend run lint|test|build`.
- **Gate R1:** diff main↔branch = cero en un caso `financial_roi` business y uno ml_ds+clf
  (kill-switch on y off).
- **Gate R2:** test cross-módulo que asserte que `impact_lens` resuelto es un único valor
  consumido por M1/M4/M5/M6 para un caso salud/educación/manufactura.
- **Gate Fase 0:** charts/narrativa generados sin la nota "benchmarks de {industria}" en
  cualquier perfil/familia; `detect_benchmark_fabrication` dispara con un número fabricado
  sintético.
- **E2E por lente:** un caso por lente; §4.5 usa KPIs acordes (sin ROI/NPV forzado en una
  lente no financiera); charts/preguntas coherentes.
- **Golden:** oráculo nuevo en `tests/golden_eval.py` (coherencia lente↔KPI + sin fabricación)
  cableado a `evaluate_downgrade_gate`; `live_llm` opt-in por lente.

## Telemetría futura (no en este ADR)

Medir la distribución de lentes resueltas por `industry`, la tasa de mismatch logger-only de
filas KPI (señal de que el LLM ignora la lente) y la tasa de degradación cualitativa por falta
de cifras. Si la lente se resuelve mal con frecuencia, endurecer el dict de intake o el
contrato `value_model` del architect.

## Extensiones posteriores (no alteran las decisiones de arriba)

- **#505 — 5ª lente `environmental_outcomes` + industria "Medio ambiente / Sector público".**
  Economía ambiental / valoración contingente: el VALOR se reencuadra a servicios ecosistémicos,
  costo por hectárea conservada/restaurada y disposición a pagar (WTP) agregada (kpi_rows en
  lenguaje natural; DD3 intacto: costos en USD). Extensión PURAMENTE ADITIVA del catálogo D-B
  (4 → 5 lentes) y del dropdown de industria (7 → 8); reusa los kill-switches `IMPACT_LENS` /
  `IMPACT_LENS_ARCHITECT` (sin switch nuevo). El bloque del architect enumera la 5ª lente
  (regenera `_MLDS_ARCHITECT_LENS_PROMPT_SHA256`; el off-path queda intacto) para que el camino
  industria-default sea coherente con el override docente. Sin nueva clave canónica/state/
  `case_sanitization`/migración.
