"""LitMinerExecutor: search → extract → verify → record pipeline with resumability.

Pipeline
--------
For each search query (from the DispatchUnit goal):

1. **Search** — fan out to all configured search clients via ``dispatch()``.
2. **Dedup / Resume** — skip papers already present in the idea-tree (keyed by
   ``external_id``).  This makes ``run()`` idempotent across session restarts.
3. **Extract** — run ``FactExtractor`` on each new paper.
4. **Wire L3 metadata** — before calling ``VerificationPipeline.verify()``, set
   ``fact.expected_year`` and ``fact.expected_authors`` from the source
   ``PaperResult`` so that L3's ``_check_metadata`` can catch mismatches between
   the expected metadata (from the search result) and the actually-resolved paper
   (from ``fetch_by_id``).  This is a dynamic attribute assignment — no structural
   change to the Fact dataclass is required because L3 reads these via ``getattr``
   with a default of ``None``.
5. **Verify** — run the full L1→L2→L3→L4 ``VerificationPipeline.verify()`` pipeline.
6. **Record** — persist verified facts via ``persist_fact()`` (which enforces the
   guard that only verified facts enter the fact base).

Paper-node dedup
----------------
A paper node is created in the idea-tree the first time a paper is processed.
On subsequent calls (same session), the paper's ``external_id`` is found in
``tree._nodes`` (via the ``refs["external_id"]`` field), and the paper is skipped.
This guarantees exactly ONE paper node per unique paper across the run.

Resumability keying
-------------------
Processed papers are tracked by ``external_id`` via the idea-tree.  Any node
whose ``refs["external_id"]`` is set has already been processed.  On ``run()``,
we collect this set first and skip matching papers.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from loop_sci.engine.types import DispatchUnit, ExecutorResult
from loop_sci.literature.extract.extractor import FactExtractor
from loop_sci.literature.factbase.persist import persist_fact
from loop_sci.literature.factbase.store import FactStore
from loop_sci.literature.search.dispatch import dispatch
from loop_sci.literature.verify.citation import VerificationPipeline
from loop_sci.state.idea_tree import Node
from loop_sci.state.session import RunSession

log = logging.getLogger(__name__)

__all__ = ["LitMinerExecutor"]


class LitMinerExecutor:
    """Wires together search → extract → verify → record with resumability.

    Parameters
    ----------
    session:
        The active ``RunSession`` that owns the idea-tree and run cursor.
    search_clients:
        Mapping from adapter name (e.g. ``"semantic_scholar"``) to a
        ``SearchClient``-compatible object (has ``search`` and ``fetch_by_id``).
    extraction_provider:
        An ``LLMProvider``-compatible object for the fact extractor.
    grounding_provider:
        An ``LLMProvider``-compatible object for the L4 grounding judge.
        Pass ``None`` to disable the LLM judge (L4 falls back to lexical).
    store_path:
        File path for the JSON ``FactStore``.  Existing store is loaded on
        construction; new facts are appended atomically.
    max_papers:
        Maximum number of papers to process per ``run()`` call.
    max_facts_per_paper:
        Passed to ``FactExtractor`` — cap on facts per paper.
    grounding_threshold:
        Passed to ``VerificationPipeline`` — midpoint for the L4 fallback path.
    """

    def __init__(
        self,
        session: RunSession,
        *,
        search_clients: dict[str, Any],
        extraction_provider: Any,
        grounding_provider: Any = None,
        store_path: Path,
        max_papers: int = 10,
        max_facts_per_paper: int = 5,
        grounding_threshold: float = 0.3,
    ) -> None:
        self._session = session
        self._clients = search_clients
        self._extractor = FactExtractor(
            extraction_provider, max_facts_per_paper=max_facts_per_paper
        )
        self._pipeline = VerificationPipeline(
            search_clients,
            grounding_provider=grounding_provider,
            grounding_threshold=grounding_threshold,
        )
        self._store = FactStore(Path(store_path))
        self._max_papers = max_papers

    async def run(self, unit: DispatchUnit) -> ExecutorResult:
        """Execute the full search→extract→verify→record pipeline.

        Parameters
        ----------
        unit:
            The ``DispatchUnit`` describing the work.  ``unit.node_id`` is the
            parent node in the idea-tree; ``unit.goal`` is used as the search query.

        Returns
        -------
        ExecutorResult
            ``status="done"`` always (even when no facts are verified).
            ``refs`` contains:
            * ``"verified_facts_count"`` — number of verified facts persisted.
            * ``"skipped_papers_count"`` — papers skipped (already processed).
            * ``"total_papers"`` — total papers returned by search.
        """
        tree = self._session.tree
        topic = unit.goal

        # ── Ensure topic root node exists (idempotent) ─────────────────────────
        topic_node_id = f"topic_{unit.node_id}"
        if topic_node_id not in tree._nodes:
            tree.add_node(
                Node(
                    id=topic_node_id,
                    parent_id=unit.node_id,
                    hypothesis=topic,
                    depth=1,
                    status="pending",
                )
            )

        # ── Search ─────────────────────────────────────────────────────────────
        papers = await dispatch(topic, self._clients, max_results_per_source=self._max_papers)

        # ── Collect already-processed external_ids (resumability) ─────────────
        # Any idea-tree node whose refs["external_id"] is set has already been processed.
        seen_eids: set[str] = {
            n.refs["external_id"]
            for n in tree._nodes.values()
            if n.refs and "external_id" in n.refs
        }

        verified_count = 0
        skipped_count = 0

        for paper in papers[: self._max_papers]:
            # ── Resume guard: skip already-processed papers ────────────────────
            if paper.external_id in seen_eids:
                skipped_count += 1
                log.debug("Skipping already-processed paper: %s", paper.external_id)
                continue

            # ── Create paper node (exactly once per paper) ─────────────────────
            # Node id is deterministic from external_id to guarantee dedup even
            # if tree._nodes is checked before and after an add.
            safe_eid = paper.external_id.replace(":", "_").replace("/", "_")
            paper_node_id = f"paper_{safe_eid}"
            if paper_node_id not in tree._nodes:
                tree.add_node(
                    Node(
                        id=paper_node_id,
                        parent_id=topic_node_id,
                        hypothesis=paper.title or paper.external_id,
                        depth=2,
                        status="pending",
                        refs={
                            "external_id": paper.external_id,
                            "source": paper.source,
                        },
                    )
                )
            # Mark as seen so a second paper with the same eid within this batch
            # is also skipped (defensive, unlikely in practice).
            seen_eids.add(paper.external_id)

            # ── Extract facts ──────────────────────────────────────────────────
            facts = await self._extractor.extract(paper)
            log.debug("Extracted %d facts from %s", len(facts), paper.external_id)

            for fact in facts:
                # ── Wire L3 metadata (HARD REQ A) ─────────────────────────────
                # Set expected_year and expected_authors from the source PaperResult
                # so that VerificationPipeline._check_metadata() can compare them
                # against the resolved paper returned by fetch_by_id.
                # These are dynamic attributes — no Fact dataclass change needed;
                # citation.py reads them via getattr(fact, "expected_year", None).
                fact.expected_year = paper.year        # type: ignore[attr-defined]
                fact.expected_authors = paper.authors  # type: ignore[attr-defined]

                # ── Verify (L1→L2→L3→L4) ──────────────────────────────────────
                status = await self._pipeline.verify(fact)
                fact.verification = status

                log.debug(
                    "Fact verification: claim=%r layer=%d status=%s",
                    fact.claim[:60],
                    status.layer_reached,
                    status.status,
                )

                # ── Persist only verified facts (HARD REQ C) ──────────────────
                if status.status == "verified":
                    try:
                        persist_fact(
                            fact,
                            tree=tree,
                            paper_node_id=paper_node_id,
                            store=self._store,
                        )
                        verified_count += 1
                        log.info(
                            "Persisted verified fact %s from paper %s",
                            fact.fact_id,
                            paper.external_id,
                        )
                    except ValueError as exc:
                        # Guard in persist_fact rejected the fact (should not happen
                        # since we check status == "verified" above, but be safe).
                        log.warning("persist_fact guard raised: %s", exc)

            # ── Mark paper node done ───────────────────────────────────────────
            tree.update_node(paper_node_id, status="done")

        # ── Advance session step counter ───────────────────────────────────────
        self._session.advance_step()

        summary = (
            f"Mined {verified_count} verified facts from "
            f"{len(papers)} papers ({skipped_count} skipped)."
        )
        log.info(summary)

        return ExecutorResult(
            status="done",
            summary=summary,
            score=None,
            insight=f"{verified_count} verified facts persisted.",
            refs={
                "verified_facts_count": verified_count,
                "skipped_papers_count": skipped_count,
                "total_papers": len(papers),
            },
        )
