"""Unified PaperResult schema — the canonical record all search adapters map to."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PaperResult:
    """Unified paper record produced by every search adapter.

    All fields are present on every instance so downstream code never needs
    adapter-specific branches.  Optional metadata fields that a source may not
    provide default to None.

    Attributes:
        source: Adapter name — "semantic_scholar" | "arxiv" | "pubmed".
        external_id: Source-scoped identifier, e.g. "s2:abc" or "arxiv:2401.0001".
        title: Paper title (always present).
        authors: Ordered author name list (may be empty if source omits it).
        year: Publication year, or None when unavailable.
        venue: Journal / conference name, or None.
        abstract: Abstract text, or None.
        url: Canonical URL for the paper, or None.
        doi: DOI string (e.g. "10.1038/nature12345"), or None when not available.
    """

    source: str
    external_id: str
    title: str
    authors: list[str]
    year: int | None
    venue: str | None
    abstract: str | None
    url: str | None
    doi: str | None = None
