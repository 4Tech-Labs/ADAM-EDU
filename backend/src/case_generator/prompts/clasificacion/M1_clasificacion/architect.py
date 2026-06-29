"""M1 Case Architect prompt - clasificacion family.

``CASE_ARCHITECT_PROMPT_CLASSIFICATION`` is assembled as the single-source generic
base (``CASE_ARCHITECT_PROMPT`` from ``case_generator.prompts._architect_base``) plus
``_M1_CLASSIFICATION_ANCHOR_ARCHITECT``. No verbatim copy of the base is kept in sync -
editing the base in ``_architect_base.py`` propagates here automatically.

The anchor block uses ONLY variables confirmed to be present in ``_build_base_context()``:
  {student_profile}, {primary_family}, {output_language}, {course_level},
  {max_investment_pct}, {case_id}, {urgency_frame}
and the context injected by ``case_architect`` itself:
  {teacher_input}
"""

from case_generator.prompts._architect_base import CASE_ARCHITECT_PROMPT

# ── Classification-specific anchor ────────────────────────────────────────────
# This block is appended after the generic case architect instructions.
# It enforces constraints that guarantee M1 ↔ downstream coherence for all
# classification-family cases (family = "clasificacion").
# Zero new format variables: all keys here exist in _build_base_context().
_M1_CLASSIFICATION_ANCHOR_ARCHITECT = """

# ── Instrucción de familia: Clasificación ─────────────────────────────────────
# Este bloque se activa ÚNICAMENTE porque el docente eligió un algoritmo de la
# familia `clasificacion`. Refuerza restricciones que garantizan coherencia entre
# M1 y los módulos de análisis y notebook downstream.

## Contrato obligatorio para casos de clasificación

1. **`dataset_schema_required.target_column.role` DEBE ser `classification_target` y
   `dtype` DEBE ser `int` binario (valores 0/1).**
   El target debe representar un evento binario (ocurre / no ocurre) directamente observable
   y accionable en producción.  Ejemplos correctos: `churn_flag`, `default_60d`,
   `approval_flag`, `fraud_flag`, `late_delivery_flag`.
   NUNCA uses un target continuo (`revenue`, `margin_pct`), un índice compuesto, ni un
   target multiclase (más de dos clases): en esta familia el evento es SIEMPRE binario.

2. **`pregunta_eje` es OBLIGATORIA cuando `student_profile = "ml_ds"` — NUNCA `null` para ese perfil en esta familia.**
   La regla del contrato base (encima de este bloque) sigue vigente:
   - Si `student_profile = "ml_ds"` → emitir `pregunta_eje` como pregunta directiva gerencial.
   - Si `student_profile = "business"` → emitir `null` (el sanitizador de graph.py lo forzará igualmente).
   La pregunta debe plantear una decisión ejecutiva que requiere clasificar entidades (clientes,
   transacciones, solicitudes) en dos categorías mutuamente excluyentes (intervenir / no intervenir).
   Formulación correcta:
     "¿A qué segmentos debe la empresa priorizar intervención para reducir la pérdida
     financiera por incumplimiento sin sobrecargar al equipo de riesgo?"
   Formulación PROHIBIDA (es técnica, no ejecutiva):
     "¿Qué modelo tiene mayor AUC?" / "¿Cuál es el threshold óptimo?"

3. **Opciones A/B/C en `dilema_brief`:** Al menos una opción debe presentar,
   en lenguaje gerencial, el trade-off entre los dos tipos de error de decisión:
   - Error de comisión: intervenir donde no era necesario (costo de acción innecesaria).
   - Error de omisión: no intervenir donde sí era urgente (costo de inacción).
   NO uses los términos técnicos "falso positivo" ni "falso negativo". Exprésalos como:
   "el riesgo de destinar recursos donde el problema no existía" frente a
   "el riesgo de no actuar donde la pérdida era evitable".

**Conteo de opciones en `dilema_brief` (anula la regla base de nivel de curso):** en
clasificación, `dilema_brief` SIEMPRE contiene exactamente 3 opciones (A, B, C), también
para `undergrad`. Esta regla REEMPLAZA la línea base de nivel de curso que sugiere
"2 opciones estratégicas claras" para undergrad: en esta familia, undergrad emite 3
opciones igual que grad. Las 3 son igualmente presentables pero no igualmente óptimas
(como ya exige la regla base de balance A/B/C). Son 3 opciones de DECISIÓN gerencial;
no 3 clases del target.

4. **Exhibit 2 (Operativo) — 2 filas obligatorias de calidad de datos:**
   Añade exactamente 2 filas numéricas y específicas que capturen la realidad del
   evento objetivo en los datos históricos de la empresa:
   - Tasa de ocurrencia del evento objetivo (ej: "Tasa histórica de abandono: 8.3 %").
     Este porcentaje DEBE ser el MISMO número que emites en
     `dataset_schema_required.target_event_rate`, expresado como fracción (8.3 % ⇔ 0.083).
     El generador determinista del dataset calibra la columna objetivo a esa prevalencia,
     de modo que si Exhibit 2 y `target_event_rate` difieren, el caso queda incoherente
     (el estudiante vería en el dataset una proporción distinta a la que anuncia el caso).
   - Completitud de campos críticos (ej: "% registros con campo contractual sin dato: 12 %").
   Esta instrucción REEMPLAZA la regla base de "al menos 2 métricas de calidad de datos"
   de Exhibit 2: para clasificación las 2 filas de calidad de datos son EXACTAMENTE las dos
   anteriores (tasa de ocurrencia del evento objetivo + completitud de campos críticos) y
   ninguna otra. No uses otras filas genéricas de plumbing como las 2 filas obligatorias.

## Matriz de costos de negocio (`business_cost_matrix`) — opcional, condicional

Emite `business_cost_matrix` SOLO para el perfil ml_ds con target binario (matriz de
confusión 2×2). Para el perfil business, target multiclase, u otras familias: NO la
emitas (déjala ausente / `null`).

Esta clave CUANTIFICA los dos errores de decisión que la regla 3 ya te obligó a narrar
en el dilema:
- `fp_cost` = costo del error de comisión (intervenir/actuar donde NO hacía falta).
- `fn_cost` = costo del error de omisión (NO actuar donde la pérdida era evitable).
Deriva ambos números del `dilema_brief` y de los Exhibits financieros (Exhibit 1/2):
deben ser TRAZABLES al caso, NUNCA inventados. Anclaje típico: `fn_cost` ≈ pérdida de
no detectar el evento (LTV del cliente perdido, monto del fraude no bloqueado);
`fp_cost` ≈ costo de la acción innecesaria (retención/descuento regalado, revisión
manual sin causa).

Condición de emisión (si NO se cumple, deja la clave ausente / `null`):
- SOLO cuando los costos de mala clasificación sean genuinamente ASIMÉTRICOS y
  derivables del caso. Si son simétricos o no inferibles → `null` (no fabriques una
  asimetría).

Valores VÁLIDOS o el pipeline la descarta en silencio:
- `fp_cost` y `fn_cost` ambos > 0 y finitos; cada uno ≤ 1e9.
- ratio max(fp,fn)/min(fp,fn) ≤ 1000:1 (en cualquier dirección).
- `currency` SIEMPRE "USD" (el caso entero está en dólares — ver la regla global de
  moneda). No uses ninguna otra moneda.

Ubicación EXACTA: añade `business_cost_matrix` como clave ANIDADA dentro de
`dataset_schema_required` (junto a `target_column` / `feature_columns`), NUNCA como
clave de nivel superior. La regla base "NO incluir claves extra" aplica a las claves de
NIVEL SUPERIOR; este es un sub-campo declarado y validado del schema, no una clave extra.

Forma exacta (dentro de `dataset_schema_required`):
{{
  "business_cost_matrix": {{
    "fp_cost": 200,
    "fn_cost": 5000,
    "currency": "USD"
  }}
}}

## Tasa de ocurrencia del evento (`target_event_rate`) — ml_ds clasificación binaria

Emite `target_event_rate` SOLO para el perfil ml_ds con target binario de clasificación
(el mismo gate que `business_cost_matrix`). Es la fracción de la población que presenta el
evento objetivo, y DEBE ser el MISMO número que la fila "Tasa de ocurrencia del evento" de
Exhibit 2, expresado como fracción en [0.01, 0.50] (8.3 % → 0.083). El generador determinista
del dataset calibra la columna objetivo a esta prevalencia (fuente única M1↔M2). Para business,
target multiclase u otras familias: NO lo emitas (déjalo ausente / `null`).

Ubicación EXACTA: clave ANIDADA dentro de `dataset_schema_required` (junto a `target_column`
/ `business_cost_matrix`), NUNCA como clave de nivel superior.

Forma exacta (dentro de `dataset_schema_required`):
{{
  "target_event_rate": 0.083
}}
"""

# ── business + clasificación: bloque de target binario de dominio (Issue #301 PR2b) ──
# Se AÑADE en tiempo de ensamblado (graph._assemble_architect_prompt) SOLO cuando
# `student_profile == "business"` y la familia es `clasificacion`. NO se concatena al
# prompt constante, de modo que el prompt ensamblado para ml_ds queda byte-idéntico
# (el snapshot de Item 4 lo vigila — Riesgo #1).
#
# Resuelve la contradicción que para business+clasificación dejan las reglas base
# (rule 7 / `dataset_schema_required`: "business puede emitir null/continuo"): el ancla ya
# exige `classification_target`, y este bloque lo hace explícito para business y empuja un
# NOMBRE de dominio (la forma binaria la garantiza además el spine determinista downstream).
#
# Sin llaves `{}` → seguro para `str.format()` (no introduce placeholders).
M1_CLASSIFICATION_BUSINESS_TARGET_BLOCK = """

# ── Instrucción business + clasificación: target binario de dominio ───────────
# Activo SOLO para perfil "business" en la familia `clasificacion`. Anula la opción de
# target gerencial continuo/`null` de las reglas base: en clasificación el caso DEBE
# resolverse con un evento binario, también para business.

1. `dataset_schema_required.target_column` es OBLIGATORIO (nunca `null` en clasificación).
2. `role` DEBE ser `classification_target` y `dtype` DEBE ser `int` binario (valores 0/1).
   PROHIBIDO un target continuo (`revenue`, `margin_pct`) o un índice compuesto.
3. El `name` debe nombrar el EVENTO del dilema en snake_case inglés, terminado en `_flag`
   cuando sea natural — deriva el nombre del sustantivo central del título:
     - incumplimiento / entrega de socios → `late_partner_flag`
     - fraude → `fraud_flag`
     - mora / default crediticio → `default_60d`
     - abandono / churn → `churn_flag`
   Evita el genérico `target_event_flag` salvo que el dilema no sugiera ningún evento concreto.
4. Declara al menos 1 feature de dominio con señal plausible hacia ese evento (no leakage).
5. `dataset_schema_required.target_event_rate` es OBLIGATORIO para este caso: la fracción de la
   población con el evento (target = 1), un decimal en el rango [0.01, 0.50] (8.3 % → 0.083).
   DEBE ser EXACTAMENTE el MISMO número que la fila «Tasa de ocurrencia del evento objetivo» que
   imprimes en Exhibit 2 (regla 4 del ancla). El generador determinista del dataset calibra la
   columna objetivo a esa prevalencia (fuente única M1↔M2), de modo que el dataset y Exhibit 2
   coinciden por construcción. IMPORTANTE: esta instrucción ANULA, para business + clasificación,
   la nota de la sección base «Tasa de ocurrencia del evento (`target_event_rate`)» que dice que
   solo se emite para ml_ds — para este perfil SÍ debes emitirla.
"""


# ── Full prompt: generic base + classification anchor ─────────────────────────
CASE_ARCHITECT_PROMPT_CLASSIFICATION = CASE_ARCHITECT_PROMPT + _M1_CLASSIFICATION_ANCHOR_ARCHITECT
