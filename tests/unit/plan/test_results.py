"""Unit tests for loop_sci.plan.results — evidence-graded formula-derivation."""
from __future__ import annotations

import json

import pytest
from loop_sci.hypothesis.ranked import RankedHypothesis
from loop_sci.plan.results import apply_load_bearing_downgrade, derive_results
from tests.conftest import MockProvider


def _hyp() -> RankedHypothesis:
    return RankedHypothesis(
        node_id="h",
        problem="p",
        mechanism="m",
        derivation_chain=[{"step": "s", "grade": "[paper]", "fact_ids": ["f1"]}],
        diff_prediction="d",
        novelty=0.4,
        self_consistency=0.5,
        overall_score=0.4,
        grounding_fact_ids=["f1"],
    )


def test_downgrade_when_load_bearing_step_is_guess():
    deriv = [{"step": "a", "grade": "[paper]"}, {"step": "b", "grade": "[guess]"}]
    assert apply_load_bearing_downgrade(deriv, "feasible") == "low"


def test_final_when_load_bearing_grounded():
    deriv = [{"step": "a", "grade": "[guess]"}, {"step": "b", "grade": "[paper]"}]
    assert apply_load_bearing_downgrade(deriv, "feasible") == "final"


@pytest.mark.asyncio
async def test_derive_results_is_graded_derivation_no_execution():
    resp = json.dumps({
        "derivation": [{"step": "bound from mechanism", "grade": "[inferred]"}],
        "conclusion": "effect size within [0.1, 0.3]",
    })
    rb = await derive_results(_hyp(), MockProvider(responses=[resp]), domain="neuroscience")
    assert rb.derivation and all(
        s["grade"] in ("[paper]", "[inferred]", "[guess]") for s in rb.derivation
    )
    assert rb.confidence == "final"
    assert rb.conclusion


@pytest.mark.asyncio
async def test_load_bearing_guess_downgrades_to_low():
    resp = json.dumps({
        "derivation": [{"step": "guessed decisive step", "grade": "[guess]"}],
        "conclusion": "feasible",
    })
    rb = await derive_results(_hyp(), MockProvider(responses=[resp]), domain="neuroscience")
    assert rb.confidence == "low"
