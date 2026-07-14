"""Live test: real Qwen-Max gen + Qwen-Plus reviewer on a seeded neuro fact base.

Requires DASHSCOPE_API_KEY.  Skipped automatically when the key is absent.

All tests in this module are marked @pytest.mark.live and are excluded from the
default CI suite (``pytest tests/`` without ``-m live``).

To run manually:
    DASHSCOPE_API_KEY=<key> python -m pytest tests/live/test_hypothesis_live.py -m live -v
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.live


@pytest.fixture
def api_key() -> str:
    key = os.environ.get("DASHSCOPE_API_KEY")
    if not key:
        pytest.skip("DASHSCOPE_API_KEY not set — skipping live hypothesis test")
    return key


@pytest.mark.asyncio
async def test_live_hypothesis_neuro_topic(api_key: str, tmp_path) -> None:
    """Real Qwen-Max generator + Qwen-Plus reviewer on a seeded hippocampal fear base.

    Seeds the FactStore with two grounded neuroscience facts, then runs the full
    hypothesis pipeline (prospect' → forge' → contract → adversary' → autopsy')
    with real Qwen model calls.

    The test passes as long as the pipeline completes without errors; finding zero
    accepted hypotheses is acceptable (all may be killed by the adversary — that is
    a correct anti-fabrication outcome, not a failure).

    Budget: max_cards=2, max_candidates=2, max_rounds=1 to keep token usage minimal.
    """
    from loop_sci.engine.types import DispatchUnit
    from loop_sci.hypothesis.config import HypothesisConfig
    from loop_sci.hypothesis.executor import HypothesisExecutor
    from loop_sci.hypothesis.ranked import RankedHypothesisStore
    from loop_sci.literature.extract.fact import Fact, SourceRef
    from loop_sci.literature.factbase.store import FactStore
    from loop_sci.provider.factory import build_provider
    from loop_sci.state.session import RunSession

    # Seed fact base with two grounded neuroscience facts
    store_path = tmp_path / "facts.json"
    store = FactStore(store_path)
    for i, claim in enumerate([
        "Long-term potentiation underlies declarative memory consolidation in the hippocampus.",
        "Fear conditioning requires amygdala basolateral nucleus activity.",
    ]):
        f = Fact(
            claim=claim,
            source_ref=SourceRef(source="s2", external_id=f"live{i}"),
            evidence_span=claim[:40],
            grounding_scope="abstract",
            confidence=0.9,
        )
        f.fact_id = f"live_fact_{i}"
        store.add(f)

    session = RunSession.create(tmp_path / "runs", task="hippocampal fear encoding")

    # Real providers: qwen-max for generation, qwen-plus for review
    gen = build_provider(model="qwen-max", api_key=api_key)
    rev = build_provider(model="qwen-plus", api_key=api_key)

    # Small caps to control spend: 2 cards × 2 candidates × 1 round
    config = HypothesisConfig(
        max_cards=2,
        max_candidates=2,
        max_rounds=1,
    )
    executor = HypothesisExecutor(
        session,
        gen_provider=gen,
        rev_provider=rev,
        store_path=store_path,
        config=config,
    )

    result = await executor.run(
        DispatchUnit(node_id="ROOT", goal="hippocampal fear encoding")
    )

    assert result.status == "done", (
        f"Live hypothesis pipeline must complete with status='done', got {result.status!r}"
    )

    # accepted_count may be 0 (anti-fabrication is correct behavior)
    accepted_count = result.refs.get("accepted_count", 0)
    print(
        f"\nLive hypothesis test: accepted_count={accepted_count} "
        f"new_accepted_count={result.refs.get('new_accepted_count', 0)} "
        f"lessons={len(result.refs.get('lessons', []))}"
    )

    # Any accepted hypotheses must be retrievable from the ranked store
    ranked = RankedHypothesisStore(session.tree).get_ranked()
    for rh in ranked:
        assert rh.mechanism != "", "Accepted ranked hypothesis must have a non-empty mechanism"
        assert rh.overall_score is not None, "Accepted ranked hypothesis must have a score"
