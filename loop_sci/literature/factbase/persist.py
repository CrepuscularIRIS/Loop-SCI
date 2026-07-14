"""Persist a verified Fact to the foundation idea-tree and JSON fact store.

Tree structure
--------------
The caller is responsible for building and managing the topic-root and
paper-level nodes.  ``persist_fact`` only creates the *fact* leaf node:

    topic root  (depth 0)  — owned by caller
        └── paper node (depth 1)  — owned by caller, passed as paper_node_id
                └── fact node (depth 2)  — created here

The full ``Fact`` payload is embedded in the node's ``refs`` dict so that
the fact is self-contained inside the tree and no separate look-up is needed
by consumers that traverse tree nodes.

Guard
-----
Only facts with ``verification.status == "verified"`` may be persisted.
Any other status (``"rejected"``, ``"pending"``, ``"failed"``, ``"flagged"``,
or ``None``) raises ``ValueError`` immediately, before touching either the
tree or the JSON store.

Atomicity note
--------------
The tree is saved first (``IdeaTree.add_node`` calls ``tree.save()``
internally via the vendor implementation), then the JSON store is flushed.
This honours the foundation's *record-before-decide* invariant: the fact is
in the tree before the store write completes, so a crash between the two
leaves a detectable incomplete state rather than a silent data loss.
"""
from __future__ import annotations

import uuid
from typing import Any

from loop_sci.literature.extract.fact import Fact
from loop_sci.literature.factbase.store import FactStore
from loop_sci.state.idea_tree import IdeaTree, Node

__all__ = ["persist_fact"]


def persist_fact(
    fact: Fact,
    *,
    tree: IdeaTree,
    paper_node_id: str,
    store: FactStore,
) -> str:
    """Persist a single verified ``Fact`` to the idea-tree and JSON store.

    Args:
        fact: The fact to persist.  Must have
            ``fact.verification.status == "verified"``; any other status
            (including ``None``) raises ``ValueError``.
        tree: The ``IdeaTree`` instance to attach the fact node to.
        paper_node_id: The id of the paper node that becomes the parent of
            the new fact node.  The caller is responsible for creating this
            node (and deduplicating it by paper).
        store: The ``FactStore`` to persist the fact to.

    Returns:
        The ``fact_id`` string assigned to the fact.

    Raises:
        ValueError: If ``fact.verification`` is ``None`` or its ``status``
            is not ``"verified"``.
    """
    # Guard — only verified facts may be persisted
    actual_status = fact.verification.status if fact.verification else None
    if actual_status != "verified":
        raise ValueError(
            f"persist_fact: only verified facts may be persisted "
            f"(got status={actual_status!r}). "
            "Rejected, pending, failed, and flagged facts must not enter the fact base."
        )

    # Assign a stable fact_id if the fact does not already have one
    if not fact.fact_id:
        fact.fact_id = f"fact_{uuid.uuid4().hex[:12]}"
    fact_id: str = fact.fact_id

    # Build the fact node payload — embed the full Fact dict in refs so
    # consumers traversing the tree are self-contained.
    refs: dict[str, Any] = fact.to_dict()

    # Determine the node id: paper_node_id + fact_id to keep it unique within
    # the paper subtree even across multiple facts from the same paper.
    node_id = f"{paper_node_id}_{fact_id}"

    # Determine depth: paper nodes are depth 1 (topic root is depth 0),
    # so fact nodes live at depth 2.
    paper_node = tree.get_node(paper_node_id)
    fact_depth = (paper_node.depth + 1) if paper_node is not None else 2

    fact_node = Node(
        id=node_id,
        parent_id=paper_node_id,
        hypothesis=fact.claim,
        depth=fact_depth,
        status="done",
        refs=refs,
    )

    # Record-before-decide: tree is written first, then JSON store.
    tree.add_node(fact_node)

    # Add to JSON store (also assigns/preserves fact_id on the fact object).
    store.add(fact)

    return fact_id
