"""Tests for LitMinerExecutor: search→extract→verify→record pipeline.

All tests run offline — no network calls, no API keys required.

Coverage:
    1. test_executor_produces_verified_fact       — full happy path
    2. test_hallucinated_citation_rejected         — L2: fetch_by_id returns None
    3. test_l3_metadata_mismatch_rejected          — L3: year mismatch → rejected
    4. test_paper_node_dedup                       — one paper node, two fact nodes
    5. test_resume_skips_already_processed         — second run skips processed paper
    6. test_rejected_fact_not_persisted            — rejected facts stay out of store
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))  # project root for conftest
sys.path.insert(0, "tests")
from conftest import MockProvider

from loop_sci.engine.types import DispatchUnit
from loop_sci.literature.executor import LitMinerExecutor
from loop_sci.literature.search.schema import PaperResult
from loop_sci.state.session import RunSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _paper(
    n: int = 1,
    *,
    year: int = 2024,
    authors: list[str] | None = None,
) -> PaperResult:
    """Build a deterministic PaperResult for tests."""
    if authors is None:
        authors = ["Author A"]
    return PaperResult(
        source="semantic_scholar",
        external_id=f"s2:p{n}",
        title=f"Paper {n}",
        authors=authors,
        year=year,
        venue="NeurIPS",
        # evidence_span must be a substring of abstract for the extractor grounding check
        abstract=f"Claim {n} is supported by evidence {n}.",
        url=None,
    )


# The extractor grounding check requires the evidence_span to be a substring of the abstract.
EXTRACT_RESP = json.dumps([
    {
        "claim": "Claim 1 is supported",
        "evidence_span": "Claim 1 is supported by evidence 1.",
        "confidence": 0.9,
        "entities": [],
    }
])

# For paper 2 (used in dedup test)
EXTRACT_RESP_2 = json.dumps([
    {
        "claim": "Claim 2 is supported",
        "evidence_span": "Claim 2 is supported by evidence 2.",
        "confidence": 0.9,
        "entities": [],
    }
])


class MockSearchClient:
    """Standard mock: same paper returned for search and fetch_by_id."""

    def __init__(self, papers: list[PaperResult]) -> None:
        self._papers = papers

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        return list(self._papers)

    async def fetch_by_id(self, eid: str) -> PaperResult | None:
        return next((p for p in self._papers if p.external_id == eid), None)


class MockSearchClientL2None:
    """Returns papers from search, but fetch_by_id always returns None → L2 rejection."""

    def __init__(self, papers: list[PaperResult]) -> None:
        self._papers = papers

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        return list(self._papers)

    async def fetch_by_id(self, eid: str) -> PaperResult | None:
        return None  # hallucinated — paper not found


class MockSearchClientL3:
    """Returns different papers for search vs fetch_by_id to test L3 metadata mismatch."""

    def __init__(
        self,
        search_paper: PaperResult,
        resolved_paper: PaperResult,
    ) -> None:
        self._search = search_paper
        self._resolved = resolved_paper

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        return [self._search]

    async def fetch_by_id(self, eid: str) -> PaperResult | None:
        # Always returns the *resolved* paper (different metadata)
        return self._resolved


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_session(tmp_path: Path) -> RunSession:
    return RunSession.create(tmp_path / "runs", task="test topic")


# ---------------------------------------------------------------------------
# Test 1: happy path — full run produces verified fact
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_produces_verified_fact(
    tmp_session: RunSession, tmp_path: Path
) -> None:
    """Full search→extract→verify→record pipeline: at least one fact persisted."""
    paper = _paper(1)
    provider = MockProvider(responses=[EXTRACT_RESP])
    clients = {"semantic_scholar": MockSearchClient([paper])}
    store_path = tmp_path / "facts.json"

    executor = LitMinerExecutor(
        session=tmp_session,
        search_clients=clients,
        extraction_provider=provider,
        grounding_provider=None,  # L4 uses fallback lexical-only
        store_path=store_path,
    )
    unit = DispatchUnit(node_id="ROOT", goal="spikes topic")
    result = await executor.run(unit)

    assert result.status == "done"
    assert result.refs.get("verified_facts_count", 0) >= 1, (
        f"Expected at least one verified fact, got: {result.refs}"
    )

    # Fact must be persisted to the JSON store
    from loop_sci.literature.factbase.store import FactStore
    store = FactStore(store_path)
    assert len(store.all()) >= 1, "FactStore should contain at least one persisted fact"


# ---------------------------------------------------------------------------
# Test 2: L2 rejection — fetch_by_id returns None (hallucinated citation)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hallucinated_citation_rejected(
    tmp_session: RunSession, tmp_path: Path
) -> None:
    """When fetch_by_id returns None, fact is rejected at L2 and NOT persisted."""
    paper = _paper(1)
    provider = MockProvider(responses=[EXTRACT_RESP])
    clients = {"semantic_scholar": MockSearchClientL2None([paper])}
    store_path = tmp_path / "facts.json"

    executor = LitMinerExecutor(
        session=tmp_session,
        search_clients=clients,
        extraction_provider=provider,
        grounding_provider=None,
        store_path=store_path,
    )
    result = await executor.run(DispatchUnit(node_id="ROOT", goal="hallucination topic"))

    # No verified facts (all rejected at L2)
    assert result.refs.get("verified_facts_count", 0) == 0, (
        "Hallucinated citations must not be counted as verified"
    )

    # Store must remain empty
    from loop_sci.literature.factbase.store import FactStore
    store = FactStore(store_path)
    assert len(store.all()) == 0, "Rejected facts must not be persisted to the store"


# ---------------------------------------------------------------------------
# Test 3: L3 metadata mismatch — year differs → rejected (HARD REQ A)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_l3_metadata_mismatch_rejected(
    tmp_session: RunSession, tmp_path: Path
) -> None:
    """HARD REQ A: L3 catches year mismatch → fact rejected, NOT persisted.

    Flow:
      1. dispatch() returns search_paper (year=2024, authors=["Author A"])
      2. Executor sets fact.expected_year=2024 and fact.expected_authors=["Author A"]
      3. fetch_by_id returns resolved_paper with year=2020, authors=["Author X"]
      4. L3 compares expected (2024) vs resolved (2020) → mismatch → rejected
    """
    search_paper = PaperResult(
        source="semantic_scholar",
        external_id="s2:p_mismatch",
        title="Mismatch Paper",
        authors=["Author A"],
        year=2024,
        venue="NeurIPS",
        abstract="Claim 1 is supported by evidence 1.",
        url=None,
    )
    # Resolver returns different year/authors than the search result
    resolved_paper = PaperResult(
        source="semantic_scholar",
        external_id="s2:p_mismatch",
        title="Mismatch Paper (resolved)",
        authors=["Author X"],
        year=2020,  # Different year → L3 mismatch
        venue="ICML",
        abstract="Claim 1 is supported by evidence 1.",
        url=None,
    )

    provider = MockProvider(responses=[EXTRACT_RESP])
    clients = {"semantic_scholar": MockSearchClientL3(search_paper, resolved_paper)}
    store_path = tmp_path / "facts.json"

    executor = LitMinerExecutor(
        session=tmp_session,
        search_clients=clients,
        extraction_provider=provider,
        grounding_provider=None,
        store_path=store_path,
    )
    result = await executor.run(DispatchUnit(node_id="ROOT", goal="L3 test topic"))

    # All facts should be rejected at L3
    assert result.refs.get("verified_facts_count", 0) == 0, (
        "L3 metadata mismatch must reject all facts"
    )

    # Store must remain empty — rejected facts must NOT be persisted
    from loop_sci.literature.factbase.store import FactStore
    store = FactStore(store_path)
    assert len(store.all()) == 0, "L3-rejected facts must not enter the fact base"

    # Verify the refs for inspection
    assert result.refs.get("total_papers", 0) >= 1, "Should have processed at least one paper"


# ---------------------------------------------------------------------------
# Test 4: paper-node dedup — two facts from same paper → ONE paper node (HARD REQ B)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paper_node_dedup(
    tmp_session: RunSession, tmp_path: Path
) -> None:
    """HARD REQ B: same paper searched twice → exactly one paper node, two fact nodes."""
    paper = _paper(1)
    # Two facts from the same paper
    two_facts_resp = json.dumps([
        {
            "claim": "Claim 1 is supported",
            "evidence_span": "Claim 1 is supported by evidence 1.",
            "confidence": 0.9,
            "entities": [],
        },
        {
            "claim": "Paper 1 is well-known",
            "evidence_span": "supported by evidence 1",
            "confidence": 0.85,
            "entities": [],
        },
    ])

    provider = MockProvider(responses=[two_facts_resp])
    clients = {"semantic_scholar": MockSearchClient([paper])}
    store_path = tmp_path / "facts.json"

    executor = LitMinerExecutor(
        session=tmp_session,
        search_clients=clients,
        extraction_provider=provider,
        grounding_provider=None,
        store_path=store_path,
        max_facts_per_paper=5,  # allow both facts
    )
    result = await executor.run(DispatchUnit(node_id="ROOT", goal="dedup test"))

    tree = tmp_session.tree

    # Count paper nodes (nodes with external_id in refs)
    paper_nodes = [
        n for n in tree._nodes.values()
        if n.refs and n.refs.get("external_id") == paper.external_id
    ]
    assert len(paper_nodes) == 1, (
        f"Expected exactly ONE paper node for {paper.external_id!r}, "
        f"got {len(paper_nodes)}: {[n.id for n in paper_nodes]}"
    )

    # Count fact nodes (children of the paper node)
    paper_node_id = paper_nodes[0].id
    fact_nodes = [
        n for n in tree._nodes.values()
        if n.parent_id == paper_node_id
    ]
    verified_count = result.refs.get("verified_facts_count", 0)
    assert verified_count >= 1, "Should have persisted at least one verified fact"
    assert len(fact_nodes) == verified_count, (
        f"Expected {verified_count} fact nodes under paper node, got {len(fact_nodes)}"
    )


# ---------------------------------------------------------------------------
# Test 5: resumability — second run skips already-processed paper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_skips_already_processed(
    tmp_session: RunSession, tmp_path: Path
) -> None:
    """Second run with same paper produces no duplicate facts (skipped_papers_count >= 1)."""
    paper = _paper(1)
    # Provide enough responses for two potential runs
    provider = MockProvider(responses=[EXTRACT_RESP] * 10)
    clients = {"semantic_scholar": MockSearchClient([paper])}
    store_path = tmp_path / "facts.json"

    async def _run() -> dict:
        ex = LitMinerExecutor(
            session=tmp_session,
            search_clients=clients,
            extraction_provider=provider,
            grounding_provider=None,
            store_path=store_path,
        )
        result = await ex.run(DispatchUnit(node_id="ROOT", goal="resume test"))
        return result.refs

    # First run
    refs1 = await _run()
    assert refs1.get("verified_facts_count", 0) >= 1, "First run must produce verified facts"

    # Second run: same session, same tree — paper is already in tree
    refs2 = await _run()
    assert refs2.get("skipped_papers_count", 0) >= 1, (
        "Second run must report skipped_papers_count >= 1"
    )
    assert refs2.get("verified_facts_count", 0) == 0, (
        "Second run must not produce new verified facts for already-processed paper"
    )

    # No duplicate facts in the store
    from loop_sci.literature.factbase.store import FactStore
    store = FactStore(store_path)
    all_facts = store.all()
    fact_ids = [f.fact_id for f in all_facts]
    assert len(fact_ids) == len(set(fact_ids)), "Duplicate fact_ids found in store"


# ---------------------------------------------------------------------------
# Test 6: rejected facts stay out of store and tree
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejected_fact_not_persisted(
    tmp_session: RunSession, tmp_path: Path
) -> None:
    """Rejected facts (any layer) must not be written to store or tree as fact nodes."""
    paper = _paper(1)
    provider = MockProvider(responses=[EXTRACT_RESP])
    # L2: fetch_by_id returns None → all facts rejected
    clients = {"semantic_scholar": MockSearchClientL2None([paper])}
    store_path = tmp_path / "facts.json"

    executor = LitMinerExecutor(
        session=tmp_session,
        search_clients=clients,
        extraction_provider=provider,
        grounding_provider=None,
        store_path=store_path,
    )
    await executor.run(DispatchUnit(node_id="ROOT", goal="rejection test"))

    # Store must be empty
    from loop_sci.literature.factbase.store import FactStore
    store = FactStore(store_path)
    assert len(store.all()) == 0, "Rejected facts must not enter the fact store"

    # No fact nodes in the tree (nodes that reference fact_id in refs)
    tree = tmp_session.tree
    fact_nodes = [
        n for n in tree._nodes.values()
        if n.refs and "fact_id" in n.refs and n.refs["fact_id"] is not None
    ]
    assert len(fact_nodes) == 0, (
        "Rejected facts must not create fact nodes in the idea tree"
    )
