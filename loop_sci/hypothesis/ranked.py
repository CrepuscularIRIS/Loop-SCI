"""Stable ranked-hypothesis query interface.

Provides :class:`RankedHypothesisStore` which wraps an :class:`IdeaTree` and
exposes a single :meth:`~RankedHypothesisStore.get_ranked` method that
returns hypothesis nodes as plain :class:`RankedHypothesis` dataclasses —
**without** leaking IdeaTree ``Node`` objects to the caller.

The downstream plan-assembler (Task 5 / OpenSpec 4.2) calls this interface to
retrieve hypotheses ranked by score.  Callers never need to import or traverse
``IdeaTree``/``Node`` internals.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from loop_sci.hypothesis.schemas import refs_from_dict
from loop_sci.state.idea_tree import IdeaTree

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public data structure — NO Node objects, NO tree ids used for navigation
# ---------------------------------------------------------------------------


@dataclass
class RankedHypothesis:
    """Plain, stable view of a hypothesis node ranked by quality score.

    All fields are primitive Python types; callers need no hypothesis-internal
    or idea-tree imports to consume this object.

    Attributes:
        node_id: Opaque string handle for the tree node (stable across runs).
        problem: Topic / problem-card question this hypothesis addresses.
        mechanism: The core mechanistic claim (``HypothesisHyp.MECHANISM``).
        derivation_chain: Ordered list of derivation steps, each a dict with
            keys ``step``, ``grade`` (``[paper]``/``[inferred]``/``[guess]``),
            and ``fact_ids``.
        diff_prediction: Testable differential prediction (``DIFF_PREDICTION``).
        novelty: Novelty sub-score (from ``Scores.novelty``; ``None`` if absent).
        self_consistency: Self-consistency sub-score (``None`` if absent).
        overall_score: Weighted overall score stored on the tree node
            (``Node.score``); ``None`` when the executor has not yet assigned it.
        grounding_fact_ids: Fact/reference ids grounding this hypothesis.
    """

    node_id: str
    problem: str
    mechanism: str
    derivation_chain: list[dict[str, Any]]
    diff_prediction: str
    novelty: float | None
    self_consistency: float | None
    overall_score: float | None
    grounding_fact_ids: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Query store
# ---------------------------------------------------------------------------


class RankedHypothesisStore:
    """Read-only view over an :class:`IdeaTree` that returns ranked hypotheses.

    Args:
        tree: The idea tree to query.  Must already contain nodes whose
            ``refs`` dict was built with :func:`~loop_sci.hypothesis.schemas.build_hyp_refs`.

    Example::

        store = RankedHypothesisStore(tree)
        top_hypotheses = store.get_ranked(topic="neuro", status="accepted")
    """

    def __init__(self, tree: IdeaTree) -> None:
        self._tree = tree

    def get_ranked(
        self,
        *,
        topic: str | None = None,
        status: str | None = None,
    ) -> list[RankedHypothesis]:
        """Return hypothesis nodes as ranked :class:`RankedHypothesis` items.

        Items are ordered **best-first** by ``Node.score`` (descending).
        Nodes with ``score=None`` sort deterministically after all scored nodes.

        Args:
            topic: When provided, only nodes whose ``refs["topic"]`` equals
                this string are included.
            status: When provided, only nodes whose ``Node.status`` equals
                this string are included (e.g. ``"accepted"``, ``"open"``).

        Returns:
            A list of :class:`RankedHypothesis` instances, sorted best-first.
            Returns an empty list when no nodes match the filters.
        """
        results: list[RankedHypothesis] = []

        for node in self._tree.get_all_nodes():
            # Skip nodes without a refs payload
            if not node.refs:
                continue
            # Only include proper hypothesis nodes
            if node.refs.get("kind") != "hypothesis":
                continue
            # Apply status filter
            if status is not None and node.status != status:
                continue
            # Apply topic filter
            if topic is not None and node.refs.get("topic") != topic:
                continue

            # Deserialise refs payload; skip malformed nodes gracefully
            try:
                refs = refs_from_dict(node.refs)
            except Exception as exc:
                log.warning("ranked: skipping malformed node %r refs payload: %s", node.id, exc)
                continue

            # Skip nodes whose payload lacks a hypothesis block
            if refs.hyp is None:
                continue

            # Extract sub-scores (may be absent for nodes not yet scored)
            novelty: float | None = None
            self_consistency: float | None = None
            if refs.scores is not None:
                novelty = refs.scores.novelty
                self_consistency = refs.scores.self_consistency

            # Build serialisable derivation chain
            derivation_chain: list[dict[str, Any]] = [
                {
                    "step": step.step,
                    "grade": step.grade,
                    "fact_ids": list(step.fact_ids),
                }
                for step in refs.derivation
            ]

            # Collect grounding fact-ids from derivation steps (deduped, order-preserving).
            # Contract (forge.py line 24-25): grounding lives in derivation[].fact_ids
            # inside hyp_refs — NEVER in the native Node.grounding string.
            seen: set[str] = set()
            grounding_fact_ids: list[str] = []
            for step in refs.derivation:
                for fid in step.fact_ids:
                    if fid not in seen:
                        seen.add(fid)
                        grounding_fact_ids.append(fid)

            results.append(
                RankedHypothesis(
                    node_id=node.id,
                    problem=refs.topic,
                    mechanism=refs.hyp.MECHANISM,
                    derivation_chain=derivation_chain,
                    diff_prediction=refs.hyp.DIFF_PREDICTION,
                    novelty=novelty,
                    self_consistency=self_consistency,
                    overall_score=node.score,
                    grounding_fact_ids=grounding_fact_ids,
                )
            )

        # Sort best-first; None scores sort last (treated as -infinity)
        return sorted(
            results,
            key=lambda r: r.overall_score if r.overall_score is not None else float("-inf"),
            reverse=True,
        )
