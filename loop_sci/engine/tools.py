"""Tool registry: register by name+schema, dispatch by name.

Design notes
------------
- ``dispatch`` is always ``async``; callers never need to branch on sync vs async.
- Sync tool functions are offloaded via ``asyncio.to_thread`` (Python 3.9+).
  This avoids the deprecated ``asyncio.get_event_loop()`` pattern and works
  cleanly under pytest-asyncio's per-test event loops without deadlocking.
- Unknown tool → structured JSON with ``error: "unknown_tool"`` + ``available`` list.
- Any exception raised by a tool fn → structured JSON with
  ``error: "tool_execution_error"`` + ``detail``.  ``dispatch`` never propagates
  unhandled exceptions — the agent loop always continues.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
from typing import Any, Callable

log = logging.getLogger(__name__)


class ToolRegistry:
    """Register tools by name+schema, supply definitions to the provider, dispatch by name.

    Single responsibility: the authoritative map from tool name → (schema, callable).
    """

    def __init__(self) -> None:
        self._tools: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        *,
        name: str,
        description: str,
        schema: dict[str, Any],
        fn: Callable,
    ) -> None:
        """Register a tool.

        Args:
            name: Unique tool name (used by the model in ``tool_use`` blocks).
            description: Human-readable description passed to the model.
            schema: JSON-Schema object describing the tool's ``input_schema``.
            fn: Callable implementing the tool; may be sync or async.
        """
        self._tools[name] = {"description": description, "schema": schema, "fn": fn}

    # ------------------------------------------------------------------
    # Provider interface
    # ------------------------------------------------------------------

    def get_definitions(self) -> list[dict[str, Any]]:
        """Return Anthropic-style tool definitions for the provider.

        Each entry follows the ``tools`` array format expected by
        ``anthropic.Client.messages.create``.
        """
        return [
            {
                "name": name,
                "description": info["description"],
                "input_schema": info["schema"],
            }
            for name, info in self._tools.items()
        ]

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def dispatch(self, name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool by name and return its string result.

        Unknown or malformed calls return a structured JSON error string —
        ``dispatch`` never raises an unhandled exception so the agent loop
        can continue regardless of tool failures.

        Args:
            name: Tool name from the model's ``tool_use`` block.
            arguments: Parsed arguments dict from the model.

        Returns:
            String result from the tool, or a JSON-encoded error object.
        """
        if name not in self._tools:
            return json.dumps(
                {
                    "error": "unknown_tool",
                    "tool": name,
                    "available": list(self._tools.keys()),
                }
            )

        fn = self._tools[name]["fn"]
        try:
            if inspect.iscoroutinefunction(fn):
                result = await fn(**arguments)
            else:
                # asyncio.to_thread is the modern (3.9+) way to run sync code
                # in a thread without touching the deprecated get_event_loop().
                result = await asyncio.to_thread(fn, **arguments)
            return str(result)
        except Exception as exc:
            log.warning("Tool %r raised %s: %s", name, type(exc).__name__, exc)
            return json.dumps(
                {
                    "error": "tool_execution_error",
                    "tool": name,
                    "detail": str(exc),
                }
            )
