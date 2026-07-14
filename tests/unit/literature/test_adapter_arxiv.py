"""Tests for arXiv adapter.

TDD: tests are written BEFORE production code — must fail (RED) first.
All HTTP is intercepted offline via MockTransport; no real network calls.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from loop_sci.literature.search.arxiv import ArxivClient, _strip_version
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


# ---------------------------------------------------------------------------
# Fix 1 regression — _strip_version must not corrupt bare numeric / old-style IDs
#
# RED (before fix): the old `rstrip("0123456789")` implementation produced:
#   "http://arxiv.org/abs/2401.00001v2" → "2401."   (stripped all trailing digits)
#   "http://arxiv.org/abs/2401.00001"   → "2401."   (no version, still corrupted)
#   "http://arxiv.org/abs/cs/0501001"   → "cs/"     (all digits stripped)
# GREEN (after fix): anchored `re.sub(r"v\d+$", "", ...)` only removes a genuine vN suffix.
# ---------------------------------------------------------------------------


def test_strip_version_with_version_suffix() -> None:
    """URL with explicit vN suffix → bare arXiv id, version digits removed."""
    assert _strip_version("http://arxiv.org/abs/2401.00001v2") == "2401.00001"


def test_strip_version_without_version_suffix() -> None:
    """URL without vN suffix → bare arXiv id intact, NOT truncated to '2401.'."""
    result = _strip_version("http://arxiv.org/abs/2401.00001")
    assert result == "2401.00001"
    assert not result.endswith(".")  # guard against old rstrip corruption


def test_strip_version_old_style_id() -> None:
    """Old-style cs/NNNNNNN id → path preserved intact, NOT truncated to 'cs/'."""
    result = _strip_version("http://arxiv.org/abs/cs/0501001")
    assert result == "cs/0501001"
    assert result != "cs/"  # guard against old rstrip corruption


def test_strip_version_https_prefix() -> None:
    """https variant is handled the same way as http."""
    assert _strip_version("https://arxiv.org/abs/2310.12345v3") == "2310.12345"


# ---------------------------------------------------------------------------
# Fix 2 — malformed-entry-skipped: a crash-inducing entry is silently dropped;
#          sibling valid entries ARE returned; no exception propagates.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_arxiv_search_malformed_entry_skipped_sibling_survives() -> None:
    """An entry with a non-numeric <published> field crashes _entry_to_paper via
    ValueError in int(published[:4]).  The valid sibling must still be returned
    without any exception propagating.
    """
    body = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <!-- Malformed entry: published is garbage, int("XXXX") raises ValueError -->
  <entry>
    <id>http://arxiv.org/abs/2401.99999v1</id>
    <title>Broken entry bad published date</title>
    <published>XXXX-garbage</published>
    <summary>Will crash on year parse.</summary>
    <link rel="alternate" href="https://arxiv.org/abs/2401.99999"/>
  </entry>
  <!-- Valid sibling -->
  <entry>
    <id>http://arxiv.org/abs/2401.00099v1</id>
    <title>Valid sibling paper</title>
    <published>2024-01-15T00:00:00Z</published>
    <summary>Good abstract.</summary>
    <link rel="alternate" href="https://arxiv.org/abs/2401.00099"/>
    <author><name>Author A</name></author>
  </entry>
</feed>"""
    transport = MockTransport({"export.arxiv.org": (200, body, "application/atom+xml")})
    http = httpx.AsyncClient(transport=transport, base_url="https://export.arxiv.org")
    client = ArxivClient(http=http)
    results = await client.search("test")
    # No exception raised; exactly the valid sibling returned
    assert len(results) == 1
    assert results[0].external_id == "arxiv:2401.00099"
    assert results[0].title == "Valid sibling paper"
