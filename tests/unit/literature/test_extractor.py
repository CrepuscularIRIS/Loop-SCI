"""Tests for the Qwen-driven FactExtractor.

All tests inject a MockProvider (scripted responses) — no network, no API key.

Coverage:
- Grounded fact is extracted with evidence span and source_ref
- Ungrounded claim (empty evidence_span) is dropped
- Confidence is clamped to [0, 1] (handles values like 5.0 and -1.0)
- Per-paper fact bound is respected
- Invalid JSON from the model returns [] and does not crash
- A paper with no abstract yields zero facts
- Per-paper bound: grounding check applied first, then cap
"""
from __future__ import annotations

import json
import sys

import pytest

sys.path.insert(0, "tests")
from conftest import MockProvider  # noqa: E402

from loop_sci.literature.extract.extractor import FactExtractor  # noqa: E402
from loop_sci.literature.extract.fact import Fact  # noqa: E402
from loop_sci.literature.search.schema import PaperResult  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _paper(abstract: str = "SNNs outperform ANNs on sparse data by 12%.") -> PaperResult:
    return PaperResult(
        source="semantic_scholar",
        external_id="s2:abc",
        title="SNN Paper",
        authors=["Smith J"],
        year=2024,
        venue="NeurIPS",
        abstract=abstract,
        url=None,
    )


GROUNDED_RESPONSE = json.dumps(
    [
        {
            "claim": "SNNs outperform ANNs on sparse data",
            "evidence_span": "SNNs outperform ANNs on sparse data by 12%",
            "confidence": 0.9,
            "entities": ["SNN", "ANN"],
        }
    ]
)

UNGROUNDED_RESPONSE = json.dumps(
    [
        {
            "claim": "SNNs are always better",
            "evidence_span": "",  # empty — must be dropped
            "confidence": 0.5,
            "entities": [],
        }
    ]
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extractor_returns_grounded_facts() -> None:
    """A grounded claim with a non-empty evidence_span becomes a Fact."""
    provider = MockProvider(responses=[GROUNDED_RESPONSE])
    extractor = FactExtractor(provider, max_facts_per_paper=5)
    facts = await extractor.extract(_paper())
    assert len(facts) == 1
    f = facts[0]
    assert isinstance(f, Fact)
    assert "12%" in f.evidence_span
    assert f.source_ref.external_id == "s2:abc"
    assert f.source_ref.source == "semantic_scholar"


@pytest.mark.asyncio
async def test_extractor_drops_empty_span_claims() -> None:
    """A claim with an empty evidence_span is dropped (returns empty list)."""
    provider = MockProvider(responses=[UNGROUNDED_RESPONSE])
    extractor = FactExtractor(provider, max_facts_per_paper=5)
    facts = await extractor.extract(_paper())
    assert facts == []


@pytest.mark.asyncio
async def test_extractor_respects_per_paper_bound() -> None:
    """max_facts_per_paper=3 caps a 6-item model response to at most 3 facts."""
    # Use a long abstract so all 6 spans are traceable; only the cap limits the count.
    abstract = (
        "SNNs outperform ANNs on sparse data by 12%. "
        "Energy is reduced by 30%. "
        "Latency drops by 20%. "
        "Memory usage falls by 15%. "
        "Accuracy improves by 5%. "
        "Training time decreases by 25%."
    )
    def _item(claim: str, span: str) -> dict:
        return {"claim": claim, "evidence_span": span, "confidence": 0.8, "entities": []}

    items = [
        _item("Claim 0", "SNNs outperform ANNs on sparse data by 12%"),
        _item("Claim 1", "Energy is reduced by 30%"),
        _item("Claim 2", "Latency drops by 20%"),
        _item("Claim 3", "Memory usage falls by 15%"),
        _item("Claim 4", "Accuracy improves by 5%"),
        _item("Claim 5", "Training time decreases by 25%"),
    ]
    provider = MockProvider(responses=[json.dumps(items)])
    extractor = FactExtractor(provider, max_facts_per_paper=3)
    facts = await extractor.extract(_paper(abstract=abstract))
    assert len(facts) == 3


@pytest.mark.asyncio
async def test_extractor_clamps_confidence_above_one() -> None:
    """Model-returned confidence > 1.0 is clamped to 1.0."""
    response = json.dumps(
        [
            {
                "claim": "SNNs outperform ANNs on sparse data",
                "evidence_span": "SNNs outperform ANNs on sparse data by 12%",
                "confidence": 5.0,  # out-of-range high
                "entities": [],
            }
        ]
    )
    provider = MockProvider(responses=[response])
    extractor = FactExtractor(provider, max_facts_per_paper=5)
    facts = await extractor.extract(_paper())
    assert len(facts) == 1
    assert facts[0].confidence == 1.0


@pytest.mark.asyncio
async def test_extractor_clamps_confidence_below_zero() -> None:
    """Model-returned confidence < 0.0 is clamped to 0.0."""
    response = json.dumps(
        [
            {
                "claim": "SNNs outperform ANNs on sparse data",
                "evidence_span": "SNNs outperform ANNs on sparse data by 12%",
                "confidence": -1.0,  # out-of-range low
                "entities": [],
            }
        ]
    )
    provider = MockProvider(responses=[response])
    extractor = FactExtractor(provider, max_facts_per_paper=5)
    facts = await extractor.extract(_paper())
    assert len(facts) == 1
    assert facts[0].confidence == 0.0


@pytest.mark.asyncio
async def test_extractor_invalid_json_returns_empty_list() -> None:
    """Malformed JSON from the model returns [] and does not raise an exception."""
    provider = MockProvider(responses=["this is not json {{{"])
    extractor = FactExtractor(provider, max_facts_per_paper=5)
    facts = await extractor.extract(_paper())
    assert facts == []


@pytest.mark.asyncio
async def test_extractor_empty_abstract_returns_zero_facts() -> None:
    """A paper with no abstract text yields zero facts."""
    provider = MockProvider(responses=[GROUNDED_RESPONSE])
    extractor = FactExtractor(provider, max_facts_per_paper=5)
    facts = await extractor.extract(_paper(abstract=""))
    assert facts == []


@pytest.mark.asyncio
async def test_extractor_none_abstract_returns_zero_facts() -> None:
    """A paper with abstract=None yields zero facts."""
    provider = MockProvider(responses=[GROUNDED_RESPONSE])
    extractor = FactExtractor(provider, max_facts_per_paper=5)
    paper = _paper()
    paper.abstract = None
    facts = await extractor.extract(paper)
    assert facts == []


@pytest.mark.asyncio
async def test_extractor_whitespace_span_is_dropped() -> None:
    """A claim whose evidence_span is whitespace-only is also dropped."""
    response = json.dumps(
        [
            {
                "claim": "Some claim",
                "evidence_span": "   ",  # whitespace only
                "confidence": 0.7,
                "entities": [],
            }
        ]
    )
    provider = MockProvider(responses=[response])
    extractor = FactExtractor(provider, max_facts_per_paper=5)
    facts = await extractor.extract(_paper())
    assert facts == []


@pytest.mark.asyncio
async def test_extractor_grounding_scope_is_abstract() -> None:
    """Facts extracted from an abstract carry grounding_scope='abstract'."""
    provider = MockProvider(responses=[GROUNDED_RESPONSE])
    extractor = FactExtractor(provider, max_facts_per_paper=5)
    facts = await extractor.extract(_paper())
    assert len(facts) == 1
    assert facts[0].grounding_scope == "abstract"


@pytest.mark.asyncio
async def test_extractor_bound_applied_after_grounding_filter() -> None:
    """Bound is checked on grounded facts; ungrounded (empty-span) ones don't count toward cap."""
    # Abstract has two traceable phrases; empty-span items are dropped before the cap.
    abstract = "SNNs outperform ANNs on sparse data by 12%. Energy is reduced by 30%."
    def _g(claim: str, span: str) -> dict:
        return {"claim": claim, "evidence_span": span, "confidence": 0.8, "entities": []}

    def _b(claim: str) -> dict:
        return {"claim": claim, "evidence_span": "", "confidence": 0.5, "entities": []}

    items = [
        _g("Claim 0", "SNNs outperform ANNs on sparse data by 12%"),  # grounded
        _b("Bad 1"),   # dropped — empty span
        _g("Claim 2", "Energy is reduced by 30%"),                     # grounded
        _b("Bad 3"),   # dropped — empty span
    ]
    provider = MockProvider(responses=[json.dumps(items)])
    extractor = FactExtractor(provider, max_facts_per_paper=2)
    facts = await extractor.extract(_paper(abstract=abstract))
    assert len(facts) == 2
    assert facts[0].claim == "Claim 0"
    assert facts[1].claim == "Claim 2"


@pytest.mark.asyncio
async def test_extractor_drops_span_absent_from_source() -> None:
    """A non-empty evidence_span not present in the source text is dropped (anti-fabrication).

    The model returns a fluent, non-empty span that is not a substring of the
    abstract.  The traceability check must catch this and drop the fact.
    """
    fabricated_response = json.dumps(
        [
            {
                "claim": "SNNs require 50% less memory than ANNs",
                "evidence_span": "SNNs require 50% less memory than ANNs in all benchmarks",
                "confidence": 0.85,
                "entities": ["SNN", "ANN"],
            }
        ]
    )
    # Abstract does NOT contain the fabricated span
    provider = MockProvider(responses=[fabricated_response])
    extractor = FactExtractor(provider, max_facts_per_paper=5)
    facts = await extractor.extract(_paper())
    assert facts == []


@pytest.mark.asyncio
async def test_extractor_keeps_span_with_reflowed_whitespace() -> None:
    """A span matching the source modulo whitespace/case differences is KEPT.

    Proves that normalisation prevents false drops on spans the model returns
    with collapsed/expanded whitespace or different capitalisation.
    """
    abstract = "SNNs outperform  ANNs on sparse data by 12%."
    # Model returns the span with single spaces and different case — still traceable
    reflowed_response = json.dumps(
        [
            {
                "claim": "SNNs outperform ANNs on sparse data",
                "evidence_span": "snns outperform anns on sparse data by 12%",
                "confidence": 0.9,
                "entities": ["SNN", "ANN"],
            }
        ]
    )
    provider = MockProvider(responses=[reflowed_response])
    extractor = FactExtractor(provider, max_facts_per_paper=5)
    facts = await extractor.extract(_paper(abstract=abstract))
    assert len(facts) == 1
    assert facts[0].claim == "SNNs outperform ANNs on sparse data"
