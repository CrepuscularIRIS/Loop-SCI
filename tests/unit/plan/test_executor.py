"""Tests for PlanAssemblerExecutor — Task 6 integration."""
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
from loop_sci.state.idea_tree import Node
from loop_sci.state.session import RunSession
from tests.conftest import MockProvider


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


@pytest.mark.asyncio
async def test_executor_assembles_gated_12_field_plan(tmp_path):
    session, store, fid = _session_with_hyp(tmp_path)
    ex = PlanAssemblerExecutor(
        session,
        provider=MockProvider(responses=[_c1(), _c2(), _c3()]),
        ranked_store=RankedHypothesisStore(session.tree),
        fact_store=store,
        config=PlanConfig(domain="neuroscience"),
    )
    res = await ex.run(DispatchUnit(node_id="hyp_node1", goal="scaling"))
    assert res.status == "done"
    assert (session.session_dir / "plans" / "hyp_node1.json").exists()
    assert (session.session_dir / "plans" / "hyp_node1.md").exists()


@pytest.mark.asyncio
async def test_resume_does_not_reassemble(tmp_path):
    session, store, fid = _session_with_hyp(tmp_path)
    prov = MockProvider(responses=[_c1(), _c2(), _c3()])
    ex = PlanAssemblerExecutor(
        session,
        provider=prov,
        ranked_store=RankedHypothesisStore(session.tree),
        fact_store=store,
    )
    await ex.run(DispatchUnit(node_id="hyp_node1", goal="scaling"))
    calls_after_first = prov._index
    await ex.run(DispatchUnit(node_id="hyp_node1", goal="scaling"))
    assert prov._index == calls_after_first  # no new provider calls on resume


@pytest.mark.asyncio
async def test_run_is_exception_safe(tmp_path):
    session, store, _ = _session_with_hyp(tmp_path)
    ex = PlanAssemblerExecutor(
        session,
        provider=MockProvider(responses=[_c1(), _c2(), _c3()]),
        ranked_store=RankedHypothesisStore(session.tree),
        fact_store=store,
    )
    res = await ex.run(DispatchUnit(node_id="does_not_exist", goal="scaling"))
    # Must be "error" — returning "done" for an unknown node is wrong
    assert res.status == "error"
    # No sentinel file must be left behind for the unknown node
    sentinel = session.session_dir / "plans" / "does_not_exist.json"
    assert not sentinel.exists(), "orphan sentinel must not be created for unknown node"


@pytest.mark.asyncio
async def test_partial_persist_no_orphan_sentinel_on_md_write_failure(tmp_path, monkeypatch):
    """Bite-test: if the .md write fails, no .json sentinel must remain on disk.

    This test verifies the write order is .md FIRST, then .json (the sentinel).
    If .json were written before .md (old order), the sentinel would be present
    even though .md failed — this test catches that regression.
    """
    session, store, _ = _session_with_hyp(tmp_path)
    ex = PlanAssemblerExecutor(
        session,
        provider=MockProvider(responses=[_c1(), _c2(), _c3()]),
        ranked_store=RankedHypothesisStore(session.tree),
        fact_store=store,
        config=PlanConfig(domain="neuroscience"),
    )

    plans_dir = session.session_dir / "plans"
    node_id = "hyp_node1"
    md_path = plans_dir / f"{node_id}.md"
    json_path = plans_dir / f"{node_id}.json"

    original_write_text = type(md_path).write_text

    def failing_write_text(self, data, *args, **kwargs):
        # Only intercept the .md write; allow all other writes (mkdir creates nothing here)
        if self == md_path:
            raise OSError("simulated .md write failure")
        return original_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(type(md_path), "write_text", failing_write_text)

    res = await ex.run(DispatchUnit(node_id=node_id, goal="scaling"))

    # (a) run must return status="error" (exception-safe wrapper catches the OSError)
    assert res.status == "error", f"expected error, got {res.status!r}: {res.summary}"
    # (b) no .json sentinel must exist — writing .md first means the .json write
    #     never ran, so disk is clean for the next resume attempt
    assert not json_path.exists(), (
        "orphan sentinel .json must NOT exist when .md write fails "
        "(this indicates .json was written BEFORE .md — wrong order)"
    )
