"""Unit coverage for the deterministic ``locals()`` existence-guard repair.

The repair rewrites the one forbidden idiom the self-bootstrap prompt invites
(``if 'X' in locals():``) into the sanctioned ``try/except NameError`` form before
notebook validation, killing the most common ``INSEGURO`` failure mode without an
extra LLM round-trip. These tests pin the repair's behaviour AND its fail-safe
contract: it must never raise, never corrupt, and discard on any doubt.

Pure/unit. No LLM, no DB, no network.
"""

from __future__ import annotations

import ast

import pytest

from case_generator.m3_notebook_repair import repair_locals_existence_guards


def _parses(code: str) -> bool:
    try:
        ast.parse(code)
    except SyntaxError:
        return False
    return True


def test_repairs_simple_in_locals_guard() -> None:
    src = '# %%\nif "X_train" in locals():\n    print(X_train)\n'
    out = repair_locals_existence_guards(src)
    assert "locals(" not in out
    assert "try:" in out and "except NameError:" in out
    assert "print(X_train)" in out
    assert _parses(out)


def test_repairs_not_in_locals_recreate_branch() -> None:
    src = '# %%\nif "X_train" not in locals():\n    X_train = rebuild()\n'
    out = repair_locals_existence_guards(src)
    assert "locals(" not in out
    # `not in` → the recreate body must land in the except (absent) branch.
    tree = ast.parse(out)
    trys = [n for n in ast.walk(tree) if isinstance(n, ast.Try)]
    assert len(trys) == 1
    handler_src = ast.unparse(trys[0].handlers[0])
    assert "X_train = rebuild()" in handler_src


def test_repairs_globals_and_vars_same_as_locals() -> None:
    for probe in ("globals", "vars"):
        src = f'# %%\nif "Z" in {probe}():\n    use(Z)\n'
        out = repair_locals_existence_guards(src)
        assert f"{probe}(" not in out
        assert "except NameError:" in out
        assert _parses(out)


def test_repairs_else_branch() -> None:
    src = '# %%\nif "X" in locals():\n    a()\nelse:\n    b()\n'
    out = repair_locals_existence_guards(src)
    tree = ast.parse(out)
    tryptr = next(n for n in ast.walk(tree) if isinstance(n, ast.Try))
    body_src = " ".join(ast.unparse(s) for s in tryptr.body)
    handler_src = ast.unparse(tryptr.handlers[0])
    assert "a()" in body_src and "b()" in handler_src


def test_leaves_multivar_or_ambiguous_untouched() -> None:
    src = '# %%\nif "a" in locals() and "b" in locals():\n    pass\n'
    assert repair_locals_existence_guards(src) == src


def test_leaves_locals_in_string_untouched() -> None:
    src = "# %%\nmsg = \"if 'X' in locals()\"\nprint(msg)\n"
    assert repair_locals_existence_guards(src) == src


def test_leaves_locals_as_value_untouched() -> None:
    # `d = locals()` is not an existence guard; repair must not touch it (the scrub
    # will reject it downstream and drive a reprompt).
    src = "# %%\nd = locals()\n"
    assert repair_locals_existence_guards(src) == src


def test_repair_is_noop_on_clean_code() -> None:
    src = "# %%\nimport pandas as pd\nx = 1\n"
    assert repair_locals_existence_guards(src) == src


def test_repaired_output_passes_safety_scrub() -> None:
    from case_generator.m3_notebook_execution import scrub_notebook_for_safe_execution

    src = '# %%\nimport pandas as pd\nif "X_train" in locals():\n    pass\n'
    out = repair_locals_existence_guards(src)
    assert "locals(" not in out
    # Must not raise — the rewrite produced scrub-clean code.
    scrub_notebook_for_safe_execution(out)


def test_repair_discards_when_unrelated_unsafe_remains() -> None:
    # Repairing locals() does not make the cell safe (getattr is still denied), so
    # the discard-on-doubt net returns the ORIGINAL untouched.
    src = '# %%\nif "X" in locals():\n    pass\ny = getattr(obj, "attr")\n'
    assert repair_locals_existence_guards(src) == src


def test_repair_preserves_section_sentinels() -> None:
    src = (
        "# %%\n"
        "# === SECTION:pr_curves ===\n"
        'if "X_train" in locals():\n'
        "    pass\n"
        "# === SECTION:cost_matrix ===\n"
    )
    out = repair_locals_existence_guards(src)
    assert "# === SECTION:pr_curves ===" in out
    assert "# === SECTION:cost_matrix ===" in out
    assert "locals(" not in out


def test_repair_never_raises_on_garbage() -> None:
    for junk in ("", "if 'X' in locals(", "def (:\n", "locals() locals() }{", "🙂"):
        # Must return *something* (the input) and never raise.
        assert repair_locals_existence_guards(junk) == junk


def test_repairs_multiple_guards_in_one_cell() -> None:
    src = (
        "# %%\n"
        'if "X_train" not in locals():\n'
        "    X_train = a()\n"
        'if "y_train" not in locals():\n'
        "    y_train = b()\n"
    )
    out = repair_locals_existence_guards(src)
    assert "locals(" not in out
    assert out.count("except NameError:") == 2
    assert _parses(out)


def test_repair_indented_guard_inside_function() -> None:
    src = (
        "# %%\n"
        "def bootstrap():\n"
        '    if "X_train" not in locals():\n'
        "        X_train = rebuild()\n"
        "    return X_train\n"
    )
    out = repair_locals_existence_guards(src)
    assert "locals(" not in out
    assert _parses(out)
    # Indentation preserved — the try lives at the function body level.
    assert "    try:" in out and "    except NameError:" in out
