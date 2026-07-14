"""Append-only verdict ledger for hypothesis lifecycle tracking.

Design
------
``VerdictLedger`` wraps a single ``verdict-ledger.jsonl`` file on disk.
Every :meth:`append` call flushes exactly one new JSON-line to disk (open
in append mode, write, close) so that entries survive process restart and
a partially-written file never corrupts earlier records.

On construction the existing file (if any) is read once to populate the
in-memory cache.  A trailing malformed line is silently skipped — only the
first ``json.JSONDecodeError`` is tolerated per line (mirror the retry-once
→ drop tolerance used in ``loop_sci.literature``).

The :meth:`accepted_node_ids` reader provides the fast scan needed by the
resume path: return the set of ``node_id`` values whose ``result`` is
``"UP"`` so the caller can skip re-critiquing already-accepted hypotheses
without re-spending a jury call.
"""
from __future__ import annotations

import json
from pathlib import Path

__all__ = ["VerdictLedger"]


class VerdictLedger:
    """Append-only JSONL ledger recording every issued hypothesis verdict.

    Args:
        path: Path to the ``verdict-ledger.jsonl`` file.  The file is
            created on the first :meth:`append`; an existing file is loaded
            on construction.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._entries: list[dict] = []
        if self._path.exists():
            for line in self._path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    self._entries.append(json.loads(line))
                except json.JSONDecodeError:
                    # Silently skip a trailing malformed line (e.g. interrupted
                    # write); earlier valid entries are unaffected.
                    continue

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def append(
        self,
        verdict_id: str,
        node_id: str,
        reviewer_model: str,
        result: str,
        *,
        round_n: int,
    ) -> None:
        """Append a single verdict entry to the ledger.

        The entry is appended to the in-memory cache **and** flushed to
        disk atomically within a single ``open``/``write``/``close`` cycle
        so the file is always in a consistent state for a re-opened reader.

        Args:
            verdict_id: Unique identifier for this verdict (e.g. ``"v1"``).
            node_id: Idea-tree node id of the hypothesis being judged.
            reviewer_model: Model name that issued the verdict.
            result: ``"UP"`` (accepted) or ``"DOWN"`` (rejected).
            round_n: Review round number (keyword-only).
        """
        entry: dict = {
            "verdict_id": verdict_id,
            "node_id": node_id,
            "reviewer_model": reviewer_model,
            "result": result,
            "round": round_n,
        }
        self._entries.append(entry)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def accepted_node_ids(self) -> set[str]:
        """Return the set of node_ids whose verdict result is ``"UP"``.

        Used by the resume path to skip already-accepted hypotheses without
        re-critiquing them or spending another jury call.
        """
        return {e["node_id"] for e in self._entries if e.get("result") == "UP"}

    def all_entries(self) -> list[dict]:
        """Return a copy of all ledger entries loaded or appended so far.

        Returns:
            List of dicts, each representing one verdict entry.  The list
            is a shallow copy; mutating it does not affect the ledger state.
        """
        return list(self._entries)
