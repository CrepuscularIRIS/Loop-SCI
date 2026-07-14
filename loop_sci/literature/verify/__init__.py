"""Citation verification package.

Exports the ``VerificationPipeline`` and ``GroundingVerifier``.

Layers:
  L1 — Format: citation has a resolvable identifier (external_id + known source, or doi).
  L2 — Existence: identifier resolves to a real paper via an adapter's fetch_by_id.
  L3 — Metadata match: year/authors/venue match within tolerance.
  L4 — Content-grounding: claim is supported by the resolved paper's text
       (hybrid lexical pre-filter + optional Qwen judge).

``VerificationPipeline.verify()`` runs all four layers with short-circuiting.
``VerificationPipeline.verify_layers_123()`` runs only L1-L3 (returns pending_l4).
``GroundingVerifier`` can also be used standalone for L4-only grounding.
"""
from loop_sci.literature.verify.citation import VerificationPipeline
from loop_sci.literature.verify.grounding import GroundingVerifier

__all__ = ["VerificationPipeline", "GroundingVerifier"]
