"""Tests for arXiv adapter.

TDD: tests are written BEFORE production code — must fail (RED) first.
All HTTP is intercepted offline via MockTransport; no real network calls.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from loop_sci.literature.search.arxiv import ArxivClient
from loop_sci.literature.search.schema import PaperResult

FIXTURES = Path(__file__).parent / "fixtures"


class MockTransport(httpx.AsyncBaseTransport):
    def __init__(self, responses: dict[str, tuple[int, bytes, str]]) -> None:
        self._responses = responses

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for prefix, (status, body, ctype) in self._responses.items():
            if prefix in url:
                return httpx.Response(status, content=body, headers={"content-type": ctype})
        return httpx.Response(404, content=b"not found")


@pytest.fixture
def arxiv_http() -> httpx.AsyncClient:
    body = FIXTURES.joinpath("arxiv_search.xml").read_bytes()
    transport = MockTransport({"export.arxiv.org": (200, body, "application/atom+xml")})
    return httpx.AsyncClient(transport=transport, base_url="https://export.arxiv.org")


# ---------------------------------------------------------------------------
# search() — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_arxiv_search_returns_list_of_paper_results(arxiv_http: httpx.AsyncClient) -> None:
    client = ArxivClient(http=arxiv_http)
    results = await client.search("spike learning", max_results=5)
    assert len(results) == 1
    assert all(isinstance(p, PaperResult) for p in results)


@pytest.mark.asyncio
async def test_arxiv_search_source_field(arxiv_http: httpx.AsyncClient) -> None:
    client = ArxivClient(http=arxiv_http)
    results = await client.search("spike learning", max_results=5)
    assert results[0].source == "arxiv"


@pytest.mark.asyncio
async def test_arxiv_search_external_id_contains_arxiv_id(arxiv_http: httpx.AsyncClient) -> None:
    client = ArxivClient(http=arxiv_http)
    results = await client.search("spike learning", max_results=5)
    assert "2401.00001" in results[0].external_id


@pytest.mark.asyncio
async def test_arxiv_search_external_id_prefixed_arxiv(arxiv_http: httpx.AsyncClient) -> None:
    client = ArxivClient(http=arxiv_http)
    results = await client.search("spike learning", max_results=5)
    assert results[0].external_id.startswith("arxiv:")


@pytest.mark.asyncio
async def test_arxiv_search_title_authors_year(arxiv_http: httpx.AsyncClient) -> None:
    client = ArxivClient(http=arxiv_http)
    results = await client.search("spike learning", max_results=5)
    p = results[0]
    assert p.title == "Spike-based learning"
    assert p.authors == ["Jones A"]
    assert p.year == 2024


@pytest.mark.asyncio
async def test_arxiv_search_abstract_and_url(arxiv_http: httpx.AsyncClient) -> None:
    client = ArxivClient(http=arxiv_http)
    results = await client.search("spike learning", max_results=5)
    p = results[0]
    assert p.abstract == "We study spike-based learning."
    assert p.url is not None
    assert "arxiv.org" in p.url


@pytest.mark.asyncio
async def test_arxiv_search_doi_is_none_when_absent(arxiv_http: httpx.AsyncClient) -> None:
    """arXiv atom feed rarely carries a DOI link; must default to None."""
    client = ArxivClient(http=arxiv_http)
    results = await client.search("spike learning", max_results=5)
    assert results[0].doi is None


@pytest.mark.asyncio
async def test_arxiv_search_venue_is_none(arxiv_http: httpx.AsyncClient) -> None:
    client = ArxivClient(http=arxiv_http)
    results = await client.search("spike learning", max_results=5)
    assert results[0].venue is None


# ---------------------------------------------------------------------------
# search() — robustness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_arxiv_search_empty_feed_returns_empty_list() -> None:
    body = b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
    transport = MockTransport({"export.arxiv.org": (200, body, "application/atom+xml")})
    http = httpx.AsyncClient(transport=transport, base_url="https://export.arxiv.org")
    client = ArxivClient(http=http)
    results = await client.search("nothing here")
    assert results == []


@pytest.mark.asyncio
async def test_arxiv_search_missing_author_defaults_to_empty_list() -> None:
    body = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2402.00001v1</id>
    <title>No-author paper</title>
    <published>2024-02-01T00:00:00Z</published>
    <summary>Abstract text.</summary>
    <link rel="alternate" href="https://arxiv.org/abs/2402.00001"/>
  </entry>
</feed>"""
    transport = MockTransport({"export.arxiv.org": (200, body, "application/atom+xml")})
    http = httpx.AsyncClient(transport=transport, base_url="https://export.arxiv.org")
    client = ArxivClient(http=http)
    results = await client.search("no author")
    assert results[0].authors == []


# ---------------------------------------------------------------------------
# fetch_by_id()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_arxiv_fetch_by_id_returns_paper_result() -> None:
    body = FIXTURES.joinpath("arxiv_search.xml").read_bytes()
    transport = MockTransport({"export.arxiv.org": (200, body, "application/atom+xml")})
    http = httpx.AsyncClient(transport=transport, base_url="https://export.arxiv.org")
    client = ArxivClient(http=http)
    result = await client.fetch_by_id("arxiv:2401.00001")
    assert result is not None
    assert "2401.00001" in result.external_id


@pytest.mark.asyncio
async def test_arxiv_fetch_by_id_empty_feed_returns_none() -> None:
    body = b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
    transport = MockTransport({"export.arxiv.org": (200, body, "application/atom+xml")})
    http = httpx.AsyncClient(transport=transport, base_url="https://export.arxiv.org")
    client = ArxivClient(http=http)
    result = await client.fetch_by_id("arxiv:9999.00000")
    assert result is None
