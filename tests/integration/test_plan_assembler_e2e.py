"""Offline end-to-end integration test for the PlanAssemblerExecutor pipeline.

Tests the complete flow from a ranked hypothesis + seeded fact base through a
MockProvider → 12-field gated plan (JSON + Markdown) + resume (no re-spend).

No network, no git, no DASHSCOPE_API_KEY required.
"""
from __future__ import annotations

import json

import pytest

from loop_sci.engine.types import DispatchUnit
from loop_sci.hypothesis.ranked import RankedHypothesisStore
from loop_sci.hypothesis.schemas import (
    DerivationStep,
    HypothesisHyp,
    Iteration,
    build_hyp_refs,
)
from loop_sci.literature.extract.fact import Fact, SourceRef
from loop_sci.literature.factbase.store import FactStore
from loop_sci.plan.config import PlanConfig
from loop_sci.plan.executor import PlanAssemblerExecutor
from loop_sci.plan.schemas import PLAN_JSON_KEYS
from loop_sci.state.idea_tree import Node
from loop_sci.state.session import RunSession
from tests.conftest import MockProvider


# ---------------------------------------------------------------------------
# Shared helpers — mirrors tests/unit/plan/test_executor.py exactly
# ---------------------------------------------------------------------------


def _c1() -> str:
    return json.dumps({
        "problem_statement": "P",
        "rationale": "R",
        "technical_details": "T",
        "methods": "M",
        "experiments": {"baselines": ["b"], "metrics": ["m"], "design": "d"},
    })


def _c2() -> str:
    return json.dumps({
        "derivation": [{"step": "s", "grade": "[paper]"}],
        "conclusion": "feasible",
    })


def _c3() -> str:
    return json.dumps({"paper_title": "Ti", "abstract": "Ab"})


def _session_with_hyp(tmp_path):
    """Create a RunSession with one accepted hypothesis node that the ranked store can resolve."""
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
    return session, store, fid


# ---------------------------------------------------------------------------
# Main e2e test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_offline_gated_complete_plan_and_resume(tmp_path):
    """Assemble a gated, complete 12-field plan then verify resume doesn't re-spend."""
    session, store, fid = _session_with_hyp(tmp_path)
    prov = MockProvider(responses=[_c1(), _c2(), _c3()])
    ex = PlanAssemblerExecutor(
        session,
        provider=prov,
        ranked_store=RankedHypothesisStore(session.tree),
        fact_store=store,
        config=PlanConfig(domain="neuroscience"),
    )
    res = await ex.run(DispatchUnit(node_id="hyp_node1", goal="scaling"))
    assert res.status == "done"

    # --- JSON assertions: all 12 PLAN_JSON_KEYS present ---
    json_path = session.session_dir / "plans" / "hyp_node1.json"
    data = json.loads(json_path.read_text())
    for k in PLAN_JSON_KEYS:
        assert k in data, f"Missing PLAN_JSON_KEY: {k!r}"

    # --- Gate must have passed ---
    assert data["gate"]["passed"] is True, f"Gate failed: {data['gate']['failures']}"

    # --- References: non-empty and all verified ---
    assert data["references"], "references list must be non-empty"
    assert all(r["verified"] for r in data["references"]), "all references must be verified"

    # --- Markdown: required sections present ---
    md_path = session.session_dir / "plans" / "hyp_node1.md"
    md = md_path.read_text()
    assert "## Problem Statement" in md
    assert "## References" in md

    # --- RESUME: run again for same node_id; assert no new provider calls ---
    idx_after_first = prov._index
    res2 = await ex.run(DispatchUnit(node_id="hyp_node1", goal="scaling"))
    assert res2.status == "done"
    assert prov._index == idx_after_first, (
        f"Resume re-spent provider calls: _index went from {idx_after_first} to {prov._index}"
    )
