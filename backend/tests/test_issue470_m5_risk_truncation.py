"""Issue #470 — el string de "riesgo principal" inyectado en el memo M5 ya no se trunca a media
palabra/cláusula.

Root cause: ``_extract_main_risk`` (closure dentro de ``_build_base_context`` en ``graph.py``)
recortaba con ``text[:200]`` DURO en sus tres rutas de retorno, dejando fragmentos crudos como
«…(cuyo rango va de 5» en la consigna y la solución del memo (visibles al estudiante). El fix
introduce el helper PURO ``_truncate_risk_text`` que colapsa whitespace y corta en frontera de
oración (preferida) o de palabra (fallback ``textwrap.shorten`` + «…»).

El fix es GENERAL (corre para TODAS las familias vía el prompt de preguntas M5 genérico
``M5_QUESTIONS_GENERATOR_PROMPT`` y el de clasificación ``M5_QUESTIONS_PROMPT_CLASSIFICATION``);
NO se gatea por familia ni perfil.
"""

from __future__ import annotations

import re

from case_generator.graph import (
    _MAX_RISK_CHARS,
    _build_base_context,
    _truncate_risk_text,
)
from case_generator.prompts import M5_QUESTIONS_GENERATOR_PROMPT
from case_generator.prompts.clasificacion.M5_clasificacion.questions import (
    M5_QUESTIONS_PROMPT_CLASSIFICATION,
)

# La cadena de riesgo EXACTA del caso real "EduVanguard" (#470). 304 chars → el viejo [:200]
# cortaba en «…va de 50 » (el síntoma reportado «va de 5»).
_LIVE_RISK = (
    "La extrema disparidad de magnitudes detectada en el análisis forense. Si el módulo se "
    "ejecuta sin aplicar previamente un StandardScaler, la amplitud de la variable monetary_value "
    "(cuyo rango va de 50 a 5000) dominaría el cálculo de distancias euclidianas, sesgando por "
    "completo la formación de clústeres."
)

_DANGLING_FRAGMENTS = ("va de 5", "va de 50")


def _placeholders(template: str) -> set[str]:
    """Nombres de placeholder ``{x}`` de un template (ignora ``{{`` escapados)."""
    return set(re.findall(r"(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_]*)\}(?!\})", template))


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _assert_no_midword_cut(result: str, source: str) -> None:
    """El resultado (quitando una elipsis final) es un prefijo word-boundary del texto normalizado:
    o es el texto completo, o el char siguiente en el origen es un espacio."""
    body = result.rstrip("…").rstrip()
    norm = _normalized(source)
    assert norm.startswith(body), f"resultado no es prefijo del origen normalizado: {result!r}"
    cut_at = len(body)
    assert cut_at == len(norm) or norm[cut_at] == " ", (
        f"corte a media palabra en posición {cut_at}: {result!r}"
    )


# ── 1. Helper puro: contrato de corte limpio ──────────────────────────────────


def test_old_hard_slice_lost_the_number_demonstrating_the_bug() -> None:
    """Regresión histórica (#470): el viejo `text[:200]` DURO perdía «a 5000» (cortaba en
    «va de 50»); el fix conserva el número completo. Lock before/after del defecto."""
    old = _LIVE_RISK[:200]
    assert "va de 50" in old and "50 a 5000" not in old, "el viejo corte debía truncar el número"
    new = _truncate_risk_text(_LIVE_RISK)
    assert "50 a 5000" in new, "el fix debe conservar el número completo"
    assert new != old


def test_live_repro_risk_is_complete_not_truncated() -> None:
    """El string EXACTO de la demo #470 ya NO se corta a media cláusula."""
    out = _truncate_risk_text(_LIVE_RISK)
    assert out, "resultado vacío"
    # 304 <= 320 → se devuelve completo, con «50 a 5000» intacto y oración terminada.
    assert "50 a 5000" in out
    assert out.rstrip().endswith("clústeres.")
    for frag in _DANGLING_FRAGMENTS:
        assert not out.rstrip("…").rstrip().endswith(frag), f"fragmento colgante {frag!r}"
    _assert_no_midword_cut(out, _LIVE_RISK)

    # Y una variante de la MISMA cadena que SÍ excede el cap → ejercita la rama de corte
    # (no solo el early-return), conservando «50 a 5000» y terminando en frontera de oración.
    over_cap = _LIVE_RISK + " " + ("Riesgo adicional de gobernanza del modelo. " * 5)
    assert len(_normalized(over_cap)) > _MAX_RISK_CHARS
    out_over = _truncate_risk_text(over_cap)
    assert out_over.endswith((".", "!", "?", "…")), f"corte no limpio: {out_over!r}"
    assert "50 a 5000" in out_over
    _assert_no_midword_cut(out_over, over_cap)
    assert len(out_over) <= _MAX_RISK_CHARS + 1


def test_multi_sentence_over_cap_cuts_at_sentence_boundary() -> None:
    """Un riesgo de 2 oraciones que excede el cap se corta en la ÚLTIMA frontera de oración que
    cabe en la ventana (aquí, la 1ª oración completa), conservándola entera y nunca a media cláusula."""
    risk = (
        "El modelo sufre de un desequilibrio severo de clases que infla la exactitud aparente al "
        "94 por ciento mientras el recall de la clase minoritaria apenas alcanza el 31 por ciento, "
        "ocultando el verdadero costo de las omisiones. Además, el umbral de decisión fijado en 0.5 "
        "no refleja la asimetría de costos descrita en la matriz de negocio del caso."
    )
    assert len(risk) > _MAX_RISK_CHARS
    out = _truncate_risk_text(risk)
    assert out.endswith((".", "!", "?")), f"no termina en frontera de oración: {out!r}"
    # La 1ª oración completa (la única frontera que cabe en la ventana) se conserva ENTERA.
    assert out.endswith("de las omisiones."), f"debió conservar la 1ª oración completa: {out!r}"
    assert "0.5" not in out, "no debió cortar dentro del decimal 0.5"
    _assert_no_midword_cut(out, risk)
    assert len(out) <= _MAX_RISK_CHARS + 1


def test_short_risk_is_passthrough_whitespace_collapsed() -> None:
    """Un riesgo corto (< cap) se devuelve completo, con whitespace colapsado."""
    risk = "El   supuesto de independencia\nentre variables no se sostiene; hay multicolinealidad."
    out = _truncate_risk_text(risk)
    assert out == "El supuesto de independencia entre variables no se sostiene; hay multicolinealidad."


def test_runon_over_cap_falls_back_to_word_boundary_ellipsis() -> None:
    """Un run-on largo sin terminador de oración cae al fallback word-safe con elipsis."""
    risk = (
        "riesgo de drift de datos en producción porque la distribución de las variables monetarias "
        "cambia con la estacionalidad y el reentrenamiento programado cada trimestre podría no "
        "capturar los picos abruptos de fin de año que distorsionan los segmentos generados por el "
        "modelo de agrupamiento no supervisado durante las campañas comerciales más intensas"
    )
    assert len(risk) > _MAX_RISK_CHARS
    out = _truncate_risk_text(risk)
    assert out.endswith("…"), f"el fallback debe marcar elisión: {out!r}"
    _assert_no_midword_cut(out, risk)
    # Cota inferior: el fallback word-safe debe aprovechar ~todo el ancho, no degenerar a un
    # fragmento corto (atrapa una regresión de `width` en textwrap.shorten).
    assert 250 < len(out) <= _MAX_RISK_CHARS + 1, f"longitud degenerada del fallback: {len(out)}"


def test_newline_separated_sentences_collapse_so_boundary_cut_works() -> None:
    """Whitespace-collapse es load-bearing: una oración separada por '\\n' debe poder cortarse en
    frontera. Sin colapsar, '.\\n' no matchearía '. ' y el corte por oración fallaría."""
    first = "La fuga de información temporal contamina la validación del modelo de manera severa."
    second = " " + ("detalle adicional " * 30)  # empuja el total por encima del cap
    risk = first + "\n" + second
    assert len(_normalized(risk)) > _MAX_RISK_CHARS
    out = _truncate_risk_text(risk)
    assert "\n" not in out
    assert out == first  # cortó exactamente en la 1ª oración completa


def test_empty_input_is_safe() -> None:
    assert _truncate_risk_text("") == ""
    assert _truncate_risk_text("   \n  ") == ""


# ── 2. Integración: ejercita el closure _extract_main_risk vía _build_base_context ─────


def test_build_base_context_main_risk_is_complete_sentence() -> None:
    """End-to-end sin LLM: un m3_content con una sección de riesgo larga produce un
    ``main_risk_from_m3_m4`` completo (sin fragmento colgante)."""
    body = (
        "La extrema disparidad de magnitudes detectada en el análisis forense exige cautela. "
        "Si el módulo se ejecuta sin aplicar previamente un StandardScaler, la amplitud de la "
        "variable monetary_value (cuyo rango va de 50 a 5000) dominaría el cálculo de distancias, "
        "sesgando por completo la formación de los segmentos del modelo no supervisado del caso."
    )
    m3 = f"### Riesgo de Implementación\n{body}\n\n### Otra sección\nTexto irrelevante."
    context = _build_base_context(  # type: ignore[arg-type]
        {
            "studentProfile": "ml_ds",
            "algoritmos": ["K-Means"],
            "m3_content": m3,
        }
    )
    main_risk = context["main_risk_from_m3_m4"]
    assert main_risk, "main_risk vacío"
    for frag in _DANGLING_FRAGMENTS:
        assert not main_risk.rstrip("…").rstrip().endswith(frag)
    assert main_risk.rstrip().endswith((".", "!", "?", "…"))


def test_build_base_context_default_when_no_m3_m4() -> None:
    """Sin M3/M4 ejecutados, cae al default fijo (ruta no tocada por el fix)."""
    context = _build_base_context(  # type: ignore[arg-type]
        {"studentProfile": "business", "algoritmos": ["Logistic Regression"]}
    )
    assert context["main_risk_from_m3_m4"] == (
        "Revisar supuestos del modelo antes de escalar la implementación"
    )


# ── 3. Render del prompt M5: el riesgo producido no deja fragmento colgante ────


def test_m5_prompts_render_with_clean_risk_no_dangling_fragment() -> None:
    """Formatear ambos prompts de preguntas M5 con el riesgo limpio no deja «va de 5» colgante
    y no lanza en .format (contrato del placeholder intacto)."""
    clean_risk = _truncate_risk_text(_LIVE_RISK)
    for template in (M5_QUESTIONS_PROMPT_CLASSIFICATION, M5_QUESTIONS_GENERATOR_PROMPT):
        ctx = {key: "x" for key in _placeholders(template)}
        ctx["main_risk_from_m3_m4"] = clean_risk
        rendered = template.format(**ctx)
        assert "50 a 5000" in rendered
        # El fragmento truncado del bug no debe aparecer pegado al texto del riesgo.
        assert "va de 50 a 5000" in rendered  # la frase completa, no el corte
        assert "{main_risk_from_m3_m4}" not in rendered
