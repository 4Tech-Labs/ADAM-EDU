"""Shared text-normalization helpers for ``case_generator`` (stdlib-only, cycle-free)."""

from __future__ import annotations

import unicodedata

__all__ = ["fold_accents"]


def fold_accents(text: str) -> str:
    """Strip diacritical marks from ``text``, preserving case and every other character.

    ``café`` -> ``cafe``, ``región`` -> ``region``, ``NIÑO`` -> ``NINO``. Non-Latin characters
    (CJK, emoji) are kept untouched; callers that need a pure-ASCII result chain
    ``.encode("ascii", "ignore")`` after this.

    Uses NFKD decomposition followed by removal of combining marks. NFKD (not NFD) is deliberate:
    it keeps the two ASCII-fold call sites that post-compose this with ``.encode("ascii", "ignore")``
    byte-for-byte unchanged — the ascii-encode already drops every combining mark, and NFKD
    reproduces the compatibility decomposition (``ﬁ`` -> ``fi``) those sites applied inline. For the
    Spanish diacritics the project actually folds (á é í ó ú ñ ü) NFD and NFKD are identical; NFKD
    additionally folds compatibility characters, which is inert for the fuzzy-matching callers (they
    lower-case and compare against ASCII constants) and was already the form in 7 of the 8 inline
    copies this consolidates.
    """
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )
