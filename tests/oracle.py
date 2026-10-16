"""P-012 oracle shim for tests.

The from-scratch global oracle lives in `evals/oracle.py` (it shares no code with
`engine/compute.py`). Re-exported here for convenient test import as `tests/oracle.py`,
per FIX_PROMPT B2.
"""
from __future__ import annotations

from evals.oracle import ground_truth, truth_for_dag  # re-export; independent of engine/compute

__all__ = ["ground_truth", "truth_for_dag"]
