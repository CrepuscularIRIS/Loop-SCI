from loop_sci.plan.schemas import (
    Candidate, ExperimentsBlock, GateResult, ResearchPlan, Reference,
    ResultsBlock, PLAN_JSON_KEYS,
)


def _plan() -> ResearchPlan:
    return ResearchPlan(
        problem_statement="P", rationale="R", technical_details="T",
        datasets=[Candidate(value="D1", candidate=True,
                            source_ref={"source": "arxiv", "external_id": "arxiv:1", "doi": None})],
        source=[Candidate(value="S1", candidate=True)],
        target=[Candidate(value="Tg1", candidate=True)],
        paper_title="Title", abstract="Abs", methods="M",
        experiments=ExperimentsBlock(baselines=["b"], metrics=["m"], design="d"),
        results=ResultsBlock(derivation=[{"step": "x", "grade": "[paper]"}], conclusion="c", confidence="final"),
        references=[Reference(source="arxiv", external_id="arxiv:1", doi=None, verified=True, fact_id="f1")],
        node_id="hyp_abc", gate=GateResult(passed=True, failures=[]),
    )


def test_plan_json_keys_are_the_12_pinned_keys_in_order():
    assert PLAN_JSON_KEYS == (
        "problem_statement", "rationale", "technical_details", "datasets",
        "source", "target", "paper_title", "abstract", "methods",
        "experiments", "results", "references",
    )


def test_to_dict_carries_all_12_keys_plus_provenance():
    d = _plan().to_dict()
    for k in PLAN_JSON_KEYS:
        assert k in d
    assert d["node_id"] == "hyp_abc"
    assert d["gate"] == {"passed": True, "failures": []}


def test_from_dict_roundtrips():
    p = _plan()
    assert ResearchPlan.from_dict(p.to_dict()).to_dict() == p.to_dict()
