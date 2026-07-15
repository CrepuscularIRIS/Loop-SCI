"""No-fabrication reference assembler for ResearchPlan.

``collect_references`` is the anti-hallucination core of change #5.  It
produces the ``references`` field of a ``ResearchPlan`` as REAL citations only:

Seed path (always active):
    Resolves each ``fact_id`` in ``hyp.grounding_fact_ids`` against the supplied
    ``facts`` list, then lifts each distinct ``SourceRef`` to a
    ``Reference(verified=True, fact_id=...)`` entry.  These are real by
    construction because the fact-base (#2) only holds verified facts.

Extras path (opt-in, off by default):
    When ``allow_provider_refs=True`` AND ``pipeline`` is set, each dict in
    ``provider_refs`` is wrapped as a ``Fact`` and routed through
    ``await pipeline.verify(fact)``.  Only citations whose status comes back as
    ``"verified"`` are admitted as ``Reference(verified=True, fact_id=None)``.
    All others are silently dropped — never presented as real.

Hard invariant: with ``allow_provider_refs=False`` (the default), the pipeline
is NEVER touched — zero verify round-trips are issued.
"""
from __future__ import annotations

import logging
from typing import Any

from loop_sci.literature.extract.fact import Fact, SourceRef
from loop_sci.literature.verify.citation import VerificationPipeline
from loop_sci.plan.schemas import Reference

log = logging.getLogger(__name__)


async def collect_references(
    hyp: Any,
    facts: list[Fact],
    *,
    provider_refs: list[dict[str, Any]] | None = None,
    allow_provider_refs: bool = False,
    pipeline: VerificationPipeline | None = None,
) -> list[Reference]:
    """Assemble verified references for a research plan.

    Parameters
    ----------
    hyp:
        A ``RankedHypothesis`` whose ``grounding_fact_ids`` field names the
        facts that ground this hypothesis.
    facts:
        All available ``Fact`` objects (e.g. from ``FactStore.all()``).
    provider_refs:
        Optional list of citation dicts proposed by an LLM provider.  Each dict
        must contain at least ``source``, ``external_id``, and ``claim`` keys.
        Ignored unless ``allow_provider_refs=True``.
    allow_provider_refs:
        When ``True``, each ``provider_refs`` dict is routed through
        ``pipeline.verify``; only ``status="verified"`` results are admitted.
        When ``False`` (default), ``provider_refs`` and ``pipeline`` are
        completely ignored — zero verify calls are issued.
    pipeline:
        The ``VerificationPipeline`` to use for extra-ref verification.  Must
        be supplied when ``allow_provider_refs=True``; ignored otherwise.

    Returns
    -------
    list[Reference]
        Deduplicated, all-verified reference list.  Order: seeded refs first
        (in ``grounding_fact_ids`` order), then admitted extras.

    Notes
    -----
    * Deduplication key: ``(source, external_id)``.  The first occurrence wins.
    * Seeded refs are ``verified=True`` by construction (fact-base guarantee).
    * Extras that raise any exception during wrapping or verification are
      skipped without raising (fail-open per extra, fail-safe overall).
    """
    refs: list[Reference] = []
    seen: set[tuple[str, str]] = set()

    # ── Seed path ────────────────────────────────────────────────────────────
    # Build a lookup of fact_id → Fact for quick resolution.
    fact_by_id: dict[str, Fact] = {
        f.fact_id: f for f in facts if f.fact_id is not None
    }

    grounding_fact_ids: list[str] = getattr(hyp, "grounding_fact_ids", []) or []

    for fid in grounding_fact_ids:
        fact = fact_by_id.get(fid)
        if fact is None:
            log.warning("collect_references: grounding fact_id %r not found in facts", fid)
            continue
        sr: SourceRef = fact.source_ref
        key = (sr.source, sr.external_id)
        if key in seen:
            continue
        seen.add(key)
        refs.append(
            Reference(
                source=sr.source,
                external_id=sr.external_id,
                doi=sr.doi,
                verified=True,
                fact_id=fact.fact_id,
            )
        )

    # ── Extras path (opt-in only) ─────────────────────────────────────────────
    # Hard invariant: when flag is OFF, never touch pipeline — zero verify calls.
    if not allow_provider_refs or pipeline is None or not provider_refs:
        return refs

    for ref_dict in provider_refs:
        try:
            source = ref_dict["source"]
            external_id = ref_dict["external_id"]
            doi: str | None = ref_dict.get("doi")
            claim: str = ref_dict.get("claim", "")
            evidence_span: str = ref_dict.get("evidence_span", claim) or claim

            # Wrap the provider dict as a Fact so the pipeline can verify it.
            extra_fact = Fact(
                claim=claim,
                source_ref=SourceRef(source=source, external_id=external_id, doi=doi),
                evidence_span=evidence_span or "unspecified",
                confidence=0.5,
                grounding_scope="abstract",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "collect_references: malformed provider_ref %r — skipping: %s",
                ref_dict,
                exc,
            )
            continue

        try:
            status = await pipeline.verify(extra_fact)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "collect_references: pipeline.verify failed for %r/%r — skipping: %s",
                source,
                external_id,
                exc,
            )
            continue

        if status.status != "verified":
            log.debug(
                "collect_references: extra ref %r/%r dropped (status=%r)",
                source,
                external_id,
                status.status,
            )
            continue

        key = (source, external_id)
        if key in seen:
            continue
        seen.add(key)
        refs.append(
            Reference(
                source=source,
                external_id=external_id,
                doi=doi,
                verified=True,
                fact_id=None,
            )
        )

    return refs
