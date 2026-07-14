"""Tool protocol seam: native tool-calls vs prompt-injected JSON fallback."""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any


class ToolProtocol(ABC):
    """Decouple how tools are offered to the model from the agent loop."""

    @abstractmethod
    def prepare_tools(self, tools: list[dict[str, Any]]) -> dict[str, Any]:
        """Return extra kwargs to pass to provider.create() for tool support."""

    def parse_tool_calls(
        self, text: str, tools: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Extract tool calls from a text response. Default: return empty list."""
        return []


class NativeToolProtocol(ToolProtocol):
    """Use the provider's native tools/tool_choice API (default)."""

    def prepare_tools(self, tools: list[dict[str, Any]]) -> dict[str, Any]:
        if not tools:
            return {}
        return {"tools": tools, "tool_choice": "auto"}


class PromptToolProtocol(ToolProtocol):
    """Inject tool schemas into the system prompt; parse JSON blocks from text.

    Fallback for Qwen tiers where native tool-calling is unreliable.
    The model is instructed to emit tool calls as:
        ```tool_call
        {"name": "<tool>", "arguments": {...}}
        ```
    """

    _FENCE_RE = re.compile(
        r"```tool_call\s*\n(.*?)\n```", re.DOTALL
    )

    def prepare_tools(self, tools: list[dict[str, Any]]) -> dict[str, Any]:
        if not tools:
            return {}
        schemas = json.dumps(tools, ensure_ascii=False, indent=2)
        suffix = (
            "\n\n## Available Tools\n"
            "When you need to call a tool, emit exactly one fenced block:\n"
            "```tool_call\n"
            '{"name": "<tool_name>", "arguments": {<args>}}\n'
            "```\n"
            f"Tool schemas:\n```json\n{schemas}\n```"
        )
        return {"system_suffix": suffix}

    def parse_tool_calls(
        self, text: str, tools: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Extract valid tool calls from fenced ```tool_call blocks.

        Robustness:
        - Tolerates malformed JSON inside a fence (skips the block, doesn't crash).
        - Handles multiple fenced blocks in a single response.
        - Only accepts blocks that contain a ``"name"`` key.
        """
        results = []
        for match in self._FENCE_RE.finditer(text):
            try:
                data = json.loads(match.group(1))
                if isinstance(data, dict) and "name" in data:
                    results.append({
                        "name": data["name"],
                        "arguments": data.get("arguments", {}),
                    })
            except json.JSONDecodeError:
                pass
        return results
