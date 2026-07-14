"""Executor: runs one DispatchUnit as a vendored Agent, returns ExecutorResult."""
from __future__ import annotations

import logging
from typing import Any

from loop_sci.config.schemas import LoopSCIConfig

from .agent_runtime import build_agent
from .types import DispatchUnit, ExecutorResult

log = logging.getLogger(__name__)

_LLM_FAILURE_SENTINEL = "Error: LLM call failed after all recovery attempts."

_EXECUTOR_SYSTEM = """\
You are a focused research executor. You have been given a single research task.
Complete it thoroughly and concisely. When done, provide:
- A one-paragraph summary of what you found or did.
- An optional numeric score (0.0-1.0) if you can assess quality.
- A key insight in one sentence.
"""


class Executor:
    """Runs one DispatchUnit as a vendored Agent and maps the result to ExecutorResult.

    Parameters
    ----------
    cfg:
        Top-level Loop-SCI config (LoopSCIConfig).  Passed to build_agent which
        handles provider construction (or the caller may supply one via provider).
    provider:
        Optional pre-built LLMProvider.  When None, build_agent constructs one
        from cfg.provider credentials (fail-fast if the API key is absent).
    bus:
        Optional EventBus for event attribution.
    """

    def __init__(
        self,
        cfg: LoopSCIConfig,
        *,
        provider: Any = None,
        bus: Any = None,
    ) -> None:
        self._cfg = cfg
        self._provider = provider
        self._bus = bus

    async def run(self, unit: DispatchUnit) -> ExecutorResult:
        """Execute one DispatchUnit and return a typed ExecutorResult.

        This method is exception-safe: any unhandled exception from the agent
        is caught and returned as status="error" so the coordinator never sees
        an unhandled exception from this layer.
        """
        system = _EXECUTOR_SYSTEM
        if unit.context:
            system += f"\n\n## Context\n{unit.context}"

        try:
            agent = build_agent(
                self._cfg,
                provider=self._provider,
                tools=unit.tools if unit.tools else [],
                bus=self._bus,
                node_id=unit.node_id,
                agent_label=f"executor:{unit.node_id}",
                system_prompt=system,
            )
            text = await agent.run(unit.goal)

            # LLM-failure sentinel is treated as an error regardless of stop_reason
            if text == _LLM_FAILURE_SENTINEL:
                return ExecutorResult(
                    status="error",
                    summary=text,
                )

            if agent.stop_reason == "finished":
                status = "done"
            else:
                # "max_turns" or any other non-finished stop_reason
                status = "bounded_exit"

            return ExecutorResult(
                status=status,  # type: ignore[arg-type]
                summary=text,
                # Foundation skeleton: no domain score/insight/refs extraction yet
                score=None,
                insight="",
                refs={},
            )

        except Exception as exc:  # noqa: BLE001
            log.error("Executor failed for node %s: %s", unit.node_id, exc)
            return ExecutorResult(
                status="error",
                summary=f"Executor error: {exc}",
            )
