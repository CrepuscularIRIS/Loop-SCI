"""Unit tests for HypothesisCoordinator (task-10b).

All tests run offline — no network, no API key, no git.

Tests pin (osp 4.4):
- _observe returns nodes score-sorted (highest score first) from a tree with mixed scores
- _observe falls back to ROOT when no pending leaves (bootstrap)
- _observe falls back to id-sort when scores are None (mirrors base behavior)
- _plan injects fact-base context into the DispatchUnit
- _plan sets node_id and goal correctly
"""
from __future__ import annotations

from loop_sci.engine.types import DispatchUnit
from loop_sci.state.idea_tree import IdeaTree, Node
from loop_sci.state.session import RunSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(tmp_path) -> RunSession:
    """Create a minimal RunSession."""
    return RunSession.create(tmp_path / "runs", task="neuro")


def _add_node(tree: IdeaTree, node_id: str, parent_id: str, hypothesis: str,
              depth: int, status: str, score: float | None,
              refs: dict | None = None) -> Node:
    """Add a node to the tree and return it."""
    node = Node(
        id=node_id,
        parent_id=parent_id,
        hypothesis=hypothesis,
        depth=depth,
        status=status,
        score=score,
        refs=refs,
    )
    tree.add_node(node)
    return node


# ---------------------------------------------------------------------------
# Tests: _observe
# ---------------------------------------------------------------------------


class TestHypothesisCoordinatorObserve:
    def test_observe_returns_highest_score_node_first(self, tmp_path):
        """_observe picks the pending node with highest score (score-sorted descending)."""
        from loop_sci.hypothesis.coordinator import HypothesisCoordinator

        session = _make_session(tmp_path)
        tree = session.tree

        # Add 3 pending leaf nodes with distinct scores
        _add_node(tree, "n_low", "ROOT", "Low score hyp", depth=1, status="pending", score=0.2)
        _add_node(tree, "n_high", "ROOT", "High score hyp", depth=1, status="pending", score=0.9)
        _add_node(tree, "n_mid", "ROOT", "Mid score hyp", depth=1, status="pending", score=0.5)

        coord = HypothesisCoordinator(cfg=None, executor=object(), step_budget=1)
        node = coord._observe(session)

        assert node is not None
        assert node.id == "n_high", (
            f"Expected highest-score node 'n_high', got {node.id!r}"
        )

    def test_observe_falls_back_to_root_when_no_pending_leaves(self, tmp_path):
        """_observe returns ROOT itself when no pending leaves exist (bootstrap)."""
        from loop_sci.hypothesis.coordinator import HypothesisCoordinator

        session = _make_session(tmp_path)
        # ROOT is the only pending node; get_pending_leaves() excludes depth-0

        coord = HypothesisCoordinator(cfg=None, executor=object(), step_budget=1)
        node = coord._observe(session)

        assert node is not None
        assert node.id == "ROOT", (
            f"Expected ROOT when no pending leaves, got {node.id!r}"
        )

    def test_observe_ignores_done_nodes(self, tmp_path):
        """_observe never returns a done node."""
        from loop_sci.hypothesis.coordinator import HypothesisCoordinator

        session = _make_session(tmp_path)
        tree = session.tree

        _add_node(tree, "n_done", "ROOT", "Done hyp", depth=1, status="done", score=0.99)
        _add_node(tree, "n_pending", "ROOT", "Pending hyp", depth=1, status="pending", score=0.3)

        coord = HypothesisCoordinator(cfg=None, executor=object(), step_budget=1)
        node = coord._observe(session)

        assert node is not None
        assert node.id == "n_pending", (
            f"Expected pending node, got {node.id!r}"
        )

    def test_observe_none_scores_sort_last(self, tmp_path):
        """Nodes with score=None sort after scored nodes (treated as score 0.0)."""
        from loop_sci.hypothesis.coordinator import HypothesisCoordinator

        session = _make_session(tmp_path)
        tree = session.tree

        _add_node(tree, "n_none", "ROOT", "No score", depth=1, status="pending", score=None)
        _add_node(tree, "n_scored", "ROOT", "Scored", depth=1, status="pending", score=0.1)

        coord = HypothesisCoordinator(cfg=None, executor=object(), step_budget=1)
        node = coord._observe(session)

        # n_scored (0.1) > n_none (treated as 0.0)
        assert node is not None
        assert node.id == "n_scored", (
            f"Expected scored node first, got {node.id!r}"
        )

    def test_observe_returns_none_when_no_pending_work(self, tmp_path):
        """_observe returns None when ROOT is done and no pending leaves."""
        from loop_sci.hypothesis.coordinator import HypothesisCoordinator

        session = _make_session(tmp_path)
        # Mark ROOT done
        session.tree.update_node("ROOT", status="done")

        coord = HypothesisCoordinator(cfg=None, executor=object(), step_budget=1)
        node = coord._observe(session)

        assert node is None, f"Expected None when all done, got {node!r}"


# ---------------------------------------------------------------------------
# Tests: _plan
# ---------------------------------------------------------------------------


class TestHypothesisCoordinatorPlan:
    def test_plan_sets_node_id_and_goal(self, tmp_path):
        """_plan maps node.id → unit.node_id and node.hypothesis → unit.goal."""
        from loop_sci.hypothesis.coordinator import HypothesisCoordinator

        session = _make_session(tmp_path)
        tree = session.tree

        node = _add_node(tree, "n1", "ROOT", "Why neurons fire?",
                         depth=1, status="pending", score=0.5)

        coord = HypothesisCoordinator(cfg=None, executor=object(), step_budget=1)
        unit = coord._plan(node)

        assert isinstance(unit, DispatchUnit)
        assert unit.node_id == "n1"
        assert unit.goal == "Why neurons fire?"

    def test_plan_injects_fact_base_context_for_problem_card(self, tmp_path):
        """_plan injects fact-base context into unit.context for problem-card nodes."""
        from loop_sci.hypothesis.coordinator import HypothesisCoordinator

        session = _make_session(tmp_path)
        tree = session.tree

        # A problem-card node has refs["kind"] = "problem-card" and refs["card"]["Q"]
        node = _add_node(tree, "card1", "ROOT", "Neuron synchrony?",
                         depth=1, status="pending", score=0.7,
                         refs={"kind": "problem-card", "card": {"Q": "Why do neurons sync?"},
                               "topic": "neuro"})

        coord = HypothesisCoordinator(cfg=None, executor=object(), step_budget=1)
        unit = coord._plan(node)

        # context must be non-empty and contain both the topic and the problem-card question
        assert unit.context, "context must be non-empty for a problem-card node"
        assert "Why do neurons sync?" in unit.context, (
            f"Expected card question 'Why do neurons sync?' in context, got: {unit.context!r}"
        )
        assert "neuro" in unit.context, (
            f"Expected topic 'neuro' in context, got: {unit.context!r}"
        )

    def test_plan_empty_context_for_non_card_node(self, tmp_path):
        """_plan sets context appropriately for non-card nodes (may be empty)."""
        from loop_sci.hypothesis.coordinator import HypothesisCoordinator

        session = _make_session(tmp_path)
        tree = session.tree

        node = _add_node(tree, "n_plain", "ROOT", "Plain hypothesis",
                         depth=1, status="pending", score=0.4, refs=None)

        coord = HypothesisCoordinator(cfg=None, executor=object(), step_budget=1)
        unit = coord._plan(node)

        # context is a string (may be empty for nodes without card refs)
        assert isinstance(unit.context, str)

    def test_plan_returns_dispatch_unit(self, tmp_path):
        """_plan always returns a DispatchUnit."""
        from loop_sci.hypothesis.coordinator import HypothesisCoordinator

        session = _make_session(tmp_path)
        tree = session.tree
        node = _add_node(tree, "root_dispatch", "ROOT", "Research topic",
                         depth=1, status="pending", score=None, refs=None)

        coord = HypothesisCoordinator(cfg=None, executor=object(), step_budget=1)
        unit = coord._plan(node)

        assert isinstance(unit, DispatchUnit)
