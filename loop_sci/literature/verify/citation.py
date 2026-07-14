"""Ordered, short-circuiting citation verification pipeline.

Layers
------
L1 — **Format**: the citation has a resolvable identifier.
     A ``SourceRef`` with a *known* source adapter OR a non-empty ``doi`` passes
     L1; a fact whose source is not registered AND has no doi has no resolution
     path and fails here.

L2 — **Existence**: the identifier resolves to a *real* paper via
     ``SearchClient.fetch_by_id``.  This is the anti-fabrication core: a
     hallucinated DOI/paper that returns ``None`` is rejected here.

L3 — **Metadata match**: the fact's optional expected metadata
     (``expected_year``, ``expected_authors``) is checked against the resolved
     paper.
     * Year: exact match (when ``expected_year`` is provided).
     * Authors: at least one surname from the expected list overlaps the actual
       author surnames (when ``expected_authors`` is provided).
     * Venue: not checked yet (reserved for future tolerance logic).

L4 — **Content-grounding** (Task 7): slots in cleanly after L3 via the hook
     point at the end of ``verify_layers_123``.  Task 7 adds
     ``verify_layers_1234`` or updates the status returned here; the L1-L3
     logic is untouched.

Short-circuit semantics
-----------------------
Execution stops at the first failure.  ``VerificationStatus.layer_reached``
records *which* layer was the last executed; ``status`` records the outcome.

A citation that passes all three layers here gets ``status="pending_l4"`` and
``layer_reached=3``, signalling that L4 (content-grounding, Task 7) has not
yet been run.

Design for L4 extension
-----------------------
To add L4, Task 7 should:
1. Create ``verify_layers_1234(fact)`` that calls ``verify_layers_123`` first,
   then runs L4 only if the result is ``status="pending_l4"``.
2. Alternatively, the pipeline can expose ``verify_layer_4(fact, paper)`` as a
   separate method and chain them in the caller.
Either way, L1-L3 code here does not need modification.
"""
from __future__ import annotations

import logging
from typing import Any

from loop_sci.literature.extract.fact import Fact, VerificationStatus
from loop_sci.literature.search.schema import PaperResult

log = logging.getLogger(__name__)


class VerificationPipeline:
    """Ordered, short-circuiting L1–L3 citation verification pipeline.

    Parameters
    ----------
    search_clients:
        Mapping from adapter name (e.g. ``"semantic_scholar"``, ``"pubmed"``) to
        a ``SearchClient`` instance.  Must satisfy the ``SearchClient`` protocol
        (has ``search`` and ``fetch_by_id`` methods).  Tests pass a
        ``MockSearchClient`` so all checks run offline.
    """

    def __init__(self, search_clients: dict[str, Any]) -> None:
        self._clients = search_clients

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def verify_layers_123(self, fact: Fact) -> VerificationStatus:
        """Run L1 → L2 → L3 in order, short-circuiting on the first failure.

        Parameters
        ----------
        fact:
            The ``Fact`` to verify.  ``fact.source_ref`` provides the
            identifier; optional attributes ``fact.expected_year`` (int) and
            ``fact.expected_authors`` (list[str]) provide L3 constraints.

        Returns
        -------
        VerificationStatus
            ``layer_reached`` is 1, 2, or 3.  ``status`` is one of:
            * ``"failed"``   — L1: no resolvable identifier path exists.
            * ``"rejected"`` — L2: paper not found; or L3: metadata mismatch.
            * ``"pending_l4"`` — passed L1-L3; awaiting L4 (content-grounding).
        """
        ref = fact.source_ref

        # -- L1: format / resolvability -----------------------------------
        if not self._has_resolvable_identifier(ref):
            return VerificationStatus(
                layer_reached=1,
                status="failed",
                detail=(
                    f"no resolvable identifier: source={ref.source!r} not registered "
                    "and no doi present"
                ),
            )

        # -- L2: existence ------------------------------------------------
        paper = await self._resolve(ref)
        if paper is None:
            return VerificationStatus(
                layer_reached=2,
                status="rejected",
                detail=f"paper not found via API for id={ref.external_id!r}",
            )

        # -- L3: metadata match -------------------------------------------
        ok, detail = _check_metadata(fact, paper)
        if not ok:
            return VerificationStatus(
                layer_reached=3,
                status="rejected",
                detail=detail,
            )

        # Passed L1-L3 — pending L4 (content-grounding, Task 7)
        return VerificationStatus(
            layer_reached=3,
            status="pending_l4",
            detail=f"resolved:{paper.external_id}",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _has_resolvable_identifier(self, ref: Any) -> bool:
        """L1 check: is there a route to look this citation up?

        Passes when:
        * The ``source`` field names a registered client (we have an adapter for it), OR
        * A ``doi`` is present (any client can attempt DOI resolution as fallback).
        """
        if ref.source in self._clients:
            return True
        if getattr(ref, "doi", None):
            return True
        return False

    async def _resolve(self, ref: Any) -> PaperResult | None:
        """L2 resolution: attempt to fetch the paper via the registered adapter.

        Strategy:
        1. If the source adapter is registered, call ``fetch_by_id(external_id)``.
        2. If not registered but a DOI is present, try every available client.
        3. Return ``None`` if all attempts fail (paper hallucinated or unreachable).
        """
        source = getattr(ref, "source", "")
        external_id = getattr(ref, "external_id", "")
        doi = getattr(ref, "doi", None)

        # Primary: use source-specific adapter
        client = self._clients.get(source)
        if client is not None:
            try:
                result = await client.fetch_by_id(external_id)
                if result is not None:
                    return result
            except Exception as exc:
                log.warning("fetch_by_id failed for %s/%s: %s", source, external_id, exc)

        # Fallback: try all adapters with the DOI
        if doi:
            for adapter_name, c in self._clients.items():
                try:
                    result = await c.fetch_by_id(doi)
                    if result is not None:
                        log.debug(
                            "DOI fallback resolved via %s: %s", adapter_name, doi
                        )
                        return result
                except Exception as exc:
                    log.warning(
                        "DOI fallback fetch_by_id failed via %s: %s", adapter_name, exc
                    )

        return None


# ---------------------------------------------------------------------------
# L3 metadata helpers
# ---------------------------------------------------------------------------


def _check_metadata(fact: Fact, paper: PaperResult) -> tuple[bool, str]:
    """Check that the resolved paper's metadata matches the fact's expectations.

    Checks performed (when the corresponding hint is present on the fact):
    * ``expected_year``: exact integer match against ``paper.year``.
    * ``expected_authors``: at least one surname overlap between the expected
      author list and the actual author list.

    Returns
    -------
    (ok, detail)
        ``ok=True`` means all checks passed; ``detail`` is empty.
        ``ok=False`` carries a human-readable explanation.
    """
    # Year: exact match (only when a hint is provided)
    expected_year: int | None = getattr(fact, "expected_year", None)
    if expected_year is not None and paper.year is not None:
        if paper.year != int(expected_year):
            return False, (
                f"year mismatch: expected {expected_year}, got {paper.year}"
            )

    # Authors: surname overlap (only when a hint is provided)
    expected_authors: list[str] | None = getattr(fact, "expected_authors", None)
    if expected_authors is not None:
        actual_surnames = {_surname(a).lower() for a in paper.authors}
        expected_surnames = {_surname(a).lower() for a in expected_authors}
        overlap = actual_surnames & expected_surnames
        if not overlap:
            return False, (
                f"author mismatch: no surname overlap between "
                f"expected={sorted(expected_surnames)!r} "
                f"and actual={sorted(actual_surnames)!r}"
            )

    return True, ""


def _surname(author_name: str) -> str:
    """Extract the surname from an author name string.

    Handles common formats:
    * ``"Smith J"``  → ``"Smith"``
    * ``"J Smith"``  → ``"Smith"``
    * ``"Smith"``    → ``"Smith"``
    * ``"Smith, J."`` → ``"Smith"``

    Strategy: the surname is the longest token.
    """
    # Strip punctuation and split
    name = author_name.replace(",", " ").replace(".", " ")
    tokens = [t.strip() for t in name.split() if t.strip()]
    if not tokens:
        return author_name
    # Return the longest token (surnames are usually longer than initials)
    return max(tokens, key=len)
