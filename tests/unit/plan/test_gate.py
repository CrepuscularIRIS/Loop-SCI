from dataclasses import replace
from loop_sci.plan.gate import run_gate
from loop_sci.plan.schemas import Reference, ResultsBlock
from tests.unit.plan.test_schemas import _plan


def test_gate_passes_on_complete_verified_plan():
    g = run_gate(_plan())
    assert g.passed and g.failures == []


def test_gate_fails_on_empty_field():
    p = replace(_plan(), problem_statement="")
    g = run_gate(p)
    assert not g.passed and any("problem_statement" in f for f in g.failures)


def test_gate_fails_on_unverified_reference():
    p = replace(_plan(), references=[Reference("arxiv", "arxiv:1", None, verified=False, fact_id=None)])
    g = run_gate(p)
    assert not g.passed and any("reference" in f.lower() for f in g.failures)


def test_gate_fails_on_ungrounded_load_bearing_claim():
    p = replace(_plan(), results=ResultsBlock(
        derivation=[{"step": "decisive", "grade": "[guess]"}], conclusion="feasible", confidence="low"))
    g = run_gate(p)
    assert not g.passed and any("load-bearing" in f.lower() or "confidence" in f.lower() for f in g.failures)
