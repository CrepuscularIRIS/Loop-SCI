"""Qwen-driven fact extractor.

Extracts structured :class:`~loop_sci.literature.extract.fact.Fact` objects
from a paper's available text (abstract or full text) by prompting the Qwen
LLM provider and parsing its JSON response.

Key invariants enforced here
----------------------------
* **Evidence-required**: every proposed claim must carry a non-empty
  ``evidence_span`` — claims without one are dropped before returning.
* **Traceable**: every ``evidence_span`` must be a substring of the source
  text (after whitespace/case normalisation) — fabricated spans that are
  absent from the source are dropped before returning.
* **Bounded**: ``max_facts_per_paper`` caps the number of grounded facts
  returned per paper (applied *after* the grounding filter).
* **Confidence clamped**: any model-returned confidence value is clamped to
  ``[0.0, 1.0]`` before constructing the :class:`Fact`.
* **Robust parsing**: malformed / non-JSON model output returns ``[]`` rather
  than raising.
* **Empty-paper guard**: a paper with no abstract text yields zero facts
  without calling the provider at all.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from loop_sci.literature.extract.fact import Fact, SourceRef
from loop_sci.literature.search.schema import PaperResult

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Text normalisation helper
# ---------------------------------------------------------------------------


def _normalize(s: str) -> str:
    """Normalise *s* for substring traceability checks.

    Applies three transformations so that trivial model reformatting does not
    cause false drops:

    1. Collapse consecutive whitespace (including newlines) to a single space.
    2. Casefold for case-insensitive matching.
    3. Normalise curly/typographic quotes and apostrophes to their straight
       ASCII equivalents.
    """
    # Straight-quote normalisation: curly single/double quotes → ASCII
    s = s.replace("‘", "'").replace("’", "'")
    s = s.replace("“", '"').replace("”", '"')
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s.casefold()

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM = """\
You are a scientific fact extractor. Given a paper abstract, extract structured facts.
Return a JSON array where each item has:
  "claim": str (a single precise claim),
  "evidence_span": str (the exact verbatim quote from the text supporting this claim — REQUIRED),
  "confidence": float (0.0-1.0),
  "entities": list[str] (key entities, may be empty).
IMPORTANT: If you cannot find a direct verbatim quote for a claim, DO NOT include that claim.
Return only valid JSON, no markdown fences.
"""


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------


class FactExtractor:
    """Extract grounded, bounded :class:`Fact` objects from a paper.

    Args:
        provider: Any object whose ``await provider.create(*, system, messages,
            max_tokens)`` returns an :class:`~loop_sci._vendor.arbor.llm.base.LLMResponse`
            with a ``.get_text()`` method.  In production this is the Qwen
            :class:`~loop_sci.provider.LLMProvider`; in tests it is a
            :class:`~conftest.MockProvider`.
        max_facts_per_paper: Upper bound on facts returned per paper (applied
            *after* dropping ungrounded claims).  Defaults to ``5``.
    """

    def __init__(self, provider: Any, *, max_facts_per_paper: int = 5) -> None:
        self._provider = provider
        self._max = max_facts_per_paper

    async def extract(self, paper: PaperResult) -> list[Fact]:
        """Extract grounded facts from *paper*'s available text.

        Returns an empty list when:
        - the paper has no abstract text, or
        - the model returns malformed JSON, or
        - no proposed claim passes the grounding check.

        Args:
            paper: A :class:`~loop_sci.literature.search.schema.PaperResult`
                whose ``abstract`` field supplies the extraction text.

        Returns:
            A list of :class:`~loop_sci.literature.extract.fact.Fact` objects,
            at most ``max_facts_per_paper`` in length, all with non-empty
            ``evidence_span`` values.
        """
        text = paper.abstract or ""
        if not text.strip():
            return []

        scope = "abstract"  # Task 9 will upgrade to "full_text" for PMC-OA/arXiv
        prompt = f"Extract facts from this paper abstract:\n\n{text}"

        try:
            resp = await self._provider.create(
                system=_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
            )
            raw = resp.get_text()
            items: list[dict[str, Any]] = json.loads(raw)
        except Exception as exc:
            log.warning(
                "Extraction failed for paper %s: %s",
                paper.external_id,
                exc,
            )
            return []

        source_ref = SourceRef(
            source=paper.source,
            external_id=paper.external_id,
            doi=paper.doi,
        )

        norm_text = _normalize(text)

        facts: list[Fact] = []
        for item in items:
            span = (item.get("evidence_span") or "").strip()
            claim = (item.get("claim") or "").strip()

            if not span or not claim:
                log.debug(
                    "Dropping claim with empty span for paper %s: %r",
                    paper.external_id,
                    claim,
                )
                continue

            if _normalize(span) not in norm_text:
                log.debug(
                    "Dropping non-traceable span for paper %s: %r",
                    paper.external_id,
                    span,
                )
                continue

            if len(facts) >= self._max:
                break

            raw_confidence = float(item.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, raw_confidence))

            facts.append(
                Fact(
                    claim=claim,
                    source_ref=source_ref,
                    evidence_span=span,
                    confidence=confidence,
                    grounding_scope=scope,
                    entities=item.get("entities") or None,
                )
            )

        return facts
