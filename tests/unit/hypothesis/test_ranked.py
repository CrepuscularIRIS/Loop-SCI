"""Tests for loop_sci.hypothesis.ranked — stable ranked-hypothesis query interface.

Covers: ordering (best-first by score, None sorts last), filtering by topic
and status, required fields on returned items, and no IdeaTree leakage.
"""
from __future__ import annotations

from loop_sci.hypothesis.ranked import RankedHypothesis, RankedHypothesisStore
from loop_sci.hypothesis.schemas import (
    DerivationStep,
    HypothesisHyp,
    Iteration,
    Scores,
    Verdict,
    build_hyp_refs,
)
from loop_sci.state.idea_tree import IdeaTree, Node


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_node(
    node_id: str,
    mechanism: str,
    topic: str,
    score: float | None,
    status: str = "accepted",
    derivation: list[DerivationStep] | None = None,
    grounding: list[str] | None = None,
) -> Node:
    """Build a hypothesis Node with a valid refs payload."""
    derivation = derivation or []
    refs = build_hyp_refs(
        kind="hypothesis",
        frame="primary",
        topic=topic,
        hyp=HypothesisHyp(
            MECHANISM=mechanism,
            KILL="kill_condition",
            BRACKET="bracket_info",
            DIFF_PREDICTION=f"prediction for {mechanism}",
        ),
        derivation=derivation,
        contract=None,
        verdict=Verdict(
            id="v1",
            reviewer_model="qwen-plus",
            result="UP",
            reasons=[],
            decided_by="jury",
        ),
        scores=Scores(novelty=score or 0.0, self_consistency=score or 0.0)
        if score is not None
        else None,
        autopsy=None,
        iteration=Iteration(),
    )
    return Node(
        id=node_id,
        parent_id="ROOT",
        hypothesis=mechanism,
        depth=1,
        status=status,
        score=score,
        refs=refs,
        grounding=grounding,
    )


def _make_tree(tmp_path, nodes: list[Node]) -> IdeaTree:
    """Create an IdeaTree with a root node and the supplied hypothesis nodes."""
    root = Node(
        id="ROOT",
        parent_id=None,
        hypothesis="root topic",
        depth=0,
        status="pending",
    )
    tree = IdeaTree(root=root, json_path=tmp_path / "tree.json")
    for n in nodes:
        tree.add_node(n)
    return tree


# ---------------------------------------------------------------------------
# Test: required fields are present and populated correctly
# ---------------------------------------------------------------------------


def test_get_ranked_returns_required_fields(tmp_path):
    """Returned RankedHypothesis carries ALL required fields."""
    derivation = [DerivationStep(step="s1", grade="[paper]", fact_ids=["fact_0"])]
    node = _make_node(
        "hyp_1", "Glia encode fear", "neuro", 0.85,
        derivation=derivation, grounding=["fact_0"]
    )
    tree = _make_tree(tmp_path, [node])

    store = RankedHypothesisStore(tree)
    results = store.get_ranked()

    assert len(results) == 1
    r = results[0]
    assert isinstance(r, RankedHypothesis)

    # required fields
    assert r.node_id == "hyp_1"
    assert r.problem == "neuro"
    assert r.mechanism == "Glia encode fear"
    assert r.diff_prediction == "prediction for Glia encode fear"
    assert r.novelty == 0.85
    assert r.self_consistency == 0.85
    assert r.overall_score == 0.85
    assert "fact_0" in r.grounding_fact_ids

    # derivation chain carries evidence grades
    assert len(r.derivation_chain) == 1
    step = r.derivation_chain[0]
    assert step["step"] == "s1"
    assert step["grade"] == "[paper]"
    assert "fact_0" in step["fact_ids"]

    # must NOT expose tree internals
    assert not hasattr(r, "refs")


def test_returned_item_is_not_a_node(tmp_path):
    """Consumer must not need to import Node or IdeaTree to read the result."""
    node = _make_node("hyp_1", "Test mechanism", "bio", 0.7)
    tree = _make_tree(tmp_path, [node])

    store = RankedHypothesisStore(tree)
    results = store.get_ranked()

    assert len(results) == 1
    r = results[0]
    # RankedHypothesis is not a Node
    assert not isinstance(r, Node)
    # All fields accessible directly — no tree traversal needed
    assert isinstance(r.node_id, str)
    assert isinstance(r.problem, str)
    assert isinstance(r.mechanism, str)
    assert isinstance(r.derivation_chain, list)
    assert isinstance(r.grounding_fact_ids, list)


# ---------------------------------------------------------------------------
# Test: ordering best-first by score (None sorts last)
# ---------------------------------------------------------------------------


def test_get_ranked_ordered_best_first(tmp_path):
    """Results are ordered descending by overall_score."""
    scores = [0.3, 0.9, 0.6]
    nodes = [
        _make_node(f"hyp_{i}", f"mechanism_{i}", "neuro", s)
        for i, s in enumerate(scores)
    ]
    tree = _make_tree(tmp_path, nodes)

    results = RankedHypothesisStore(tree).get_ranked()

    result_scores = [r.overall_score for r in results]
    assert result_scores == sorted(result_scores, reverse=True)
    assert result_scores[0] == 0.9


def test_none_score_sorts_last(tmp_path):
    """A node with score=None appears after all scored nodes."""
    node_scored = _make_node("hyp_scored", "Scored mechanism", "neuro", 0.5)
    node_none = _make_node("hyp_none", "Unscored mechanism", "neuro", None)
    tree = _make_tree(tmp_path, [node_none, node_scored])

    results = RankedHypothesisStore(tree).get_ranked()

    assert len(results) == 2
    assert results[0].node_id == "hyp_scored"
    assert results[1].node_id == "hyp_none"
    # None score exposed as None in result (or 0.0 sentinel — check it's last)
    assert results[0].overall_score >= (results[1].overall_score or -1)


# ---------------------------------------------------------------------------
# Test: filter by topic
# ---------------------------------------------------------------------------


def test_filter_by_topic(tmp_path):
    """get_ranked(topic=...) returns only nodes with matching topic."""
    node_neuro = _make_node("hyp_neuro", "Neuro mechanism", "neuro", 0.8)
    node_bio = _make_node("hyp_bio", "Bio mechanism", "bio", 0.9)
    tree = _make_tree(tmp_path, [node_neuro, node_bio])

    results = RankedHypothesisStore(tree).get_ranked(topic="neuro")

    assert len(results) == 1
    assert results[0].node_id == "hyp_neuro"
    assert results[0].problem == "neuro"


def test_filter_by_topic_no_match(tmp_path):
    """get_ranked(topic=...) returns empty list when no match."""
    node = _make_node("hyp_1", "Some mechanism", "bio", 0.7)
    tree = _make_tree(tmp_path, [node])

    results = RankedHypothesisStore(tree).get_ranked(topic="physics")

    assert results == []


# ---------------------------------------------------------------------------
# Test: filter by status
# ---------------------------------------------------------------------------


def test_filter_by_status(tmp_path):
    """get_ranked(status=...) returns only nodes with matching status."""
    node_accepted = _make_node("hyp_a", "Accepted mechanism", "neuro", 0.8, status="accepted")
    node_open = _make_node("hyp_o", "Open mechanism", "neuro", 0.6, status="open")
    tree = _make_tree(tmp_path, [node_accepted, node_open])

    results = RankedHypothesisStore(tree).get_ranked(status="accepted")

    assert len(results) == 1
    assert results[0].node_id == "hyp_a"


def test_filter_by_status_open(tmp_path):
    """Filter by status='open' works."""
    node_accepted = _make_node("hyp_a", "Accepted mechanism", "neuro", 0.8, status="accepted")
    node_open = _make_node("hyp_o", "Open mechanism", "neuro", 0.6, status="open")
    tree = _make_tree(tmp_path, [node_accepted, node_open])

    results = RankedHypothesisStore(tree).get_ranked(status="open")

    assert len(results) == 1
    assert results[0].node_id == "hyp_o"


# ---------------------------------------------------------------------------
# Test: combined filters
# ---------------------------------------------------------------------------


def test_filter_by_topic_and_status(tmp_path):
    """Combining topic and status filters ANDs them together."""
    node_a = _make_node("hyp_a", "Mech A", "neuro", 0.9, status="accepted")
    node_b = _make_node("hyp_b", "Mech B", "neuro", 0.7, status="open")
    node_c = _make_node("hyp_c", "Mech C", "bio", 0.8, status="accepted")
    tree = _make_tree(tmp_path, [node_a, node_b, node_c])

    results = RankedHypothesisStore(tree).get_ranked(topic="neuro", status="accepted")

    assert len(results) == 1
    assert results[0].node_id == "hyp_a"


# ---------------------------------------------------------------------------
# Test: nodes without refs (root/problem-card) are skipped
# ---------------------------------------------------------------------------


def test_nodes_without_refs_are_skipped(tmp_path):
    """Non-hypothesis nodes (no refs or kind != hypothesis) are excluded."""
    hyp_node = _make_node("hyp_1", "Valid mechanism", "neuro", 0.7)
    tree = _make_tree(tmp_path, [hyp_node])
    # The root node has no refs and should be excluded
    results = RankedHypothesisStore(tree).get_ranked()

    # Only the hypothesis node, not the root
    assert len(results) == 1
    assert results[0].node_id == "hyp_1"
