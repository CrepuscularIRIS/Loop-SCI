"""JSON fact store and idea-tree persistence for verified scientific facts.

Public API
----------
- ``FactStore`` — queryable JSON-backed store for verified facts.
- ``persist_fact`` — persist a single verified fact to both the JSON store
  and the foundation idea-tree (topic → paper → fact node structure).

Only facts with ``verification.status == "verified"`` may be persisted.
Attempting to persist any other status raises ``ValueError``.
"""
from __future__ import annotations

from loop_sci.literature.factbase.store import FactStore
from loop_sci.literature.factbase.persist import persist_fact

__all__ = ["FactStore", "persist_fact"]
