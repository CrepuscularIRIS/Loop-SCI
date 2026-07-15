"""Targeted coverage tests for uncovered branches in loop_sci/plan.

Covers:
- results.py: empty derivation → "low"; non-dict raw step → _coerce_step; invalid grade → "[guess]";
  both attempts fail → low-confidence fallback; provider response not a dict; derivation not a list.
- tools.py: invalid node_id (empty string) → structured error; executor not None → success path;
  executor raises → tool_error structured error.
"""
from __future__ import annotations

import json

import pytest

from loop_sci.engine.tools import ToolRegistry
from loop_sci.hypothesis.ranked import RankedHypothesis
from loop_sci.plan.results import _coerce_step, apply_load_bearing_downgrade, derive_results
from loop_sci.plan.tools import register_plan_tools
from tests.conftest import MockProvider


# ---------------------------------------------------------------------------
# results.py uncovered branches
# ---------------------------------------------------------------------------


def test_apply_downgrade_empty_derivation():
    """Line 89: not derivation → return "low"."""
    assert apply_load_bearing_downgrade([], "any conclusion") == "low"


def test_coerce_step_non_dict_raw():
    """Line 120: raw is not a dict → str(raw) + default grade."""
    result = _coerce_step("plain string step")
    assert result["step"] == "plain string step"
    assert result["grade"] == "[guess]"


def test_coerce_step_invalid_grade():
    """Line 125: grade not in _VALID_GRADES → default to "[guess]"."""
    result = _coerce_step({"step": "step text", "grade": "INVALID_GRADE"})
    assert result["grade"] == "[guess]"
    assert result["step"] == "step text"


def _make_hyp() -> RankedHypothesis:
    return RankedHypothesis(
        node_id="h",
        problem="p",
        mechanism="m",
        derivation_chain=[],
        diff_prediction="d",
        novelty=0.4,
        self_consistency=0.5,
        overall_score=0.4,
        grounding_fact_ids=[],
    )


@pytest.mark.asyncio
async def test_derive_results_both_attempts_fail_returns_low_fallback():
    """Lines 193-199: both provider attempts fail → low-confidence ResultsBlock."""
    # MockProvider returns invalid JSON (not parseable)
    prov = MockProvider(responses=["NOT_JSON", "ALSO_NOT_JSON"])
    rb = await derive_results(_make_hyp(), prov, domain="neuroscience")
    assert rb.confidence == "low"
    assert rb.derivation == []
    assert rb.conclusion == ""


@pytest.mark.asyncio
async def test_derive_results_non_dict_parsed_falls_back():
    """Lines 181-182: parsed JSON is not a dict (e.g. a list) → continue retry → fallback."""
    prov = MockProvider(responses=["[1, 2, 3]", "[4, 5, 6]"])
    rb = await derive_results(_make_hyp(), prov, domain="neuroscience")
    assert rb.confidence == "low"


@pytest.mark.asyncio
async def test_derive_results_derivation_not_list_falls_back():
    """Lines 186-187: parsed "derivation" is not a list → continue retry → fallback."""
    bad = json.dumps({"derivation": "not-a-list", "conclusion": "c"})
    prov = MockProvider(responses=[bad, bad])
    rb = await derive_results(_make_hyp(), prov, domain="neuroscience")
    assert rb.confidence == "low"


# ---------------------------------------------------------------------------
# tools.py uncovered branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assemble_tool_empty_node_id_is_invalid_input():
    """Line 49: empty node_id → invalid_input error."""
    reg = ToolRegistry()
    register_plan_tools(reg, executor=None)
    out = await reg.dispatch("assemble", {"node_id": ""})
    data = json.loads(out)
    assert data["error"] == "invalid_input"


@pytest.mark.asyncio
async def test_assemble_tool_with_executor_success(tmp_path):
    """Lines 58-71: executor is not None + run succeeds → status/gate_passed in result."""
    from loop_sci.hypothesis.schemas import (
        DerivationStep,
        HypothesisHyp,
        Iteration,
        build_hyp_refs,
    )
    from loop_sci.literature.extract.fact import Fact, SourceRef
    from loop_sci.literature.factbase.store import FactStore
    from loop_sci.hypothesis.ranked import RankedHypothesisStore
    from loop_sci.plan.config import PlanConfig
    from loop_sci.plan.executor import PlanAssemblerExecutor
    from loop_sci.state.idea_tree import Node
    from loop_sci.state.session import RunSession

    session = RunSession.create(runs_root=tmp_path, task="t")
    store = FactStore(session.session_dir / "facts.json")
    fid = store.add(
        Fact(
            claim="ImageNet helps",
            source_ref=SourceRef("arxiv", "arxiv:1", None),
            evidence_span="e",
            confidence=0.9,
            grounding_scope="abstract",
            entities=["ImageNet"],
        )
    )
    refs = build_hyp_refs(
        kind="hypothesis",
        frame="primary",
        topic="scaling",
        hyp=HypothesisHyp(MECHANISM="m", KILL="k", BRACKET="br", DIFF_PREDICTION="d"),
        derivation=[DerivationStep(step="s", grade="[paper]", fact_ids=[fid])],
        contract=None,
        verdict=None,
        scores=None,
        autopsy=None,
        iteration=Iteration(),
    )
    node = Node(
        id="hyp_node1",
        parent_id="ROOT",
        hypothesis="m",
        depth=2,
        status="accepted",
        refs=refs,
    )
    node.score = 0.5
    session.tree.add_node(node)
    session.tree.save()

    c1 = json.dumps({
        "problem_statement": "P", "rationale": "R", "technical_details": "T",
        "methods": "M", "experiments": {"baselines": ["b"], "metrics": ["m"], "design": "d"},
    })
    c2 = json.dumps({"derivation": [{"step": "s", "grade": "[paper]"}], "conclusion": "feasible"})
    c3 = json.dumps({"paper_title": "Ti", "abstract": "Ab"})
    prov = MockProvider(responses=[c1, c2, c3])

    executor = PlanAssemblerExecutor(
        session,
        provider=prov,
        ranked_store=RankedHypothesisStore(session.tree),
        fact_store=store,
        config=PlanConfig(domain="neuroscience"),
    )

    reg = ToolRegistry()
    register_plan_tools(reg, executor=executor)
    out = await reg.dispatch("assemble", {"node_id": "hyp_node1"})
    data = json.loads(out)
    assert data["status"] == "done"
    assert "gate_passed" in data


@pytest.mark.asyncio
async def test_assemble_tool_executor_raises_structured_tool_error(tmp_path):
    """Lines 69-74: executor.run raises → tool_error structured error."""
    class BrokenExecutor:
        async def run(self, unit):
            raise RuntimeError("simulated executor crash")

    reg = ToolRegistry()
    register_plan_tools(reg, executor=BrokenExecutor())
    out = await reg.dispatch("assemble", {"node_id": "any_node"})
    data = json.loads(out)
    assert data["error"] == "tool_error"
    assert "simulated executor crash" in data["detail"]
