"""Issue #305 — regression guard for the dataset-seed determinism fix.

`_generate_dataset_from_schema` derives its RNG seed from the schema. It used the builtin
`hash(json.dumps(schema))`, but `hash()` of a `str` is salted per-process by `PYTHONHASHSEED`,
so the seed — and thus the whole generated dataset — varied between runs/processes, breaking
the "same schema → same dataset" contract. The fix switched to `hashlib.sha256`, which is
stable across processes.

This guard runs generation in independent subprocesses with different `PYTHONHASHSEED` and
asserts byte-identical output. It FAILS on the pre-fix `hash()` code and PASSES after — i.e.
it actually pins the bug, not just the symptom. Pure stdlib; spawns short-lived subprocesses.
"""

from __future__ import annotations

import inspect
import os
import re
import subprocess
import sys

# Runs in a fresh interpreter (own PYTHONHASHSEED). Prints a marker-prefixed digest so the
# parent can ignore any import-time stdout noise.
_SNIPPET = """
import json, hashlib
from case_generator.graph import _generate_dataset_from_schema

schema = {
    "columns": [
        {"name": "period", "type": "date"},
        {"name": "revenue", "type": "float"},
        {"name": "driver_score", "type": "float"},
        {"name": "event_flag", "type": "int", "range_min": 0, "range_max": 1,
         "dependency": {"depends_on": "driver_score", "relationship": "linear", "noise_factor": 0.3}},
    ],
    "n_rows": 24,
    "time_granularity": "monthly",
    "constraints": {},
}
rows = _generate_dataset_from_schema(schema, profile="business")
digest = hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()
print("ADAM_SEED_DIGEST=" + digest)
"""


def _digest_with_hashseed(seed: str) -> str:
    env = {**os.environ, "PYTHONHASHSEED": seed}
    proc = subprocess.run(
        [sys.executable, "-c", _SNIPPET],
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )
    assert proc.returncode == 0, f"subprocess (PYTHONHASHSEED={seed}) failed:\n{proc.stderr[-2000:]}"
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("ADAM_SEED_DIGEST=")]
    assert lines, f"no digest emitted (PYTHONHASHSEED={seed}); stdout tail:\n{proc.stdout[-1000:]}"
    return lines[-1].split("=", 1)[1].strip()


def test_dataset_generation_reproducible_across_process_hash_seeds() -> None:
    digests = {seed: _digest_with_hashseed(seed) for seed in ("0", "1", "12345")}
    unique = set(digests.values())
    assert len(unique) == 1, (
        "dataset generation is NOT reproducible across PYTHONHASHSEED values "
        f"(builtin hash() leaked into the seed?): {digests}"
    )


def test_seed_derivation_does_not_use_builtin_hash() -> None:
    """White-box backstop: the seed must derive from hashlib, not the process-salted builtin
    hash(). The subprocess test above is the real guard; this pins the in-file form so a silent
    revert is caught regardless of what expression gets hashed. Robust against two weak spots:
    comment-only lines are stripped (so a stale comment can't satisfy the positive assert), and
    the negative match catches ANY builtin ``hash(...)`` call, not just the exact prior literal."""
    from case_generator import graph

    # Drop comment-only lines so neither assertion can be satisfied/tripped by a comment.
    code = "\n".join(
        ln for ln in inspect.getsource(graph._generate_dataset_from_schema).splitlines()
        if not ln.lstrip().startswith("#")
    )
    assert "hashlib.sha256" in code, "seed must be derived via hashlib.sha256 (in code, not a comment)"
    # `hash(` NOT preceded by a word char or dot → the builtin, never `hashlib.`/`.sha256(`.
    assert re.search(r"(?<![\w.])hash\s*\(", code) is None, (
        "builtin hash() reintroduced — seed would be process-salted again"
    )
