"""Issue #237 — Python-deterministic data/chart builders for case generation.

This package hosts the small Python helpers that produce *bit-deterministic*
artefacts for the teacher preview, replacing LLM-fabricated numbers in
sensitive paths. Today it ships:

* ``eda_charts_classification`` — 6-chart EDA panel for the
  ``ml_ds + clasificacion`` path.

Future work (TODO-237-A/B/C) will extend the same pattern to ``regresion``
(A), ``clustering`` (B), and ``serie_temporal`` (C) families.
"""
