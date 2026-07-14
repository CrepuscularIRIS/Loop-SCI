"""PubMed search adapter (E-utilities, two-hop: esearch → efetch).

Maps NCBI E-utilities responses to the unified ``PaperResult`` schema.

Usage
-----
::

    import httpx
    from loop_sci.literature.search.client import make_async_client
    from loop_sci.literature.search.pubmed import PubMedClient

    async with make_async_client() as http:
        client = PubMedClient(http=http, email="you@example.com", tool="my-app")
        papers = await client.search("cortical circuits attention", max_results=20)

API notes (E-utilities)
-----------------------
- **esearch.fcgi**: Converts a text query to a list of PMIDs (JSON by default).
- **efetch.fcgi**: Fetches full records for a list of PMIDs (XML format).
- NCBI policy requires ``tool`` and ``email`` query parameters on every call;
  omitting them risks being blocked.
- Both endpoints live under ``https://eutils.ncbi.nlm.nih.gov/entrez/eutils/``.
- ``retmode=json`` applies only to esearch; efetch must use ``rettype=xml``.
- DOI may appear in ``<ArticleId IdType="doi">``; surfaced when present.

Two-hop routing (offline tests)
--------------------------------
The MockTransport in tests distinguishes the two hops by URL substring:
``"esearch.fcgi"`` and ``"efetch.fcgi"`` are disjoint, so routing is
unambiguous without coupling to query-string ordering.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

import httpx

from .schema import PaperResult

logger = logging.getLogger(__name__)

_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class PubMedClient:
    """Adapter for NCBI PubMed via the E-utilities REST API.

    Parameters
    ----------
    http:
        An ``httpx.AsyncClient`` instance (from :func:`.make_async_client`).
        Tests inject a ``MockTransport``; production passes the default transport.
    email:
        Required by NCBI policy — identifies the calling application.
    tool:
        Tool name forwarded to NCBI; defaults to ``"loop-sci"``.
    """

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        email: str,
        tool: str = "loop-sci",
    ) -> None:
        self._http = http
        self._base_params: dict[str, str] = {"tool": tool, "email": email}

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        """Return up to *max_results* papers matching *query*.

        Executes two HTTP calls:
        1. esearch.fcgi — converts *query* to a list of PMIDs.
        2. efetch.fcgi  — fetches full XML records for those PMIDs.

        An empty idlist short-circuits before step 2 and returns ``[]``.
        Malformed article records are skipped gracefully.
        """
        pmids = await self._esearch(query, max_results=max_results)
        if not pmids:
            return []
        return await self._fetch_many(pmids)

    async def fetch_by_id(self, external_id: str) -> PaperResult | None:
        """Fetch a single paper by its PubMed ID.

        *external_id* must be in the ``"pubmed:<PMID>"`` form produced by this
        adapter.  Returns ``None`` when no matching article record is found.
        """
        pmid = external_id.removeprefix("pubmed:")
        results = await self._fetch_many([pmid])
        return results[0] if results else None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _esearch(self, query: str, *, max_results: int) -> list[str]:
        """Hop 1: convert *query* to a list of PubMed IDs."""
        r = await self._http.get(
            f"{_EUTILS}/esearch.fcgi",
            params={
                **self._base_params,
                "db": "pubmed",
                "term": query,
                "retmax": max_results,
                "retmode": "json",
            },
        )
        r.raise_for_status()
        return r.json()["esearchresult"]["idlist"]

    async def _fetch_many(self, pmids: list[str]) -> list[PaperResult]:
        """Hop 2: fetch full XML records for a list of PMIDs."""
        r = await self._http.get(
            f"{_EUTILS}/efetch.fcgi",
            params={
                **self._base_params,
                "db": "pubmed",
                "id": ",".join(pmids),
                "rettype": "xml",
                "retmode": "xml",
            },
        )
        r.raise_for_status()
        root = ET.fromstring(r.content)
        results: list[PaperResult] = []
        for article in root.findall(".//PubmedArticle"):
            try:
                results.append(_article_to_paper(article))
            except Exception:
                logger.warning("Skipping malformed PubMed article")
        return results


# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------


def _article_to_paper(article: ET.Element) -> PaperResult:
    """Map a single ``<PubmedArticle>`` element to :class:`PaperResult`."""
    pmid = (article.findtext(".//PMID") or "").strip()
    title = (article.findtext(".//ArticleTitle") or "").strip()
    abstract = (article.findtext(".//AbstractText") or "").strip()

    authors: list[str] = [
        last_name
        for author in article.findall(".//Author")
        if (last_name := (author.findtext("LastName") or "").strip())
    ]

    year_text = (article.findtext(".//PubDate/Year") or "").strip()
    year: int | None = int(year_text) if year_text.isdigit() else None

    venue: str | None = article.findtext(".//Journal/Title") or None

    # DOI may appear in <ArticleIdList>
    doi: str | None = None
    for aid in article.findall(".//ArticleId"):
        if aid.get("IdType") == "doi":
            doi = (aid.text or "").strip() or None
            break

    return PaperResult(
        source="pubmed",
        external_id=f"pubmed:{pmid}",
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        abstract=abstract or None,
        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None,
        doi=doi,
    )
