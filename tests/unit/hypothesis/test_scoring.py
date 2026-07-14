"""Unit tests for loop_sci.hypothesis.scoring.

TDD RED → GREEN cycle.  All tests run fully offline (no network / no provider).
"""
from __future__ import annotations

from loop_sci.hypothesis.scoring import score_hypothesis
from loop_sci.hypothesis.schemas import DerivationStep, Scores
from loop_sci.literature.extract.fact import Fact, SourceRef


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fact(claim: str) -> Fact:
    """Build a minimal Fact for testing — all mandatory fields present."""
    return Fact(
        claim=claim,
        source_ref=SourceRef(source="s2", external_id="x"),
        evidence_span=claim[:20],
        confidence=1.0,
        grounding_scope="abstract",
    )


# ---------------------------------------------------------------------------
# Novelty band tests
# ---------------------------------------------------------------------------


def test_restatement_gets_low_novelty():
    """Mechanism that is a near-substring of an existing fact → novelty ≤ LOW (0.15)."""
    facts = [_fact("Synaptic plasticity enables memory consolidation.")]
    s = score_hypothesis("Synaptic plasticity enables memory", [], facts)
    assert isinstance(s, Scores)
    assert s.novelty <= 0.15


def test_novel_mechanism_gets_high_novelty():
    """Mechanism with no lexical overlap with facts → novelty ≥ HIGH (0.60)."""
    facts = [_fact("Synaptic plasticity enables memory consolidation.")]
    s = score_hypothesis(
        "Glial oscillations encode fear traces via gap junctions.", [], facts
    )
    assert s.novelty >= 0.60


def test_no_facts_gives_high_novelty():
    """Empty fact base → mechanism is inherently novel (no baseline to compare)."""
    s = score_hypothesis("Some mechanism about quantum tunnelling.", [], [])
    assert s.novelty >= 0.60


# ---------------------------------------------------------------------------
# Self-consistency tests
# ---------------------------------------------------------------------------


def test_guess_derivation_lowers_self_consistency():
    """All-[guess] derivation → self_consistency < 0.5 (deterministic floor)."""
    steps = [
        DerivationStep(step="step1", grade="[guess]", fact_ids=[]),
        DerivationStep(step="step2", grade="[guess]", fact_ids=[]),
    ]
    s = score_hypothesis("Some mech", steps, [])
    assert s.self_consistency < 0.5


def test_paper_graded_derivation_raises_self_consistency():
    """All-[paper] derivation → self_consistency ≥ 0.8."""
    steps = [
        DerivationStep(step="step1", grade="[paper]", fact_ids=["f1"]),
        DerivationStep(step="step2", grade="[paper]", fact_ids=["f2"]),
    ]
    s = score_hypothesis("Some mech", steps, [])
    assert s.self_consistency >= 0.8


def test_empty_derivation_gives_full_self_consistency():
    """No derivation steps → no contradiction possible → self_consistency == 1.0."""
    s = score_hypothesis("Some mech", [], [])
    assert s.self_consistency == 1.0


# ---------------------------------------------------------------------------
# Anti-fabrication floor: load-bearing [guess] must not be rescued by judge
# ---------------------------------------------------------------------------


def test_load_bearing_guess_deterministically_penalized():
    """A load-bearing [guess] step must penalize self_consistency deterministically.

    The scorer must NOT delegate this case to the judge path — the anti-fab
    floor is the backstop.  The penalty must hold even if a mock judge would
    otherwise return a high score.
    """
    steps = [
        DerivationStep(step="critical_claim", grade="[guess]", fact_ids=[]),
    ]
    s = score_hypothesis("Some mech", steps, [])
    # Deterministic floor: self_consistency strictly below 1.0 (cannot be rescued)
    assert s.self_consistency < 1.0
    # decided_by must be deterministic (not judge)
    assert s.decided_by == "deterministic"


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


def test_returns_scores_dataclass():
    """score_hypothesis always returns a Scores instance."""
    s = score_hypothesis("mech", [], [])
    assert isinstance(s, Scores)
    assert hasattr(s, "novelty")
    assert hasattr(s, "self_consistency")
    assert hasattr(s, "decided_by")
