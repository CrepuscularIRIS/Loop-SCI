"""Canonical-JSON → Markdown rendering and parity assertion for ResearchPlan.

Public API
----------
- ``PLAN_FIELD_TITLES``: mapping from each of the 12 ``PLAN_JSON_KEYS`` to its
  PDF-section display title.
- ``render_markdown(plan) -> str``: walks ``PLAN_JSON_KEYS`` in order and emits
  a ``## <Title>`` section per field.  Each field type is rendered by a
  dedicated helper.
- ``assert_json_markdown_parity(plan) -> None``: renders once, then asserts that
  all 12 ``## <Title>`` headings are present.  Raises ``AssertionError`` on any
  missing heading.  Markdown is DERIVED from JSON — this check is a structural
  invariant, never an independent content comparison.
"""
from __future__ import annotations

from loop_sci.plan.schemas import (
    Candidate,
    ExperimentsBlock,
    Reference,
    ResearchPlan,
    ResultsBlock,
    PLAN_JSON_KEYS,
)

# ---------------------------------------------------------------------------
# Title map — 12 keys in PLAN_JSON_KEYS order
# ---------------------------------------------------------------------------

PLAN_FIELD_TITLES: dict[str, str] = {
    "problem_statement": "Problem Statement",
    "rationale": "Rationale",
    "technical_details": "Technical Details",
    "datasets": "Datasets",
    "source": "Source",
    "target": "Target",
    "paper_title": "Paper Title",
    "abstract": "Abstract",
    "methods": "Methods",
    "experiments": "Experiments",
    "results": "Results",
    "references": "References",
}

# ---------------------------------------------------------------------------
# Field-type body renderers
# ---------------------------------------------------------------------------


def _render_str(value: str) -> str:
    """Render a plain-string field body."""
    return value


def _render_candidates(candidates: list[Candidate]) -> str:
    """Render a list of Candidate objects as a bullet list.

    Each bullet includes the ``(candidate)`` marker when ``candidate`` is True.
    """
    lines: list[str] = []
    for c in candidates:
        marker = " (candidate)" if c.candidate else ""
        lines.append(f"- {c.value}{marker}")
    return "\n".join(lines)


def _render_experiments(exp: ExperimentsBlock) -> str:
    """Render an ExperimentsBlock as labelled fields."""
    baselines = ", ".join(exp.baselines) if exp.baselines else "(none)"
    metrics = ", ".join(exp.metrics) if exp.metrics else "(none)"
    return f"Baselines: {baselines}\nMetrics: {metrics}\nDesign: {exp.design}"


def _render_results(res: ResultsBlock) -> str:
    """Render a ResultsBlock as graded derivation bullets plus summary."""
    lines: list[str] = []
    for item in res.derivation:
        step = item.get("step", "")
        grade = item.get("grade", "")
        lines.append(f"- {step} {grade}")
    lines.append(f"Conclusion: {res.conclusion}")
    lines.append(f"Confidence: {res.confidence}")
    return "\n".join(lines)


def _render_references(refs: list[Reference]) -> str:
    """Render a list of Reference objects as bullet lines."""
    lines: list[str] = []
    for ref in refs:
        verified_tag = "verified" if ref.verified else "unverified"
        lines.append(f"- {ref.source}:{ref.external_id} ({verified_tag})")
    return "\n".join(lines)


def _render_field(key: str, value: object) -> str:
    """Dispatch to the appropriate renderer for the given field value type."""
    if isinstance(value, ExperimentsBlock):
        return _render_experiments(value)
    if isinstance(value, ResultsBlock):
        return _render_results(value)
    if isinstance(value, list):
        if not value:
            return "(empty)"
        first = value[0]
        if isinstance(first, Candidate):
            return _render_candidates(value)  # type: ignore[arg-type]
        if isinstance(first, Reference):
            return _render_references(value)  # type: ignore[arg-type]
        # fallback: join as bullets
        return "\n".join(f"- {item}" for item in value)
    return _render_str(str(value))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_markdown(plan: ResearchPlan) -> str:
    """Render a ResearchPlan to Markdown.

    Walks ``PLAN_JSON_KEYS`` in order.  For each key emits a ``## <Title>``
    heading (from ``PLAN_FIELD_TITLES``) followed by the rendered body.

    Args:
        plan: The research plan to render.

    Returns:
        A UTF-8 Markdown string with one ``##``-level section per field.
    """
    sections: list[str] = []
    for key in PLAN_JSON_KEYS:
        title = PLAN_FIELD_TITLES[key]
        value = getattr(plan, key)
        body = _render_field(key, value)
        sections.append(f"## {title}\n\n{body}")
    return "\n\n".join(sections) + "\n"


def assert_json_markdown_parity(plan: ResearchPlan) -> None:
    """Assert that the rendered Markdown contains all 12 field headings.

    Raises:
        AssertionError: If any ``## <Title>`` heading derived from
            ``PLAN_FIELD_TITLES`` is absent from the rendered output.
    """
    md = render_markdown(plan)
    missing: list[str] = []
    for key in PLAN_JSON_KEYS:
        heading = f"## {PLAN_FIELD_TITLES[key]}"
        if heading not in md:
            missing.append(heading)
    if missing:
        raise AssertionError(
            f"Markdown parity failure — missing headings: {missing}"
        )
