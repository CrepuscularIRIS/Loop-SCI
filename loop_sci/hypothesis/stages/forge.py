"""forge' stage — generate candidate hypotheses from a problem-card node.

Given a problem-card node (its node-id and refs dict) and a populated FactStore,
prompts an LLM provider to generate ``MECHANISM / KILL / BRACKET / DIFF_PREDICTION``
candidates using induction and deduction.  Each returned tuple is a
``(hyp_node_id, hyp_refs, derivation)`` triple that callers may attach to the
idea-tree under the card node as children.

Key invariants
--------------
* **Rival frame**: every call must include ≥1 rival-frame candidate; the LLM is
  instructed to do so and the test suite verifies it.
* **Relabeling filter (osp 1.4)**: a candidate is discarded when its
  ``DIFF_PREDICTION`` content tokens (after lower-casing, stripping punctuation,
  and removing stopwords) are entirely contained within the mechanism tokens —
  i.e. the prediction introduces no new predictive token beyond the mechanism.
  Verbatim equality (after whitespace normalisation) is a strict subset of this.
* **Per-run cap (osp 1.5)**: at most ``max_candidates`` candidates are returned
  (Hydra-configurable; default 4).
* **Retry-once → drop (osp 1.6)**: if the provider returns malformed JSON, one
  retry is attempted; on second failure the stage returns an empty list (no crash).
* **JSON robustness (osp 1.6)**: after ``json.loads`` a non-list ``candidates``
  field is treated as an empty list (no ``AttributeError``).
* **Grounding by fact-id**: grounding lives in ``derivation[].fact_ids`` inside
  ``hyp_refs``, never in the native ``Node.grounding`` string.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from loop_sci.hypothesis.schemas import (
    DerivationStep,
    HypothesisHyp,
    Iteration,
    build_hyp_refs,
)
from loop_sci.literature.factbase.store import FactStore

log = logging.getLogger(__name__)

_FORGE_SYSTEM = (
    "You are a hypothesis forge. Given a research gap card and verified facts, "
    "generate candidate hypotheses using induction and deduction. "
    "Return ONLY a JSON object with key \"candidates\" whose value is a list. "
    "Each element must have keys: MECHANISM (string), KILL (string), "
    "BRACKET (string), DIFF_PREDICTION (string), "
    "frame (\"primary\" or \"rival\"), "
    "derivation (list of {step, grade, fact_ids} objects where grade is one of "
    "[paper], [inferred], [guess]). "
    "Include at least one candidate with frame=\"rival\"."
)


# ---------------------------------------------------------------------------
# Relabeling filter (osp 1.4)
# ---------------------------------------------------------------------------

# Small stopword set — high-frequency function words that carry no predictive
# content on their own.  Deterministic, no external NLP library required.
_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "are", "was", "were", "be",
    "been", "being", "it", "its", "this", "that", "these", "those",
    "will", "would", "can", "could", "should", "may", "might", "must",
    "do", "does", "did", "not", "no", "nor", "so", "yet", "than", "then",
    "when", "where", "which", "who", "how", "what", "if", "while",
    "has", "have", "had", "also",
})


def _normalise(s: str) -> str:
    """Lowercase and collapse whitespace for comparison."""
    return re.sub(r"\s+", " ", s.lower().strip())


def _content_tokens(s: str) -> frozenset[str]:
    """Return the set of meaningful content tokens from *s*.

    Tokenizes by splitting on whitespace and punctuation, lower-cases every
    token, then drops single-character tokens and stopwords.  The result is a
    frozenset so that order and repetition are irrelevant — only unique
    predictive words matter.
    """
    # Strip punctuation: replace any non-alphanumeric-non-space character with
    # a space so that "EEG-signature" → {"eeg", "signature"}.
    cleaned = re.sub(r"[^a-z0-9\s]", " ", s.lower())
    tokens = cleaned.split()
    return frozenset(
        t for t in tokens if len(t) > 1 and t not in _STOPWORDS
    )


def _is_relabeling(mechanism: str, diff_prediction: str) -> bool:
    """Return True when diff_prediction introduces no new predictive content.

    Two conditions both count as a relabeling (osp 1.4):

    1. Verbatim echo: *diff_prediction* is identical to *mechanism* after
       whitespace normalisation (strict subset of condition 2, kept explicit
       for clarity and backward-compatibility).
    2. Content containment: after tokenising both strings into content-token
       sets (lowercase, punctuation-stripped, stopwords removed), every token
       in *diff_prediction* is already present in *mechanism* — i.e.
       ``diff_tokens - mechanism_tokens == ∅``.  This catches paraphrases /
       re-wordings that carry no new predictive information.
    """
    # Fast path: verbatim equality after normalisation.
    if _normalise(mechanism) == _normalise(diff_prediction):
        return True

    # Content-containment check: diff must introduce ≥1 new token.
    diff_tokens = _content_tokens(diff_prediction)
    mechanism_tokens = _content_tokens(mechanism)
    # If diff has no tokens at all (empty prediction), also treat as relabeling.
    if not diff_tokens:
        return True
    return (diff_tokens - mechanism_tokens) == frozenset()


# ---------------------------------------------------------------------------
# Public stage entry-point
# ---------------------------------------------------------------------------


async def run_forge(
    card_node_id: str,
    card_refs: dict[str, Any],
    store: FactStore,
    provider: Any,
    *,
    max_candidates: int = 4,
) -> list[tuple[str, dict[str, Any], list[DerivationStep]]]:
    """Generate candidate hypotheses grounded in the problem card and fact base.

    Args:
        card_node_id: Node-id of the parent problem-card node in the idea-tree.
            Callers use this to attach returned hypothesis nodes as children.
        card_refs: The ``Node.refs`` dict of the problem-card node
            (as produced by :func:`~loop_sci.hypothesis.schemas.build_card_refs`).
        store: FactStore to draw verified facts from.
        provider: LLM provider implementing
            ``await create(*, system, messages, max_tokens) -> LLMResponse``.
        max_candidates: Upper bound on candidates returned (Hydra-configurable).

    Returns:
        List of ``(hyp_node_id, hyp_refs, derivation)`` triples.
        ``hyp_refs`` conforms to :func:`~loop_sci.hypothesis.schemas.build_hyp_refs`.
        Derivation fact-ids (grounding) live inside ``hyp_refs["derivation"]``.
        Returns an empty list when the provider fails, JSON is malformed, or all
        candidates are filtered (relabeling / over-cap).
    """
    # --- 1. Build fact summary for the prompt ---
    all_facts = store.all()
    fact_summary = "\n".join(
        f"[{f.fact_id}] {f.claim}" for f in all_facts[:50] if f.fact_id
    )

    card_data = card_refs.get("card", {})
    topic = card_refs.get("topic", "")

    prompt = (
        f"Gap card:\n{json.dumps(card_data, ensure_ascii=False)}\n\n"
        f"Verified facts:\n{fact_summary}\n\n"
        f"Generate up to {max_candidates} hypothesis candidates "
        f"(include ≥1 rival-frame candidate)."
    )

    # --- 2. Call provider with retry-once → drop ---
    raw = await _call_with_retry(provider, prompt)
    if raw is None:
        return []

    # --- 3. Parse JSON; guard against non-list candidates ---
    try:
        data = json.loads(raw)
        raw_candidates = data.get("candidates", [])
        if not isinstance(raw_candidates, list):
            log.debug("forge: candidates field is not a list; returning empty")
            return []
    except (json.JSONDecodeError, AttributeError):
        return []

    # --- 4. Filter, cap, and build result tuples ---
    results: list[tuple[str, dict[str, Any], list[DerivationStep]]] = []
    for item in raw_candidates[:max_candidates]:
        mechanism = item.get("MECHANISM", "")
        diff_prediction = item.get("DIFF_PREDICTION", "")

        # Relabeling filter (osp 1.4)
        if _is_relabeling(mechanism, diff_prediction):
            log.debug("forge: discarding relabeling candidate: %s", mechanism)
            continue

        derivation = [
            DerivationStep(
                step=str(s.get("step", "")),
                grade=s.get("grade", "[guess]"),
                fact_ids=list(s.get("fact_ids", [])),
            )
            for s in (item.get("derivation") or [])
        ]

        hyp = HypothesisHyp(
            MECHANISM=mechanism,
            KILL=item.get("KILL", ""),
            BRACKET=item.get("BRACKET", ""),
            DIFF_PREDICTION=diff_prediction,
        )

        frame = item.get("frame", "primary")
        hyp_refs = build_hyp_refs(
            kind="hypothesis",
            frame=frame,  # type: ignore[arg-type]
            topic=topic,
            hyp=hyp,
            derivation=derivation,
            contract=None,
            verdict=None,
            scores=None,
            autopsy=None,
            iteration=Iteration(),
        )

        hyp_node_id = f"hyp_{uuid.uuid4().hex[:8]}"
        results.append((hyp_node_id, hyp_refs, derivation))

    return results


# ---------------------------------------------------------------------------
# Provider call with retry-once → drop (mirrors prospect.py / FactExtractor)
# ---------------------------------------------------------------------------


async def _call_with_retry(provider: Any, prompt: str) -> str | None:
    """Call the provider, retry once on failure, return None if both attempts fail.

    Mirrors the ``try / except ... log.warning ... return None`` pattern from
    :func:`~loop_sci.hypothesis.stages.prospect._call_with_retry`.
    """
    for attempt in range(2):
        try:
            resp = await provider.create(
                system=_FORGE_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2048,
            )
            raw = resp.get_text()
            json.loads(raw)  # validate — raises JSONDecodeError if malformed
            return raw
        except Exception as exc:
            log.warning("forge: provider call/parse failed (attempt %d): %s", attempt, exc)
    return None
