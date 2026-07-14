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
async def test_extractor_drops_ungrounded_claims() -> None:
    """A claim with an empty evidence_span is dropped (returns empty list)."""
    provider = MockProvider(responses=[UNGROUNDED_RESPONSE])
    extractor = FactExtractor(provider, max_facts_per_paper=5)
    facts = await extractor.extract(_paper())
    assert facts == []


@pytest.mark.asyncio
async def test_extractor_respects_per_paper_bound() -> None:
    """max_facts_per_paper=3 caps a 6-item model response to at most 3 facts."""
    items = [
        {
            "claim": f"Claim {i}",
            "evidence_span": f"Evidence {i}",
            "confidence": 0.8,
            "entities": [],
        }
        for i in range(6)
    ]
    provider = MockProvider(responses=[json.dumps(items)])
    extractor = FactExtractor(provider, max_facts_per_paper=3)
    facts = await extractor.extract(_paper())
    assert len(facts) <= 3


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
    """Bound is checked on grounded facts; ungrounded ones don't count toward cap."""
    # 4 items: 2 grounded, 2 ungrounded; max=2 → both grounded survive
    items = [
        {"claim": "Claim 0", "evidence_span": "Evidence 0", "confidence": 0.8, "entities": []},
        {"claim": "Bad 1", "evidence_span": "", "confidence": 0.5, "entities": []},
        {"claim": "Claim 2", "evidence_span": "Evidence 2", "confidence": 0.8, "entities": []},
        {"claim": "Bad 3", "evidence_span": "", "confidence": 0.5, "entities": []},
    ]
    provider = MockProvider(responses=[json.dumps(items)])
    extractor = FactExtractor(provider, max_facts_per_paper=2)
    facts = await extractor.extract(_paper())
    assert len(facts) == 2
    assert all(f.evidence_span.startswith("Evidence") for f in facts)
