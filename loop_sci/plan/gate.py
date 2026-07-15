"""Deterministic, provider-free completeness and anti-fabrication gate.

Public API
----------
- ``run_gate(plan) -> GateResult``: checks the 12 content fields for emptiness,
  verifies that all references are marked verified, and confirms that
  ``plan.results.confidence == "final"`` (load-bearing claim check).
  Returns a ``GateResult`` with ``passed=True`` iff no failures were collected.

Gate rules (all deterministic — no network, no provider call):
1. String fields (``problem_statement``, ``rationale``, ``technical_details``,
   ``paper_title``, ``abstract``, ``methods``): fail if falsy (empty/None).
2. List-of-Candidate fields (``datasets``, ``source``, ``target``): fail if the
   list is empty.  A list containing even a grounding-absent marker
   ``Candidate(value="", candidate=True, source_ref=None)`` is PRESENT — do not
   fail merely because a candidate's value string is "".
3. Structured fields: ``experiments`` — ExperimentsBlock is always structurally
   present if the plan was constructed normally; only its string sub-field
   ``design`` is checked for non-emptiness.  ``results`` — checked via the
   confidence rule below.
4. ``references`` list: fail if empty; also fail for every Reference whose
   ``verified`` is False (failure string contains "reference").
5. ``results.confidence``: fail if not equal to ``"final"`` (failure string
   contains "load-bearing" and "confidence").
"""
from __future__ import annotations

from loop_sci.plan.schemas import (
    GateResult,
    ResearchPlan,
    PLAN_JSON_KEYS,
)

# Keys that are plain strings — checked for truthiness
_STR_KEYS: frozenset[str] = frozenset(
    {
        "problem_statement",
        "rationale",
        "technical_details",
        "paper_title",
        "abstract",
        "methods",
    }
)

# Keys that are list[Candidate] — checked for non-empty list only
_CANDIDATE_LIST_KEYS: frozenset[str] = frozenset({"datasets", "source", "target"})


def run_gate(plan: ResearchPlan) -> GateResult:
    """Run the deterministic completeness and anti-fabrication gate.

    Args:
        plan: The research plan to evaluate.

    Returns:
        ``GateResult(passed=True, failures=[])`` when all checks pass, or
        ``GateResult(passed=False, failures=[...])`` with descriptive failure
        strings otherwise.
    """
    failures: list[str] = []

    # --- 1. String fields: must be non-empty ---
    for key in PLAN_JSON_KEYS:
        if key not in _STR_KEYS:
            continue
        value: str = getattr(plan, key)
        if not value:
            failures.append(f"empty field: {key}")

    # --- 2. List-of-Candidate fields: list must be non-empty ---
    for key in _CANDIDATE_LIST_KEYS:
        candidates = getattr(plan, key)
        if not candidates:  # list is empty
            failures.append(f"empty field: {key}")
        # non-empty list (even with grounding-absent markers) is PRESENT

    # --- 3. experiments: check design sub-field ---
    if not plan.experiments.design:
        failures.append("empty field: experiments.design")

    # --- 4. references: non-empty + all verified ---
    if not plan.references:
        failures.append("empty field: references")
    else:
        for ref in plan.references:
            if not ref.verified:
                failures.append(
                    f"unverified reference: {ref.source}:{ref.external_id}"
                )

    # --- 5. results confidence check ---
    if plan.results.confidence != "final":
        failures.append(
            f"load-bearing ungrounded claim / confidence != final "
            f"(got: {plan.results.confidence!r})"
        )

    return GateResult(passed=not failures, failures=failures)
