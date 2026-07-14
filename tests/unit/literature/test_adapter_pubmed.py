"""Tests for PubMed adapter (two-hop: esearch → efetch).

TDD: tests are written BEFORE production code — must fail (RED) first.
All HTTP is intercepted offline via a URL-routing MockTransport that
dispatches esearch.fcgi and efetch.fcgi to separate canned responses,
verifying the two-hop logic without any real network calls.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from loop_sci.literature.search.pubmed import PubMedClient, _article_to_paper
from loop_sci.literature.search.schema import PaperResult

FIXTURES = Path(__file__).parent / "fixtures"


class MockTransport(httpx.AsyncBaseTransport):
    """Routes requests to canned responses by matching URL substrings.

    The PubMed adapter makes two distinct calls:
      1.  ...esearch.fcgi?... → JSON list of PMIDs
      2.  ...efetch.fcgi?...  → XML article records

    Keying on the .fcgi endpoint name reliably distinguishes the two hops
    without coupling tests to exact query-string ordering.
    """

    def __init__(self, responses: dict[str, tuple[int, bytes, str]]) -> None:
        self._responses = responses

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for prefix, (status, body, ctype) in self._responses.items():
            if prefix in url:
                return httpx.Response(status, content=body, headers={"content-type": ctype})
        return httpx.Response(404, content=b"not found")


@pytest.fixture
def pubmed_http() -> httpx.AsyncClient:
    esearch_body = FIXTURES.joinpath("pubmed_esearch.json").read_bytes()
    efetch_body = FIXTURES.joinpath("pubmed_efetch.xml").read_bytes()
    transport = MockTransport(
        {
            "esearch.fcgi": (200, esearch_body, "application/json"),
            "efetch.fcgi": (200, efetch_body, "application/xml"),
        }
    )
    return httpx.AsyncClient(
        transport=transport, base_url="https://eutils.ncbi.nlm.nih.gov"
    )


# ---------------------------------------------------------------------------
# search() — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pubmed_search_returns_list_of_paper_results(pubmed_http: httpx.AsyncClient) -> None:
    client = PubMedClient(http=pubmed_http, email="test@example.com", tool="loop-sci-test")
    results = await client.search("cortical attention", max_results=5)
    assert len(results) == 1
    assert all(isinstance(p, PaperResult) for p in results)


@pytest.mark.asyncio
async def test_pubmed_search_source_field(pubmed_http: httpx.AsyncClient) -> None:
    client = PubMedClient(http=pubmed_http, email="test@example.com", tool="loop-sci-test")
    results = await client.search("cortical attention", max_results=5)
    assert results[0].source == "pubmed"


@pytest.mark.asyncio
async def test_pubmed_search_external_id(pubmed_http: httpx.AsyncClient) -> None:
    client = PubMedClient(http=pubmed_http, email="test@example.com", tool="loop-sci-test")
    results = await client.search("cortical attention", max_results=5)
    assert results[0].external_id == "pubmed:38000001"


@pytest.mark.asyncio
async def test_pubmed_search_title(pubmed_http: httpx.AsyncClient) -> None:
    client = PubMedClient(http=pubmed_http, email="test@example.com", tool="loop-sci-test")
    results = await client.search("cortical attention", max_results=5)
    assert results[0].title == "Cortical circuits for attention"


@pytest.mark.asyncio
async def test_pubmed_search_authors(pubmed_http: httpx.AsyncClient) -> None:
    client = PubMedClient(http=pubmed_http, email="test@example.com", tool="loop-sci-test")
    results = await client.search("cortical attention", max_results=5)
    assert results[0].authors == ["Wang"]


@pytest.mark.asyncio
async def test_pubmed_search_year_and_venue(pubmed_http: httpx.AsyncClient) -> None:
    client = PubMedClient(http=pubmed_http, email="test@example.com", tool="loop-sci-test")
    results = await client.search("cortical attention", max_results=5)
    p = results[0]
    assert p.year == 2023
    assert p.venue == "Nature Neuroscience"


@pytest.mark.asyncio
async def test_pubmed_search_abstract(pubmed_http: httpx.AsyncClient) -> None:
    client = PubMedClient(http=pubmed_http, email="test@example.com", tool="loop-sci-test")
    results = await client.search("cortical attention", max_results=5)
    assert results[0].abstract == "We map cortical circuits."


@pytest.mark.asyncio
async def test_pubmed_search_url_contains_pmid(pubmed_http: httpx.AsyncClient) -> None:
    client = PubMedClient(http=pubmed_http, email="test@example.com", tool="loop-sci-test")
    results = await client.search("cortical attention", max_results=5)
    p = results[0]
    assert p.url is not None
    assert "38000001" in p.url


# ---------------------------------------------------------------------------
# search() — robustness: esearch returns empty idlist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pubmed_search_empty_idlist_returns_empty_list() -> None:
    esearch_body = b'{"esearchresult": {"idlist": []}}'
    # efetch should never be called, but we provide it for completeness
    efetch_body = b"<PubmedArticleSet/>"
    transport = MockTransport(
        {
            "esearch.fcgi": (200, esearch_body, "application/json"),
            "efetch.fcgi": (200, efetch_body, "application/xml"),
        }
    )
    http = httpx.AsyncClient(transport=transport, base_url="https://eutils.ncbi.nlm.nih.gov")
    client = PubMedClient(http=http, email="test@example.com", tool="loop-sci-test")
    results = await client.search("nonexistent query")
    assert results == []


# ---------------------------------------------------------------------------
# Two-hop routing verification: esearch and efetch go to different URLs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pubmed_search_makes_two_http_calls() -> None:
    """Verify the adapter actually issues two HTTP requests (esearch then efetch)."""
    captured_urls: list[str] = []

    class CapturingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            captured_urls.append(url)
            if "esearch.fcgi" in url:
                body = b'{"esearchresult": {"idlist": ["38000001"]}}'
                return httpx.Response(200, content=body, headers={"content-type": "application/json"})
            if "efetch.fcgi" in url:
                body = FIXTURES.joinpath("pubmed_efetch.xml").read_bytes()
                return httpx.Response(200, content=body, headers={"content-type": "application/xml"})
            return httpx.Response(404, content=b"")

    http = httpx.AsyncClient(transport=CapturingTransport(), base_url="https://eutils.ncbi.nlm.nih.gov")
    client = PubMedClient(http=http, email="test@example.com", tool="loop-sci-test")
    results = await client.search("cortical attention")
    assert len(captured_urls) == 2
    assert any("esearch.fcgi" in u for u in captured_urls)
    assert any("efetch.fcgi" in u for u in captured_urls)
    assert len(results) == 1


# ---------------------------------------------------------------------------
# tool and email params are sent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pubmed_tool_and_email_in_esearch_request() -> None:
    captured: list[httpx.Request] = []

    class CapturingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "esearch.fcgi" in str(request.url):
                return httpx.Response(
                    200,
                    content=b'{"esearchresult": {"idlist": []}}',
                    headers={"content-type": "application/json"},
                )
            return httpx.Response(404, content=b"")

    http = httpx.AsyncClient(transport=CapturingTransport(), base_url="https://eutils.ncbi.nlm.nih.gov")
    client = PubMedClient(http=http, email="tester@lab.edu", tool="my-tool")
    await client.search("test")
    assert len(captured) >= 1
    esearch_req = next(r for r in captured if "esearch.fcgi" in str(r.url))
    params = dict(esearch_req.url.params)
    assert params.get("email") == "tester@lab.edu"
    assert params.get("tool") == "my-tool"


# ---------------------------------------------------------------------------
# fetch_by_id()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pubmed_fetch_by_id_returns_paper_result(pubmed_http: httpx.AsyncClient) -> None:
    client = PubMedClient(http=pubmed_http, email="test@example.com", tool="loop-sci-test")
    # fetch_by_id skips esearch and calls efetch directly
    result = await client.fetch_by_id("pubmed:38000001")
    assert result is not None
    assert result.external_id == "pubmed:38000001"
    assert result.title == "Cortical circuits for attention"


@pytest.mark.asyncio
async def test_pubmed_fetch_by_id_missing_article_returns_none() -> None:
    efetch_body = b"<PubmedArticleSet/>"
    transport = MockTransport({"efetch.fcgi": (200, efetch_body, "application/xml")})
    http = httpx.AsyncClient(transport=transport, base_url="https://eutils.ncbi.nlm.nih.gov")
    client = PubMedClient(http=http, email="test@example.com", tool="loop-sci-test")
    result = await client.fetch_by_id("pubmed:99999999")
    assert result is None


# ---------------------------------------------------------------------------
# Fix 2 — malformed-entry-skipped for PubMed: one article crashes _article_to_paper;
#          the valid sibling must survive; no exception propagates.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pubmed_malformed_article_skipped_sibling_survives(
    pubmed_http: httpx.AsyncClient,
) -> None:
    """Simulate a crash in _article_to_paper for the FIRST article by patching it
    to raise RuntimeError on the first call and delegate normally on subsequent calls.
    The valid second article must appear in results without any exception.
    """
    efetch_body = b"""<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation><PMID>99000001</PMID>
      <Article><ArticleTitle>Crasher article</ArticleTitle></Article>
    </MedlineCitation>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation><PMID>38000001</PMID>
      <Article>
        <ArticleTitle>Valid sibling article</ArticleTitle>
        <Abstract><AbstractText>Good abstract.</AbstractText></Abstract>
        <AuthorList><Author><LastName>Lee</LastName></Author></AuthorList>
        <Journal>
          <Title>Nature</Title>
          <JournalIssue><PubDate><Year>2023</Year></PubDate></JournalIssue>
        </Journal>
      </Article>
    </MedlineCitation>
    <PubmedData><ArticleIdList>
      <ArticleId IdType="doi">10.1234/valid</ArticleId>
    </ArticleIdList></PubmedData>
  </PubmedArticle>
</PubmedArticleSet>"""

    esearch_body = b'{"esearchresult": {"idlist": ["99000001", "38000001"]}}'
    transport = MockTransport(
        {
            "esearch.fcgi": (200, esearch_body, "application/json"),
            "efetch.fcgi": (200, efetch_body, "application/xml"),
        }
    )
    http = httpx.AsyncClient(transport=transport, base_url="https://eutils.ncbi.nlm.nih.gov")
    client = PubMedClient(http=http, email="test@example.com", tool="loop-sci-test")

    call_count = 0
    real_article_to_paper = _article_to_paper

    def _crashing_first_call(article):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Simulated crash in _article_to_paper")
        return real_article_to_paper(article)

    with patch("loop_sci.literature.search.pubmed._article_to_paper", side_effect=_crashing_first_call):
        results = await client.search("anything")

    # Malformed entry skipped; valid sibling returned
    assert len(results) == 1
    assert results[0].external_id == "pubmed:38000001"
    assert results[0].title == "Valid sibling article"
