"""Unit tests for HypothesisExecutor (task-10a).

All tests run offline with MockProvider + seeded FactStore — no network, no API key.

RED checklist (TDD):
- test_executor_produces_accepted_hypothesis
- test_executor_resume_skips_accepted
- test_executor_never_raises
- test_executor_caps_respected
- test_executor_no_self_acquit_honored
- test_executor_resume_interrupted_does_not_respend   (Finding 1)
- test_executor_region_close_stops_generation          (Finding 2)
- test_executor_pivot_injects_lessons                  (Finding 3)
"""
from __future__ import annotations

import json

import pytest

from loop_sci.engine.types import DispatchUnit
from loop_sci.hypothesis.config import HypothesisConfig
from loop_sci.hypothesis.executor import HypothesisExecutor
from loop_sci.literature.extract.fact import Fact, SourceRef
from loop_sci.literature.factbase.store import FactStore
from loop_sci.state.session import RunSession
from tests.conftest import MockProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seeded_store(tmp_path) -> "Path":  # noqa: F821
    """Create a FactStore with one known fact and return its path."""
    from pathlib import Path

    path: Path = tmp_path / "facts.json"
    store = FactStore(path)
    f = Fact(
        claim="Neurons fire action potentials.",
        source_ref=SourceRef(source="s2", external_id="x0"),
        evidence_span="Neurons fire",
        confidence=0.9,
        grounding_scope="abstract",
    )
    f.fact_id = "fact_0"
    store.add(f)
    return path


def _cards_json() -> str:
    """Valid prospect response — one card grounded in fact_0."""
    return json.dumps([
        {
            "Q": "Why do neurons fire synchronously?",
            "WHY_NOW": "New imaging tech",
            "PROBE_KILL": "No oscillation found",
            "STAKES": 0.9,
            "fact_ids": ["fact_0"],
        }
    ])


def _hyps_json() -> str:
    """Valid forge response — primary candidate with [paper] step grounded in fact_0."""
    return json.dumps({
        "candidates": [
            {
                "MECHANISM": "Glial sync",
                "KILL": "no glial",
                "BRACKET": "plausible",
                "DIFF_PREDICTION": "Distinct EEG pattern emerges from glial oscillation",
                "frame": "primary",
                "derivation": [
                    {
                        "step": "Neurons → glia",
                        "grade": "[paper]",
                        "fact_ids": ["fact_0"],
                    }
                ],
            },
            {
                "MECHANISM": "Rival sync",
                "KILL": "rival kill",
                "BRACKET": "low",
                "DIFF_PREDICTION": "Different EEG frequency band shifts",
                "frame": "rival",
                "derivation": [],
            },
        ]
    })


def _contract_json() -> str:
    return json.dumps({
        "HYPOTHESIS": "Glial sync",
        "LATENT_ROOT": "glial",
        "ACCEPT_IF": "EEG band differs",
        "KILL_IF": "No transient spike",
    })


def _up_verdict_json() -> str:
    return json.dumps({"result": "UP", "reasons": ["novel mechanism"]})


def _down_verdict_json() -> str:
    return json.dumps({"result": "DOWN", "reasons": ["insufficient grounding"]})


def _gen_responses_happy() -> list[str]:
    """
    Sequence consumed by the generator provider for a single round, 1 card, 2 candidates:
      1. prospect call  → cards JSON
      2. forge call     → hyps JSON (both candidates)
      3. contract call  → contract JSON  (candidate 1)
      4. contract call  → contract JSON  (candidate 2 — rival has empty derivation so gate may fire)
    """
    return [
        _cards_json(),
        _hyps_json(),
        _contract_json(),
        _contract_json(),
    ]


def _make_executor(
    tmp_path,
    *,
    gen_responses: list[str] | None = None,
    rev_responses: list[str] | None = None,
    max_cards: int = 2,
    max_candidates: int = 2,
    max_rounds: int = 1,
    cfg: HypothesisConfig | None = None,
) -> tuple[HypothesisExecutor, RunSession]:
    session = RunSession.create(tmp_path / "runs", task="neuro")
    store_path = _seeded_store(tmp_path)
    gen = MockProvider(responses=gen_responses or _gen_responses_happy(), model="qwen-max")
    rev = MockProvider(
        responses=rev_responses or [_up_verdict_json()] * 10,
        model="qwen-plus",
    )
    config = cfg or HypothesisConfig(
        max_cards=max_cards,
        max_candidates=max_candidates,
        max_rounds=max_rounds,
    )
    executor = HypothesisExecutor(
        session,
        gen_provider=gen,
        rev_provider=rev,
        store_path=store_path,
        config=config,
    )
    return executor, session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_produces_accepted_hypothesis(tmp_path):
    """run() executes the full loop and produces ≥1 accepted hypothesis."""
    exec_, session = _make_executor(tmp_path)
    unit = DispatchUnit(node_id="ROOT", goal="neuro")

    result = await exec_.run(unit)

    assert result.status == "done"
    accepted = [
        n for n in session.tree.get_all_nodes()
        if n.status == "accepted"
    ]
    assert len(accepted) >= 1, "Expected at least 1 accepted hypothesis"


@pytest.mark.asyncio
async def test_accepted_node_has_score_and_refs_scores(tmp_path):
    """Node.score = w_n*novelty + w_c*self_consistency; refs['scores'] has sub-scores."""
    exec_, session = _make_executor(tmp_path)
    unit = DispatchUnit(node_id="ROOT", goal="neuro")

    await exec_.run(unit)

    accepted = [
        n for n in session.tree.get_all_nodes()
        if n.status == "accepted"
    ]
    assert accepted, "No accepted nodes"
    node = accepted[0]
    assert node.score is not None, "Node.score must be set"
    assert 0.0 <= node.score <= 1.0, "Node.score must be in [0,1]"
    assert node.refs is not None, "refs must be set"
    assert "scores" in node.refs, "refs['scores'] must have sub-scores"
    scores = node.refs["scores"]
    assert "novelty" in scores
    assert "self_consistency" in scores
    assert "overall" in scores, "refs['scores'] must include 'overall'"


@pytest.mark.asyncio
async def test_executor_resume_skips_accepted(tmp_path):
    """On re-run, already-accepted nodes are skipped (no duplicate nodes in tree).

    Resume strategy: node ids are now DETERMINISTIC (SHA-1 of content), so the
    per-node skip guards fire correctly.  On the second run, prospect and forge are
    still called (to discover any new work), but accepted hypothesis nodes are
    skipped entirely — no duplicate tree entries and no re-verdict for accepted nodes.
    """
    exec_, session = _make_executor(tmp_path)
    unit = DispatchUnit(node_id="ROOT", goal="neuro")

    await exec_.run(unit)

    # Verify first run actually produced accepted nodes
    accepted_after_first = [n for n in session.tree.get_all_nodes() if n.status == "accepted"]
    assert len(accepted_after_first) >= 1, "First run must produce ≥1 accepted node"
    accepted_ids_after_first = {n.id for n in accepted_after_first}

    # Second run — accepted nodes must be skipped (no duplicates, same count)
    await exec_.run(unit)

    accepted_after_second = [n for n in session.tree.get_all_nodes() if n.status == "accepted"]
    accepted_ids_after_second = {n.id for n in accepted_after_second}

    # The set of accepted node ids must be identical (no new accepted from re-run)
    assert accepted_ids_after_second == accepted_ids_after_first, (
        "Second run must not produce new accepted nodes for already-accepted hypotheses"
    )
    # No duplicate node ids in the tree at all
    all_node_ids = [n.id for n in session.tree.get_all_nodes()]
    assert len(all_node_ids) == len(set(all_node_ids)), (
        "Tree must have no duplicate node ids after resume"
    )


@pytest.mark.asyncio
async def test_executor_resume_interrupted_does_not_respend(tmp_path):
    """Deterministic ids: re-run on same executor does not duplicate accepted nodes.

    With 2 candidates (Glial sync UP, Rival sync DOWN), run once. Then run again.
    Assert:
    - accepted node count is still exactly 1 (no duplicate)
    - tree has no duplicate node ids
    - accepted node ids set is identical between run 1 and run 2
    """
    # Use UP for primary (Glial sync) and DOWN for rival (Rival sync)
    exec_, session = _make_executor(
        tmp_path,
        rev_responses=[_up_verdict_json(), _down_verdict_json()] * 10,
    )
    unit = DispatchUnit(node_id="ROOT", goal="neuro")

    # First run — primary (Glial sync) gets UP, rival (Rival sync) gets DOWN
    await exec_.run(unit)

    accepted_after_first = [n for n in session.tree.get_all_nodes() if n.status == "accepted"]
    assert len(accepted_after_first) == 1, (
        f"Expected exactly 1 accepted node after first run, got {len(accepted_after_first)}"
    )
    accepted_id_run1 = accepted_after_first[0].id

    # Second run — same executor, same tree, same ledger
    await exec_.run(unit)

    accepted_after_second = [n for n in session.tree.get_all_nodes() if n.status == "accepted"]
    # Still exactly 1 accepted (the same one)
    assert len(accepted_after_second) == 1, (
        f"Expected 1 accepted node after second run (no duplicate), "
        f"got {len(accepted_after_second)}"
    )
    assert accepted_after_second[0].id == accepted_id_run1, (
        "Accepted node id must be stable across runs (deterministic id)"
    )
    # No duplicate node ids in the entire tree
    all_node_ids = [n.id for n in session.tree.get_all_nodes()]
    assert len(all_node_ids) == len(set(all_node_ids)), (
        "Tree must have no duplicate node ids after resume"
    )


@pytest.mark.asyncio
async def test_executor_never_raises(tmp_path, monkeypatch):
    """run() must never raise — returns status='error' on an UNHANDLED internal failure.

    The stages themselves degrade gracefully (retry-once → drop/fallback), so a
    broken provider alone yields status="done" with 0 accepted.  To exercise the
    top-level try/except that converts an unhandled internal error into
    ``status="error"`` (rather than propagating), we force an unhandled failure
    inside ``_run_loop`` by making the (un-guarded) prospect' stage raise.  The
    contract is: ``run()`` catches it and returns ``status == "error"``.
    """
    session = RunSession.create(tmp_path / "runs", task="crash")
    store_path = _seeded_store(tmp_path)

    class _BrokenProvider:
        model = "broken"

        async def create(self, **kwargs):
            raise RuntimeError("simulated provider crash")

    from loop_sci.hypothesis.config import HypothesisConfig

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated unhandled internal error")

    # Force an unhandled error on the executor's prospect' call site.
    monkeypatch.setattr("loop_sci.hypothesis.executor.run_prospect", _boom)

    executor = HypothesisExecutor(
        session,
        gen_provider=_BrokenProvider(),
        rev_provider=_BrokenProvider(),
        store_path=store_path,
        config=HypothesisConfig(max_cards=1, max_candidates=1, max_rounds=1),
    )
    unit = DispatchUnit(node_id="ROOT", goal="crash_test")

    result = await executor.run(unit)  # must not raise

    assert result.status == "error", (
        f"Expected status='error' on unhandled internal failure, got {result.status!r}"
    )
    assert "error" in result.refs


@pytest.mark.asyncio
async def test_executor_caps_respected(tmp_path):
    """max_cards and max_candidates caps are respected within a single round."""
    # Prospect returns 10 cards (more than max_cards=2)
    many_cards = json.dumps([
        {"Q": f"Q{i}", "WHY_NOW": "now", "PROBE_KILL": "pk",
         "STAKES": float(10 - i) / 10, "fact_ids": ["fact_0"]}
        for i in range(10)
    ])
    # Forge returns 10 candidates (more than max_candidates=2)
    many_hyps = json.dumps({
        "candidates": [
            {
                "MECHANISM": f"Mech{i}",
                "KILL": "kill",
                "BRACKET": "plausible",
                "DIFF_PREDICTION": f"Prediction {i} adds new token distinct",
                "frame": "primary" if i % 2 == 0 else "rival",
                "derivation": [
                    {"step": "step", "grade": "[paper]", "fact_ids": ["fact_0"]}
                ],
            }
            for i in range(10)
        ]
    })
    # Interleave: prospect, forge, contract*N  — repeated for max_cards iterations
    # With max_cards=2: prospect(1) + forge(2) + contract(2*2) + forge(2) + contract(2*2)
    # Plus extras to avoid cycling into wrong JSON
    gen_responses = (
        [many_cards]                  # prospect round 1
        + [many_hyps]                 # forge card 1
        + [_contract_json()] * 4      # contract for up to 2 candidates of card 1
        + [many_hyps]                 # forge card 2
        + [_contract_json()] * 4      # contract for up to 2 candidates of card 2
    )
    exec_, session = _make_executor(
        tmp_path,
        gen_responses=gen_responses,
        max_cards=2,
        max_candidates=2,
        max_rounds=1,
    )
    unit = DispatchUnit(node_id="ROOT", goal="neuro")
    result = await exec_.run(unit)

    hyp_nodes = [n for n in session.tree.get_all_nodes() if n.id.startswith("hyp_")]
    # With max_cards=2 and max_candidates=2: at most 4 hyp nodes
    assert len(hyp_nodes) <= 4, f"Too many hypothesis nodes: {len(hyp_nodes)}"
    assert result.status in ("done", "bounded_exit")


@pytest.mark.asyncio
async def test_executor_no_self_acquit_honored(tmp_path):
    """When gen and rev have the same model, no-self-acquit fires → DOWN → not accepted."""
    session = RunSession.create(tmp_path / "runs", task="neuro")
    store_path = _seeded_store(tmp_path)
    # Both gen and rev have the SAME model — triggers no-self-acquit in adversary
    gen = MockProvider(responses=_gen_responses_happy(), model="qwen-max")
    rev = MockProvider(responses=[_up_verdict_json()] * 10, model="qwen-max")  # SAME model!

    from loop_sci.hypothesis.config import HypothesisConfig

    executor = HypothesisExecutor(
        session,
        gen_provider=gen,
        rev_provider=rev,
        store_path=store_path,
        config=HypothesisConfig(max_cards=1, max_candidates=2, max_rounds=1),
    )
    unit = DispatchUnit(node_id="ROOT", goal="neuro")
    await executor.run(unit)

    accepted = [n for n in session.tree.get_all_nodes() if n.status == "accepted"]
    assert len(accepted) == 0, (
        "No hypotheses should be accepted when gen==rev model (no-self-acquit)"
    )

    # Verify the pruned nodes show "deterministic-gate" decided_by (no-self-acquit path)
    pruned = [n for n in session.tree.get_all_nodes() if n.status == "pruned"]
    for node in pruned:
        if node.refs and "verdict" in node.refs:
            verdict = node.refs["verdict"]
            assert verdict.get("decided_by") == "deterministic-gate", (
                f"no-self-acquit should set decided_by='deterministic-gate', "
                f"got {verdict.get('decided_by')!r}"
            )


@pytest.mark.asyncio
async def test_executor_region_close_stops_generation(tmp_path):
    """region_close_threshold=1: after 1 kill in a region, further hyps in same region are pruned.

    We use threshold=1 so the first DOWN in region 'glial' immediately closes it.
    The second hypothesis candidate (rival) also maps to 'glial' via the contract.
    After the first kill, the rival should be pruned without an adversary call.
    """
    # Both candidates contract to the same LATENT_ROOT = "glial"
    same_root_contract = json.dumps({
        "HYPOTHESIS": "some hyp",
        "LATENT_ROOT": "glial",
        "ACCEPT_IF": "EEG differs",
        "KILL_IF": "No spike",
    })
    # Primary gets DOWN verdict, rival contract returns same region → should be pruned
    gen_responses = [
        _cards_json(),         # prospect
        _hyps_json(),          # forge — 2 candidates
        same_root_contract,    # contract for primary (glial sync)
        same_root_contract,    # contract for rival (also glial root)
    ]
    rev_responses = [
        _down_verdict_json(),  # primary → DOWN (kills glial region with threshold=1)
        _up_verdict_json(),    # rival → UP (but should never be called if region is closed)
    ]

    session = RunSession.create(tmp_path / "runs", task="neuro")
    store_path = _seeded_store(tmp_path)
    gen = MockProvider(responses=gen_responses, model="qwen-max")
    rev = MockProvider(responses=rev_responses, model="qwen-plus")

    executor = HypothesisExecutor(
        session,
        gen_provider=gen,
        rev_provider=rev,
        store_path=store_path,
        config=HypothesisConfig(
            max_cards=1,
            max_candidates=2,
            max_rounds=1,
            region_close_threshold=1,  # close region after just 1 kill
        ),
    )
    unit = DispatchUnit(node_id="ROOT", goal="neuro")
    await executor.run(unit)

    # With threshold=1: primary is killed (DOWN), glial region closes.
    # Rival candidate is in the same region → should be pruned without adversary call.
    # Therefore rev._index should be 1 (only called for primary candidate).
    assert rev._index == 1, (
        f"Expected reviewer called exactly once (region closed after first kill), "
        f"got rev._index={rev._index}"
    )
    # No accepted nodes (primary was DOWN, rival was region-pruned)
    accepted = [n for n in session.tree.get_all_nodes() if n.status == "accepted"]
    assert len(accepted) == 0, (
        f"Expected 0 accepted nodes with region close at threshold=1, got {len(accepted)}"
    )


@pytest.mark.asyncio
async def test_executor_pivot_injects_lessons(tmp_path):
    """When pivot fires, round 1's prospect'/forge' calls RECEIVE the constraints block.

    The pivot mechanism: round 0 produces all-DOWN verdicts → stall_count reaches
    pivot_at → action="pivot" → executor sets pivot_context = tree.get_constraints_block()
    and threads it into round 1's prospect'/forge' via the ``context`` kwarg.

    Bite test: this asserts that the CONTEXT passed to the stages CHANGES between
    round 0 (empty) and round 1 (non-empty, carrying pruned lessons).  Against the
    old no-op pivot implementation, round 1's context would still be "" and this
    fails.  We spy on the ``context`` kwarg that the executor passes to
    ``run_prospect``.
    """
    # Round 0: gen produces cards + hyps + 2 contracts; rev returns DOWN for all.
    # Round 1: prospect + forge are called again (hyp nodes skip via verdict guard).
    gen_responses = (
        _gen_responses_happy()   # round 0: prospect + forge + 2 contracts
        + _gen_responses_happy() # round 1: prospect + forge
    )
    rev_responses = [_down_verdict_json()] * 10  # all DOWN every round

    session = RunSession.create(tmp_path / "runs", task="neuro")
    store_path = _seeded_store(tmp_path)
    gen = MockProvider(responses=gen_responses, model="qwen-max")
    rev = MockProvider(responses=rev_responses, model="qwen-plus")

    # Spy on the context passed to run_prospect on each round.
    import loop_sci.hypothesis.executor as executor_mod

    captured_contexts: list[str] = []
    real_run_prospect = executor_mod.run_prospect

    async def _spy_prospect(*args, **kwargs):
        captured_contexts.append(kwargs.get("context", ""))
        return await real_run_prospect(*args, **kwargs)

    executor_mod.run_prospect = _spy_prospect
    try:
        executor = HypothesisExecutor(
            session,
            gen_provider=gen,
            rev_provider=rev,
            store_path=store_path,
            config=HypothesisConfig(
                max_cards=1,
                max_candidates=2,
                max_rounds=2,
                pivot_at=1,    # pivot after 1 stale round
                escalate_at=4,
            ),
        )
        unit = DispatchUnit(node_id="ROOT", goal="neuro")
        result = await executor.run(unit)
    finally:
        executor_mod.run_prospect = real_run_prospect

    # Round 0 must produce pruned nodes with insights (DOWN verdicts → autopsy → insight)
    pruned = [n for n in session.tree.get_all_nodes() if n.status == "pruned"]
    assert len(pruned) >= 1, "Round 0 must have produced ≥1 pruned nodes (all-DOWN scenario)"

    # Two prospect' calls captured — one per round.
    assert len(captured_contexts) == 2, (
        f"Expected prospect' called once per round (2 total), got {len(captured_contexts)}"
    )
    # Round 0 context is empty; round 1 context is the injected constraints block.
    assert captured_contexts[0] == "", "Round 0 must receive an empty context"
    assert captured_contexts[1], (
        "Round 1 (post-pivot) must receive a non-empty constraints block context"
    )
    assert captured_contexts[1] != captured_contexts[0], (
        "Pivot must change the context passed to prospect' between round 0 and round 1"
    )
    # The injected context must carry the pruned lessons (constraints block content).
    assert "PRUNED LESSONS" in captured_contexts[1] or "KILL" in captured_contexts[1], (
        "Round 1 context must surface pruned lessons from get_constraints_block()"
    )

    # The result refs must record lessons from round 0
    assert result.refs.get("lessons"), (
        "Executor result must include non-empty 'lessons' list after a pivot round"
    )


# ---------------------------------------------------------------------------
# BLOCKER 2 executor-level bite-test: executor wiring passes REAL gen.model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blocker2_executor_uses_real_gen_model_not_config_string(tmp_path) -> None:
    """HypothesisExecutor must pass getattr(gen, 'model', cfg.generator_model) to
    run_adversary, NOT the stale cfg.generator_model string.

    Scenario
    --------
    gen.model  = "qwen-plus"  (the REAL generator identity)
    rev.model  = "qwen-plus"  (same — no-self-acquit SHOULD fire)
    cfg.generator_model = "qwen-max"  (stale/wrong config string)

    Failure mode matrix (at the executor level):
      OLD executor (passes cfg.generator_model="qwen-max"):
        run_adversary receives generator_model="qwen-max"
        → comparison: rev.model "qwen-plus" != "qwen-max" → no-self-acquit SKIPPED
        → jury receives UP response → candidate ACCEPTED
        → len(accepted_nodes) >= 1 → assertion `len(accepted_nodes)==0` FAILS
        → test bites the old code ✓
      NEW executor (passes getattr(gen, 'model', cfg.generator_model)="qwen-plus"):
        run_adversary receives generator_model="qwen-plus"
        → comparison: rev.model "qwen-plus" == "qwen-plus" → no-self-acquit FIRES
        → DOWN for all candidates
        → len(accepted_nodes)==0 → assertion PASSES ✓
    """
    session = RunSession.create(tmp_path / "runs", task="neuro")
    store_path = _seeded_store(tmp_path)

    # CRITICAL: both gen and rev share the SAME real model "qwen-plus",
    # but cfg.generator_model is deliberately set to "qwen-max" (stale config).
    gen = MockProvider(
        responses=_gen_responses_happy(),
        model="qwen-plus",  # REAL gen identity — same as rev → no-self-acquit MUST fire
    )
    rev = MockProvider(
        responses=[_up_verdict_json()] * 10,  # UP so old code would accept
        model="qwen-plus",  # same model as gen
    )
    config = HypothesisConfig(
        max_cards=1,
        max_candidates=2,
        max_rounds=1,
        generator_model="qwen-max",  # stale/wrong config string — must NOT be used
    )
    executor = HypothesisExecutor(
        session,
        gen_provider=gen,
        rev_provider=rev,
        store_path=store_path,
        config=config,
    )
    unit = DispatchUnit(node_id="ROOT", goal="neuro")
    await executor.run(unit)

    accepted_nodes = [n for n in session.tree.get_all_nodes() if n.status == "accepted"]
    assert len(accepted_nodes) == 0, (
        "No-self-acquit must fire: gen.model=='qwen-plus'==rev.model, so no candidate "
        f"can be accepted. Got {len(accepted_nodes)} accepted node(s). "
        "If this fails, the executor is still passing cfg.generator_model ('qwen-max') "
        "instead of getattr(self._gen, 'model', ...) ('qwen-plus') to run_adversary."
    )

    # Also verify that the pruned nodes carry the no-self-acquit gate verdict.
    pruned = [n for n in session.tree.get_all_nodes() if n.status == "pruned"]
    for node in pruned:
        if node.refs and "verdict" in node.refs:
            verdict = node.refs["verdict"]
            assert verdict.get("decided_by") == "deterministic-gate", (
                "No-self-acquit path must set decided_by='deterministic-gate', "
                f"got {verdict.get('decided_by')!r}"
            )
