"""arXiv search adapter.

Maps the arXiv Atom API (export.arxiv.org/api/query) responses to the unified
``PaperResult`` schema.

Usage
-----
::

    import httpx
    from loop_sci.literature.search.client import make_async_client
    from loop_sci.literature.search.arxiv import ArxivClient

    async with make_async_client() as http:
        client = ArxivClient(http=http)
        papers = await client.search("spiking neural networks", max_results=20)

API notes
---------
- Endpoint: GET https://export.arxiv.org/api/query
- Response format: Atom XML feed (``application/atom+xml``).
- ``<id>`` looks like ``http://arxiv.org/abs/2401.00001v1``; we strip the
  version suffix and extract the bare arXiv id (e.g. ``2401.00001``).
- DOI is rarely present in Atom entries; defaults to ``None``.
- ``venue`` has no arXiv equivalent; always ``None``.
- Rate limit: 3 requests per second (unauthenticated); no auth required.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

import httpx

from .schema import PaperResult

logger = logging.getLogger(__name__)

_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
_BASE = "https://export.arxiv.org/api/query"


class ArxivClient:
    """Adapter for the arXiv Atom feed API.

    Parameters
    ----------
    http:
        An ``httpx.AsyncClient`` instance (from :func:`.make_async_client`).
        Tests inject a ``MockTransport``; production passes the default transport.
    """

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        """Return up to *max_results* papers matching *query*.

        Malformed entries are skipped; a completely empty feed returns ``[]``.
        """
        r = await self._http.get(
            _BASE,
            params={"search_query": f"all:{query}", "max_results": max_results},
        )
        r.raise_for_status()
        root = ET.fromstring(r.content)
        results: list[PaperResult] = []
        for entry in root.findall("atom:entry", _ATOM_NS):
            try:
                results.append(_entry_to_paper(entry))
            except Exception:
                logger.warning("Skipping malformed arXiv entry")
        return results

    async def fetch_by_id(self, external_id: str) -> PaperResult | None:
        """Fetch a single arXiv paper by its arXiv ID.

        *external_id* must be in the ``"arxiv:<arxivId>"`` form produced by
        this adapter (e.g. ``"arxiv:2401.00001"``).  Returns ``None`` when the
        feed contains no matching entry.
        """
        arxiv_id = external_id.removeprefix("arxiv:")
        r = await self._http.get(_BASE, params={"id_list": arxiv_id})
        r.raise_for_status()
        root = ET.fromstring(r.content)
        entries = root.findall("atom:entry", _ATOM_NS)
        if not entries:
            return None
        return _entry_to_paper(entries[0])


# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------


def _strip_version(raw_id: str) -> str:
    """Strip the trailing version number from an arXiv ``<id>`` value.

    Examples
    --------
    ``"http://arxiv.org/abs/2401.00001v1"`` → ``"2401.00001"``
    ``"http://arxiv.org/abs/2401.00001"``   → ``"2401.00001"``
    """
    # Remove trailing version suffix (v followed by one or more digits)
    bare = raw_id.rstrip("0123456789")
    if bare.endswith("v"):
        bare = bare[:-1]
    return bare.split("/abs/")[-1] if "/abs/" in bare else bare


def _entry_to_paper(entry: ET.Element) -> PaperResult:
    """Map a single Atom ``<entry>`` element to :class:`PaperResult`."""
    ns = _ATOM_NS

    raw_id = entry.findtext("atom:id", namespaces=ns) or ""
    arxiv_id = _strip_version(raw_id)

    authors: list[str] = [
        name
        for author in entry.findall("atom:author", ns)
        if (name := (author.findtext("atom:name", namespaces=ns) or "").strip())
    ]

    published = entry.findtext("atom:published", namespaces=ns) or ""
    year: int | None = int(published[:4]) if len(published) >= 4 else None

    # Prefer the human-readable alternate link; fall back to first link
    link_el = entry.find("atom:link[@rel='alternate']", ns)
    if link_el is None:
        link_el = entry.find("atom:link", ns)
    url: str | None = link_el.get("href") if link_el is not None else None

    title = (entry.findtext("atom:title", namespaces=ns) or "").strip()
    abstract = (entry.findtext("atom:summary", namespaces=ns) or "").strip()

    return PaperResult(
        source="arxiv",
        external_id=f"arxiv:{arxiv_id}",
        title=title,
        authors=authors,
        year=year,
        venue=None,  # arXiv is a preprint server; no venue concept
        abstract=abstract or None,
        url=url,
        doi=None,  # DOI absent in most arXiv Atom entries
    )
