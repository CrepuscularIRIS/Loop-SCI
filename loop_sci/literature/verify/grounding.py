"""L4 hybrid content-grounding verifier.

Hybrid router
-------------
Given the resolved paper's text (abstract by default) and the fact's
``evidence_span``, the verifier decides in three stages:

1. **Lexical pre-filter** — compute a cheap Jaccard token-overlap score between
   the evidence span and the source text.
   * score >= ``HIGH_THRESHOLD`` (0.60) → **GROUNDED** without any LLM call.
   * score <= ``LOW_THRESHOLD``  (0.15) → **NOT GROUNDED** without any LLM call.

2. **Borderline band** (``LOW_THRESHOLD < score < HIGH_THRESHOLD``) → invoke the
   Qwen judge: prompt the LLM provider to determine whether the text ENTAILS
   the claim.  The LLM verdict decides the outcome.

3. **Fallback** — if the provider is absent or the LLM call fails, the raw
   lexical score vs. ``threshold`` (a midpoint sentinel, default 0.3) decides.

Recorded on ``VerificationStatus.detail``:
  ``"<path>:<confidence>"`` where *path* is one of
  ``"lexical"``, ``"qwen_judge"``, ``"lexical_no_judge"``, ``"fallback"``.

Design notes
------------
* ``LOW_THRESHOLD`` and ``HIGH_THRESHOLD`` are class-level attributes so they
  can be overridden per-instance or subclassed.
* The grounding scope is always ``"abstract"`` (the resolved paper's abstract).
  Full-text grounding is reserved for a future iteration.
* This module is purely additive; L1-L3 logic in ``citation.py`` is unchanged.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from loop_sci.literature.extract.fact import Fact, VerificationStatus
from loop_sci.literature.search.schema import PaperResult

log = logging.getLogger(__name__)

_JUDGE_SYSTEM = """\
You are a citation grounding judge. Given a source text and a claim, determine
whether the claim is SUPPORTED by the source text.
Respond with ONLY valid JSON in the form: {"supported": bool, "confidence": float}.
Do not include any explanation outside the JSON object.
"""


def _tokenize(text: str) -> set[str]:
    """Lowercase, strip punctuation, and split into word tokens.

    Removes leading/trailing non-alphanumeric characters from each token so
    that "ANNs." and "ANNs" are treated as the same token.
    """
    import re
    return {re.sub(r"[^a-z0-9]", "", w) for w in text.lower().split() if re.sub(r"[^a-z0-9]", "", w)}


def _lexical_score(span: str, text: str) -> float:
    """Jaccard recall score: how much of the span's vocabulary appears in text.

    Returns a float in [0.0, 1.0].  If the span is empty the score is 0.0.
    The denominator is the span token set size (recall-oriented: how much of the
    span is covered by the text).  Punctuation is stripped before comparison.

    Parameters
    ----------
    span:
        The evidence span or claim text from the ``Fact``.
    text:
        The resolved paper's source text (abstract or full text).
    """
    span_tokens = _tokenize(span)
    if not span_tokens:
        return 0.0
    text_tokens = _tokenize(text)
    return len(span_tokens & text_tokens) / len(span_tokens)


class GroundingVerifier:
    """Hybrid lexical + LLM content-grounding verifier (L4).

    Parameters
    ----------
    provider:
        An ``LLMProvider``-compatible object with an ``async create(...)``
        method.  Pass ``None`` to disable the Qwen judge path (borderline
        cases then fall back to the raw lexical score vs. ``threshold``).
    threshold:
        Midpoint sentinel for the offline / fallback path.  When the lexical
        score is in the borderline band and no provider is available, scores
        >= ``threshold`` are treated as GROUNDED.  Default 0.3.

    Class attributes
    ----------------
    LOW_THRESHOLD:
        Scores at or below this value are immediately NOT GROUNDED (no Qwen).
        Default 0.15.
    HIGH_THRESHOLD:
        Scores at or above this value are immediately GROUNDED (no Qwen).
        Default 0.60.
    """

    LOW_THRESHOLD: float = 0.15
    HIGH_THRESHOLD: float = 0.60

    def __init__(self, provider: Any, *, threshold: float = 0.3) -> None:
        self._provider = provider
        self._threshold = threshold

    async def verify(self, fact: Fact, paper: PaperResult) -> VerificationStatus:
        """Ground the fact's claim/evidence against the resolved paper's text.

        Parameters
        ----------
        fact:
            The ``Fact`` to ground.  ``fact.evidence_span`` and ``fact.claim``
            are used for the lexical pre-filter; ``fact.claim`` is sent to the
            Qwen judge in the borderline band.
        paper:
            The resolved ``PaperResult`` from L2.  ``paper.abstract`` is the
            primary source text (``None`` is treated as empty string).

        Returns
        -------
        VerificationStatus
            ``layer_reached=4``.  ``status`` is ``"verified"`` or
            ``"rejected"``.  ``detail`` encodes the decision path and
            confidence as ``"<path>:<score>"``.
        """
        source_text: str = paper.abstract or ""
        # Use the evidence span for lexical matching (verbatim quote from source)
        score = _lexical_score(fact.evidence_span, source_text)

        log.debug(
            "L4 grounding: evidence_span=%r score=%.3f abstract_len=%d",
            fact.evidence_span[:60],
            score,
            len(source_text),
        )

        # ── Fast path: clearly grounded ──────────────────────────────────────
        if score >= self.HIGH_THRESHOLD:
            return VerificationStatus(
                layer_reached=4,
                status="verified",
                detail=f"lexical:{score:.2f}",
            )

        # ── Fast path: clearly not grounded ──────────────────────────────────
        if score <= self.LOW_THRESHOLD:
            return VerificationStatus(
                layer_reached=4,
                status="rejected",
                detail=f"lexical:{score:.2f}",
            )

        # ── Borderline band: invoke Qwen judge ───────────────────────────────
        if self._provider is None:
            # Offline / no provider configured — fall back to threshold
            grounded = score >= self._threshold
            return VerificationStatus(
                layer_reached=4,
                status="verified" if grounded else "rejected",
                detail=f"lexical_no_judge:{score:.2f}",
            )

        return await self._call_qwen_judge(fact, source_text, score)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _call_qwen_judge(
        self,
        fact: Fact,
        source_text: str,
        lexical_score: float,
    ) -> VerificationStatus:
        """Invoke the LLM judge for borderline cases.

        Parameters
        ----------
        fact:
            The fact whose claim is being judged.
        source_text:
            The resolved paper's abstract (or other text scope).
        lexical_score:
            Pre-computed lexical score (used in fallback logging only).
        """
        try:
            resp = await self._provider.create(
                system=_JUDGE_SYSTEM,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Source text:\n{source_text}\n\n"
                            f"Claim:\n{fact.claim}"
                        ),
                    }
                ],
                max_tokens=128,
            )
            raw: str = resp.content[0].text if resp.content else "{}"
            verdict: dict = json.loads(raw)
            supported: bool = bool(verdict.get("supported", False))
            conf: float = float(verdict.get("confidence", 0.5))
            return VerificationStatus(
                layer_reached=4,
                status="verified" if supported else "rejected",
                detail=f"qwen_judge:{conf:.2f}",
            )
        except Exception as exc:
            log.warning(
                "Qwen judge failed (score=%.3f): %s — falling back to lexical",
                lexical_score,
                exc,
            )
            grounded = lexical_score >= self._threshold
            return VerificationStatus(
                layer_reached=4,
                status="verified" if grounded else "rejected",
                detail=f"fallback:{lexical_score:.2f}",
            )
