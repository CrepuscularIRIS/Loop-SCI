"""Tests for autopsy' stage: classify_kill, StallLedger, RegionTracker.

Covers OpenSpec tasks 3.1 (classify_kill), 3.2 (region-close), 3.3 (stall ledger).
All tests are offline/deterministic — no provider calls.
"""
from __future__ import annotations

from loop_sci.hypothesis.schemas import Autopsy, Verdict
from loop_sci.hypothesis.stages.autopsy import (
    RegionTracker,
    StallLedger,
    classify_kill,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _verdict(result: str = "DOWN", reasons: list[str] | None = None) -> Verdict:
    return Verdict(
        id="v1",
        reviewer_model="qwen-plus",
        result=result,  # type: ignore[arg-type]
        reasons=reasons or ["too speculative"],
        decided_by="jury",
    )


def _hyp_refs(latent_root: str = "glial plasticity") -> dict:
    return {
        "hyp": {"MECHANISM": "Glial mech"},
        "topic": "neuro",
        "contract": {"LATENT_ROOT": latent_root},
    }


# ---------------------------------------------------------------------------
# classify_kill (osp 3.1)
# ---------------------------------------------------------------------------


def test_kill_produces_autopsy_with_valid_outcome():
    """classify_kill returns an Autopsy with a valid outcome string."""
    a = classify_kill(_verdict("DOWN"), _hyp_refs())
    assert isinstance(a, Autopsy)
    assert a.outcome in {"CONSTRAINT", "CANDIDATE", "REGION_CLOSE"}


def test_kill_outcome_is_constraint_by_default():
    """Generic speculative reason → CONSTRAINT (feeds constraints block)."""
    a = classify_kill(_verdict("DOWN", reasons=["too speculative"]), _hyp_refs())
    assert a.outcome == "CONSTRAINT"


def test_kill_outcome_region_close_when_region_in_reason():
    """Reason containing 'region' → REGION_CLOSE outcome."""
    a = classify_kill(
        _verdict("DOWN", reasons=["region exhausted", "dead end"]),
        _hyp_refs(),
    )
    assert a.outcome == "REGION_CLOSE"


def test_kill_outcome_candidate_when_alternative_in_reason():
    """Reason containing 'alternative' → CANDIDATE outcome."""
    a = classify_kill(
        _verdict("DOWN", reasons=["alternative pathway exists"]),
        _hyp_refs(),
    )
    assert a.outcome == "CANDIDATE"


def test_kill_region_field_matches_latent_root():
    """Autopsy.region is set from contract.LATENT_ROOT."""
    a = classify_kill(_verdict("DOWN"), _hyp_refs(latent_root="synaptic remodeling"))
    assert a.region == "synaptic remodeling"


def test_kill_note_contains_reason_text():
    """Autopsy.note carries the verdict reasons so the kill reason survives."""
    a = classify_kill(_verdict("DOWN", reasons=["too speculative", "weak evidence"]), _hyp_refs())
    assert "too speculative" in a.note
    assert "weak evidence" in a.note


def test_kill_missing_contract_defaults_region_unknown():
    """hyp_refs without contract → Autopsy.region = 'unknown'."""
    hyp_refs = {"hyp": {"MECHANISM": "Some mech"}, "topic": "bio"}
    a = classify_kill(_verdict("DOWN"), hyp_refs)
    assert a.region == "unknown"


# ---------------------------------------------------------------------------
# prune feedback (osp 3.1 — killed node pruned with reason retained)
# ---------------------------------------------------------------------------


def test_classify_kill_feeds_prune_reason_through_get_constraints_block():
    """After prune_node with the kill reason, get_constraints_block surfaces it."""
    import tempfile
    from pathlib import Path
    from loop_sci.state.idea_tree import IdeaTree, Node

    with tempfile.TemporaryDirectory() as tmp:
        json_path = Path(tmp) / "tree.json"
        root = Node(
            id="ROOT",
            parent_id=None,
            children_ids=["1"],
            depth=0,
            hypothesis="root",
        )
        child = Node(
            id="1",
            parent_id="ROOT",
            children_ids=[],
            depth=1,
            hypothesis="Glial plasticity drives cortical remapping",
        )
        tree = IdeaTree(root=root, json_path=json_path, md_path=json_path.with_suffix(".md"))
        tree._nodes["1"] = child

        a = classify_kill(_verdict("DOWN", reasons=["too speculative"]), _hyp_refs())
        # Prune the node using the autopsy note as the reason (kills retain their reason)
        tree.prune_node("1", reason=a.note)

        constraints = tree.get_constraints_block()
        # The pruned reason should appear in the constraints block
        assert "too speculative" in constraints


# ---------------------------------------------------------------------------
# StallLedger (osp 3.3)
# ---------------------------------------------------------------------------


def test_stall_continue_when_new_findings():
    """Non-zero new_accepted_count resets stall and returns 'continue'."""
    sl = StallLedger()
    assert sl.record_round(1) == "continue"
    assert sl.record_round(2) == "continue"


def test_stall_continue_on_first_empty_round():
    """First round with 0 new findings: stale_count=1 < 2 → 'continue'."""
    sl = StallLedger()
    assert sl.record_round(0) == "continue"


def test_stall_pivot_at_2():
    """stale_count reaches 2 → 'pivot' (structural PIVOT signal)."""
    sl = StallLedger()
    sl.record_round(0)  # stale_count = 1
    assert sl.record_round(0) == "pivot"  # stale_count = 2


def test_stall_escalate_at_4():
    """stale_count reaches 4 → 'escalate' (stop nudging signal)."""
    sl = StallLedger()
    for _ in range(3):
        sl.record_round(0)
    assert sl.record_round(0) == "escalate"  # stale_count = 4


def test_stall_escalate_stays_escalate_beyond_4():
    """Once escalated, further empty rounds stay 'escalate'."""
    sl = StallLedger()
    for _ in range(4):
        sl.record_round(0)
    assert sl.record_round(0) == "escalate"


def test_stall_resets_on_new_finding():
    """A non-zero round resets the stale counter."""
    sl = StallLedger()
    sl.record_round(0)
    sl.record_round(0)  # at pivot
    sl.record_round(1)  # reset
    assert sl.record_round(0) == "continue"  # stale_count = 1 again


# ---------------------------------------------------------------------------
# RegionTracker (osp 3.2)
# ---------------------------------------------------------------------------


def test_region_close_first_kill_returns_false():
    """First kill of a root does not close the region."""
    rt = RegionTracker()
    assert rt.record_kill("glial_plasticity") is False


def test_region_close_after_two_same_root():
    """Second kill of the same root closes the region → True."""
    rt = RegionTracker()
    assert rt.record_kill("glial_plasticity") is False
    assert rt.record_kill("glial_plasticity") is True


def test_region_close_different_roots_no_close():
    """Kills on different roots do not close either region."""
    rt = RegionTracker()
    rt.record_kill("root_a")
    assert rt.record_kill("root_b") is False


def test_region_is_closed_query():
    """is_closed() reflects the closed set correctly."""
    rt = RegionTracker()
    rt.record_kill("root_x")
    assert rt.is_closed("root_x") is False
    rt.record_kill("root_x")
    assert rt.is_closed("root_x") is True
    assert rt.is_closed("root_y") is False


def test_region_close_third_kill_still_true():
    """Once closed, any additional kills for that root still return True."""
    rt = RegionTracker()
    rt.record_kill("r")
    rt.record_kill("r")  # closed
    assert rt.record_kill("r") is True
