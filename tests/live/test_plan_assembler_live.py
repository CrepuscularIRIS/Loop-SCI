"""Live opt-in test for PlanAssemblerExecutor with real Bailian/Qwen provider.

Requires DASHSCOPE_API_KEY.  Skipped automatically when the key is absent.

All tests in this module are marked @pytest.mark.live and are excluded from the
default CI suite (``pytest tests/`` without ``-m live``).

To run manually:
    DASHSCOPE_API_KEY=<key> python -m pytest tests/live/test_plan_assembler_live.py -m live -v
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.live


@pytest.fixture
def api_key() -> str:
    key = os.environ.get("DASHSCOPE_API_KEY")
    if not key:
        pytest.skip("DASHSCOPE_API_KEY not set — skipping live plan assembler test")
    return key


@pytest.mark.skipif(not os.environ.get("DASHSCOPE_API_KEY"), reason="needs DASHSCOPE_API_KEY")
@pytest.mark.asyncio
async def test_live_assembly_small_domain_topic(api_key: str, tmp_path) -> None:
    """Real Bailian provider + seeded fact base + one RankedHypothesis → gated plan.

    Seeds the FactStore with two grounded neuroscience facts, then runs the full
    PlanAssemblerExecutor pipeline with a real Qwen-Plus provider call.

    The test passes as long as status="done" and valid JSON + Markdown files are
    written to disk.  Gate may or may not pass depending on provider output —
    only file presence and status are asserted (anti-fabrication may produce an
    ungated plan, which is a correct outcome).

    Budget: call_budget=3, domain="neuroscience" to keep token usage minimal.
    """
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
    from loop_sci.provider.factory import build_provider
    from loop_sci.state.idea_tree import Node
    from loop_sci.state.session import RunSession

    import json

    # Seed fact base with two grounded neuroscience facts
    store_path = tmp_path / "facts.json"
    store = FactStore(store_path)
    for i, (claim, entity) in enumerate([
        ("Long-term potentiation underlies declarative memory consolidation in the hippocampus.", "LTP"),
        ("Fear conditioning requires amygdala basolateral nucleus activity.", "amygdala"),
    ]):
        f = Fact(
            claim=claim,
            source_ref=SourceRef(source="s2", external_id=f"live_plan_{i}"),
            evidence_span=claim[:40],
            grounding_scope="abstract",
            confidence=0.9,
            entities=[entity],
        )
        f.fact_id = f"live_plan_fact_{i}"
        store.add(f)

    session = RunSession.create(tmp_path / "runs", task="hippocampal fear encoding plan")

    # Build hyp refs using the live_plan_fact_0 grounding
    fid = "live_plan_fact_0"
    refs = build_hyp_refs(
        kind="hypothesis",
        frame="primary",
        topic="hippocampal fear encoding",
        hyp=HypothesisHyp(
            MECHANISM="LTP in hippocampus enables fear memory consolidation",
            KILL="LTP blocked → no fear memory",
            BRACKET="hippocampus, amygdala",
            DIFF_PREDICTION="LTP inhibition reduces fear response",
        ),
        derivation=[DerivationStep(step="LTP cited in fear memory", grade="[paper]", fact_ids=[fid])],
        contract=None,
        verdict=None,
        scores=None,
        autopsy=None,
        iteration=Iteration(),
    )
    node = Node(
        id="live_hyp_node1",
        parent_id="ROOT",
        hypothesis="LTP in hippocampus enables fear memory consolidation",
        depth=2,
        status="accepted",
        refs=refs,
    )
    node.score = 0.7
    session.tree.add_node(node)
    session.tree.save()

    # Real Qwen-Plus provider (minimal cost)
    provider = build_provider(model="qwen-plus", api_key=api_key)

    config = PlanConfig(
        domain="neuroscience",
        call_budget=3,
    )

    executor = PlanAssemblerExecutor(
        session,
        provider=provider,
        ranked_store=RankedHypothesisStore(session.tree),
        fact_store=store,
        config=config,
    )

    result = await executor.run(
        DispatchUnit(node_id="live_hyp_node1", goal="hippocampal fear encoding")
    )

    assert result.status == "done", (
        f"Live plan assembly must complete with status='done', got {result.status!r}: {result.summary}"
    )

    # Files must exist
    plans_dir = session.session_dir / "plans"
    json_path = plans_dir / "live_hyp_node1.json"
    md_path = plans_dir / "live_hyp_node1.md"
    assert json_path.exists(), "JSON plan file must be written to disk"
    assert md_path.exists(), "Markdown plan file must be written to disk"

    # JSON must contain all 12 PLAN_JSON_KEYS
    data = json.loads(json_path.read_text())
    for k in PLAN_JSON_KEYS:
        assert k in data, f"Missing PLAN_JSON_KEY: {k!r} in live plan output"

    # Markdown structure
    md = md_path.read_text()
    assert "## Problem Statement" in md
    assert "## References" in md

    gate_passed = data.get("gate", {}).get("passed", False)
    print(
        f"\nLive plan assembler test: gate_passed={gate_passed} "
        f"node_id=live_hyp_node1 "
        f"ref_count={len(data.get('references', []))}"
    )
