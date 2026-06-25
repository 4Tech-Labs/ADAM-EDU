"""Teaching Note (Módulo 6) prompt helpers.

Deterministic, code-owned building blocks for the teacher-only M6 "Guía del Docente".
The per-module roster (which modules exist, their numbering and bilingual labels) is
assembled in Python so it is correct BY CONSTRUCTION and cannot be hallucinated by the LLM.
"""

from case_generator.prompts.teaching_note.module_guide_block import (
    build_module_guide_block,
    build_roster_allowlist,
    module_guide_roster_ids,
)

__all__ = [
    "build_module_guide_block",
    "build_roster_allowlist",
    "module_guide_roster_ids",
]
