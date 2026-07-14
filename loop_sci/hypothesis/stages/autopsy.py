"""autopsy' stage — convert kills into CONSTRAINT / CANDIDATE / REGION_CLOSE.

Implements OpenSpec tasks 3.1, 3.2, 3.3:

* **autopsy' (3.1):** Each DOWN verdict is classified into one of three outcomes:
  ``CONSTRAINT`` (the kill reason narrows the search space),
  ``CANDIDATE``   (an alternative pathway was identified),
  ``REGION_CLOSE`` (the region is exhausted / dead end).
  Classification is keyword-based and fully deterministic.

* **region-close (3.2):** :class:`RegionTracker` counts kills by latent root
  within the run.  When a root accumulates ≥2 kills it is CLOSED and
  ``record_kill`` returns ``True``.  Subsequent generation in that region
  is suppressed by the executor (Task 10) via :meth:`RegionTracker.is_closed`.

* **stall ledger (3.3):** :class:`StallLedger` tracks rounds that produce zero
  new accepted hypotheses (``new_accepted_count == 0``).  Signals:
  - ``"continue"``  — stale_count < 2
  - ``"pivot"``     — stale_count >= 2  (structural PIVOT)
  - ``"escalate"``  — stale_count >= 4  (ESCALATE: stop nudging)

  A non-zero round resets the stale counter.

Note: region-close and stall detection are fully deterministic — no provider
calls are made here.  Only classify_kill may optionally be extended with a
provider; in the current implementation it is also deterministic.
"""
from __future__ import annotations

from collections import Counter
from typing import Literal

from loop_sci.hypothesis.schemas import Autopsy, Verdict


# ---------------------------------------------------------------------------
# autopsy' (osp 3.1) — classify a DOWN verdict
# ---------------------------------------------------------------------------

_REGION_KEYWORDS: frozenset[str] = frozenset({"region", "dead", "exhausted"})
_CANDIDATE_KEYWORDS: frozenset[str] = frozenset({"alternative", "candidate"})


def classify_kill(verdict: Verdict, hyp_refs: dict) -> Autopsy:
    """Classify a DOWN verdict into an :class:`~loop_sci.hypothesis.schemas.Autopsy`.

    Classification is deterministic and keyword-based:

    * Any reason containing ``"region"``, ``"dead"``, or ``"exhausted"`` →
      ``REGION_CLOSE``.
    * Any reason containing ``"alternative"`` or ``"candidate"`` →
      ``CANDIDATE``.
    * Otherwise → ``CONSTRAINT`` (the default: the kill reason constrains
      future generation).

    ``Autopsy.region`` is populated from ``contract.LATENT_ROOT`` in
    *hyp_refs*, defaulting to ``"unknown"`` when absent.

    ``Autopsy.note`` contains all verdict reasons joined by ``"; "`` so the
    kill reason is never silently dropped — it persists for audit and is
    surfaced via :meth:`~loop_sci.state.idea_tree.IdeaTree.prune_node` /
    :meth:`~loop_sci.state.idea_tree.IdeaTree.get_constraints_block`.

    Args:
        verdict: A DOWN :class:`~loop_sci.hypothesis.schemas.Verdict` from
            the adversary' stage.
        hyp_refs: The ``Node.refs`` dict of the killed hypothesis node.
            Expected shape:
            ``{"contract": {"LATENT_ROOT": "..."}, "hyp": {...}, ...}``.

    Returns:
        An :class:`~loop_sci.hypothesis.schemas.Autopsy` instance.
    """
    contract = hyp_refs.get("contract") or {}
    latent_root: str = (
        contract.get("LATENT_ROOT", "unknown")
        if isinstance(contract, dict)
        else "unknown"
    )

    reasons_text: str = " ".join(verdict.reasons).lower()

    outcome: Literal["CONSTRAINT", "CANDIDATE", "REGION_CLOSE"]
    if any(kw in reasons_text for kw in _REGION_KEYWORDS):
        outcome = "REGION_CLOSE"
    elif any(kw in reasons_text for kw in _CANDIDATE_KEYWORDS):
        outcome = "CANDIDATE"
    else:
        outcome = "CONSTRAINT"

    return Autopsy(
        outcome=outcome,
        region=latent_root,
        note="; ".join(verdict.reasons),
    )


# ---------------------------------------------------------------------------
# StallLedger (osp 3.3) — detect structural stall
# ---------------------------------------------------------------------------


class StallLedger:
    """Track rounds with zero new accepted hypotheses and signal stall severity.

    Iteration state:

    * ``stale_count < 2``  → ``"continue"``
    * ``stale_count >= 2`` → ``"pivot"``   (structural PIVOT)
    * ``stale_count >= 4`` → ``"escalate"`` (ESCALATE: stop nudging)

    A non-zero *new_accepted_count* resets the stale counter.

    The executor (Task 10) persists round/stale_count via
    ``refs["iteration"]`` on the idea-tree node; :class:`StallLedger` is a
    stateful helper that owns the in-memory counter within a single run.

    Args:
        pivot_at:    Stale-count threshold for the PIVOT signal (default 2).
        escalate_at: Stale-count threshold for the ESCALATE signal (default 4).
    """

    def __init__(self, pivot_at: int = 2, escalate_at: int = 4) -> None:
        self._stall_count: int = 0
        self._pivot_at: int = pivot_at
        self._escalate_at: int = escalate_at

    @property
    def stall_count(self) -> int:
        """Current stale round counter (read-only)."""
        return self._stall_count

    def record_round(
        self, new_accepted_count: int
    ) -> Literal["continue", "pivot", "escalate"]:
        """Record the outcome of one generation round.

        Args:
            new_accepted_count: Number of NEW hypotheses accepted this round.
                Zero increments the stale counter; positive resets it.

        Returns:
            ``"continue"``  — no action needed.
            ``"pivot"``     — stale_count >= 2; signal structural PIVOT.
            ``"escalate"``  — stale_count >= 4; signal ESCALATE (stop).
        """
        if new_accepted_count == 0:
            self._stall_count += 1
        else:
            self._stall_count = 0

        if self._stall_count >= self._escalate_at:
            return "escalate"
        if self._stall_count >= self._pivot_at:
            return "pivot"
        return "continue"


# ---------------------------------------------------------------------------
# RegionTracker (osp 3.2) — close exhausted search regions
# ---------------------------------------------------------------------------


class RegionTracker:
    """Track kills per latent root and close regions that accumulate ≥threshold kills.

    When the same ``latent_root`` is killed ``threshold`` times within a run,
    that region is CLOSED.  :meth:`record_kill` returns ``True`` at the moment
    of closure and for all subsequent calls.  The executor (Task 10) checks
    :meth:`is_closed` before generating new hypotheses in a region.

    Region-close logic is fully deterministic — no provider calls.

    Args:
        threshold: Number of kills required to close a region (default 2).
    """

    def __init__(self, threshold: int = 2) -> None:
        self._kills: Counter[str] = Counter()
        self._closed: set[str] = set()
        self._threshold: int = threshold

    def record_kill(self, latent_root: str) -> bool:
        """Record one kill for *latent_root*.

        Args:
            latent_root: The ``contract.LATENT_ROOT`` of the killed hypothesis.

        Returns:
            ``True`` if this kill closes the region (i.e. the root now has ≥threshold
            kills), ``False`` otherwise.
        """
        self._kills[latent_root] += 1
        if self._kills[latent_root] >= self._threshold:
            self._closed.add(latent_root)
            return True
        return False

    def is_closed(self, latent_root: str) -> bool:
        """Return ``True`` if *latent_root* has been closed for this run."""
        return latent_root in self._closed
