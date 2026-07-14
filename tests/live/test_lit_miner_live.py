"""Live end-to-end test — requires DASHSCOPE_API_KEY and optional SEMANTIC_SCHOLAR_API_KEY.

All tests in this module are marked @pytest.mark.live and are skipped cleanly
when the required credentials are absent.  They are EXCLUDED from the default
CI suite (``pytest tests/`` without ``-m live``).

To run manually:
    DASHSCOPE_API_KEY=... uv run pytest tests/live/test_lit_miner_live.py -m live -v
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.live


@pytest.fixture
def api_key() -> str:
    key = os.environ.get("DASHSCOPE_API_KEY")
    if not key:
        pytest.skip("DASHSCOPE_API_KEY not set — skipping live test")
    return key


@pytest.mark.asyncio
async def test_live_literature_mining_small_neuro_topic(api_key: str, tmp_path) -> None:
    """Real multi-source search + real Qwen extraction + real 4-layer verification.

    Searches for papers on "spiking neural network energy efficiency" using the
    real Semantic Scholar API, extracts facts with the real Qwen provider, and
    runs the full 4-layer VerificationPipeline.

    The test passes as long as the pipeline completes without errors; finding
    zero verified facts is acceptable (all may be rejected by the verifier —
    that is a correct anti-fabrication outcome, not a failure).
    """
    import httpx

    from loop_sci.engine.types import DispatchUnit
    from loop_sci.literature.executor import LitMinerExecutor
    from loop_sci.literature.factbase.store import FactStore
    from loop_sci.literature.search.semantic_scholar import SemanticScholarClient
    from loop_sci.provider.factory import build_provider
    from loop_sci.state.session import RunSession

    provider = build_provider(api_key=api_key)
    ss_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    http = httpx.AsyncClient()
    clients = {"semantic_scholar": SemanticScholarClient(http=http, api_key=ss_key)}

    session = RunSession.create(tmp_path, task="spiking neural networks energy")
    store_path = tmp_path / "facts.json"
    executor = LitMinerExecutor(
        session=session,
        search_clients=clients,
        extraction_provider=provider,
        grounding_provider=provider,
        store_path=store_path,
        max_papers=3,
        max_facts_per_paper=2,
    )
    result = await executor.run(
        DispatchUnit(node_id="ROOT", goal="spiking neural network energy efficiency")
    )
    await http.aclose()

    assert result.status == "done", (
        f"Live pipeline must complete with status='done', got {result.status!r}"
    )

    store = FactStore(store_path)
    facts = store.all()
    print(
        f"\nLive test: {len(facts)} verified facts "
        f"from {result.refs.get('total_papers', '?')} papers "
        f"(skipped={result.refs.get('skipped_papers_count', 0)})"
    )

    # Any verified facts that ARE found must carry valid verification
    for fact in facts:
        assert fact.verification is not None, "Persisted fact must have verification"
        assert fact.verification.status == "verified", (
            f"Persisted fact must be verified, got {fact.verification.status!r}"
        )
        assert fact.fact_id is not None, "Persisted fact must have a fact_id"
