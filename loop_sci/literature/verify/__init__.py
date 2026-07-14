"""Citation verification package.

Exports the ``VerificationPipeline`` — the ordered, short-circuiting verification
pipeline for scientific fact citations.

Layers implemented here:
  L1 — Format: citation has a resolvable identifier (external_id + known source, or doi).
  L2 — Existence: identifier resolves to a real paper via an adapter's fetch_by_id.
  L3 — Metadata match: year/authors/venue match within tolerance.

Layer 4 (content-grounding) is added in Task 7 without rewriting L1-L3.
"""
from loop_sci.literature.verify.citation import VerificationPipeline

__all__ = ["VerificationPipeline"]
