"""SearchClient protocol and httpx transport boundary.

Design
------
SearchClient is a *structural* typing.Protocol — adapters implement it by duck
typing, no inheritance required.  This keeps the dependency inversion clean.

The transport boundary is expressed through ``make_async_client``: every adapter
that needs HTTP receives an ``httpx.AsyncClient`` from this factory, injecting
the transport at construction time.  Tests pass ``httpx.MockTransport`` to
intercept all requests offline; production code passes nothing and httpx uses its
default transport (real TCP sockets).

No ``base_url`` is set on the client so adapters can use fully-qualified URLs,
which is required when a single client instance might talk to multiple distinct
API hosts (or when test assertions need to inspect the exact URL sent).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

import httpx

from .schema import PaperResult


@runtime_checkable
class SearchClient(Protocol):
    """Structural protocol that every search adapter must satisfy.

    Adapters are NOT required to inherit from this class — structural
    (duck-type) compatibility is sufficient.  ``@runtime_checkable`` enables
    ``isinstance(obj, SearchClient)`` checks in dispatch code.
    """

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        """Return up to *max_results* papers matching *query*."""
        ...

    async def fetch_by_id(self, external_id: str) -> PaperResult | None:
        """Fetch a single paper by its source-scoped *external_id*.

        Returns None when the paper is not found.
        """
        ...


def make_async_client(
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout: float = 30.0,
    headers: dict[str, str] | None = None,
) -> httpx.AsyncClient:
    """Return an ``httpx.AsyncClient`` with an injectable transport.

    Parameters
    ----------
    transport:
        An ``httpx.AsyncBaseTransport`` implementation.  Pass
        ``httpx.MockTransport(handler)`` in tests to intercept all requests
        without opening any real network connections.  Omit (or pass ``None``)
        in production to use httpx's default async transport.
    timeout:
        Default request timeout in seconds.  Adapters may override per-request.
    headers:
        Optional default headers merged into every request (e.g. User-Agent,
        API key headers).

    Notes
    -----
    No ``base_url`` is set intentionally: adapters issue requests to distinct
    API hosts (api.semanticscholar.org, export.arxiv.org, eutils.ncbi.nlm.nih.gov)
    and must supply fully-qualified URLs.  Setting a base_url would break that.
    """
    kwargs: dict = {"timeout": timeout}
    if transport is not None:
        kwargs["transport"] = transport
    if headers is not None:
        kwargs["headers"] = headers
    return httpx.AsyncClient(**kwargs)
