"""Abstract base class for all tools, with result persistence for large outputs."""

from __future__ import annotations

import os
import uuid
from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """Base class every tool must inherit from.

    Features mirroring Claude Code's tool system:
    - JSON Schema input definition for the LLM
    - Concurrency safety flag for parallel execution
    - Smart result handling: persist large results to disk instead of truncating
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    is_read_only: bool = False
    max_result_chars: int = 50_000
    # If a result exceeds persist_threshold, save to disk and return preview.
    # Set to 0 to always persist, or float('inf') to never persist.
    persist_threshold: int = 30_000

    def __init__(self, *, cwd: str, workspace_dir: str | None = None):
        self.cwd = cwd
        self.workspace_dir = workspace_dir

    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """Run the tool and return a text result."""

    def drain_notifications(self) -> list[str]:
        """Return messages this tool wants pushed to the agent, then clear them.

        Default: no notifications. Tools that own background work (e.g. Bash's
        fire-and-forget jobs) override this to deliver completed results to the
        agent on the next turn — replacing the old poll-the-status loop (#8).
        Called once per turn by the agent loop; must not block.
        """
        return []

    async def aclose(self) -> None:
        """Release any background resources this tool owns. Default: no-op.

        Called once when the owning agent finishes its run (including on
        cancellation), so fire-and-forget work doesn't outlive the agent (#8).
        """
        return None

    def to_api_schema(self) -> dict[str, Any]:
        """Convert to the format expected by the LLM API (Anthropic tool schema)."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    def process_result(self, text: str) -> str:
        """Process a tool result: persist large results to disk, truncate if needed.

        This replaces the old _truncate() approach. Instead of silently losing
        data, large results are saved to a file and the LLM gets a preview with
        a path to the full result. The LLM can then use Read to access the
        full content if needed.
        """
        if len(text) <= self.persist_threshold:
            return text

        # Persist to disk
        persist_root = self.workspace_dir or self.cwd
        persist_dir = os.path.join(persist_root, ".arbor", "tool_results")
        os.makedirs(persist_dir, exist_ok=True)
        result_id = uuid.uuid4().hex[:12]
        result_path = os.path.join(persist_dir, f"{self.name}_{result_id}.txt")

        try:
            with open(result_path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception:
            # If persistence fails, fall back to truncation
            return self._truncate(text)

        # Build preview: first 2KB + last 1KB + pointer to full file
        preview_head = text[:2000]
        preview_tail = text[-1000:] if len(text) > 3000 else ""
        separator = "\n\n...[middle section omitted]...\n\n" if preview_tail else ""

        return (
            f"{preview_head}{separator}{preview_tail}\n\n"
            f"[Full output ({len(text):,} chars) saved to: {result_path}]\n"
            f"[Use the Read tool to access the complete result if needed.]"
        )

    def _truncate(self, text: str) -> str:
        """Hard truncation fallback (used when persistence fails)."""
        if len(text) <= self.max_result_chars:
            return text
        return (
            text[:self.max_result_chars]
            + f"\n\n... [truncated, showing first {self.max_result_chars:,} of {len(text):,} chars]"
        )
