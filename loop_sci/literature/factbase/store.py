"""JSON-backed fact store for verified scientific facts.

Design
------
- ``FactStore`` wraps a single JSON file on disk.
- Every ``add`` call immediately flushes to disk using an atomic
  write-then-rename pattern (write to ``.tmp``, replace target) so the
  on-disk state is always a valid JSON array.
- ``all()`` and ``filter()`` reconstruct ``Fact`` objects via
  ``Fact.from_dict`` so that every round-trip is lossless.
- ``filter()`` accepts keyword-only ``source`` and ``topic`` arguments so
  the (future) hypothesis-engine can query WITHOUT touching idea-tree
  internals.

Only the ``FactStore`` interface (``add``, ``all``, ``filter``) is public.
Internal helpers are module-private.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from loop_sci.literature.extract.fact import Fact

__all__ = ["FactStore"]


class FactStore:
    """Queryable, JSON-backed store for verified scientific facts.

    Args:
        path: File path for the JSON store.  The file is created on first
            ``add``; an existing file is loaded on construction.

    The public query interface is intentionally minimal so that downstream
    consumers (hypothesis-engine etc.) never need to touch idea-tree internals:

    * ``all()`` — return every stored fact.
    * ``filter(*, source=None, topic=None)`` — return facts matching all
      supplied predicates (``AND`` semantics).
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._records: list[dict[str, Any]] = []
        if self._path.exists():
            self._records = json.loads(self._path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def add(self, fact: Fact) -> str:
        """Persist *fact* to the store and return its stable ``fact_id``.

        A ``fact_id`` is assigned if the fact does not already carry one.
        The store is flushed to disk atomically after each call.

        Args:
            fact: The fact to store.  **Caller is responsible for ensuring
                only verified facts are added** (``persist_fact`` enforces
                this; direct callers of ``add`` may add any fact).

        Returns:
            The stable ``fact_id`` string.
        """
        if not fact.fact_id:
            fact.fact_id = f"fact_{uuid.uuid4().hex[:12]}"
        record = fact.to_dict()
        self._records.append(record)
        self._flush()
        return fact.fact_id

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def all(self) -> list[Fact]:
        """Return all facts currently in the store.

        Facts are reconstructed via ``Fact.from_dict`` so the result is
        identical to the original ``Fact`` objects (lossless round-trip).
        """
        return [Fact.from_dict(r) for r in self._records]

    def filter(
        self,
        *,
        source: str | None = None,
        topic: str | None = None,
    ) -> list[Fact]:
        """Return facts matching all supplied predicates (AND semantics).

        Args:
            source: If given, keep only facts whose
                ``source_ref.source`` equals this string (exact match).
            topic: If given, keep only facts whose ``claim`` contains this
                string (case-insensitive substring match).

        Returns:
            Filtered list of ``Fact`` objects.  An empty list is returned
            when no facts match, never ``None``.
        """
        results: list[Fact] = self.all()
        if source is not None:
            results = [f for f in results if f.source_ref.source == source]
        if topic is not None:
            needle = topic.lower()
            results = [f for f in results if needle in f.claim.lower()]
        return results

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _flush(self) -> None:
        """Atomically write the current in-memory records to disk."""
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self._path)
