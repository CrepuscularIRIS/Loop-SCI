"""Tests for Semantic Scholar adapter.

TDD: tests are written BEFORE production code — must fail (RED) first.
All HTTP is intercepted offline via MockTransport; no real network calls.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from loop_sci.literature.search.semantic_scholar import SemanticScholarClient
from loop_sci.literature.search.schema import PaperResult

FIXTURES = Path(__file__).parent / "fixtures"


class MockTransport(httpx.AsyncBaseTransport):
    """Route requests to canned responses based on URL substring."""

    def __init__(self, responses: dict[str, tuple[int, bytes, str]]) -> None:
        # url_substring -> (status, body_bytes, content_type)
        self._responses = responses

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for prefix, (status, body, ctype) in self._responses.items():
            if prefix in url:
                return httpx.Response(status, content=body, headers={"content-type": ctype})
        return httpx.Response(404, content=b"not found")


@pytest.fixture
def ss_http() -> httpx.AsyncClient:
    body = FIXTURES.joinpath("ss_search.json").read_bytes()
    transport = MockTransport(
        {"graph.api.semanticscholar.org": (200, body, "application/json")}
    )
    # The adapter issues fully-qualified requests, base_url is used only to
    # establish a reachable host for httpx; the MockTransport intercepts by URL
    # substring before any network I/O occurs.
    return httpx.AsyncClient(
        transport=transport, base_url="https://api.semanticscholar.org"
    )


# ---------------------------------------------------------------------------
# search() — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ss_search_returns_list_of_paper_results(ss_http: httpx.AsyncClient) -> None:
    client = SemanticScholarClient(http=ss_http)
    results = await client.search("neural spikes", max_results=5)
    assert len(results) == 1
    assert all(isinstance(p, PaperResult) for p in results)


@pytest.mark.asyncio
async def test_ss_search_source_field(ss_http: httpx.AsyncClient) -> None:
    client = SemanticScholarClient(http=ss_http)
    results = await client.search("neural spikes", max_results=5)
    assert results[0].source == "semantic_scholar"


@pytest.mark.asyncio
async def test_ss_search_external_id_prefixed_s2(ss_http: httpx.AsyncClient) -> None:
    client = SemanticScholarClient(http=ss_http)
    results = await client.search("neural spikes", max_results=5)
    assert results[0].external_id == "s2:s2abc123"


@pytest.mark.asyncio
async def test_ss_search_doi_mapped(ss_http: httpx.AsyncClient) -> None:
    client = SemanticScholarClient(http=ss_http)
    results = await client.search("neural spikes", max_results=5)
    assert results[0].doi == "10.1234/test"


@pytest.mark.asyncio
async def test_ss_search_title_authors_year_venue(ss_http: httpx.AsyncClient) -> None:
    client = SemanticScholarClient(http=ss_http)
    results = await client.search("neural spikes", max_results=5)
    p = results[0]
    assert p.title == "Neural Evidence for X"
    assert p.authors == ["Smith J", "Lee K"]
    assert p.year == 2023
    assert p.venue == "NeurIPS"


@pytest.mark.asyncio
async def test_ss_search_abstract_and_url(ss_http: httpx.AsyncClient) -> None:
    client = SemanticScholarClient(http=ss_http)
    results = await client.search("neural spikes", max_results=5)
    p = results[0]
    assert p.abstract == "We show that X is real."
    assert "s2abc123" in (p.url or "")


# ---------------------------------------------------------------------------
# search() — robustness: missing optional fields map to None, not crash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ss_search_missing_optional_fields_returns_none() -> None:
    """A result with missing doi/venue/abstract/year must not crash."""
    body = b'{"data": [{"paperId": "minimal", "title": "Min paper", "authors": [], "externalIds": {}}]}'
    transport = MockTransport({"graph.api.semanticscholar.org": (200, body, "application/json")})
    http = httpx.AsyncClient(transport=transport, base_url="https://api.semanticscholar.org")
    client = SemanticScholarClient(http=http)
    results = await client.search("test")
    assert len(results) == 1
    p = results[0]
    assert p.doi is None
    assert p.year is None
    assert p.venue is None
    assert p.abstract is None


@pytest.mark.asyncio
async def test_ss_search_empty_data_returns_empty_list() -> None:
    body = b'{"data": []}'
    transport = MockTransport({"graph.api.semanticscholar.org": (200, body, "application/json")})
    http = httpx.AsyncClient(transport=transport, base_url="https://api.semanticscholar.org")
    client = SemanticScholarClient(http=http)
    results = await client.search("nothing")
    assert results == []


# ---------------------------------------------------------------------------
# fetch_by_id()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ss_fetch_by_id_returns_paper_result() -> None:
    body = (
        b'{"paperId": "s2abc123", "externalIds": {"DOI": "10.1234/test"}, '
        b'"title": "Neural Evidence for X", "authors": [], "year": 2023, '
        b'"venue": "NeurIPS", "abstract": "abstract", "url": "http://example.com"}'
    )
    transport = MockTransport({"graph.api.semanticscholar.org": (200, body, "application/json")})
    http = httpx.AsyncClient(transport=transport, base_url="https://api.semanticscholar.org")
    client = SemanticScholarClient(http=http)
    result = await client.fetch_by_id("s2:s2abc123")
    assert result is not None
    assert result.external_id == "s2:s2abc123"


@pytest.mark.asyncio
async def test_ss_fetch_by_id_not_found_returns_none() -> None:
    transport = MockTransport({"graph.api.semanticscholar.org": (404, b"", "application/json")})
    http = httpx.AsyncClient(transport=transport, base_url="https://api.semanticscholar.org")
    client = SemanticScholarClient(http=http)
    result = await client.fetch_by_id("s2:nonexistent")
    assert result is None


# ---------------------------------------------------------------------------
# API key forwarded in header
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ss_api_key_sent_in_header() -> None:
    captured: list[httpx.Request] = []

    class CapturingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured.append(request)
            body = b'{"data": []}'
            return httpx.Response(200, content=body, headers={"content-type": "application/json"})

    http = httpx.AsyncClient(transport=CapturingTransport(), base_url="https://api.semanticscholar.org")
    client = SemanticScholarClient(http=http, api_key="test-key-abc")
    await client.search("test")
    assert len(captured) == 1
    assert captured[0].headers.get("x-api-key") == "test-key-abc"
