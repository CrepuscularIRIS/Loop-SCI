"""TDD tests for L4 hybrid content-grounding (grounding.py).

RED phase — written BEFORE implementation exists.

Tests cover:
  - Clear lexical support (score >= HIGH_THRESHOLD) → verified WITHOUT Qwen call
  - Clear lexical mismatch (score <= LOW_THRESHOLD) → rejected WITHOUT Qwen call
  - Borderline band → Qwen judge invoked; its verdict decides outcome
  - Misattributed claim (real paper, wrong claim) → rejected at L4
  - Grounding confidence/path recorded in VerificationStatus.detail

All tests are OFFLINE: MockProvider replaces Qwen; no network I/O.
"""
from __future__ import annotations

import json

import pytest

from loop_sci.literature.extract.fact import Fact, SourceRef
from loop_sci.literature.search.schema import PaperResult
from loop_sci.literature.verify.grounding import GroundingVerifier

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../"))
from tests.conftest import MockProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fact(evidence: str, scope: str = "abstract") -> Fact:
    """Build a minimal Fact for grounding tests."""
    return Fact(
        claim="SNNs beat ANNs",
        source_ref=SourceRef(source="semantic_scholar", external_id="s2:abc"),
        evidence_span=evidence,
        confidence=0.9,
        grounding_scope=scope,
    )


def _paper(abstract: str) -> PaperResult:
    """Build a minimal PaperResult for grounding tests."""
    return PaperResult(
        source="semantic_scholar",
        external_id="s2:abc",
        title="T",
        authors=["A"],
        year=2024,
        venue=None,
        abstract=abstract,
        url=None,
    )


# ---------------------------------------------------------------------------
# L4 grounding tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lexical_pass_without_qwen():
    """High overlap -> pass verified WITHOUT calling Qwen judge.

    evidence_span is nearly identical to the abstract — lexical score will
    be >= HIGH_THRESHOLD (0.60).  provider=None proves Qwen was never invoked.
    """
    verifier = GroundingVerifier(provider=None, threshold=0.3)
    paper = _paper("SNNs outperform ANNs on sparse data by 12%.")
    fact = _fact("SNNs outperform ANNs on sparse data by 12%")
    status = await verifier.verify(fact, paper)
    assert status.status == "verified"
    assert status.layer_reached == 4
    # Confirm the lexical path was used (not qwen)
    assert "lexical" in status.detail
    assert "qwen" not in status.detail


@pytest.mark.asyncio
async def test_lexical_fail_without_qwen():
    """Zero overlap -> rejected at L4 WITHOUT calling Qwen.

    Abstract and evidence span share no tokens at all — lexical score 0.0
    is well below LOW_THRESHOLD (0.15).  provider=None proves Qwen never invoked.
    """
    verifier = GroundingVerifier(provider=None, threshold=0.3)
    paper = _paper("The cat sat on the mat.")
    fact = _fact("quantum tunneling enables flight")
    status = await verifier.verify(fact, paper)
    assert status.status == "rejected"
    assert status.layer_reached == 4
    assert "lexical" in status.detail
    assert "qwen" not in status.detail


@pytest.mark.asyncio
async def test_borderline_uses_qwen_judge_and_returns_verified():
    """Borderline overlap -> Qwen judge invoked; Qwen says supported -> verified."""
    qwen_response = json.dumps({"supported": True, "confidence": 0.75})
    provider = MockProvider(responses=[qwen_response])
    verifier = GroundingVerifier(provider=provider, threshold=0.3)
    # "Spiking neural networks have some advantages over ANNs." — partial match
    # "SNNs beat ANNs in energy" — score in borderline (LOW < score < HIGH)
    paper = _paper("Spiking neural networks have some advantages over ANNs.")
    fact = _fact("SNNs beat ANNs in energy")
    status = await verifier.verify(fact, paper)
    assert status.status == "verified"
    assert status.layer_reached == 4
    assert "qwen" in status.detail
    # Provider was called exactly once
    assert provider._index == 1


@pytest.mark.asyncio
async def test_borderline_uses_qwen_judge_and_returns_rejected():
    """Borderline overlap -> Qwen judge invoked; Qwen says NOT supported -> rejected."""
    qwen_response = json.dumps({"supported": False, "confidence": 0.82})
    provider = MockProvider(responses=[qwen_response])
    verifier = GroundingVerifier(provider=provider, threshold=0.3)
    paper = _paper("Spiking neural networks have some advantages over ANNs.")
    fact = _fact("SNNs beat ANNs in energy")
    status = await verifier.verify(fact, paper)
    assert status.status == "rejected"
    assert status.layer_reached == 4
    assert "qwen" in status.detail
    assert provider._index == 1


@pytest.mark.asyncio
async def test_misattributed_claim_rejected_at_l4():
    """Misattributed claim: real paper, correct metadata, but claim absent from text.

    This is the anti-fabrication L4 test from the spec:
    'Catch misattributed claims (content-grounding)'.
    """
    verifier = GroundingVerifier(provider=None, threshold=0.3)
    paper = _paper("This paper studies protein folding in bacteria.")
    fact = _fact("transformers outperform LSTMs on NLP tasks")
    status = await verifier.verify(fact, paper)
    assert status.status == "rejected"
    assert status.layer_reached == 4


@pytest.mark.asyncio
async def test_grounding_confidence_recorded_in_detail_lexical():
    """Grounding confidence score is recorded in VerificationStatus.detail."""
    verifier = GroundingVerifier(provider=None, threshold=0.3)
    paper = _paper("SNNs outperform ANNs on sparse data by 12%.")
    fact = _fact("SNNs outperform ANNs on sparse data by 12%")
    status = await verifier.verify(fact, paper)
    # detail must contain a numeric score, e.g. "lexical:0.88"
    assert ":" in status.detail  # format: "path:score"


@pytest.mark.asyncio
async def test_grounding_confidence_recorded_in_detail_qwen():
    """Grounding confidence and path='qwen_judge' recorded when Qwen is called."""
    qwen_response = json.dumps({"supported": True, "confidence": 0.91})
    provider = MockProvider(responses=[qwen_response])
    verifier = GroundingVerifier(provider=provider, threshold=0.3)
    paper = _paper("Spiking neural networks have some advantages over ANNs.")
    fact = _fact("SNNs beat ANNs in energy")
    status = await verifier.verify(fact, paper)
    assert "qwen_judge" in status.detail
    assert "0.91" in status.detail


@pytest.mark.asyncio
async def test_clear_support_does_not_call_provider():
    """Assert provider is NOT called when lexical score >= HIGH_THRESHOLD.

    This is the efficiency guarantee: obvious cases skip the expensive Qwen call.
    """
    # Use MockProvider that would fail if called (via tracking _index)
    provider = MockProvider(responses=["should_not_be_called"])
    verifier = GroundingVerifier(provider=provider, threshold=0.3)
    paper = _paper("SNNs outperform ANNs on sparse data by 12%.")
    fact = _fact("SNNs outperform ANNs on sparse data by 12%")
    status = await verifier.verify(fact, paper)
    assert status.status == "verified"
    # If index is still 0, provider.create was never called
    assert provider._index == 0, "Provider should NOT have been called for clear lexical match"


@pytest.mark.asyncio
async def test_clear_mismatch_does_not_call_provider():
    """Assert provider is NOT called when lexical score <= LOW_THRESHOLD."""
    provider = MockProvider(responses=["should_not_be_called"])
    verifier = GroundingVerifier(provider=provider, threshold=0.3)
    paper = _paper("The cat sat on the mat.")
    fact = _fact("quantum tunneling enables flight")
    status = await verifier.verify(fact, paper)
    assert status.status == "rejected"
    assert provider._index == 0, "Provider should NOT have been called for clear lexical mismatch"


@pytest.mark.asyncio
async def test_abstract_none_treated_as_empty():
    """If paper has no abstract (None), grounding rejects (no text to ground against)."""
    verifier = GroundingVerifier(provider=None, threshold=0.3)
    paper = PaperResult(
        source="semantic_scholar",
        external_id="s2:abc",
        title="T",
        authors=["A"],
        year=2024,
        venue=None,
        abstract=None,
        url=None,
    )
    fact = _fact("SNNs outperform ANNs")
    status = await verifier.verify(fact, paper)
    # With empty source text, score = 0.0 < LOW_THRESHOLD → rejected
    assert status.status == "rejected"
    assert status.layer_reached == 4
