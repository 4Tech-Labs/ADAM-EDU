from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

TRUNCATION_MARKER = "...[truncated]"
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_INLINE_WHITESPACE_RE = re.compile(r"[^\S\n]+")
_EXCESS_NEWLINES_RE = re.compile(r"\n{3,}")


def _stringify_untrusted(value: Any) -> str:
    """Convert arbitrary input to text without raising on JSON-incompatible objects."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


def _truncate_text(value: str, max_chars: int) -> str:
    """Trim text to a fixed limit while preserving a visible truncation marker."""
    if max_chars <= 0:
        return ""
    if len(value) <= max_chars:
        return value
    cutoff = max(0, max_chars - len(TRUNCATION_MARKER))
    return value[:cutoff].rstrip() + TRUNCATION_MARKER


def sanitize_untrusted_text(value: Any, max_chars: int) -> str:
    """
    Normalize and bound untrusted text before it enters prompts or persisted context.

    Rules:
    - None -> ""
    - Normalize CRLF to LF
    - Remove control chars except tab/newline
    - Collapse repeated inline whitespace
    - Collapse excessive blank lines
    - Enforce a hard character limit
    """
    raw_text = _stringify_untrusted(value).replace("\r\n", "\n").replace("\r", "\n")
    no_controls = _CONTROL_CHARS_RE.sub("", raw_text)
    collapsed_inline = _INLINE_WHITESPACE_RE.sub(" ", no_controls)
    collapsed_blocks = _EXCESS_NEWLINES_RE.sub("\n\n", collapsed_inline)
    normalized = collapsed_blocks.strip()
    return _truncate_text(normalized, max_chars)


def sanitize_untrusted_payload(
    mapping: Mapping[str, Any],
    per_field_limit: int,
    total_limit: int,
) -> str:
    """Render a mapping of untrusted fields as bounded JSON text for prompt inclusion."""
    sanitized: dict[str, str] = {}
    for key, value in mapping.items():
        clean_key = sanitize_untrusted_text(key, 120)
        clean_value = sanitize_untrusted_text(value, per_field_limit)
        if clean_key and clean_value:
            sanitized[clean_key] = clean_value

    if not sanitized:
        return ""

    rendered = json.dumps(sanitized, ensure_ascii=False, indent=2)
    return _truncate_text(rendered, total_limit)
