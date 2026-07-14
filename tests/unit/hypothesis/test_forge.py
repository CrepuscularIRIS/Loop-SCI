"""Tests for loop_sci.hypothesis.stages.forge (forge' stage).

All tests are offline — use MockProvider from conftest, no network, no API key.
"""
import json

import pytest

from loop_sci.hypothesis.stages.forge import run_forge, _is_relabeling
from loop_sci.hypothesis.schemas import ProblemCard, build_card_refs
from loop_sci.literature.extract.fact import Fact, SourceRef
from loop_sci.literature.factbase.store import FactStore
from loop_sci.state.idea_tree import IdeaTree, Node

from tests.conftest import MockProvider


def _store_with_fact(tmp_path) -> FactStore:
    store = FactStore(tmp_path / "facts.json")
    f = Fact(
        claim="Neurons fire action potentials.",
        source_ref=SourceRef(source="s2", external_id="s0"),
        evidence_span="Neurons fire",
        confidence=0.9,
        grounding_scope="abstract",
    )
    f.fact_id = "fact_0"
    store.add(f)
    return store


def _card_refs() -> dict:
    card = ProblemCard(Q="Why?", WHY_NOW="now", PROBE_KILL="pk", STAKES=0.9)
    return build_card_refs(kind="problem-card", frame="primary", topic="neuro", card=card)


@pytest.mark.asyncio
async def test_candidates_have_required_fields(tmp_path):
    """Each candidate has MECHANISM/KILL/BRACKET/DIFF_PREDICTION; rival frame present."""
    store = _store_with_fact(tmp_path)
    response = json.dumps({"candidates": [
        {
            "MECHANISM": "Glial sync",
            "KILL": "no glial",
            "BRACKET": "plausible",
            "DIFF_PREDICTION": "Distinct EEG signature",
            "frame": "primary",
            "derivation": [
                {"step": "Neurons → glia", "grade": "[inferred]", "fact_ids": ["fact_0"]}
            ],
        },
        {
            "MECHANISM": "Rival mech",
            "KILL": "rival kill",
            "BRACKET": "low",
            "DIFF_PREDICTION": "Different pattern",
            "frame": "rival",
            "derivation": [{"step": "Alternative", "grade": "[guess]", "fact_ids": []}],
        },
    ]})
    provider = MockProvider(responses=[response])
    results = await run_forge("card_1", _card_refs(), store, provider, max_candidates=4)
    assert len(results) >= 2
    hyp_node_id, hyp_refs, derivation = results[0]
    assert hyp_refs["hyp"]["MECHANISM"] == "Glial sync"
    frames = [r[1]["frame"] for r in results]
    assert "rival" in frames


@pytest.mark.asyncio
async def test_relabeling_verbatim_discarded(tmp_path):
    """Candidate whose DIFF_PREDICTION is verbatim identical to MECHANISM is discarded."""
    store = _store_with_fact(tmp_path)
    # DIFF_PREDICTION identical to MECHANISM = verbatim relabeling; must be discarded
    response = json.dumps({"candidates": [
        {
            "MECHANISM": "Neurons fire",
            "KILL": "k",
            "BRACKET": "b",
            "DIFF_PREDICTION": "Neurons fire",
            "frame": "primary",
            "derivation": [],
        },
    ]})
    provider = MockProvider(responses=[response])
    results = await run_forge("card_1", _card_refs(), store, provider, max_candidates=4)
    assert len(results) == 0


def test_is_relabeling_reworded_discard():
    """Reordered DIFF_PREDICTION with no new content tokens is classified as a relabeling.

    MECHANISM and DIFF_PREDICTION share exactly the same content tokens
    ("glial", "coupling", "increases", "neuronal", "gain") rearranged with
    only stopwords added.  No new predictive token is introduced → DISCARD.
    """
    mechanism = "Glial coupling increases neuronal gain"
    # Same five content tokens, different word order; "and" is a stopword.
    diff_pred = "Neuronal gain and glial coupling increases"
    assert _is_relabeling(mechanism, diff_pred) is True


def test_is_relabeling_new_token_survives():
    """DIFF_PREDICTION that introduces a genuinely new predictive token survives.

    "threshold" and "reduces" are content tokens not present in the mechanism,
    so this is NOT a relabeling and must SURVIVE.
    """
    mechanism = "Glial coupling increases neuronal gain"
    diff_pred = "Glial coupling increases neuronal gain and reduces threshold"
    assert _is_relabeling(mechanism, diff_pred) is False


@pytest.mark.asyncio
async def test_relabeling_reworded_discarded_end_to_end(tmp_path):
    """End-to-end: reordered DIFF_PREDICTION with no new tokens is discarded by run_forge."""
    store = _store_with_fact(tmp_path)
    response = json.dumps({"candidates": [
        {
            "MECHANISM": "Glial coupling increases neuronal gain",
            "KILL": "k",
            "BRACKET": "b",
            # Same five content tokens rearranged with a stopword → relabeling.
            "DIFF_PREDICTION": "Neuronal gain and glial coupling increases",
            "frame": "primary",
            "derivation": [],
        },
    ]})
    provider = MockProvider(responses=[response])
    results = await run_forge("card_1", _card_refs(), store, provider, max_candidates=4)
    assert len(results) == 0


@pytest.mark.asyncio
async def test_new_predictive_token_survives_end_to_end(tmp_path):
    """End-to-end: DIFF_PREDICTION with genuinely new tokens is NOT discarded."""
    store = _store_with_fact(tmp_path)
    response = json.dumps({"candidates": [
        {
            "MECHANISM": "Glial coupling increases neuronal gain",
            "KILL": "k",
            "BRACKET": "b",
            # "reduces" and "threshold" are new predictive tokens not in MECHANISM.
            "DIFF_PREDICTION": "Glial coupling increases neuronal gain and reduces threshold",
            "frame": "primary",
            "derivation": [],
        },
    ]})
    provider = MockProvider(responses=[response])
    results = await run_forge("card_1", _card_refs(), store, provider, max_candidates=4)
    assert len(results) == 1


@pytest.mark.asyncio
async def test_cap_respected(tmp_path):
    """At most max_candidates results are returned regardless of how many LLM generates."""
    store = _store_with_fact(tmp_path)
    candidates = [
        {
            "MECHANISM": f"Mech {i}",
            "KILL": "k",
            "BRACKET": "b",
            "DIFF_PREDICTION": f"Distinct pred {i}",
            "frame": "primary" if i == 0 else "rival",
            "derivation": [],
        }
        for i in range(10)
    ]
    response = json.dumps({"candidates": candidates})
    provider = MockProvider(responses=[response])
    results = await run_forge("card_1", _card_refs(), store, provider, max_candidates=4)
    assert len(results) <= 4


@pytest.mark.asyncio
async def test_malformed_json_returns_empty(tmp_path):
    """Non-JSON or non-object LLM response returns empty list without crashing."""
    store = _store_with_fact(tmp_path)
    provider = MockProvider(responses=["not json", "also not json"])
    results = await run_forge("card_1", _card_refs(), store, provider, max_candidates=4)
    assert results == []


@pytest.mark.asyncio
async def test_non_list_candidates_returns_empty(tmp_path):
    """JSON response with non-list candidates does not crash and returns empty list."""
    store = _store_with_fact(tmp_path)
    response = json.dumps({"candidates": "not a list"})
    provider = MockProvider(responses=[response])
    results = await run_forge("card_1", _card_refs(), store, provider, max_candidates=4)
    assert results == []


@pytest.mark.asyncio
async def test_candidate_grounding_fact_ids_in_refs(tmp_path):
    """Hypothesis refs carry derivation with fact_ids (grounding by fact-id in refs)."""
    store = _store_with_fact(tmp_path)
    response = json.dumps({"candidates": [
        {
            "MECHANISM": "Glial sync",
            "KILL": "no glial",
            "BRACKET": "plausible",
            "DIFF_PREDICTION": "Distinct EEG signature",
            "frame": "primary",
            "derivation": [
                {"step": "Neurons → glia", "grade": "[inferred]", "fact_ids": ["fact_0"]}
            ],
        },
    ]})
    provider = MockProvider(responses=[response])
    results = await run_forge("card_1", _card_refs(), store, provider, max_candidates=4)
    assert len(results) == 1
    _, hyp_refs, derivation = results[0]
    # Grounding fact-ids live in derivation within refs
    assert hyp_refs["derivation"][0]["fact_ids"] == ["fact_0"]
    assert derivation[0].fact_ids == ["fact_0"]


@pytest.mark.asyncio
async def test_hypothesis_nodes_are_children_and_siblings_of_card_node(tmp_path):
    """Forge triples attached to a real IdeaTree become children of the card node.

    Verifies:
    - Both hyp nodes have parent_id == card_node_id (children of card).
    - Both appear in tree.get_children(card_node_id) (siblings of each other).
    - hyp_node_ids are unique.
    """
    store = _store_with_fact(tmp_path)
    card_node_id = "card_node_xyz"
    response = json.dumps({"candidates": [
        {
            "MECHANISM": "Mech A",
            "KILL": "k",
            "BRACKET": "b",
            "DIFF_PREDICTION": "Pred A distinct observable",
            "frame": "primary",
            "derivation": [],
        },
        {
            "MECHANISM": "Rival A",
            "KILL": "rk",
            "BRACKET": "rb",
            "DIFF_PREDICTION": "Rival pred distinct signature",
            "frame": "rival",
            "derivation": [],
        },
    ]})
    provider = MockProvider(responses=[response])
    results = await run_forge(card_node_id, _card_refs(), store, provider, max_candidates=4)

    assert len(results) == 2
    hyp_node_id_0 = results[0][0]
    hyp_node_id_1 = results[1][0]
    # IDs must be unique
    assert hyp_node_id_0 != hyp_node_id_1

    # Build a real IdeaTree and attach the returned triples as children of the card node.
    root = Node(id="ROOT", parent_id=None, hypothesis="root topic", depth=0, status="pending")
    tree = IdeaTree(root=root, json_path=tmp_path / "tree.json")

    card_node = Node(
        id=card_node_id,
        parent_id="ROOT",
        hypothesis="Why neurons synchronize?",
        depth=1,
        status="pending",
    )
    tree.add_node(card_node)

    # Attach each returned forge triple as a child of the card node.
    for hyp_node_id, hyp_refs, _derivation in results:
        hyp_statement = hyp_refs.get("hyp", {}).get("MECHANISM", hyp_node_id)
        node = Node(
            id=hyp_node_id,
            parent_id=card_node_id,
            hypothesis=hyp_statement,
            depth=2,
            status="pending",
            refs=hyp_refs,
        )
        tree.add_node(node)

    # Assert both hypothesis nodes are children of the card node.
    assert tree.get_node(hyp_node_id_0).parent_id == card_node_id
    assert tree.get_node(hyp_node_id_1).parent_id == card_node_id

    # Assert tree.get_children returns both — they are siblings under the card node.
    child_ids = {child.id for child in tree.get_children(card_node_id)}
    assert hyp_node_id_0 in child_ids
    assert hyp_node_id_1 in child_ids
