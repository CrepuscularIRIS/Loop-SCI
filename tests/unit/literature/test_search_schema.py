"""Tests for PaperResult schema and SearchClient protocol.

TDD: these tests are written BEFORE any production code.
All tests must FAIL first (RED), then pass after implementation (GREEN).
"""
from __future__ import annotations

import dataclasses
import inspect

import httpx
import pytest


# ---------------------------------------------------------------------------
# PaperResult schema tests
# ---------------------------------------------------------------------------


def test_paper_result_fields():
    """PaperResult must expose the unified schema fields all adapters map to."""
    from loop_sci.literature.search.schema import PaperResult

    required = {"source", "external_id", "title", "authors", "year", "venue", "abstract", "url"}
    names = {f.name for f in dataclasses.fields(PaperResult)}
    assert required.issubset(names), f"Missing fields: {required - names}"


def test_paper_result_construction_with_all_required():
    """PaperResult can be constructed with required fields."""
    from loop_sci.literature.search.schema import PaperResult

    p = PaperResult(
        source="semantic_scholar",
        external_id="s2:abc123",
        title="Test Paper",
        authors=["Smith J", "Doe A"],
        year=2024,
        venue="NeurIPS",
        abstract="This paper tests things.",
        url="https://example.com/paper",
    )
    assert p.source == "semantic_scholar"
    assert p.external_id == "s2:abc123"
    assert p.title == "Test Paper"
    assert p.authors == ["Smith J", "Doe A"]
    assert p.year == 2024
    assert p.venue == "NeurIPS"
    assert p.abstract == "This paper tests things."
    assert p.url == "https://example.com/paper"


def test_paper_result_doi_defaults_to_none():
    """doi is optional and defaults to None."""
    from loop_sci.literature.search.schema import PaperResult

    p = PaperResult(
        source="arxiv",
        external_id="arxiv:2401.00001",
        title="ArXiv Paper",
        authors=["Alice B"],
        year=2024,
        venue=None,
        abstract=None,
        url="https://arxiv.org/abs/2401.00001",
    )
    assert p.doi is None


def test_paper_result_doi_can_be_set():
    """doi can be explicitly set."""
    from loop_sci.literature.search.schema import PaperResult

    p = PaperResult(
        source="pubmed",
        external_id="pmid:12345678",
        title="PubMed Paper",
        authors=["Jones C"],
        year=2023,
        venue="Nature",
        abstract="A groundbreaking study.",
        url="https://pubmed.ncbi.nlm.nih.gov/12345678",
        doi="10.1038/nature12345",
    )
    assert p.doi == "10.1038/nature12345"


def test_paper_result_nullable_optional_fields():
    """year, venue, abstract, url can all be None."""
    from loop_sci.literature.search.schema import PaperResult

    p = PaperResult(
        source="semantic_scholar",
        external_id="s2:xyz",
        title="Minimal Paper",
        authors=[],
        year=None,
        venue=None,
        abstract=None,
        url=None,
    )
    assert p.year is None
    assert p.venue is None
    assert p.abstract is None
    assert p.url is None


def test_paper_result_is_dataclass():
    """PaperResult must be a dataclass (not a pydantic model, not an attrs class)."""
    from loop_sci.literature.search.schema import PaperResult

    assert dataclasses.is_dataclass(PaperResult)


# ---------------------------------------------------------------------------
# SearchClient protocol tests
# ---------------------------------------------------------------------------


def test_search_client_is_protocol():
    """SearchClient must be a typing.Protocol, not an ABC."""
    from loop_sci.literature.search.client import SearchClient

    assert inspect.isclass(SearchClient)
    # Protocol classes have __protocol_attrs__ or _is_protocol
    assert getattr(SearchClient, "_is_protocol", False), "SearchClient must be a Protocol"


def test_search_client_has_search_method():
    """SearchClient protocol declares async search(query, *, max_results) method."""
    from loop_sci.literature.search.client import SearchClient

    assert hasattr(SearchClient, "search"), "SearchClient must declare search()"


def test_search_client_has_fetch_by_id_method():
    """SearchClient protocol declares async fetch_by_id(external_id) method."""
    from loop_sci.literature.search.client import SearchClient

    assert hasattr(SearchClient, "fetch_by_id"), "SearchClient must declare fetch_by_id()"


# ---------------------------------------------------------------------------
# Mockable httpx transport boundary tests
# ---------------------------------------------------------------------------


def test_httpx_available():
    """httpx must be importable — it's a runtime dependency."""
    import httpx  # noqa: F401  # already imported at module level

    assert httpx.__version__


@pytest.mark.asyncio
async def test_mock_transport_returns_canned_response_without_network():
    """OFFLINE test: MockTransport intercepts calls — no real network connection is made.

    This test proves the injectable transport boundary is genuinely mockable:
    a concrete adapter built on httpx.AsyncClient(transport=...) can be tested
    without any network access.
    """
    from loop_sci.literature.search.client import make_async_client

    canned_body = b'{"paperId": "abc123", "title": "Offline Paper"}'

    def handler(request: httpx.Request) -> httpx.Response:
        # Assert NO real network socket is opened
        assert request.url.host == "api.semanticscholar.org"
        return httpx.Response(200, content=canned_body)

    transport = httpx.MockTransport(handler)
    client = make_async_client(transport=transport)

    async with client:
        resp = await client.get("https://api.semanticscholar.org/graph/v1/paper/abc123")

    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Offline Paper"


@pytest.mark.asyncio
async def test_mock_transport_can_simulate_errors_without_network():
    """OFFLINE test: MockTransport can inject HTTP error responses."""
    from loop_sci.literature.search.client import make_async_client

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    transport = httpx.MockTransport(handler)
    client = make_async_client(transport=transport)

    async with client:
        resp = await client.get("https://api.semanticscholar.org/graph/v1/paper/nonexistent")

    assert resp.status_code == 404
    assert resp.json()["error"] == "not found"


@pytest.mark.asyncio
async def test_make_async_client_with_no_base_url():
    """make_async_client must NOT set a base_url so adapters can use full URLs."""
    from loop_sci.literature.search.client import make_async_client

    canned_body = b'{}'

    def handler(request: httpx.Request) -> httpx.Response:
        # If base_url were set, this full URL would fail or be mangled
        assert str(request.url) == "https://api.semanticscholar.org/graph/v1/paper/abc"
        return httpx.Response(200, content=canned_body)

    transport = httpx.MockTransport(handler)
    client = make_async_client(transport=transport)

    async with client:
        resp = await client.get("https://api.semanticscholar.org/graph/v1/paper/abc")

    assert resp.status_code == 200
