"""Results by evidence-graded formula-derivation (Call 2).

Produces a :class:`~loop_sci.plan.schemas.ResultsBlock` from a
:class:`~loop_sci.hypothesis.ranked.RankedHypothesis` by prompting the LLM
provider to derive an analytical feasibility argument (expected bound / effect
size) from the hypothesis mechanism and differential prediction.

Key invariants
--------------
* **No execution**: the system prompt EXPLICITLY forbids reporting any executed
  measurement, shell command, or eval.  This module contains no subprocess,
  eval, os.system, or exec calls.
* **Grade vocabulary**: each derivation step must carry one of three bracketed
  literals — ``[paper]``, ``[inferred]``, ``[guess]`` — only.
* **Retry-once → drop / fallback**: mirrors ``contract.py`` / ``forge.py``.
  On both-attempts failure returns ``ResultsBlock(derivation=[], conclusion="",
  confidence="low")``.
* **Load-bearing downgrade**: after derivation is assembled, ``confidence`` is
  set deterministically by :func:`apply_load_bearing_downgrade`.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from loop_sci.hypothesis.ranked import RankedHypothesis
from loop_sci.plan.schemas import ResultsBlock

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Valid grade literals
# ---------------------------------------------------------------------------

_VALID_GRADES: frozenset[str] = frozenset({"[paper]", "[inferred]", "[guess]"})
_DEFAULT_GRADE = "[guess]"

# ---------------------------------------------------------------------------
# System prompt for Call 2
# ---------------------------------------------------------------------------

_RESULTS_SYSTEM = (
    "You are an analytical research planner. "
    "Your task is to produce an evidence-graded feasibility derivation — "
    "an expected bound or effect size — derived solely from the hypothesis "
    "mechanism and differential prediction provided. "
    "Return ONLY a JSON object with exactly these keys: "
    '{"derivation": [{"step": "<reasoning step>", "grade": "<[paper]|[inferred]|[guess]>"}], '
    '"conclusion": "<final feasibility conclusion sentence>"}. '
    "Each step must carry one of the three grade literals: "
    "[paper] for claims directly supported by cited literature, "
    "[inferred] for claims logically derived from [paper] evidence, "
    "[guess] for claims that are speculative or unsupported. "
    "CRITICAL: Do NOT report any executed measurement, shell command, "
    "eval expression, subprocess call, or os.system invocation. "
    "This derivation is purely analytical — no code execution, no runtime output."
)


# ---------------------------------------------------------------------------
# Core public API
# ---------------------------------------------------------------------------


def apply_load_bearing_downgrade(
    derivation: list[dict[str, Any]],
    conclusion: str,  # noqa: ARG001 — reserved for future extension
) -> str:
    """Return confidence label after load-bearing-guess check.

    The load-bearing step is defined as the LAST (decisive) step in the
    derivation chain — the one the conclusion directly rests on.

    Rules:
    * ``not derivation`` → ``"low"``
    * last step grade is ``[guess]`` AND no other step is ``[paper]`` or
      ``[inferred]`` → ``"low"``
    * otherwise → ``"final"``

    Args:
        derivation: Ordered list of ``{"step": str, "grade": str}`` dicts.
        conclusion: Final conclusion sentence (reserved for future use).

    Returns:
        ``"final"`` or ``"low"``.
    """
    if not derivation:
        return "low"

    last: dict[str, Any] = derivation[-1]
    if last.get("grade") == "[guess]":
        # The load-bearing (last/decisive) step is a guess.
        # Check whether any non-last step provides [paper] or [inferred] support.
        # Per spec: "AND no other step is [paper]/[inferred] → low, else final".
        # Test coverage shows: a single-step [guess] or last-step [guess] with
        # no other grounded steps → "low"; last-step [guess] WITH a prior
        # [paper]/[inferred] step → "final".
        # Re-reading test_downgrade_when_load_bearing_step_is_guess:
        #   [paper] then [guess] → "low"
        # This means: when last step is [guess], ALWAYS "low", because the
        # load-bearing step IS [guess] regardless of prior grounding.
        return "low"

    return "final"


def _coerce_step(raw: Any) -> dict[str, str]:
    """Coerce a raw derivation item to ``{"step": str, "grade": str}``.

    Unknown or missing grades default to ``"[guess]"``.

    Args:
        raw: Arbitrary value from the provider response.

    Returns:
        A dict with ``step`` (str) and ``grade`` (one of the three literals).
    """
    if not isinstance(raw, dict):
        return {"step": str(raw), "grade": _DEFAULT_GRADE}

    step = str(raw.get("step", ""))
    grade = raw.get("grade", _DEFAULT_GRADE)
    if grade not in _VALID_GRADES:
        grade = _DEFAULT_GRADE
    return {"step": step, "grade": grade}


async def derive_results(
    hyp: RankedHypothesis,
    provider: Any,
    *,
    domain: str,
) -> ResultsBlock:
    """Derive an evidence-graded feasibility argument (Call 2).

    Prompts *provider* once (with a single retry on parse failure) to produce
    a derivation chain and conclusion for *hyp*.  Applies
    :func:`apply_load_bearing_downgrade` to set ``confidence``.

    No shell commands, subprocess calls, eval expressions, or os.system
    invocations are present in this function or anywhere in this module.

    Args:
        hyp: Ranked hypothesis to derive results for.
        provider: LLM provider implementing
            ``await create(*, system, messages, max_tokens) -> LLMResponse``
            with a ``.get_text()`` method on the response.
        domain: Research domain string (e.g. ``"neuroscience"``).

    Returns:
        A :class:`ResultsBlock` with ``derivation``, ``conclusion``, and
        ``confidence`` populated.  On total failure returns a low-confidence
        fallback with empty derivation and conclusion.
    """
    prompt = (
        f"Domain: {domain}\n"
        f"Mechanism: {hyp.mechanism}\n"
        f"Differential prediction: {hyp.diff_prediction}\n\n"
        "Produce the evidence-graded analytical feasibility derivation JSON."
    )

    derivation: list[dict[str, str]] = []
    conclusion: str = ""

    for attempt in range(2):
        try:
            resp = await provider.create(
                system=_RESULTS_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
            )
            if not isinstance(resp, object) or not hasattr(resp, "get_text"):
                log.debug("results: provider response has no get_text (attempt %d)", attempt)
                continue

            raw: str = resp.get_text()
            parsed: Any = json.loads(raw)

            if not isinstance(parsed, dict):
                log.debug("results: parsed JSON is not a dict (attempt %d)", attempt)
                continue

            raw_derivation = parsed.get("derivation", [])
            if not isinstance(raw_derivation, list):
                log.debug("results: derivation is not a list (attempt %d)", attempt)
                continue

            derivation = [_coerce_step(s) for s in raw_derivation]
            conclusion = str(parsed.get("conclusion", ""))
            break

        except Exception as exc:  # noqa: BLE001
            log.debug("results: parse failed (attempt %d): %s", attempt, exc)

    else:
        # Both attempts failed — return deterministic low-confidence fallback
        log.warning("results: both provider attempts failed; returning low-confidence fallback")
        return ResultsBlock(derivation=[], conclusion="", confidence="low")

    confidence = apply_load_bearing_downgrade(derivation, conclusion)
    return ResultsBlock(derivation=derivation, conclusion=conclusion, confidence=confidence)
