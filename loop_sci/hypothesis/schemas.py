"""Fused hypothesis schema: Node.refs payload dataclasses and round-trip helpers.

Defines the structured payload stored in ``Node.refs`` on the idea-tree.  All
dataclasses serialise to plain dicts (via :func:`build_card_refs` /
:func:`build_hyp_refs`) and deserialise back (via :func:`refs_from_dict`) so
that payloads survive ``json.dumps``/``json.loads`` and the
``Node.to_dict``/``Node.from_dict`` round-trip without information loss.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


# ---------------------------------------------------------------------------
# Leaf dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ProblemCard:
    """Structured problem framing attached to a problem-card node."""

    Q: str
    WHY_NOW: str
    PROBE_KILL: str
    STAKES: float


@dataclass
class HypothesisHyp:
    """Hypothesis-specific framing fields."""

    MECHANISM: str
    KILL: str
    BRACKET: str
    DIFF_PREDICTION: str


@dataclass
class DerivationStep:
    """Single step in a hypothesis derivation chain."""

    step: str
    grade: Literal["[paper]", "[inferred]", "[guess]"]
    fact_ids: list[str] = field(default_factory=list)


@dataclass
class Contract:
    """Falsifiability contract for a hypothesis."""

    HYPOTHESIS: str
    LATENT_ROOT: str
    ACCEPT_IF: str
    KILL_IF: str


@dataclass
class Verdict:
    """Reviewer verdict emitted by the judge agent."""

    id: str
    reviewer_model: str
    result: Literal["UP", "DOWN"]
    reasons: list[str]
    decided_by: Literal["jury", "deterministic-gate"]


@dataclass
class Scores:
    """Quality scores attached to a hypothesis."""

    novelty: float
    self_consistency: float
    decided_by: Literal["deterministic", "judge"] = "deterministic"


@dataclass
class Autopsy:
    """Post-mortem record when a hypothesis is killed."""

    outcome: Literal["CONSTRAINT", "CANDIDATE", "REGION_CLOSE"]
    region: str
    note: str


@dataclass
class Iteration:
    """Iteration bookkeeping for the hypothesis lifecycle."""

    round: int = 0
    stall_count: int = 0


# ---------------------------------------------------------------------------
# Top-level payload dataclass
# ---------------------------------------------------------------------------


@dataclass
class HypothesisRefs:
    """Root payload stored in ``Node.refs``.

    Serialises to a plain dict that round-trips through JSON and
    ``Node.to_dict``/``Node.from_dict`` without loss.
    """

    kind: Literal["problem-card", "hypothesis"]
    frame: Literal["primary", "rival"]
    topic: str
    card: ProblemCard | None = None
    hyp: HypothesisHyp | None = None
    derivation: list[DerivationStep] = field(default_factory=list)
    contract: Contract | None = None
    verdict: Verdict | None = None
    scores: Scores | None = None
    autopsy: Autopsy | None = None
    iteration: Iteration = field(default_factory=Iteration)


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _dc_to_dict(obj: Any) -> Any:
    """Recursively convert a dataclass (or plain value) to a JSON-safe dict."""
    if obj is None:
        return None
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _dc_to_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [_dc_to_dict(i) for i in obj]
    return obj


def build_card_refs(
    *,
    kind: str,
    frame: str,
    topic: str,
    card: ProblemCard,
) -> dict[str, Any]:
    """Build a ``Node.refs`` payload dict for a problem-card node."""
    return _dc_to_dict(  # type: ignore[return-value]
        HypothesisRefs(
            kind=kind,  # type: ignore[arg-type]
            frame=frame,  # type: ignore[arg-type]
            topic=topic,
            card=card,
        )
    )


def build_hyp_refs(
    *,
    kind: str,
    frame: str,
    topic: str,
    hyp: HypothesisHyp,
    derivation: list[DerivationStep],
    contract: Contract | None,
    verdict: Verdict | None,
    scores: Scores | None,
    autopsy: Autopsy | None,
    iteration: Iteration,
) -> dict[str, Any]:
    """Build a ``Node.refs`` payload dict for a hypothesis node."""
    return _dc_to_dict(  # type: ignore[return-value]
        HypothesisRefs(
            kind=kind,  # type: ignore[arg-type]
            frame=frame,  # type: ignore[arg-type]
            topic=topic,
            hyp=hyp,
            derivation=derivation,
            contract=contract,
            verdict=verdict,
            scores=scores,
            autopsy=autopsy,
            iteration=iteration,
        )
    )


def refs_from_dict(d: dict[str, Any]) -> HypothesisRefs:
    """Deserialise a plain dict (from JSON or Node.refs) into a :class:`HypothesisRefs`."""
    card = ProblemCard(**d["card"]) if d.get("card") else None
    hyp = HypothesisHyp(**d["hyp"]) if d.get("hyp") else None
    derivation = [DerivationStep(**s) for s in (d.get("derivation") or [])]
    contract = Contract(**d["contract"]) if d.get("contract") else None
    verdict_d = d.get("verdict")
    verdict = Verdict(**verdict_d) if verdict_d else None
    scores_d = d.get("scores")
    if scores_d:
        # The executor persists extra keys (overall, w_n, w_c) alongside the Scores
        # fields; extract only the fields that Scores accepts to avoid TypeError.
        scores = Scores(
            novelty=scores_d["novelty"],
            self_consistency=scores_d["self_consistency"],
            decided_by=scores_d.get("decided_by", "deterministic"),
        )
    else:
        scores = None
    autopsy_d = d.get("autopsy")
    autopsy = Autopsy(**autopsy_d) if autopsy_d else None
    iteration = Iteration(**(d.get("iteration") or {}))
    return HypothesisRefs(
        kind=d["kind"],  # type: ignore[arg-type]
        frame=d["frame"],  # type: ignore[arg-type]
        topic=d["topic"],
        card=card,
        hyp=hyp,
        derivation=derivation,
        contract=contract,
        verdict=verdict,
        scores=scores,
        autopsy=autopsy,
        iteration=iteration,
    )
