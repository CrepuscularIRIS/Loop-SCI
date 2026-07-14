"""ToolRegistry registrations for the literature-mining sub-system.

Exposes ``register_literature_tools`` which wires the Task 1-9 components
(search dispatch, fact extractor, 4-layer verification pipeline) into a
:class:`~loop_sci.engine.tools.ToolRegistry` as four agent-callable tools:

- ``lit_search``   — fan-out keyword search across configured adapters.
- ``lit_fetch``    — fetch a single paper by source + external_id.
- ``lit_extract``  — extract structured facts from a paper's abstract text.
- ``lit_verify``   — run 4-layer citation verification on a claim/source triple.

Design decisions
----------------
* **Dependency injection**: all collaborators (search_clients, extractor,
  pipeline) are injected at registration time, not imported globally.  This
  keeps the tools testable offline with mocks.
* **Return contract**: every tool function returns a JSON-serialised string so
  the ToolRegistry ``dispatch`` contract (always returns ``str``) is satisfied.
  Errors surface as a serialisable ``{"error": ...}`` payload rather than a
  raised exception — the ToolRegistry already wraps remaining exceptions too.
* **No coupling to internals**: only the public interfaces of each Task 1-9
  component are called here (``dispatch``, ``FactExtractor.extract``,
  ``VerificationPipeline.verify``, ``client.fetch_by_id``).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from loop_sci.engine.tools import ToolRegistry

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public registration helper
# ---------------------------------------------------------------------------


def register_literature_tools(
    registry: ToolRegistry,
    *,
    search_clients: dict[str, Any],
    extractor: Any,
    pipeline: Any,
) -> None:
    """Register lit_search, lit_fetch, lit_extract, and lit_verify into *registry*.

    Parameters
    ----------
    registry:
        The foundation :class:`~loop_sci.engine.tools.ToolRegistry` instance.
    search_clients:
        Mapping of adapter name → ``SearchClient``-compatible object (must
        have ``async search(query, *, max_results)`` and
        ``async fetch_by_id(eid)`` methods).
    extractor:
        A :class:`~loop_sci.literature.extract.extractor.FactExtractor`
        (or mock) with ``async extract(paper) -> list[Fact]``.
    pipeline:
        A :class:`~loop_sci.literature.verify.citation.VerificationPipeline`
        (or mock) with ``async verify(fact) -> VerificationStatus``.
    """

    # -----------------------------------------------------------------------
    # lit_search
    # -----------------------------------------------------------------------

    async def _search(query: str, sources: list[str] | None = None) -> str:
        """Fan-out search across *sources* (or all configured if omitted)."""
        from loop_sci.literature.search.dispatch import dispatch as search_dispatch

        clients: dict[str, Any]
        if sources is None:
            clients = search_clients
        else:
            clients = {k: v for k, v in search_clients.items() if k in sources}

        papers = await search_dispatch(query, clients)
        return json.dumps({
            "papers": [
                {
                    "source": p.source,
                    "external_id": p.external_id,
                    "title": p.title,
                    "authors": p.authors,
                    "year": p.year,
                    "abstract": p.abstract,
                    "url": p.url,
                }
                for p in papers
            ]
        })

    # -----------------------------------------------------------------------
    # lit_fetch
    # -----------------------------------------------------------------------

    async def _fetch(external_id: str, source: str) -> str:
        """Fetch a single paper by *external_id* from the named *source* adapter."""
        client = search_clients.get(source)
        if client is None:
            return json.dumps({"error": f"unknown source: {source!r}"})

        paper = await client.fetch_by_id(external_id)
        if paper is None:
            return json.dumps({"error": "paper not found", "external_id": external_id})

        return json.dumps({
            "source": paper.source,
            "external_id": paper.external_id,
            "title": paper.title,
            "authors": paper.authors,
            "year": paper.year,
            "venue": paper.venue,
            "abstract": paper.abstract,
            "url": paper.url,
        })

    # -----------------------------------------------------------------------
    # lit_extract
    # -----------------------------------------------------------------------

    async def _extract(external_id: str, source: str, abstract: str) -> str:
        """Extract structured facts from a paper's *abstract* text."""
        from loop_sci.literature.search.schema import PaperResult

        paper = PaperResult(
            source=source,
            external_id=external_id,
            title="",
            authors=[],
            year=None,
            venue=None,
            abstract=abstract,
            url=None,
        )
        facts = await extractor.extract(paper)
        return json.dumps({
            "facts": [
                {
                    "claim": f.claim,
                    "evidence_span": f.evidence_span,
                    "confidence": f.confidence,
                    "entities": f.entities,
                }
                for f in facts
            ]
        })

    # -----------------------------------------------------------------------
    # lit_verify
    # -----------------------------------------------------------------------

    async def _verify(
        claim: str,
        source_ref: dict[str, Any],
        evidence_span: str,
        grounding_scope: str = "abstract",
    ) -> str:
        """Run 4-layer citation verification on a claim/source/evidence triple."""
        from loop_sci.literature.extract.fact import Fact, SourceRef

        ref = SourceRef(
            source=source_ref.get("source", ""),
            external_id=source_ref.get("external_id", ""),
            doi=source_ref.get("doi"),
        )
        fact = Fact(
            claim=claim,
            source_ref=ref,
            evidence_span=evidence_span,
            confidence=0.5,
            grounding_scope=grounding_scope,
        )
        status = await pipeline.verify(fact)
        return json.dumps({
            "layer_reached": status.layer_reached,
            "status": status.status,
            "detail": status.detail,
        })

    # -----------------------------------------------------------------------
    # Register all four tools
    # -----------------------------------------------------------------------

    registry.register(
        name="lit_search",
        description=(
            "Search scholarly literature across configured adapters "
            "(semantic_scholar, arxiv, pubmed). Returns a list of papers with "
            "title, authors, year, abstract, and source metadata."
        ),
        schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Free-text search query.",
                },
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Adapter names to query (e.g. ['semantic_scholar']). "
                        "Omit to query all configured adapters."
                    ),
                },
            },
            "required": ["query"],
        },
        fn=_search,
    )

    registry.register(
        name="lit_fetch",
        description=(
            "Fetch a specific paper by external_id from a named source adapter. "
            "Returns the paper's metadata (title, abstract, year, authors, etc.)."
        ),
        schema={
            "type": "object",
            "properties": {
                "external_id": {
                    "type": "string",
                    "description": "Source-scoped paper identifier (e.g. 's2:abc').",
                },
                "source": {
                    "type": "string",
                    "description": "Adapter name (e.g. 'semantic_scholar').",
                },
            },
            "required": ["external_id", "source"],
        },
        fn=_fetch,
    )

    registry.register(
        name="lit_extract",
        description=(
            "Extract structured scientific facts from a paper's abstract text. "
            "Returns a list of facts, each with claim, evidence_span, and confidence."
        ),
        schema={
            "type": "object",
            "properties": {
                "external_id": {
                    "type": "string",
                    "description": "Source-scoped paper identifier.",
                },
                "source": {
                    "type": "string",
                    "description": "Adapter name the paper came from.",
                },
                "abstract": {
                    "type": "string",
                    "description": "Abstract text to extract facts from.",
                },
            },
            "required": ["external_id", "source", "abstract"],
        },
        fn=_extract,
    )

    registry.register(
        name="lit_verify",
        description=(
            "Run 4-layer citation verification on a claim + source + evidence triple. "
            "Layers: L1 format, L2 existence, L3 metadata match, L4 content grounding. "
            "Returns layer_reached, status (verified/rejected/failed/pending_l4), and detail."
        ),
        schema={
            "type": "object",
            "properties": {
                "claim": {
                    "type": "string",
                    "description": "The scientific claim to verify.",
                },
                "source_ref": {
                    "type": "object",
                    "description": (
                        "Paper reference with 'source' (adapter name), "
                        "'external_id', and optional 'doi'."
                    ),
                    "properties": {
                        "source": {"type": "string"},
                        "external_id": {"type": "string"},
                        "doi": {"type": "string"},
                    },
                    "required": ["source", "external_id"],
                },
                "evidence_span": {
                    "type": "string",
                    "description": "Verbatim quote from the source that grounds the claim.",
                },
                "grounding_scope": {
                    "type": "string",
                    "enum": ["abstract", "full_text"],
                    "description": "Which part of the paper was used as evidence.",
                },
            },
            "required": ["claim", "source_ref", "evidence_span"],
        },
        fn=_verify,
    )
