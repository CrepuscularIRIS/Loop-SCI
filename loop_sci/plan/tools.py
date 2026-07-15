"""Plan tool registrations for the ToolRegistry.

Registers one tool — ``assemble`` — that wraps the plan-assembly pipeline with
an injected executor.  The tool returns structured JSON on success, or a
structured error dict on bad input or missing executor.  It never raises; the
:class:`~loop_sci.engine.tools.ToolRegistry` dispatch layer catches exceptions,
but this function defends itself too.

Offline-capable: when ``executor=None``, the tool returns a structured empty /
error payload rather than raising.

Usage::

    from loop_sci.engine.tools import ToolRegistry
    from loop_sci.plan.tools import register_plan_tools

    registry = ToolRegistry()
    register_plan_tools(registry, executor=my_executor)
"""
from __future__ import annotations

import json
import logging
from typing import Any

from loop_sci.engine.tools import ToolRegistry

log = logging.getLogger(__name__)

__all__ = ["register_plan_tools"]


def register_plan_tools(registry: ToolRegistry, executor: Any) -> None:
    """Register the ``assemble`` tool on *registry*.

    Parameters
    ----------
    registry:
        The :class:`~loop_sci.engine.tools.ToolRegistry` to register onto.
    executor:
        A :class:`~loop_sci.plan.executor.PlanAssemblerExecutor` instance
        (or ``None`` for schema-only / offline use).  The executor is captured
        by closure inside the tool function; no global state is used.
    """

    async def _assemble(node_id: str) -> str:
        """Assemble a research plan for the hypothesis at *node_id*."""
        if not node_id or not isinstance(node_id, str):
            return json.dumps({
                "error": "invalid_input",
                "detail": "node_id must be a non-empty string",
            })
        if executor is None:
            return json.dumps({
                "error": "no_executor",
                "detail": "PlanAssemblerExecutor not configured",
            })
        try:
            from loop_sci.engine.types import DispatchUnit

            unit = DispatchUnit(node_id=node_id, goal="")
            result = await executor.run(unit)
            return json.dumps({
                "status": result.status,
                "summary": result.summary,
                "gate_passed": result.refs.get("gate_passed") if result.refs else None,
                "node_id": node_id,
            })
        except Exception as exc:  # noqa: BLE001
            log.warning("assemble tool error for node %r: %s", node_id, exc)
            return json.dumps({
                "error": "tool_error",
                "detail": str(exc),
                "node_id": node_id,
            })

    registry.register(
        name="assemble",
        description=(
            "Assemble a full 12-field research plan (JSON + Markdown) from a "
            "ranked hypothesis node and persist it to the session directory."
        ),
        schema={
            "type": "object",
            "properties": {
                "node_id": {
                    "type": "string",
                    "description": (
                        "The tree node id of the ranked hypothesis to assemble "
                        "a research plan for."
                    ),
                },
            },
            "required": ["node_id"],
        },
        fn=_assemble,
    )
