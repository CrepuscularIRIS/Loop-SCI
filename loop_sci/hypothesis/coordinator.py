"""HypothesisCoordinator — score-sorted observe + fact-base context injection.

Subclass of :class:`~loop_sci.engine.coordinator.Coordinator` that overrides
ONLY ``_observe`` and ``_plan``.  All other methods (``run``, ``_record``) are
inherited unchanged.

``_observe`` picks the pending leaf with the highest ``Node.score`` (descending)
instead of the id-sorted order used by the base class.  When no scored pending
leaves exist the same ROOT-bootstrap and running-node fallbacks as the base class
apply, so the coordinator is safe to use on fresh sessions.

``_plan`` injects fact-base context (problem-card question + topic) into
``DispatchUnit.context`` so downstream stages receive the relevant framing.
"""
from __future__ import annotations

import logging

from loop_sci.engine.coordinator import Coordinator
from loop_sci.engine.types import DispatchUnit
from loop_sci.state.idea_tree import Node
from loop_sci.state.session import RunSession

log = logging.getLogger(__name__)

__all__ = ["HypothesisCoordinator"]


class HypothesisCoordinator(Coordinator):
    """Coordinator subclass for the hypothesis engine.

    Differences from the base :class:`Coordinator`:
    - ``_observe``: picks the next pending leaf by highest ``Node.score``
      (descending) rather than lowest ``Node.id`` (ascending).  Nodes with
      ``score=None`` are treated as ``0.0`` so they sort after any scored node.
      The ROOT-bootstrap and stale-running fallbacks from the base class are
      preserved.
    - ``_plan``: injects fact-base context (problem-card question + topic) into
      ``DispatchUnit.context`` so downstream stages receive relevant framing.

    No other method is overridden.  ``auto_git`` stays OFF (inherited from base).
    """

    # ------------------------------------------------------------------
    # Observe — score-priority expansion
    # ------------------------------------------------------------------

    def _observe(self, session: RunSession) -> Node | None:
        """Return the pending leaf with the highest score, or ROOT for bootstrap.

        Strategy (mirrors base class bootstrap logic):
        1. get_pending_leaves() returns non-ROOT pending leaves.
           Sort descending by score (None → 0.0).  Return best.
        2. If empty and ROOT is pending → return ROOT (bootstrap case).
        3. If empty and stale ``running`` leaves exist → return highest-score one.
        4. If ROOT is stale ``running`` → return ROOT.
        5. Otherwise → return None (session done).
        """
        pending = session.tree.get_pending_leaves()
        if pending:
            return max(pending, key=lambda n: n.score if n.score is not None else 0.0)

        root = session.tree.get_root()
        if root.status == "pending":
            return root

        # Recover stale running leaves (crash-interrupted mid-dispatch)
        running = [
            n
            for n in session.tree.get_all_nodes()
            if n.status == "running"
            and not n.children_ids
            and n.depth > 0
        ]
        if running:
            return max(running, key=lambda n: n.score if n.score is not None else 0.0)

        if root.status == "running":
            return root

        return None

    # ------------------------------------------------------------------
    # Plan — inject fact-base context
    # ------------------------------------------------------------------

    def _plan(self, node: Node) -> DispatchUnit:
        """Build a DispatchUnit, injecting fact-base context for problem-card nodes.

        For nodes whose ``refs["kind"] == "problem-card"``, the context is
        populated with the card question and topic so downstream stages can
        leverage the fact-base framing.  All other nodes receive an empty
        context (same as the base class).
        """
        context = ""

        if node.refs:
            kind = node.refs.get("kind", "")
            if kind == "problem-card":
                card = node.refs.get("card", {})
                question = card.get("Q", "")
                topic = node.refs.get("topic", "")
                parts: list[str] = []
                if topic:
                    parts.append(f"Topic: {topic}")
                if question:
                    parts.append(f"Problem card: {question}")
                context = " | ".join(parts)
            elif node.refs.get("topic"):
                # For hypothesis nodes, inject the topic for orientation
                context = f"Topic: {node.refs['topic']}"

        return DispatchUnit(
            node_id=node.id,
            goal=node.hypothesis,
            context=context,
            tools=[],
        )
