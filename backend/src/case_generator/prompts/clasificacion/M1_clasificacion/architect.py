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

1. **`dataset_schema_required.target_column.role` DEBE ser `classification_target`.**
   El target debe representar un evento binario o multiclase directamente observable
   y accionable en producción.  Ejemplos correctos: `churn_flag`, `default_60d`,
   `approval_flag`, `fraud_flag`, `late_delivery_flag`.
   NUNCA uses un target continuo (`revenue`, `margin_pct`) ni un índice compuesto.

2. **`pregunta_eje` es OBLIGATORIA cuando `student_profile = "ml_ds"` — NUNCA `null` para ese perfil en esta familia.**
   La regla del contrato base (encima de este bloque) sigue vigente:
   - Si `student_profile = "ml_ds"` → emitir `pregunta_eje` como pregunta directiva gerencial.
   - Si `student_profile = "business"` → emitir `null` (el sanitizador de graph.py lo forzará igualmente).
   La pregunta debe plantear una decisión ejecutiva que requiere clasificar entidades (clientes,
   transacciones, solicitudes) en categorías mutuamente excluyentes.
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

4. **Exhibit 2 (Operativo) — 2 filas obligatorias de calidad de datos:**
   Añade exactamente 2 filas numéricas y específicas que capturen la realidad del
   evento objetivo en los datos históricos de la empresa:
   - Tasa de ocurrencia del evento objetivo (ej: "Tasa histórica de abandono: 8.3 %").
   - Completitud de campos críticos (ej: "% registros con campo contractual sin dato: 12 %").
   Sin estas filas el `schema_designer` downstream no puede modelar el desbalance de
   clases real del caso, comprometiendo la coherencia pedagógica del notebook M3.
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
"""


# ── Full prompt: generic base + classification anchor ─────────────────────────
CASE_ARCHITECT_PROMPT_CLASSIFICATION = CASE_ARCHITECT_PROMPT + _M1_CLASSIFICATION_ANCHOR_ARCHITECT
