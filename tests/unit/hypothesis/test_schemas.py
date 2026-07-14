import json

from loop_sci.hypothesis.schemas import (
    HypothesisHyp,
    Iteration,
    ProblemCard,
    Verdict,
    build_card_refs,
    build_hyp_refs,
    refs_from_dict,
)
from loop_sci.state.idea_tree import Node


def test_card_refs_round_trips_through_node():
    card = ProblemCard(Q="Why?", WHY_NOW="now", PROBE_KILL="pk", STAKES=0.8)
    refs = build_card_refs(kind="problem-card", frame="primary", topic="neuro", card=card)
    node = Node(id="n1", parent_id=None, hypothesis="h", depth=1, status="pending", refs=refs)
    d = node.to_dict()
    node2 = Node.from_dict(d)
    assert node2.refs["kind"] == "problem-card"
    assert node2.refs["card"]["STAKES"] == 0.8


def test_hyp_refs_verdict_serializable():
    v = Verdict(
        id="v1",
        reviewer_model="qwen-plus",
        result="DOWN",
        reasons=["fab"],
        decided_by="deterministic-gate",
    )
    hyp = HypothesisHyp(MECHANISM="m", KILL="k", BRACKET="b", DIFF_PREDICTION="d")
    refs = build_hyp_refs(
        kind="hypothesis",
        frame="primary",
        topic="neuro",
        hyp=hyp,
        derivation=[],
        contract=None,
        verdict=v,
        scores=None,
        autopsy=None,
        iteration=Iteration(round=1, stall_count=0),
    )
    raw = json.dumps(refs)
    back = refs_from_dict(json.loads(raw))
    assert back.verdict.result == "DOWN"
    assert back.verdict.decided_by == "deterministic-gate"
