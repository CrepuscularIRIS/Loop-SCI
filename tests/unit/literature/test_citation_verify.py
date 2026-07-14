"""TDD tests for citation verification L1-L3.

RED phase: written before any implementation exists.

Layer order (short-circuit: stop at first fail):
  L1 — format: citation has a resolvable identifier (external_id or doi)
  L2 — existence: identifier resolves to a real paper via adapter.fetch_by_id
  L3 — metadata match: authors/year/venue match within tolerance
  L4 — content-grounding (Task 7, not implemented here)

All tests run OFFLINE via a MockSearchClient (no real network calls).
"""
from __future__ import annotations

import pytest

from loop_sci.literature.extract.fact import Fact, SourceRef, VerificationStatus
from loop_sci.literature.search.schema import PaperResult
from loop_sci.literature.verify.citation import VerificationPipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _source_ref(
    source: str = "semantic_scholar",
    external_id: str = "s2:abc123",
    doi: str | None = None,
) -> SourceRef:
    return SourceRef(source=source, external_id=external_id, doi=doi)


def _fact(
    *,
    source: str = "semantic_scholar",
    external_id: str = "s2:abc123",
    doi: str | None = None,
    expected_year: int | None = None,
    expected_authors: list[str] | None = None,
    claim: str = "X causes Y",
) -> Fact:
    """Build a Fact with optional expected_year/expected_authors stored as claim metadata."""
    ref = _source_ref(source=source, external_id=external_id, doi=doi)
    # Store expected metadata in the claim text — VerificationPipeline reads
    # them from fact.expected_year / fact.expected_authors attributes that we
    # attach here for test convenience.  The pipeline must read these from
    # optional Fact attributes or the fact's source_ref.
    fact = Fact(
        claim=claim,
        source_ref=ref,
        evidence_span="X causes Y in our study",
        confidence=0.9,
        grounding_scope="abstract",
    )
    # Attach extra verification hints as instance attributes (the pipeline
    # reads these when present; they are None by default on Fact)
    if expected_year is not None:
        object.__setattr__(fact, "expected_year", expected_year)
    if expected_authors is not None:
        object.__setattr__(fact, "expected_authors", expected_authors)
    return fact


def _paper(
    external_id: str = "s2:abc123",
    authors: list[str] | None = None,
    year: int | None = 2023,
    venue: str | None = "NeurIPS",
) -> PaperResult:
    return PaperResult(
        source="semantic_scholar",
        external_id=external_id,
        title="Test Paper",
        authors=authors if authors is not None else ["Smith J", "Jones A"],
        year=year,
        venue=venue,
        abstract="X causes Y in our study.",
        url=None,
    )


class MockSearchClient:
    """Offline mock — returns a pre-configured result without any network call."""

    def __init__(self, result: PaperResult | None) -> None:
        self._result = result
        self.fetch_calls: list[str] = []

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        return []

    async def fetch_by_id(self, external_id: str) -> PaperResult | None:
        self.fetch_calls.append(external_id)
        return self._result


# ---------------------------------------------------------------------------
# L1 — format checks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_l1_rejects_fact_with_no_external_id_and_no_doi():
    """L1 must reject a citation that has no resolvable identifier at all."""
    # We must build a Fact with a technically valid SourceRef but then
    # override the pipeline's L1 logic by testing with an empty external_id via
    # a SourceRef that carries a placeholder.  Since SourceRef.__post_init__
    # rejects empty external_id, we construct a minimal valid one and then
    # verify the pipeline's L1 logic by passing a SourceRef with only whitespace
    # that bypasses SourceRef validation... but wait: SourceRef rejects empty
    # external_id at construction time.
    #
    # Instead we test L1 by constructing a Fact whose source does NOT match any
    # registered client AND has no doi — meaning there is no route to resolve it.
    # The pipeline must detect "no resolvable path" and fail at L1.
    #
    # Rationale: L1 is "well-formed with a resolvable identifier".  A fact with
    # an unknown source and no doi has no resolvable path.
    clients: dict = {}  # no clients at all
    pipeline = VerificationPipeline(search_clients=clients)
    fact = _fact(source="unknown_source", external_id="???", doi=None)
    status = await pipeline.verify_layers_123(fact)
    assert status.layer_reached == 1
    assert status.status == "failed"


@pytest.mark.asyncio
async def test_l1_accepts_fact_with_doi_even_when_source_unknown():
    """L1 must PASS when a DOI is present, even if the source adapter is unknown.

    The pipeline may not find the paper (L2 fails later), but L1 itself should
    pass because a DOI is a resolvable identifier format.
    """
    # No client for "unknown_source", but there's a doi — L1 passes; L2 fails.
    clients: dict = {}
    pipeline = VerificationPipeline(search_clients=clients)
    fact = _fact(source="unknown_source", external_id="unk:1", doi="10.1000/test")
    status = await pipeline.verify_layers_123(fact)
    # L1 passes (doi present), L2 fails (no client can resolve it)
    assert status.layer_reached == 2
    assert status.status == "rejected"


# ---------------------------------------------------------------------------
# L2 — existence / anti-fabrication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_l2_rejects_hallucinated_id_that_does_not_resolve():
    """Core anti-fabrication test: a hallucinated ID that returns None → rejected@2."""
    clients = {"semantic_scholar": MockSearchClient(result=None)}
    pipeline = VerificationPipeline(search_clients=clients)
    fact = _fact(external_id="s2:nonexistent_hallucination")
    status = await pipeline.verify_layers_123(fact)
    assert status.layer_reached == 2
    assert status.status == "rejected"


@pytest.mark.asyncio
async def test_l2_reject_does_not_attempt_l3():
    """Short-circuit: after L2 rejection, L3 must NOT be attempted."""
    mock_client = MockSearchClient(result=None)
    clients = {"semantic_scholar": mock_client}
    pipeline = VerificationPipeline(search_clients=clients)
    fact = _fact(external_id="s2:ghost", expected_year=2023)
    status = await pipeline.verify_layers_123(fact)
    # Only one fetch call (L2) — not two (L2+L3)
    assert status.layer_reached == 2
    assert status.status == "rejected"
    # The mock was called exactly once (for L2 resolution attempt)
    assert len(mock_client.fetch_calls) == 1


@pytest.mark.asyncio
async def test_l2_passes_when_paper_found():
    """L2 must pass when the adapter returns a real PaperResult."""
    clients = {"semantic_scholar": MockSearchClient(result=_paper())}
    pipeline = VerificationPipeline(search_clients=clients)
    fact = _fact()
    status = await pipeline.verify_layers_123(fact)
    # Should proceed past L2 (layer_reached >= 3)
    assert status.layer_reached >= 3


# ---------------------------------------------------------------------------
# L3 — metadata match
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_l3_rejects_year_mismatch():
    """L3 must fail when expected year does not match the resolved paper's year."""
    paper = _paper(year=1999)  # paper says 1999
    clients = {"semantic_scholar": MockSearchClient(result=paper)}
    pipeline = VerificationPipeline(search_clients=clients)
    # Fact expects year 2023 — mismatch with paper's 1999
    fact = _fact(expected_year=2023)
    status = await pipeline.verify_layers_123(fact)
    assert status.layer_reached == 3
    assert status.status == "rejected"


@pytest.mark.asyncio
async def test_l3_rejects_when_no_author_overlap():
    """L3 must fail when there is zero surname overlap between expected and actual authors."""
    paper = _paper(authors=["Wang Z", "Li Y"])
    clients = {"semantic_scholar": MockSearchClient(result=paper)}
    pipeline = VerificationPipeline(search_clients=clients)
    # Expected authors have no overlap with actual paper authors
    fact = _fact(expected_authors=["Smith J", "Jones A"])
    status = await pipeline.verify_layers_123(fact)
    assert status.layer_reached == 3
    assert status.status == "rejected"


@pytest.mark.asyncio
async def test_l3_passes_when_metadata_matches():
    """L3 must pass (→ pending_l4) when year and author overlap are correct."""
    paper = _paper(year=2023, authors=["Smith J", "Jones A"])
    clients = {"semantic_scholar": MockSearchClient(result=paper)}
    pipeline = VerificationPipeline(search_clients=clients)
    fact = _fact(expected_year=2023, expected_authors=["Smith J"])
    status = await pipeline.verify_layers_123(fact)
    assert status.layer_reached == 3
    assert status.status == "pending_l4"


@pytest.mark.asyncio
async def test_l3_passes_when_no_metadata_hints_provided():
    """L3 must pass when the fact carries no expected_year/expected_authors (no constraints)."""
    paper = _paper()
    clients = {"semantic_scholar": MockSearchClient(result=paper)}
    pipeline = VerificationPipeline(search_clients=clients)
    fact = _fact()  # no expected_year, no expected_authors
    status = await pipeline.verify_layers_123(fact)
    assert status.layer_reached == 3
    assert status.status == "pending_l4"


# ---------------------------------------------------------------------------
# Full pipeline: valid citation passes L1→L2→L3
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_citation_passes_all_three_layers():
    """Happy path: a well-formed, resolvable, metadata-matching citation passes L1-L3."""
    paper = _paper(year=2023, authors=["Smith J", "Jones A"], venue="NeurIPS")
    clients = {"semantic_scholar": MockSearchClient(result=paper)}
    pipeline = VerificationPipeline(search_clients=clients)
    fact = _fact(expected_year=2023, expected_authors=["Smith J"])
    status = await pipeline.verify_layers_123(fact)
    assert status.layer_reached == 3
    assert status.status == "pending_l4"


# ---------------------------------------------------------------------------
# VerificationStatus — Literal/Enum tightening (T4 deferral)
# ---------------------------------------------------------------------------


def test_verification_status_accepts_valid_statuses():
    """VerificationStatus must accept all valid literal status values."""
    valid_statuses = ["pending", "verified", "rejected", "failed", "pending_l4"]
    for s in valid_statuses:
        vs = VerificationStatus(layer_reached=1, status=s)
        assert vs.status == s


def test_verification_status_rejects_invalid_status():
    """VerificationStatus must reject an unrecognised status string."""
    with pytest.raises(ValueError, match="status"):
        VerificationStatus(layer_reached=1, status="unknown_garbage_status")


def test_verification_status_rejects_out_of_range_layer():
    """VerificationStatus.layer_reached must be in [1, 4]."""
    with pytest.raises(ValueError, match="layer_reached"):
        VerificationStatus(layer_reached=0, status="pending")


def test_verification_status_rejects_layer_above_4():
    """VerificationStatus.layer_reached must not exceed 4."""
    with pytest.raises(ValueError, match="layer_reached"):
        VerificationStatus(layer_reached=5, status="verified")


def test_verification_status_valid_layer_range():
    """VerificationStatus accepts layer_reached values 1 through 4."""
    for layer in (1, 2, 3, 4):
        vs = VerificationStatus(layer_reached=layer, status="pending")
        assert vs.layer_reached == layer


def test_verification_status_to_dict_round_trip_with_tightened_values():
    """to_dict/from_dict round-trip must work after Literal tightening."""
    vs = VerificationStatus(layer_reached=3, status="rejected", detail="year mismatch")
    d = vs.to_dict()
    restored = VerificationStatus.from_dict(d)
    assert restored == vs
    assert restored.status == "rejected"
    assert restored.layer_reached == 3


def test_existing_fact_schema_tests_still_pass_after_tightening():
    """Existing usages in fact_schema tests must still work after status tightening."""
    # These statuses were used in test_fact_schema.py:
    # "verified", "rejected", "flagged" — flagged may not be a valid Literal now.
    # The existing test uses "flagged" in test_verification_status_defaults.
    # We must ensure "flagged" either works or the existing test is updated.
    # Per task brief: keep existing tests green — so "flagged" must remain valid.
    vs = VerificationStatus(layer_reached=1, status="flagged")
    assert vs.status == "flagged"


# ---------------------------------------------------------------------------
# L4 wiring: full verify() (L1→L2→L3→L4) on VerificationPipeline
# ---------------------------------------------------------------------------


import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../"))
from tests.conftest import MockProvider  # noqa: E402


def _pipeline_with_paper(paper: PaperResult, grounding_provider=None) -> VerificationPipeline:
    """Build a VerificationPipeline wired with a mock search client returning *paper*."""
    client = MockSearchClient(result=paper)
    return VerificationPipeline(
        search_clients={"semantic_scholar": client},
        grounding_provider=grounding_provider,
        grounding_threshold=0.3,
    )


@pytest.mark.asyncio
async def test_full_pipeline_verified_when_claim_grounded():
    """L1→L2→L3→L4 happy path: grounded claim → status='verified', layer_reached=4."""
    # Abstract contains the evidence span verbatim → high lexical score
    paper = _paper(year=2023, authors=["Smith J"])
    paper_with_abstract = PaperResult(
        source=paper.source,
        external_id=paper.external_id,
        title=paper.title,
        authors=paper.authors,
        year=paper.year,
        venue=paper.venue,
        abstract="X causes Y in our study.",
        url=None,
    )
    pipeline = _pipeline_with_paper(paper_with_abstract)
    fact = _fact(expected_year=2023, expected_authors=["Smith J"])
    # The default evidence_span is "X causes Y in our study" — high overlap with abstract
    status = await pipeline.verify(fact)
    assert status.status == "verified"
    assert status.layer_reached == 4


@pytest.mark.asyncio
async def test_full_pipeline_rejected_at_l4_when_claim_absent():
    """L4 catches misattribution: real paper, correct metadata, claim NOT in abstract."""
    paper_with_unrelated_abstract = PaperResult(
        source="semantic_scholar",
        external_id="s2:abc123",
        title="Protein Folding Study",
        authors=["Smith J"],
        year=2023,
        venue="Nature",
        abstract="This paper studies protein folding in bacteria and archaea.",
        url=None,
    )
    pipeline = _pipeline_with_paper(paper_with_unrelated_abstract)
    fact = _fact(expected_year=2023, expected_authors=["Smith J"])
    # evidence_span="X causes Y in our study" — zero overlap with protein paper
    status = await pipeline.verify(fact)
    assert status.status == "rejected"
    assert status.layer_reached == 4


@pytest.mark.asyncio
async def test_full_pipeline_still_short_circuits_at_l2():
    """Short-circuit still works: L2 rejection doesn't reach L4."""
    # Search client returns None → paper not found → rejected at L2
    client = MockSearchClient(result=None)
    pipeline = VerificationPipeline(search_clients={"semantic_scholar": client})
    fact = _fact()
    status = await pipeline.verify(fact)
    assert status.layer_reached == 2
    assert status.status == "rejected"


@pytest.mark.asyncio
async def test_full_pipeline_still_short_circuits_at_l3():
    """Short-circuit still works: L3 metadata mismatch doesn't reach L4."""
    paper = _paper(year=1999)  # wrong year
    pipeline = _pipeline_with_paper(paper)
    fact = _fact(expected_year=2023)
    status = await pipeline.verify(fact)
    assert status.layer_reached == 3
    assert status.status == "rejected"


@pytest.mark.asyncio
async def test_verify_layers_123_still_returns_pending_l4():
    """verify_layers_123() must still return pending_l4 (L4 not run here)."""
    paper = _paper(year=2023, authors=["Smith J"])
    client = MockSearchClient(result=paper)
    pipeline = VerificationPipeline(search_clients={"semantic_scholar": client})
    fact = _fact(expected_year=2023, expected_authors=["Smith J"])
    status = await pipeline.verify_layers_123(fact)
    assert status.layer_reached == 3
    assert status.status == "pending_l4"


@pytest.mark.asyncio
async def test_verify_calls_fetch_by_id_exactly_once_for_l4_verified_path():
    """Cost regression: fetch_by_id must be called EXACTLY ONCE on a full L1→L4 verified path.

    Before the fix, verify() called _resolve() twice: once inside verify_layers_123()
    (L2 existence) and again in verify() itself (L4 grounding).  The fix inlines
    L1-L3 inside verify() so the resolved paper object is reused at L4 — only one
    fetch_by_id call is issued against the real (or mocked) API.
    """
    paper_with_abstract = PaperResult(
        source="semantic_scholar",
        external_id="s2:abc123",
        title="Test Paper",
        authors=["Smith J", "Jones A"],
        year=2023,
        venue="NeurIPS",
        abstract="X causes Y in our study.",
        url=None,
    )
    client = MockSearchClient(result=paper_with_abstract)
    pipeline = VerificationPipeline(
        search_clients={"semantic_scholar": client},
        grounding_threshold=0.3,
    )
    fact = _fact(expected_year=2023, expected_authors=["Smith J"])
    status = await pipeline.verify(fact)

    # Functional: claim is grounded → verified
    assert status.status == "verified"
    assert status.layer_reached == 4

    # Cost guard: exactly ONE fetch_by_id call, not two
    assert len(client.fetch_calls) == 1, (
        f"Expected exactly 1 fetch_by_id call, got {len(client.fetch_calls)}: "
        f"{client.fetch_calls!r}"
    )
