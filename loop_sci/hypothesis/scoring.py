"""Hypothesis scorer: novelty + self-consistency → Scores.

Scoring is **fully deterministic** on the base paths so that the system is
reproducible offline with no provider calls.  An optional judge callable
(``judge``) can be injected for in-band novelty and borderline consistency
cases; if omitted, the deterministic in-band interpolation is used instead.

The anti-fabrication backstop is unconditional: a derivation that contains
any ``[guess]`` step is penalised deterministically and cannot be rescued to a
high self-consistency score by the judge path.

Note: this scorer returns only the two sub-scores (``novelty``,
``self_consistency``).  The weighted combination
``w_n * novelty + w_c * self_consistency`` is computed by the **downstream
caller** (Task 9 ranking / Task 10 executor) using weights from Hydra config.

Public API
----------
.. code-block:: python

    from loop_sci.hypothesis.scoring import score_hypothesis
    from loop_sci.hypothesis.schemas import Scores

    scores: Scores = score_hypothesis(
        mechanism="Glial oscillations encode fear via gap junctions.",
        derivation=[DerivationStep(step="...", grade="[paper]", fact_ids=[])],
        facts=[...],            # list[Fact] from FactStore.all()
        low=0.15,              # LOW novelty band boundary
        high=0.60,             # HIGH novelty band boundary
        judge=None,            # injectable / mockable; None → deterministic
    )
"""
from __future__ import annotations

import re
from typing import Callable

from loop_sci.hypothesis.schemas import DerivationStep, Scores
from loop_sci.literature.extract.fact import Fact

__all__ = ["score_hypothesis"]

# ---------------------------------------------------------------------------
# Constants (defaults; all overridable via constructor / function params)
# ---------------------------------------------------------------------------

_DEFAULT_LOW: float = 0.15
_DEFAULT_HIGH: float = 0.60

_GRADE_WEIGHTS: dict[str, float] = {
    "[paper]": 1.0,
    "[inferred]": 0.6,
    "[guess]": 0.0,
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> set[str]:
    """Return lower-cased alphabetic tokens from *text* as a set."""
    return set(re.findall(r"[a-z]+", text.lower()))


def _jaccard_overlap(tokens_a: set[str], tokens_b: set[str]) -> float:
    """Jaccard-like overlap: |intersection| / |a| (asymmetric, a=mechanism)."""
    if not tokens_a:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a)


def _novelty_score(
    mechanism: str,
    facts: list[Fact],
    low: float,
    high: float,
    judge: Callable[[str, list[Fact]], float] | None,
) -> tuple[float, str]:
    """Compute novelty of *mechanism* against *facts*.

    Returns:
        (novelty_score, decided_by) where decided_by is "deterministic" or "judge".

    Band logic:
    - max_overlap >= (1 - low)  → restatement → novelty ≤ LOW
    - max_overlap <= (1 - high) → genuinely novel → novelty ≥ HIGH
    - in-band               → judge path (if provided) or linear interpolation
    """
    if not facts:
        # No baseline — mechanism is inherently novel
        return high, "deterministic"

    mech_tokens = _tokenize(mechanism)
    max_overlap = max(
        _jaccard_overlap(mech_tokens, _tokenize(f.claim)) for f in facts
    )

    # Restatement band: mechanism is largely a re-expression of a known fact
    if max_overlap >= (1.0 - low):
        # Scale within [0, LOW] proportional to overlap
        return low * max_overlap, "deterministic"

    # Novel band: mechanism is lexically distant from all known facts
    if max_overlap <= (1.0 - high):
        # Scale within [HIGH, 1.0] inversely proportional to overlap
        return high + (1.0 - high) * (1.0 - max_overlap), "deterministic"

    # In-band: defer to judge if available, else linear interpolation
    if judge is not None:
        try:
            score = float(judge(mechanism, facts))
            score = max(0.0, min(1.0, score))
            return score, "judge"
        except Exception:
            pass  # drop-on-failure: fall through to deterministic interpolation

    # Deterministic in-band fallback: 1 - max_overlap ∈ (low, high)
    return 1.0 - max_overlap, "deterministic"


def _self_consistency_score(
    derivation: list[DerivationStep],
) -> tuple[float, str]:
    """Compute self-consistency across derivation steps.

    The DETERMINISTIC FLOOR is the anti-fabrication backstop:
    - Any ``[guess]`` step contributes 0.0 to the weighted mean.
    - This penalty is unconditional: the judge path cannot rescue it.

    Returns:
        (self_consistency_score, decided_by)
    """
    if not derivation:
        return 1.0, "deterministic"

    weights = [_GRADE_WEIGHTS.get(s.grade, 0.0) for s in derivation]
    score = sum(weights) / len(weights)
    return score, "deterministic"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def score_hypothesis(
    mechanism: str,
    derivation: list[DerivationStep],
    facts: list[Fact],
    *,
    low: float = _DEFAULT_LOW,
    high: float = _DEFAULT_HIGH,
    judge: Callable[[str, list[Fact]], float] | None = None,
) -> Scores:
    """Score a hypothesis on novelty and self-consistency.

    Returns only the two sub-scores; the weighted combination
    ``w_n * novelty + w_c * self_consistency`` is the downstream caller's
    responsibility (weights live in Hydra config consumed by ranking/executor).

    Args:
        mechanism: The hypothesis mechanism text.
        derivation: Ordered list of :class:`~loop_sci.hypothesis.schemas.DerivationStep`.
        facts: Fact-base snapshot from ``FactStore.all()``; may be empty.
        low: LOW novelty-band boundary (default 0.15, Hydra-configurable).
        high: HIGH novelty-band boundary (default 0.60, Hydra-configurable).
        judge: Optional callable ``(mechanism, facts) -> float`` returning a
            score in [0, 1] for in-band novelty or borderline consistency.
            Inject a mock for offline tests; leave ``None`` for fully
            deterministic behaviour.

    Returns:
        A :class:`~loop_sci.hypothesis.schemas.Scores` dataclass with
        ``novelty``, ``self_consistency``, and ``decided_by``.
    """
    novelty, n_decided = _novelty_score(mechanism, facts, low, high, judge)
    consistency, c_decided = _self_consistency_score(derivation)

    # decided_by is "judge" when EITHER score used the judge path;
    # the anti-fab deterministic floor takes precedence for consistency.
    decided_by: str
    if n_decided == "judge" or c_decided == "judge":
        decided_by = "judge"
    else:
        decided_by = "deterministic"

    # Clamp to [0, 1] for safety
    novelty = max(0.0, min(1.0, novelty))
    consistency = max(0.0, min(1.0, consistency))

    return Scores(
        novelty=novelty,
        self_consistency=consistency,
        decided_by=decided_by,  # type: ignore[arg-type]
    )
