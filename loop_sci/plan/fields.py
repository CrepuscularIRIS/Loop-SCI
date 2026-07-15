"""Qwen-call helpers and deterministic DST candidate builder for ResearchPlan.

Three public callables:

* :func:`assemble_reasoning_fields` (Call 1) — async; prompts the LLM to
  produce problem_statement, rationale, technical_details, methods, and an
  ExperimentsBlock.  Retry-once → empty fallback so the downstream gate fails.
* :func:`assemble_title_abstract` (Call 3) — async; prompts the LLM to
  produce paper_title and abstract from a partial plan context.
* :func:`build_dst_candidates` — synchronous/deterministic; resolves grounding
  facts via ``hyp.grounding_fact_ids`` and returns datasets/source/target
  candidate lists.  Never invents a concrete dataset.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from loop_sci.hypothesis.ranked import RankedHypothesis
from loop_sci.literature.extract.fact import Fact
from loop_sci.plan.schemas import Candidate, ExperimentsBlock

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_REASONING_SYSTEM_TMPL = (
    "You are a scientific research plan writer for the domain: {domain}. "
    "Given a ranked hypothesis, produce a JSON object with EXACTLY these keys: "
    '{{"problem_statement": "...", "rationale": "...", "technical_details": "...", '
    '"methods": "...", "experiments": {{"baselines": [...], "metrics": [...], "design": "..."}}}}. '
    "Anchor every field to the provided hypothesis mechanism, derivation chain, "
    "and differential prediction.  Return ONLY the JSON object, no prose."
)

_TITLE_ABSTRACT_SYSTEM_TMPL = (
    "You are an academic title and abstract writer for the domain: {domain}. "
    "Given a partial research plan context, produce a JSON object with EXACTLY "
    'these keys: {{"paper_title": "...", "abstract": "..."}}. '
    "Return ONLY the JSON object, no prose."
)

# ---------------------------------------------------------------------------
# Call 1: reasoning fields
# ---------------------------------------------------------------------------


async def assemble_reasoning_fields(
    hyp: RankedHypothesis,
    facts: list[Fact],
    provider: Any,
    *,
    domain: str,
) -> dict[str, Any]:
    """Assemble reasoning fields via an LLM call (Call 1).

    Prompts *provider* to produce ``problem_statement``, ``rationale``,
    ``technical_details``, ``methods``, and ``experiments`` anchored to the
    hypothesis and domain.  Retries once on parse failure; on both-attempts
    failure returns empty strings / empty :class:`ExperimentsBlock` so the
    downstream gate can detect the error.

    Args:
        hyp: Ranked hypothesis providing problem, mechanism, derivation_chain,
            and diff_prediction.
        facts: All grounding facts (used for context, not parsed here).
        provider: LLM provider with
            ``await create(*, system, messages, max_tokens) -> LLMResponse``.
        domain: Research domain to parameterise the prompt (e.g. "neuroscience").

    Returns:
        Dict with keys ``problem_statement``, ``rationale``,
        ``technical_details``, ``methods``, ``experiments``.
    """
    system = _REASONING_SYSTEM_TMPL.format(domain=domain)

    # Build a brief fact-context snippet (first 3 facts' claims)
    fact_context = "; ".join(f.claim for f in facts[:3]) if facts else "(no grounding facts)"

    prompt = (
        f"Domain: {domain}\n"
        f"Problem: {hyp.problem}\n"
        f"Mechanism: {hyp.mechanism}\n"
        f"Derivation chain: {json.dumps(hyp.derivation_chain)}\n"
        f"Differential prediction: {hyp.diff_prediction}\n"
        f"Grounding facts context: {fact_context}\n\n"
        "Produce the research plan JSON."
    )

    for attempt in range(2):
        try:
            resp = await provider.create(
                system=system,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2048,
            )
            raw: str = resp.get_text()
            d: dict[str, Any] = json.loads(raw)
            if not isinstance(d, dict):
                raise ValueError("Response is not a JSON object")

            exp_raw = d.get("experiments", {})
            baselines = exp_raw.get("baselines", [])
            metrics = exp_raw.get("metrics", [])
            design = exp_raw.get("design", "")

            # Coerce baselines/metrics to list[str]
            if not isinstance(baselines, list):
                baselines = [str(baselines)]
            else:
                baselines = [str(b) for b in baselines]

            if not isinstance(metrics, list):
                metrics = [str(metrics)]
            else:
                metrics = [str(m) for m in metrics]

            return {
                "problem_statement": str(d.get("problem_statement", "")),
                "rationale": str(d.get("rationale", "")),
                "technical_details": str(d.get("technical_details", "")),
                "methods": str(d.get("methods", "")),
                "experiments": ExperimentsBlock(
                    baselines=baselines,
                    metrics=metrics,
                    design=str(design),
                ),
            }
        except Exception as exc:  # noqa: BLE001
            log.debug("assemble_reasoning_fields: parse failed (attempt %d): %s", attempt, exc)

    log.warning("assemble_reasoning_fields: both provider attempts failed; returning empty fields")
    return {
        "problem_statement": "",
        "rationale": "",
        "technical_details": "",
        "methods": "",
        "experiments": ExperimentsBlock([], [], ""),
    }


# ---------------------------------------------------------------------------
# Call 3: title + abstract
# ---------------------------------------------------------------------------


async def assemble_title_abstract(
    plan_context: dict[str, Any],
    provider: Any,
    *,
    domain: str,
) -> dict[str, str]:
    """Assemble paper title and abstract via an LLM call (Call 3).

    Args:
        plan_context: Partial plan fields assembled so far (used as context).
        provider: LLM provider with
            ``await create(*, system, messages, max_tokens) -> LLMResponse``.
        domain: Research domain to parameterise the prompt.

    Returns:
        Dict with keys ``paper_title`` and ``abstract``.
    """
    system = _TITLE_ABSTRACT_SYSTEM_TMPL.format(domain=domain)

    prompt = (
        f"Domain: {domain}\n"
        f"Plan context: {json.dumps(plan_context, ensure_ascii=False)}\n\n"
        "Produce the paper_title and abstract JSON."
    )

    for attempt in range(2):
        try:
            resp = await provider.create(
                system=system,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
            )
            raw: str = resp.get_text()
            d: dict[str, Any] = json.loads(raw)
            if not isinstance(d, dict):
                raise ValueError("Response is not a JSON object")
            return {
                "paper_title": str(d.get("paper_title", "")),
                "abstract": str(d.get("abstract", "")),
            }
        except Exception as exc:  # noqa: BLE001
            log.debug("assemble_title_abstract: parse failed (attempt %d): %s", attempt, exc)

    log.warning("assemble_title_abstract: both provider attempts failed; returning empty fields")
    return {"paper_title": "", "abstract": ""}


# ---------------------------------------------------------------------------
# Deterministic DST candidate builder (no provider)
# ---------------------------------------------------------------------------

# Simple heuristic tokens that suggest dataset references in a claim or entity.
_DATASET_TOKENS: frozenset[str] = frozenset({
    "dataset", "data", "corpus", "benchmark", "imagenet", "mnist", "cifar",
    "squad", "glue", "coco", "openimages", "wikipedia", "commonvoice",
})


def _is_dataset_like(text: str) -> bool:
    """Return True if *text* contains a dataset-like token (case-insensitive)."""
    lower = text.lower()
    return any(tok in lower for tok in _DATASET_TOKENS)


def build_dst_candidates(
    hyp: RankedHypothesis,
    facts: list[Fact],
) -> dict[str, list[Candidate]]:
    """Build datasets/source/target candidate lists deterministically (no LLM).

    Resolves grounding facts from ``hyp.grounding_fact_ids`` against *facts*
    by ``fact.fact_id``.  Never invents a concrete dataset.

    * **datasets** — one :class:`Candidate` per grounding fact whose claim or
      entities mention a dataset-like token; carries ``fact.source_ref.to_dict()``
      as provenance.  When no grounding facts exist, returns a single
      grounding-absent marker ``Candidate(value="", candidate=True, source_ref=None)``.
    * **source** — one :class:`Candidate` per grounding fact (historical data
      the derivation rests on); carries ``source_ref`` provenance.  Falls back
      to the grounding-absent marker when empty.
    * **target** — one :class:`Candidate`` per non-empty token in
      ``hyp.diff_prediction`` (split on whitespace/punctuation); no source_ref
      (to-be-collected features).  Falls back to the grounding-absent marker.

    Args:
        hyp: Ranked hypothesis providing ``grounding_fact_ids`` and
            ``diff_prediction``.
        facts: All facts from the fact store (used to resolve ids).

    Returns:
        Dict with keys ``"datasets"``, ``"source"``, ``"target"``.
    """
    # Index facts by fact_id for O(1) lookup
    fact_index: dict[str, Fact] = {}
    for f in facts:
        if f.fact_id is not None:
            fact_index[f.fact_id] = f

    # Resolve grounding facts in order
    grounding_facts: list[Fact] = []
    for fid in hyp.grounding_fact_ids:
        fact = fact_index.get(fid)
        if fact is not None:
            grounding_facts.append(fact)

    _absent_marker = Candidate(value="", candidate=True, source_ref=None)

    # --- datasets ---
    dataset_candidates: list[Candidate] = []
    for fact in grounding_facts:
        # Check claim and entities for dataset-like tokens
        entities = fact.entities or []
        relevant_texts = [fact.claim] + entities
        if any(_is_dataset_like(t) for t in relevant_texts):
            # Use the most specific entity name if available, else a claim snippet
            value = entities[0] if entities else fact.claim[:80]
            dataset_candidates.append(
                Candidate(
                    value=value,
                    candidate=True,
                    source_ref=fact.source_ref.to_dict(),
                )
            )

    if not dataset_candidates:
        dataset_candidates = [_absent_marker]

    # --- source: candidates from grounding facts' claims ---
    source_candidates: list[Candidate] = [
        Candidate(
            value=fact.claim[:80],
            candidate=True,
            source_ref=fact.source_ref.to_dict(),
        )
        for fact in grounding_facts
    ]
    if not source_candidates:
        source_candidates = [_absent_marker]

    # --- target: derived from diff_prediction tokens (no source_ref) ---
    # Split diff_prediction on whitespace and basic punctuation, keep non-trivial tokens
    raw_tokens = re.split(r"[\s\->/,;:.!?()]+", hyp.diff_prediction)
    target_tokens = [t for t in raw_tokens if len(t) > 2]  # skip arrows, connectors

    target_candidates: list[Candidate] = [
        Candidate(value=tok, candidate=True, source_ref=None)
        for tok in target_tokens
    ]
    if not target_candidates:
        target_candidates = [_absent_marker]

    return {
        "datasets": dataset_candidates,
        "source": source_candidates,
        "target": target_candidates,
    }
