"""Tests for loop_sci.hypothesis.stages.prospect (prospect' stage).

All tests are offline — use MockProvider from conftest, no network, no API key.
"""
import json

import pytest

from loop_sci.hypothesis.stages.prospect import run_prospect
from loop_sci.literature.extract.fact import Fact, SourceRef
from loop_sci.literature.factbase.store import FactStore

from tests.conftest import MockProvider


def _make_store(tmp_path, claims: list[str]) -> FactStore:
    """Build a FactStore with one Fact per claim, assigning fact_id sequentially."""
    store = FactStore(tmp_path / "facts.json")
    for i, c in enumerate(claims):
        f = Fact(
            claim=c,
            source_ref=SourceRef(source="s2", external_id=f"s{i}"),
            evidence_span=c[:20],
            confidence=0.9,
            grounding_scope="abstract",
        )
        f.fact_id = f"fact_{i}"
        store.add(f)
    return store


@pytest.mark.asyncio
async def test_gap_cards_derived_from_facts(tmp_path):
    """Cards citing valid fact_ids are returned with correct STAKES and grounding refs."""
    store = _make_store(tmp_path, ["Neurons fire. Evidence X.", "Evidence Y contradicts X."])
    response = json.dumps([
        {
            "Q": "Why?",
            "WHY_NOW": "now",
            "PROBE_KILL": "pk",
            "STAKES": 0.9,
            "fact_ids": ["fact_0", "fact_1"],
        }
    ])
    provider = MockProvider(responses=[response])
    cards = await run_prospect("neuro", store, provider, max_cards=5)
    assert len(cards) == 1
    node_id, refs = cards[0]
    assert refs["card"]["STAKES"] == 0.9
    assert set(refs.get("grounding_fact_ids", [])) == {"fact_0", "fact_1"}


@pytest.mark.asyncio
async def test_card_with_nonexistent_fact_id_dropped(tmp_path):
    """A card citing a fact_id not in the store must be dropped before returning."""
    store = _make_store(tmp_path, ["Neurons fire."])
    response = json.dumps([
        {
            "Q": "Q1",
            "WHY_NOW": "n",
            "PROBE_KILL": "p",
            "STAKES": 0.8,
            "fact_ids": ["fact_0", "NONEXISTENT"],
        }
    ])
    provider = MockProvider(responses=[response])
    cards = await run_prospect("neuro", store, provider, max_cards=5)
    assert len(cards) == 0  # dropped because NONEXISTENT not in store


@pytest.mark.asyncio
async def test_invalid_json_retried_then_dropped(tmp_path):
    """Two consecutive malformed responses → empty list, no crash."""
    store = _make_store(tmp_path, ["Fact A."])
    provider = MockProvider(responses=["not json", "also not json"])
    cards = await run_prospect("neuro", store, provider, max_cards=5)
    assert cards == []


@pytest.mark.asyncio
async def test_cards_ordered_by_stakes_descending(tmp_path):
    """Multiple valid cards are sorted by STAKES in descending order."""
    store = _make_store(tmp_path, ["Fact X.", "Fact Y."])
    response = json.dumps([
        {"Q": "Q-low", "WHY_NOW": "n", "PROBE_KILL": "p", "STAKES": 0.3, "fact_ids": ["fact_0"]},
        {"Q": "Q-high", "WHY_NOW": "n", "PROBE_KILL": "p", "STAKES": 0.9, "fact_ids": ["fact_1"]},
    ])
    provider = MockProvider(responses=[response])
    cards = await run_prospect("neuro", store, provider, max_cards=5)
    assert len(cards) == 2
    stakes_order = [c[1]["card"]["STAKES"] for c in cards]
    assert stakes_order == sorted(stakes_order, reverse=True)


@pytest.mark.asyncio
async def test_cards_carry_all_four_fields(tmp_path):
    """Each returned card contains Q, WHY_NOW, PROBE_KILL, STAKES."""
    store = _make_store(tmp_path, ["Some claim."])
    response = json.dumps([
        {
            "Q": "open question",
            "WHY_NOW": "recent data",
            "PROBE_KILL": "kill criterion",
            "STAKES": 0.7,
            "fact_ids": ["fact_0"],
        }
    ])
    provider = MockProvider(responses=[response])
    cards = await run_prospect("neuro", store, provider, max_cards=5)
    assert len(cards) == 1
    _, refs = cards[0]
    card_dict = refs["card"]
    assert "Q" in card_dict
    assert "WHY_NOW" in card_dict
    assert "PROBE_KILL" in card_dict
    assert "STAKES" in card_dict
    assert isinstance(card_dict["STAKES"], float)
