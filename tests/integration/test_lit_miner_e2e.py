"""Offline integration tests: anti-fabrication + resume-no-reverify.

Drives the REAL LitMinerExecutor (with real VerificationPipeline, real
FactExtractor, real FactStore, real IdeaTree) against mock network seams:
  - MockSearchClient variants (canned PaperResult lists, controlled fetch_by_id)
  - MockProvider (scripted extraction/judge responses)

NO network calls, NO API keys required.  All tests belong to the default suite
(no @pytest.mark.live) and must pass in CI.

Scenarios covered
-----------------
1. Happy path: grounded claim → VERIFIED, persisted to BOTH tree and store,
   survives disk reload (verifies persistence end-to-end).
2. Hallucinated citation → rejected at L2 (layer_reached==2), NOT persisted to
   either store or tree.
3. Misattributed claim → rejected at L4 (layer_reached==4), NOT persisted.
   (claim not present in paper abstract → lexical score below LOW_THRESHOLD)
4. L3 metadata mismatch → rejected at L3, layer_reached==3 EXPLICITLY ASSERTED.
   This pins the rejection layer so a change to L4 thresholds/fixtures cannot
   silently move it.
5. Resume-no-reverify: second run over same paper skips it (skipped_papers_count
   >= 1), no new verified facts, no duplicate fact_ids in store.
6. Only-verified persisted: across a mixed batch (some verified, some rejected at
   various layers), ONLY the verified facts appear in tree and store.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from loop_sci.engine.types import DispatchUnit
from loop_sci.literature.executor import LitMinerExecutor
from loop_sci.literature.factbase.store import FactStore
from loop_sci.literature.search.schema import PaperResult
from loop_sci.state.idea_tree import IdeaTree
from loop_sci.state.session import RunSession

import sys
sys.path.insert(0, str(Path(__file__).parents[2]))  # project root so 'tests' is findable
sys.path.insert(0, str(Path(__file__).parents[2] / "tests"))  # expose tests/ for conftest
from conftest import MockProvider  # noqa: E402


# ---------------------------------------------------------------------------
# Shared abstract texts
# ---------------------------------------------------------------------------

# Abstract whose key phrase IS present verbatim — L4 lexical score will be HIGH
_ABSTRACT_SNN = (
    "Spiking neural networks consume 10x less energy than ANNs on neuromorphic hardware."
)

# Abstract about a completely different domain — claim about LSTM will NOT appear
# in this abstract; L4 lexical score will be LOW (below LOW_THRESHOLD=0.15)
_ABSTRACT_PROTEIN = (
    "We study protein folding mechanisms in yeast using cryo-EM at atomic resolution."
)

# ---------------------------------------------------------------------------
# Scripted extraction JSON responses
# ---------------------------------------------------------------------------

# Evidence span IS a verbatim substring of _ABSTRACT_SNN — extractor grounding
# check passes, L4 lexical score will be >= HIGH_THRESHOLD (0.60) → verified
_EXTRACT_VALID = json.dumps([{
    "claim": "SNNs consume 10x less energy than ANNs",
    "evidence_span": "Spiking neural networks consume 10x less energy than ANNs on neuromorphic hardware",
    "confidence": 0.92,
    "entities": ["SNN", "ANN"],
}])

# Paper abstract mentions "transformers accuracy" — but fetch_by_id returns None
# (hallucinated citation).  The extractor can pass grounding check since the
# evidence_span IS in the abstract, but L2 will reject it.
_ABSTRACT_HALLUCINATED = (
    "transformers 99% accuracy on vision tasks in our benchmark."
)
_EXTRACT_HALLUCINATED = json.dumps([{
    "claim": "Transformers achieve 99% accuracy on all tasks",
    "evidence_span": "transformers 99% accuracy on vision tasks in our benchmark",
    "confidence": 0.9,
    "entities": [],
}])

# Evidence span NOT in _ABSTRACT_PROTEIN → extractor drops it after grounding check
# So we need the evidence_span to be a substring of the abstract for the extractor
# to accept it, but completely absent from the REAL paper text that the verifier
# sees at L4.
# Strategy: use _ABSTRACT_PROTEIN as both the search abstract AND the resolved
# paper abstract.  The claim "LSTM outperforms transformers" is not in that text.
# We craft the evidence_span to pass the extractor's grounding check against
# _ABSTRACT_PROTEIN by matching a fragment that IS in the abstract, but the claim
# itself is about LSTM — so at L4 the evidence_span must still NOT be grounded.
#
# Actually, the extractor's grounding check requires evidence_span ⊆ abstract.
# For the misattributed test we want:
#   - evidence_span IS in the abstract (extractor passes)
#   - but the CLAIM is misattributed (not what the paper is about)
#   - L4 grounding checks evidence_span against paper.abstract
#   - since evidence_span IS in abstract, L4 will also PASS (verified)!
#
# That is NOT the misattribution scenario we want.  To get L4 rejected we need
# evidence_span NOT in the abstract.  But the extractor drops it if the span
# is not in the abstract.
#
# Resolution: use a paper whose SEARCH abstract has the claim but whose RESOLVED
# (fetch_by_id) abstract does NOT.  This is realistic: search result has a short
# snippet that mentions the claim, but the full resolved paper has a different
# abstract.
#
# This mirrors "misattributed" in real life: the search result looked relevant,
# but when we actually fetch the paper the claim is nowhere in the real text.

_ABSTRACT_SEARCH_LSTM = (
    "LSTM outperforms transformers on time series forecasting tasks."
)
_ABSTRACT_RESOLVED_PROTEIN = _ABSTRACT_PROTEIN  # resolved paper is about proteins

_EXTRACT_MISATTRIBUTED = json.dumps([{
    "claim": "LSTM outperforms transformers on time series",
    # evidence_span IS in the SEARCH abstract → extractor grounding check passes
    "evidence_span": "LSTM outperforms transformers on time series forecasting tasks",
    "confidence": 0.85,
    "entities": [],
}])


# ---------------------------------------------------------------------------
# Mock search clients
# ---------------------------------------------------------------------------


class _RealSearchClient:
    """Returns the same paper for search AND fetch_by_id — realistic resolved paper."""

    def __init__(self, papers: list[PaperResult]) -> None:
        self._by_id: dict[str, PaperResult] = {p.external_id: p for p in papers}

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        return list(self._by_id.values())

    async def fetch_by_id(self, eid: str) -> PaperResult | None:
        return self._by_id.get(eid)


class _HallucinatedSearchClient:
    """search() returns papers; fetch_by_id() always returns None (hallucinated DOI)."""

    def __init__(self, papers: list[PaperResult]) -> None:
        self._papers = list(papers)

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        return self._papers

    async def fetch_by_id(self, eid: str) -> PaperResult | None:
        return None  # hallucinated — cannot be resolved via any API


class _MisattributedSearchClient:
    """search() returns a paper with one abstract; fetch_by_id returns a DIFFERENT paper.

    This is the "misattributed" scenario: the search result looks relevant (claim
    appears in the search abstract), but the REAL resolved paper has a completely
    different abstract — so L4 rejects the claim as not grounded.
    """

    def __init__(self, search_paper: PaperResult, resolved_paper: PaperResult) -> None:
        self._search_paper = search_paper
        self._resolved_paper = resolved_paper

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        return [self._search_paper]

    async def fetch_by_id(self, eid: str) -> PaperResult | None:
        return self._resolved_paper  # always returns the resolved (different) paper


class _L3MismatchSearchClient:
    """search() returns paper with year=2023; fetch_by_id returns paper with year=2099.

    This forces L3 (metadata mismatch) to fire: the executor wires expected_year=2023
    from the search result, but the resolved paper says year=2099.
    """

    def __init__(self, search_paper: PaperResult, resolved_paper: PaperResult) -> None:
        self._search_paper = search_paper
        self._resolved_paper = resolved_paper

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        return [self._search_paper]

    async def fetch_by_id(self, eid: str) -> PaperResult | None:
        return self._resolved_paper


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _make_session(tmp_path: Path, suffix: str = "") -> RunSession:
    return RunSession.create(tmp_path / f"runs{suffix}", task="integration test topic")


# ---------------------------------------------------------------------------
# Scenario 1: Happy path — verified fact persisted to tree AND store, disk reload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_verified_fact_in_tree_and_store(tmp_path: Path) -> None:
    """Grounded claim → VERIFIED, written to tree + store, survives disk reload.

    Assertions
    ----------
    - result.status == "done"
    - result.refs["verified_facts_count"] >= 1
    - FactStore.all() returns >= 1 fact with verification.status == "verified"
    - At least one tree node has refs["verification_status"] == "verified"
    - After loading IdeaTree from disk, the fact node is still present
    """
    session = _make_session(tmp_path, "_happy")
    provider = MockProvider(responses=[_EXTRACT_VALID])
    paper = PaperResult(
        source="semantic_scholar",
        external_id="s2:real1",
        title="SNN Energy Paper",
        authors=["Smith J"],
        year=2023,
        venue="NeurIPS",
        abstract=_ABSTRACT_SNN,
        url=None,
    )
    clients: dict = {"semantic_scholar": _RealSearchClient([paper])}
    store_path = tmp_path / "facts_happy.json"

    executor = LitMinerExecutor(
        session=session,
        search_clients=clients,
        extraction_provider=provider,
        grounding_provider=None,  # L4 uses fallback lexical-only path
        store_path=store_path,
    )
    result = await executor.run(DispatchUnit(node_id="ROOT", goal="spiking networks"))

    # --- executor-level assertions ---
    assert result.status == "done", f"Expected status='done', got {result.status!r}"
    assert result.refs["verified_facts_count"] >= 1, (
        f"Expected >= 1 verified fact, got {result.refs}"
    )

    # --- fact store: reload from disk to confirm persistence ---
    store = FactStore(store_path)
    facts = store.all()
    assert len(facts) >= 1, "FactStore must contain at least one fact after disk reload"
    assert all(f.verification is not None for f in facts), (
        "Every persisted fact must carry a VerificationStatus"
    )
    assert all(f.verification.status == "verified" for f in facts), (
        "Every persisted fact must have verification.status == 'verified'"
    )

    # --- idea-tree: fact nodes carry verification_status == "verified" ---
    tree = session.tree
    # persist_fact embeds the full Fact.to_dict() in refs; verification_status key
    # does NOT exist there (the dict key is "verification" → nested dict).
    # So we look for nodes whose refs["verification"]["status"] == "verified":
    fact_nodes_verified = [
        n for n in tree._nodes.values()
        if (
            n.refs
            and isinstance(n.refs.get("verification"), dict)
            and n.refs["verification"].get("status") == "verified"
        )
    ]
    assert len(fact_nodes_verified) >= 1, (
        "At least one fact node in the idea-tree must have verification.status='verified'"
    )

    # --- disk reload: tree file exists and contains the fact node ---
    tree_path = session.session_dir / "idea_tree.json"
    assert tree_path.exists(), "idea_tree.json must be written to disk"
    reloaded_tree = IdeaTree.load_json(tree_path)
    reloaded_fact_nodes = [
        n for n in reloaded_tree._nodes.values()
        if (
            n.refs
            and isinstance(n.refs.get("verification"), dict)
            and n.refs["verification"].get("status") == "verified"
        )
    ]
    assert len(reloaded_fact_nodes) >= 1, (
        "After disk reload, the fact node must still be present in the idea-tree"
    )


# ---------------------------------------------------------------------------
# Scenario 2: Hallucinated citation → rejected at L2, NOT persisted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hallucinated_citation_rejected_at_l2(tmp_path: Path) -> None:
    """fetch_by_id returns None → L2 rejection; fact must NOT appear in store or tree.

    Assertions
    ----------
    - result.refs["verified_facts_count"] == 0
    - FactStore.all() == []
    - No tree nodes with fact_id set (no fact nodes created)
    - Verification layer_reached == 2 (explicit L2 pin)
    """
    session = _make_session(tmp_path, "_l2")
    provider = MockProvider(responses=[_EXTRACT_HALLUCINATED])
    hallucinated_paper = PaperResult(
        source="semantic_scholar",
        external_id="s2:fake999",
        title="Fake Transformer Paper",
        authors=["Ghost A"],
        year=2099,
        venue=None,
        abstract=_ABSTRACT_HALLUCINATED,
        url=None,
    )
    clients: dict = {"semantic_scholar": _HallucinatedSearchClient([hallucinated_paper])}
    store_path = tmp_path / "facts_l2.json"

    executor = LitMinerExecutor(
        session=session,
        search_clients=clients,
        extraction_provider=provider,
        grounding_provider=None,
        store_path=store_path,
    )
    result = await executor.run(DispatchUnit(node_id="ROOT", goal="transformers"))

    # --- verified count == 0 ---
    assert result.refs["verified_facts_count"] == 0, (
        "Hallucinated citation: verified_facts_count must be 0"
    )

    # --- store is empty ---
    store = FactStore(store_path)
    assert store.all() == [], "Hallucinated citation: FactStore must be empty"

    # --- no fact nodes in tree ---
    tree = session.tree
    fact_nodes = [
        n for n in tree._nodes.values()
        if n.refs and n.refs.get("fact_id") is not None
    ]
    assert len(fact_nodes) == 0, (
        "Hallucinated citation: no fact nodes must exist in the idea-tree"
    )

    # --- EXPLICIT L2 pin: run the verification pipeline directly to confirm ---
    # We re-run the pipeline standalone to pin layer_reached==2 explicitly,
    # since the executor only exposes verified_facts_count in its result.
    from loop_sci.literature.extract.fact import Fact, SourceRef
    from loop_sci.literature.verify.citation import VerificationPipeline

    fact = Fact(
        claim="Transformers achieve 99% accuracy on all tasks",
        source_ref=SourceRef(
            source="semantic_scholar",
            external_id="s2:fake999",
        ),
        evidence_span="transformers 99% accuracy on vision tasks in our benchmark",
        confidence=0.9,
        grounding_scope="abstract",
        entities=[],
    )
    pipeline = VerificationPipeline(
        {"semantic_scholar": _HallucinatedSearchClient([hallucinated_paper])},
        grounding_provider=None,
    )
    status = await pipeline.verify(fact)
    assert status.layer_reached == 2, (
        f"Hallucinated citation must be rejected at L2 (layer_reached==2), "
        f"got layer_reached={status.layer_reached}, status={status.status!r}"
    )
    assert status.status == "rejected", (
        f"Hallucinated citation must have status='rejected', got {status.status!r}"
    )


# ---------------------------------------------------------------------------
# Scenario 3: Misattributed claim → rejected at L4, NOT persisted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_misattributed_claim_rejected_at_l4(tmp_path: Path) -> None:
    """Search abstract contains claim; resolved paper does not → L4 rejection.

    Construction
    ------------
    - search_paper.abstract = "LSTM outperforms transformers on time series..."
      → extractor grounding check passes (evidence_span is a substring)
    - resolved_paper.abstract = protein folding text (no LSTM mention)
      → L4 lexical score of evidence_span against protein abstract ≈ 0
      → score <= LOW_THRESHOLD (0.15) → immediately REJECTED without LLM

    Assertions
    ----------
    - result.refs["verified_facts_count"] == 0
    - FactStore.all() == []
    - layer_reached == 4 (explicit L4 pin)
    - status == "rejected"
    """
    session = _make_session(tmp_path, "_l4")
    provider = MockProvider(responses=[_EXTRACT_MISATTRIBUTED])

    search_paper = PaperResult(
        source="semantic_scholar",
        external_id="s2:lstm1",
        title="LSTM Time Series Paper",
        authors=["Zhang W"],
        year=2023,
        venue="ICLR",
        abstract=_ABSTRACT_SEARCH_LSTM,  # claim IS here → extractor passes
        url=None,
    )
    resolved_paper = PaperResult(
        source="semantic_scholar",
        external_id="s2:lstm1",
        title="Protein Folding (resolved)",
        authors=["Zhang W"],  # same author to pass L3 author check
        year=2023,            # same year to pass L3 year check
        venue="ICLR",
        abstract=_ABSTRACT_RESOLVED_PROTEIN,  # claim NOT here → L4 rejects
        url=None,
    )
    clients: dict = {
        "semantic_scholar": _MisattributedSearchClient(search_paper, resolved_paper)
    }
    store_path = tmp_path / "facts_l4.json"

    executor = LitMinerExecutor(
        session=session,
        search_clients=clients,
        extraction_provider=provider,
        grounding_provider=None,
        store_path=store_path,
    )
    result = await executor.run(DispatchUnit(node_id="ROOT", goal="LSTM forecasting"))

    # --- no verified facts ---
    assert result.refs["verified_facts_count"] == 0, (
        "Misattributed claim: verified_facts_count must be 0"
    )

    # --- store is empty ---
    assert FactStore(store_path).all() == [], (
        "Misattributed claim: FactStore must be empty"
    )

    # --- EXPLICIT L4 pin via standalone pipeline ---
    from loop_sci.literature.extract.fact import Fact, SourceRef
    from loop_sci.literature.verify.citation import VerificationPipeline

    fact = Fact(
        claim="LSTM outperforms transformers on time series",
        source_ref=SourceRef(
            source="semantic_scholar",
            external_id="s2:lstm1",
        ),
        evidence_span="LSTM outperforms transformers on time series forecasting tasks",
        confidence=0.85,
        grounding_scope="abstract",
        entities=[],
    )
    # Wire expected_year and expected_authors the same way the executor does
    fact.expected_year = search_paper.year        # type: ignore[attr-defined]
    fact.expected_authors = search_paper.authors  # type: ignore[attr-defined]

    pipeline = VerificationPipeline(
        {"semantic_scholar": _MisattributedSearchClient(search_paper, resolved_paper)},
        grounding_provider=None,
    )
    status = await pipeline.verify(fact)
    assert status.layer_reached == 4, (
        f"Misattributed claim must be rejected at L4 (layer_reached==4), "
        f"got layer_reached={status.layer_reached}, status={status.status!r}"
    )
    assert status.status == "rejected", (
        f"Misattributed claim must have status='rejected', got {status.status!r}"
    )


# ---------------------------------------------------------------------------
# Scenario 4: L3 metadata mismatch → rejected at L3, layer_reached==3 EXPLICIT PIN
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_l3_metadata_mismatch_rejected_layer_reached_3(tmp_path: Path) -> None:
    """HARD REQUIREMENT: year mismatch → rejected at L3, layer_reached MUST be 3.

    This test PINS the rejection at L3 by construction so that a change to L4
    thresholds, fixtures, or grounding providers cannot silently move the
    rejection to a different layer.

    Construction
    ------------
    - search_paper: year=2023, authors=["Smith J"] → executor wires
      fact.expected_year=2023, fact.expected_authors=["Smith J"]
    - resolved_paper: year=2099, authors=["Totally Different"] →
      year mismatch (2023 ≠ 2099) → L3 immediately rejects

    Assertions
    ----------
    - result.refs["verified_facts_count"] == 0  (no verified facts)
    - FactStore.all() == []                       (not persisted)
    - status.layer_reached == 3                   (EXPLICIT PIN — must be 3, not 4)
    - status.status == "rejected"
    """
    session = _make_session(tmp_path, "_l3")

    _ABSTRACT_L3 = "Spiking neural networks consume 10x less energy than ANNs on neuromorphic hardware."
    _EXTRACT_L3 = json.dumps([{
        "claim": "SNNs consume 10x less energy than ANNs",
        "evidence_span": "Spiking neural networks consume 10x less energy than ANNs on neuromorphic hardware",
        "confidence": 0.92,
        "entities": ["SNN", "ANN"],
    }])

    search_paper = PaperResult(
        source="semantic_scholar",
        external_id="s2:snn_l3",
        title="SNN Energy Paper",
        authors=["Smith J"],
        year=2023,
        venue="NeurIPS",
        abstract=_ABSTRACT_L3,
        url=None,
    )
    resolved_paper = PaperResult(
        source="semantic_scholar",
        external_id="s2:snn_l3",
        title="SNN Energy Paper (resolved — different metadata)",
        authors=["Totally Different"],
        year=2099,               # YEAR MISMATCH: 2023 expected vs 2099 resolved
        venue="NeurIPS",
        abstract=_ABSTRACT_L3,  # same abstract so L4 would pass IF reached
        url=None,
    )
    clients: dict = {
        "semantic_scholar": _L3MismatchSearchClient(search_paper, resolved_paper)
    }
    store_path = tmp_path / "facts_l3.json"
    provider = MockProvider(responses=[_EXTRACT_L3])

    executor = LitMinerExecutor(
        session=session,
        search_clients=clients,
        extraction_provider=provider,
        grounding_provider=None,
        store_path=store_path,
    )
    result = await executor.run(DispatchUnit(node_id="ROOT", goal="SNN energy L3 test"))

    # --- executor-level: no verified facts, store empty ---
    assert result.refs["verified_facts_count"] == 0, (
        "L3 mismatch: verified_facts_count must be 0"
    )
    assert FactStore(store_path).all() == [], (
        "L3 mismatch: FactStore must be empty (rejected facts not persisted)"
    )

    # --- EXPLICIT L3 PIN via standalone pipeline ---
    from loop_sci.literature.extract.fact import Fact, SourceRef
    from loop_sci.literature.verify.citation import VerificationPipeline

    fact = Fact(
        claim="SNNs consume 10x less energy than ANNs",
        source_ref=SourceRef(
            source="semantic_scholar",
            external_id="s2:snn_l3",
        ),
        evidence_span="Spiking neural networks consume 10x less energy than ANNs on neuromorphic hardware",
        confidence=0.92,
        grounding_scope="abstract",
        entities=["SNN", "ANN"],
    )
    # Wire expected metadata the same way the executor does (from the SEARCH paper)
    fact.expected_year = search_paper.year        # type: ignore[attr-defined]
    fact.expected_authors = search_paper.authors  # type: ignore[attr-defined]

    pipeline = VerificationPipeline(
        {"semantic_scholar": _L3MismatchSearchClient(search_paper, resolved_paper)},
        grounding_provider=None,
    )
    status = await pipeline.verify(fact)

    # HARD REQUIREMENT: must be exactly 3, not 4
    assert status.layer_reached == 3, (
        f"L3 metadata mismatch MUST be rejected at layer_reached==3, "
        f"got layer_reached={status.layer_reached!r} with status={status.status!r}. "
        "If this is 4, the year-mismatch check was bypassed — check _check_metadata."
    )
    assert status.status == "rejected", (
        f"L3 mismatch must produce status='rejected', got {status.status!r}"
    )


# ---------------------------------------------------------------------------
# Scenario 5: Resume-no-reverify — second run skips, no duplicates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_no_reverify(tmp_path: Path) -> None:
    """Second run over same paper is skipped; no duplicate facts in store.

    Construction
    ------------
    - Two runs on the same session / same store_path / same paper.
    - First run: paper is new → processes, extracts, verifies, persists.
    - Second run: paper already in tree (external_id seen) → skipped.

    Assertions
    ----------
    - result2.refs["skipped_papers_count"] >= 1
    - result2.refs["verified_facts_count"] == 0
    - len(store.all()) after both runs == len(store.all()) after first run
    - No duplicate fact_ids in the store
    """
    session = _make_session(tmp_path, "_resume")
    paper = PaperResult(
        source="semantic_scholar",
        external_id="s2:resume1",
        title="Resume Test Paper",
        authors=["Lee K"],
        year=2023,
        venue="ICML",
        abstract=_ABSTRACT_SNN,
        url=None,
    )
    clients: dict = {"semantic_scholar": _RealSearchClient([paper])}
    store_path = tmp_path / "facts_resume.json"

    # Provide plenty of responses so both potential runs can extract
    provider = MockProvider(responses=[_EXTRACT_VALID] * 10)

    async def _run() -> "ExecutorResult":  # noqa: F821
        ex = LitMinerExecutor(
            session=session,
            search_clients=clients,
            extraction_provider=provider,
            grounding_provider=None,
            store_path=store_path,
        )
        return await ex.run(DispatchUnit(node_id="ROOT", goal="resume test"))

    # First run
    result1 = await _run()
    count_after_first = result1.refs["verified_facts_count"]
    assert count_after_first >= 1, (
        "First run must produce at least one verified fact for the resume test to be meaningful"
    )
    store_count_after_first = len(FactStore(store_path).all())

    # Second run: same session, same tree → paper already seen
    result2 = await _run()
    assert result2.refs["skipped_papers_count"] >= 1, (
        f"Second run must skip already-processed paper "
        f"(skipped_papers_count={result2.refs['skipped_papers_count']})"
    )
    assert result2.refs["verified_facts_count"] == 0, (
        "Second run must produce zero NEW verified facts (paper was skipped)"
    )

    # Store size must be unchanged after the second run
    store_after_both = FactStore(store_path).all()
    assert len(store_after_both) == store_count_after_first, (
        f"Store size must not grow after resume run: "
        f"after_first={store_count_after_first}, after_both={len(store_after_both)}"
    )

    # No duplicate fact_ids
    fact_ids = [f.fact_id for f in store_after_both]
    assert len(fact_ids) == len(set(fact_ids)), (
        f"Duplicate fact_ids found after resume: {fact_ids}"
    )


# ---------------------------------------------------------------------------
# Scenario 6: Only-verified persisted across a mixed batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_only_verified_persisted_in_mixed_batch(tmp_path: Path) -> None:
    """Mixed batch: verified + L2-rejected papers → only verified appear in store/tree.

    Construction
    ------------
    - paper_good: real paper with grounded claim → VERIFIED
    - paper_bad:  hallucinated citation → L2 rejected

    Both are returned by search() in sequence (two separate clients or a
    combined client).  The executor processes both.

    Assertions
    ----------
    - result.refs["verified_facts_count"] == exactly N_good verified facts
    - FactStore contains ONLY facts from paper_good (verified)
    - No fact nodes in tree from paper_bad (none with external_id "s2:bad1")
    """
    session = _make_session(tmp_path, "_mixed")
    store_path = tmp_path / "facts_mixed.json"

    paper_good = PaperResult(
        source="semantic_scholar",
        external_id="s2:good1",
        title="Good SNN Paper",
        authors=["Smith J"],
        year=2023,
        venue="NeurIPS",
        abstract=_ABSTRACT_SNN,
        url=None,
    )
    paper_bad = PaperResult(
        source="semantic_scholar",
        external_id="s2:bad1",
        title="Fake Paper",
        authors=["Ghost A"],
        year=2099,
        venue=None,
        abstract=_ABSTRACT_HALLUCINATED,
        url=None,
    )

    # Extractor responses: first call → valid extract; second call → hallucinated extract
    # (Executor processes papers in order: paper_good first, paper_bad second)
    provider = MockProvider(responses=[_EXTRACT_VALID, _EXTRACT_HALLUCINATED])

    class _MixedSearchClient:
        """Returns both papers from search; fetch_by_id resolves only paper_good."""

        async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
            return [paper_good, paper_bad]

        async def fetch_by_id(self, eid: str) -> PaperResult | None:
            if eid == paper_good.external_id:
                return paper_good
            return None  # paper_bad is hallucinated

    clients: dict = {"semantic_scholar": _MixedSearchClient()}

    executor = LitMinerExecutor(
        session=session,
        search_clients=clients,
        extraction_provider=provider,
        grounding_provider=None,
        store_path=store_path,
        max_papers=10,
    )
    result = await executor.run(DispatchUnit(node_id="ROOT", goal="mixed batch test"))

    # --- only verified facts counted ---
    assert result.refs["verified_facts_count"] >= 1, (
        "At least one fact from paper_good must be verified"
    )

    # --- store contains ONLY verified facts ---
    store = FactStore(store_path)
    all_facts = store.all()
    assert all(f.verification is not None and f.verification.status == "verified"
               for f in all_facts), (
        "FactStore must contain ONLY facts with verification.status=='verified'"
    )

    # --- all store facts come from paper_good, none from paper_bad ---
    for fact in all_facts:
        assert fact.source_ref.external_id == paper_good.external_id, (
            f"Rejected fact from paper_bad must not appear in store: "
            f"found external_id={fact.source_ref.external_id!r}"
        )

    # --- no fact nodes from paper_bad in the tree ---
    tree = session.tree
    # Fact nodes for paper_bad would have parent paper node id containing "s2_bad1"
    bad_safe_eid = paper_bad.external_id.replace(":", "_").replace("/", "_")
    bad_paper_node_id = f"paper_{bad_safe_eid}"
    bad_fact_nodes = [
        n for n in tree._nodes.values()
        if n.parent_id == bad_paper_node_id
           and n.refs
           and n.refs.get("fact_id") is not None
    ]
    assert len(bad_fact_nodes) == 0, (
        f"No fact nodes from rejected paper_bad must appear in the tree, "
        f"found: {[n.id for n in bad_fact_nodes]}"
    )
