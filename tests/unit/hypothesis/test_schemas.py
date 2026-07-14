import json

from loop_sci.hypothesis.schemas import (
    Autopsy,
    Contract,
    DerivationStep,
    HypothesisHyp,
    HypothesisRefs,
    Iteration,
    ProblemCard,
    Scores,
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


def test_fully_populated_refs_round_trip():
    """All eight payload groups survive both refs_from_dict and Node round-trip."""
    original = HypothesisRefs(
        kind="hypothesis",
        frame="rival",
        topic="spinal-cord-injury",
        card=ProblemCard(Q="Q?", WHY_NOW="now", PROBE_KILL="pk", STAKES=0.9),
        hyp=HypothesisHyp(MECHANISM="m", KILL="k", BRACKET="b", DIFF_PREDICTION="d"),
        derivation=[
            DerivationStep(
                step="Literature supports X",
                grade="[paper]",
                fact_ids=["fact-001", "fact-002"],
            )
        ],
        contract=Contract(
            HYPOTHESIS="H0",
            LATENT_ROOT="lr",
            ACCEPT_IF="p<0.05",
            KILL_IF="p>0.1",
        ),
        verdict=Verdict(
            id="v42",
            reviewer_model="qwen-plus",
            result="UP",
            reasons=["novel", "testable"],
            decided_by="jury",
        ),
        scores=Scores(novelty=0.7, self_consistency=0.85, decided_by="judge"),
        autopsy=Autopsy(outcome="CANDIDATE", region="motor-cortex", note="promising"),
        iteration=Iteration(round=3, stall_count=1),
    )

    # --- path 1: refs_from_dict round-trip ---
    built_dict = json.loads(json.dumps(original.__dict__ if False else
                                       __import__("dataclasses").asdict(original)))
    reconstructed = refs_from_dict(built_dict)
    assert reconstructed == original

    # --- path 2: Node.to_dict / Node.from_dict round-trip ---
    node = Node(
        id="n99",
        parent_id=None,
        hypothesis="h",
        depth=1,
        status="pending",
        refs=built_dict,
    )
    node2 = Node.from_dict(node.to_dict())
    assert refs_from_dict(node2.refs) == original
