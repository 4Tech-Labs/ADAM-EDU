"""Deterministic, fail-safe repairs for LLM-generated M3 classification notebooks.

The M3 notebook generator (``graph.py``) asks a Flash-tier model to emit a large
classification notebook under a strict contract. The prompt *requires* every cell
to "self-bootstrap" (recreate the train/test splits if they are absent), but the
single most natural Python idiom for "does this variable exist?" is
``if 'X' in locals():`` — which the kernel safety scrub (``_DENIED_CALL_NAMES``)
rejects, failing the whole job. Rule 8 of the prompt prohibits it and teaches the
sanctioned ``try/except NameError`` form, yet weaker models still reach for it.

This module mechanically rewrites that *one* known forbidden idiom into the
sanctioned ``try/except NameError`` form **before** validation, so the most common
``INSEGURO`` failure mode disappears without an extra LLM round-trip.

Design guarantees (this code must NEVER corrupt a notebook):

* Pure and total: ``repair_locals_existence_guards`` never raises and returns the
  input unchanged on *any* ambiguity (syntax error, multi-variable test,
  ``locals()`` used as a value, ``elif`` chains, attribute calls, …).
* AST-located **line-splice** (never ``ast.unparse`` of a whole cell — that would
  erase the ``# === SECTION:* ===`` sentinel comments and *manufacture* FALTANTE
  violations).
* Discard-on-doubt: the rewritten code is kept only if it still parses, preserves
  every section sentinel, and is fully accepted by the same safety scrub used at
  generation/execution time. Otherwise the original is returned and the normal
  validate→reprompt (with model escalation) path takes over.
"""

from __future__ import annotations

import ast

from case_generator.m3_notebook_execution import scrub_notebook_for_safe_execution

# Bare zero-arg builtins whose membership test is an existence check on the local
# / global namespace. ``vars()`` with no args is equivalent to ``locals()``.
_EXISTENCE_PROBE_NAMES = frozenset({"locals", "globals", "vars"})

# Sanity cap: each rewrite strictly removes one matchable guard, so this only
# guards against pathological input; real notebooks have a handful at most.
_MAX_REWRITES = 64


def _leading_ws(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _section_sentinels(code: str) -> list[str]:
    return [ln.strip() for ln in code.splitlines() if ln.strip().startswith("# === SECTION:")]


def _match_existence_guard(node: ast.If) -> tuple[str, bool] | None:
    """Return ``(identifier, negated)`` if ``node`` is a simple existence guard.

    Matches exactly ``if '<ident>' in locals():`` / ``... not in locals()``
    (and ``globals``/``vars``), nothing else. ``negated`` is True for ``not in``.
    Returns ``None`` (skip) on any deviation — including ``elif`` chains.
    """
    test = node.test
    if not isinstance(test, ast.Compare):
        return None
    if len(test.ops) != 1 or len(test.comparators) != 1:
        return None

    op = test.ops[0]
    if isinstance(op, ast.In):
        negated = False
    elif isinstance(op, ast.NotIn):
        negated = True
    else:
        return None

    left = test.left
    if not isinstance(left, ast.Constant) or not isinstance(left.value, str):
        return None
    identifier = left.value
    if not identifier.isidentifier():
        return None

    call = test.comparators[0]
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
        return None
    if call.func.id not in _EXISTENCE_PROBE_NAMES:
        return None
    if call.args or call.keywords:
        return None  # vars(obj)/locals(x) is not an existence check

    # Reject elif: the orelse is a single If aligned with this If's column.
    if (
        len(node.orelse) == 1
        and isinstance(node.orelse[0], ast.If)
        and node.orelse[0].col_offset == node.col_offset
    ):
        return None

    return identifier, negated


def _first_guard(tree: ast.AST) -> tuple[ast.If, str, bool] | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            matched = _match_existence_guard(node)
            if matched is not None:
                return node, matched[0], matched[1]
    return None


def _rewrite_once(code: str) -> str | None:
    """Rewrite the first existence guard found, or return ``None`` if none/unsafe."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    found = _first_guard(tree)
    if found is None:
        return None
    node, identifier, negated = found

    if node.end_lineno is None or node.body[0].end_lineno is None:
        return None  # missing position info — bail on this node

    lines = code.splitlines()
    if_idx = node.lineno - 1
    end_idx = node.end_lineno - 1
    base_indent = lines[if_idx][: node.col_offset]

    body_last_end = node.body[-1].end_lineno
    if body_last_end is None:
        return None
    body_start = node.body[0].lineno - 1
    body_end = body_last_end - 1
    body_lines = lines[body_start : body_end + 1]
    body_indent = _leading_ws(lines[body_start]) or (base_indent + "    ")

    else_lines: list[str] = []
    if node.orelse:
        else_start = node.orelse[0].lineno - 1
        else_last_end = node.orelse[-1].end_lineno
        else_end = (else_last_end - 1) if else_last_end is not None else else_start
        else_lines = lines[else_start : else_end + 1]

    # `in`  : X defined → body ; absent → else
    # `not in`: X absent → body ; defined → else
    if negated:
        try_extra, except_block = else_lines, body_lines
    else:
        try_extra, except_block = body_lines, else_lines

    if not except_block:
        except_block = [body_indent + "pass"]

    new_block = [base_indent + "try:", body_indent + identifier]
    new_block += try_extra
    new_block.append(base_indent + "except NameError:")
    new_block += except_block

    rewritten = lines[:if_idx] + new_block + lines[end_idx + 1 :]
    result = "\n".join(rewritten)
    if code.endswith("\n"):
        result += "\n"
    return result


def repair_locals_existence_guards(code: str) -> str:
    """Rewrite ``if '<ident>' in locals()/globals()/vars()`` existence guards into
    the sanctioned ``try: <ident> / except NameError`` form.

    Pure and total. Returns ``code`` unchanged on any ambiguity or if the rewrite
    cannot be proven safe (still parses, sentinels intact, scrub-clean)."""
    if not code:
        return code
    if not any(token in code for token in ("locals(", "globals(", "vars(")):
        return code

    current = code
    for _ in range(_MAX_REWRITES):
        nxt = _rewrite_once(current)
        if nxt is None:
            break
        current = nxt

    if current == code:
        return code

    # Discard-on-doubt net: only keep the rewrite if it is provably no worse.
    try:
        ast.parse(current)
    except SyntaxError:
        return code
    if _section_sentinels(current) != _section_sentinels(code):
        return code
    try:
        scrub_notebook_for_safe_execution(current)
    except Exception:
        # Repaired code is not fully scrub-clean (an unrelated unsafe construct may
        # remain) — fall back to the original and let validate→reprompt handle it.
        return code

    return current
