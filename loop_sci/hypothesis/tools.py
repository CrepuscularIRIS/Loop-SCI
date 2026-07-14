"""Hypothesis tool registrations for the ToolRegistry.

Registers three tools — ``generate``, ``critique``, ``rank`` — that wrap the
underlying hypothesis pipeline with injected dependencies.  Tools return
structured JSON results (dict/list) on success, or a structured error dict on
bad input.  They never raise; the :class:`~loop_sci.engine.tools.ToolRegistry`
dispatch layer catches exceptions, but these functions defend themselves too.

Offline-capable: when ``executor=None``, all tools return structured empty /
error payloads rather than raising.

Usage::

    from loop_sci.engine.tools import ToolRegistry
    from loop_sci.hypothesis.tools import register_hypothesis_tools

    registry = ToolRegistry()
    register_hypothesis_tools(registry, executor=my_executor)
"""
from __future__ import annotations

import json
import logging
from typing import Any

from loop_sci.engine.tools import ToolRegistry

log = logging.getLogger(__name__)

__all__ = ["register_hypothesis_tools"]


def register_hypothesis_tools(registry: ToolRegistry, executor: Any) -> None:
    """Register generate / critique / rank tools on *registry*.

    Parameters
    ----------
    registry:
        The :class:`~loop_sci.engine.tools.ToolRegistry` to register onto.
    executor:
        A :class:`~loop_sci.hypothesis.executor.HypothesisExecutor` instance
        (or None for schema-only / offline use).  The executor is captured by
        closure inside each tool function; no global state is used.
    """

    # ------------------------------------------------------------------
    # generate — run the full hypothesis pipeline for a topic
    # ------------------------------------------------------------------

    async def _generate(topic: str) -> str:
        """Generate hypotheses for *topic* via the injected executor."""
        if not topic or not isinstance(topic, str):
            return json.dumps({"error": "invalid_input", "detail": "topic must be a non-empty string"})
        if executor is None:
            return json.dumps({"error": "no_executor", "detail": "executor not configured"})
        try:
            from loop_sci.engine.types import DispatchUnit

            unit = DispatchUnit(node_id="ROOT", goal=topic)
            result = await executor.run(unit)
            return json.dumps({
                "status": result.status,
                "summary": result.summary,
                "accepted_count": result.refs.get("accepted_count", 0) if result.refs else 0,
            })
        except Exception as exc:
            log.warning("generate tool error: %s", exc)
            return json.dumps({"error": "tool_error", "detail": str(exc)})

    registry.register(
        name="generate",
        description=(
            "Generate hypotheses for a research topic by running the full "
            "prospect → forge → contract → adversary pipeline."
        ),
        schema={
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The research topic or question to generate hypotheses for.",
                },
            },
            "required": ["topic"],
        },
        fn=_generate,
    )

    # ------------------------------------------------------------------
    # critique — run adversarial critique on a specific hypothesis node
    # ------------------------------------------------------------------

    async def _critique(node_id: str) -> str:
        """Critique the hypothesis at *node_id* via the injected executor."""
        if not node_id or not isinstance(node_id, str):
            return json.dumps({"error": "invalid_input", "detail": "node_id must be a non-empty string"})
        if executor is None:
            return json.dumps({"error": "no_executor", "detail": "executor not configured"})
        try:
            result = await executor.run_critique(node_id)
            # run_critique returns a structured dict; for backward-compat with
            # mock executors that return a plain string, normalise here.
            if isinstance(result, dict):
                return json.dumps(result)
            return json.dumps({"verdict": result, "node_id": node_id})
        except Exception as exc:
            log.warning("critique tool error for node %r: %s", node_id, exc)
            return json.dumps({"error": "tool_error", "detail": str(exc)})

    registry.register(
        name="critique",
        description=(
            "Run an adversarial critique on a specific hypothesis node and "
            "return the verdict (UP/DOWN)."
        ),
        schema={
            "type": "object",
            "properties": {
                "node_id": {
                    "type": "string",
                    "description": "The tree node id of the hypothesis to critique.",
                },
            },
            "required": ["node_id"],
        },
        fn=_critique,
    )

    # ------------------------------------------------------------------
    # rank — return hypotheses ranked by score
    # ------------------------------------------------------------------

    def _rank(topic: str = "", status: str = "accepted") -> str:
        """Return ranked hypotheses from the injected RankedHypothesisStore."""
        if executor is None:
            return json.dumps([])
        try:
            store = executor.ranked_store() if hasattr(executor, "ranked_store") else None
            if store is None:
                return json.dumps([])
            ranked = store.get_ranked(
                topic=topic if topic else None,
                status=status if status else None,
            )
            return json.dumps([
                {
                    "node_id": r.node_id,
                    "mechanism": r.mechanism,
                    "overall_score": r.overall_score,
                    "diff_prediction": r.diff_prediction,
                }
                for r in ranked
            ])
        except Exception as exc:
            log.warning("rank tool error: %s", exc)
            return json.dumps({"error": "tool_error", "detail": str(exc)})

    registry.register(
        name="rank",
        description=(
            "Return hypotheses from the idea tree ranked by overall quality score "
            "(best first). Optionally filter by topic and/or status."
        ),
        schema={
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Filter hypotheses by research topic (optional).",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by node status, e.g. 'accepted' (optional).",
                },
            },
        },
        fn=_rank,
    )
