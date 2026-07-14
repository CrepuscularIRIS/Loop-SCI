"""prospect' stage — mine gap/contradiction problem cards from the fact base.

Queries ``FactStore`` for facts relevant to a topic, prompts the LLM provider
to identify open research questions, and returns problem cards grounded in real
fact-ids.

Key invariants
--------------
* **Fact-grounded**: every card must cite only fact-ids that exist in the store;
  cards citing non-existent ids are dropped before returning.
* **Retry-once → drop**: if the provider returns malformed JSON, one retry is
  attempted; on second failure the stage returns an empty list (no crash).
* **Ordered**: cards are sorted by ``STAKES`` (float, 0–1) descending.
* **Bounded**: at most ``max_cards`` cards are returned.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from loop_sci.hypothesis.schemas import ProblemCard, build_card_refs
from loop_sci.literature.factbase.store import FactStore

log = logging.getLogger(__name__)

_PROSPECT_SYSTEM = (
    "You are a research gap analyst. Given verified facts about a topic, "
    "identify the most important open questions. Return ONLY a JSON array of objects, "
    "each with keys: Q (string), WHY_NOW (string), PROBE_KILL (string), "
    "STAKES (float 0-1), fact_ids (list of fact_id strings that support this gap)."
)


async def run_prospect(
    topic: str,
    store: FactStore,
    provider: Any,
    *,
    max_cards: int = 5,
    context: str = "",
) -> list[tuple[str, dict[str, Any]]]:
    """Mine gap/contradiction problem cards from the fact base.

    Args:
        topic: Research topic string used to filter facts and label cards.
        store: FactStore instance to query for verified facts.
        provider: LLM provider implementing ``await create(...) -> LLMResponse``.
        max_cards: Upper bound on cards returned (applied after filtering).
        context: Optional context string (e.g. pivot lessons) prepended to the
            prompt.  Empty string (default) means no additional context.

    Returns:
        List of ``(node_id, refs_dict)`` tuples ordered by ``STAKES`` descending.
        ``refs_dict`` conforms to :func:`~loop_sci.hypothesis.schemas.build_card_refs`
        with an additional ``"grounding_fact_ids"`` key.
        Returns an empty list when the provider returns malformed JSON or all
        candidate cards cite non-existent fact-ids.
    """
    # --- 1. Gather facts from the store (prefer topic-filtered for the prompt,
    #         but build the anti-fabrication index from ALL stored facts) ---
    all_facts = store.all()
    prompt_facts = store.filter(topic=topic) or all_facts
    # Anti-fabrication index: a card can only cite ids that actually exist in
    # the store (not just the filtered subset sent to the model).
    fact_index: dict[str, Any] = {f.fact_id: f for f in all_facts if f.fact_id}

    fact_summary = "\n".join(f"[{f.fact_id}] {f.claim}" for f in prompt_facts[:50])
    context_prefix = f"{context}\n\n" if context else ""
    prompt = (
        f"{context_prefix}Topic: {topic}\n\nVerified facts:\n{fact_summary}\n\n"
        f"Return up to {max_cards} gap cards as a JSON array."
    )

    # --- 2. Call provider with retry-once → drop discipline (mirrors FactExtractor) ---
    raw = await _call_with_retry(provider, prompt)
    if raw is None:
        return []

    try:
        items: list[dict[str, Any]] = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return []

    # --- 3. Build cards, dropping any that cite non-existent fact-ids ---
    cards: list[tuple[str, dict[str, Any]]] = []
    for item in items[:max_cards]:
        cited: list[str] = item.get("fact_ids", [])
        if not all(fid in fact_index for fid in cited):
            log.debug(
                "prospect: dropping card citing non-existent fact_ids %s", cited
            )
            continue

        card = ProblemCard(
            Q=str(item.get("Q", "")),
            WHY_NOW=str(item.get("WHY_NOW", "")),
            PROBE_KILL=str(item.get("PROBE_KILL", "")),
            STAKES=float(item.get("STAKES", 0.0)),
        )
        node_id = f"card_{uuid.uuid4().hex[:8]}"
        refs = build_card_refs(kind="problem-card", frame="primary", topic=topic, card=card)
        refs["grounding_fact_ids"] = cited
        cards.append((node_id, refs))

    # --- 4. Sort by STAKES descending ---
    return sorted(cards, key=lambda t: t[1]["card"]["STAKES"], reverse=True)


async def _call_with_retry(provider: Any, prompt: str) -> str | None:
    """Call the provider, retry once on failure, return None if both attempts fail.

    Mirrors the ``try / except ... log.warning ... return []`` pattern from
    :class:`~loop_sci.literature.extract.extractor.FactExtractor`.
    """
    for attempt in range(2):
        try:
            resp = await provider.create(
                system=_PROSPECT_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2048,
            )
            raw = resp.get_text()
            json.loads(raw)  # validate — raises JSONDecodeError if malformed
            return raw
        except Exception as exc:
            log.warning("prospect: provider call/parse failed (attempt %d): %s", attempt, exc)
    return None
