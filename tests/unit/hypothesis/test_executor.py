"""Unit tests for HypothesisExecutor (task-10a).

All tests run offline with MockProvider + seeded FactStore — no network, no API key.

RED checklist (TDD):
- test_executor_produces_accepted_hypothesis
- test_executor_resume_skips_accepted
- test_executor_never_raises
- test_executor_caps_respected
- test_executor_no_self_acquit_honored
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


@pytest.mark.asyncio
async def test_executor_resume_skips_accepted(tmp_path):
    """On re-run, already-accepted nodes are skipped (no new gen calls for them).

    Resume strategy: when ALL accepted-eligible hypotheses have already been
    accepted (as recorded in the VerdictLedger), a second run must not spend
    any new provider calls for those nodes.  The executor detects this by
    checking accepted_ids at round start and skipping cards/hyps that already
    resolved.  Because prospect/forge re-generate fresh UUIDs each call, the
    resume works at the SESSION level: when the ledger contains ≥1 accepted
    node AND the tree already has accepted nodes, the executor returns early
    with no new gen calls.
    """
    exec_, session = _make_executor(tmp_path)
    unit = DispatchUnit(node_id="ROOT", goal="neuro")

    await exec_.run(unit)
    gen_calls_after_first = exec_._gen._index

    # Verify first run actually produced accepted nodes
    accepted = [n for n in session.tree.get_all_nodes() if n.status == "accepted"]
    assert len(accepted) >= 1, "First run must produce ≥1 accepted node"

    # Second run — the executor must detect already-accepted state and skip
    await exec_.run(unit)
    gen_calls_after_second = exec_._gen._index

    assert gen_calls_after_second == gen_calls_after_first, (
        f"Expected no new gen calls on resume, but got "
        f"{gen_calls_after_second - gen_calls_after_first} additional call(s)"
    )


@pytest.mark.asyncio
async def test_executor_never_raises(tmp_path):
    """run() must never raise — returns status='error' on internal failure."""
    # Provide a broken gen_provider that raises on every call
    session = RunSession.create(tmp_path / "runs", task="crash")
    store_path = _seeded_store(tmp_path)

    class _BrokenProvider:
        model = "broken"

        async def create(self, **kwargs):
            raise RuntimeError("simulated provider crash")

    from loop_sci.hypothesis.config import HypothesisConfig

    executor = HypothesisExecutor(
        session,
        gen_provider=_BrokenProvider(),
        rev_provider=_BrokenProvider(),
        store_path=store_path,
        config=HypothesisConfig(max_cards=1, max_candidates=1, max_rounds=1),
    )
    unit = DispatchUnit(node_id="ROOT", goal="crash_test")

    result = await executor.run(unit)  # must not raise

    assert result.status in ("done", "bounded_exit", "error")


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
