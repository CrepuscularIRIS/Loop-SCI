"""Semantic Scholar search adapter.

Maps the Semantic Scholar Graph API (graph.api.semanticscholar.org/graph/v1)
responses to the unified ``PaperResult`` schema.

Usage
-----
::

    import httpx
    from loop_sci.literature.search.client import make_async_client
    from loop_sci.literature.search.semantic_scholar import SemanticScholarClient

    async with make_async_client() as http:
        client = SemanticScholarClient(http=http)
        papers = await client.search("spiking neural networks", max_results=20)

API notes
---------
- Endpoint: GET /graph/v1/paper/search (search) and /graph/v1/paper/{id} (lookup)
- Optional ``x-api-key`` header raises rate limits from 1 req/s to 10 req/s.
- ``externalIds`` may carry DOI, ArXiv, PubMed, etc.; we surface only DOI.
- ``url`` is a canonical link to the Semantic Scholar paper page.
"""
from __future__ import annotations

import logging

import httpx

from .schema import PaperResult

logger = logging.getLogger(__name__)

_BASE = "https://graph.api.semanticscholar.org/graph/v1"
_FIELDS = "paperId,externalIds,title,authors,year,venue,abstract,url"


class SemanticScholarClient:
    """Adapter for the Semantic Scholar Graph REST API.

    Parameters
    ----------
    http:
        An ``httpx.AsyncClient`` instance (from :func:`.make_async_client`).
        Tests inject a ``MockTransport``; production passes the default transport.
    api_key:
        Optional Semantic Scholar API key forwarded as ``x-api-key``.
        Raises the unauthenticated rate limit (1 req/s → 10 req/s).
    """

    def __init__(self, http: httpx.AsyncClient, *, api_key: str | None = None) -> None:
        self._http = http
        self._api_key = api_key

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self._api_key} if self._api_key else {}

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        """Return up to *max_results* papers matching *query*.

        Missing or malformed entries in the response are skipped gracefully.
        """
        r = await self._http.get(
            f"{_BASE}/paper/search",
            params={"query": query, "limit": max_results, "fields": _FIELDS},
            headers=self._headers(),
        )
        r.raise_for_status()
        results: list[PaperResult] = []
        for item in r.json().get("data", []):
            try:
                results.append(_to_paper(item))
            except Exception:
                logger.warning("Skipping malformed Semantic Scholar entry: %r", item)
        return results

    async def fetch_by_id(self, external_id: str) -> PaperResult | None:
        """Fetch a single paper by its Semantic Scholar paper ID.

        *external_id* must be in the ``"s2:<paperId>"`` form produced by this
        adapter.  Returns ``None`` when the paper is not found (HTTP 404).
        """
        sid = external_id.removeprefix("s2:")
        r = await self._http.get(
            f"{_BASE}/paper/{sid}",
            params={"fields": _FIELDS},
            headers=self._headers(),
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return _to_paper(r.json())


# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------


def _to_paper(d: dict) -> PaperResult:
    """Map a single Semantic Scholar paper dict to :class:`PaperResult`."""
    eids: dict = d.get("externalIds") or {}
    authors: list[str] = [a["name"] for a in (d.get("authors") or []) if "name" in a]
    return PaperResult(
        source="semantic_scholar",
        external_id=f"s2:{d['paperId']}",
        title=d.get("title") or "",
        authors=authors,
        year=d.get("year"),
        venue=d.get("venue") or None,
        abstract=d.get("abstract") or None,
        url=d.get("url") or None,
        doi=eids.get("DOI") or None,
    )
