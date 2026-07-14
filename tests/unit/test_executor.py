"""Tests for loop_sci/engine/executor.py — Executor maps DispatchUnit to ExecutorResult.

TDD: tests written BEFORE production code (RED phase first).

Test seam: monkeypatch build_agent in loop_sci.engine.executor to return a
FakeAgent whose async run() returns a scripted text and exposes stop_reason.
This isolates Executor's MAPPING logic from any real LLM or network.

Contracts tested:
  1. finished (stop_reason=="finished") → status="done", summary=returned text.
  2. max_turns (stop_reason=="max_turns") → status="bounded_exit".
  3. exception raised by agent.run → status="error", no propagation.
  4. LLM-failure sentinel text → status="error".
  5. score, insight, refs are None/empty by default (no domain extraction).
  6. Executor.run is exception-safe (coordinator never sees an unhandled exc).
"""
from __future__ import annotations

import pytest

from loop_sci.engine.types import DispatchUnit, ExecutorResult

# ---------------------------------------------------------------------------
# Fake agent and helpers
# ---------------------------------------------------------------------------

_LLM_FAILURE_SENTINEL = "Error: LLM call failed after all recovery attempts."


class FakeAgent:
    """Minimal stub Agent: returns scripted text, sets stop_reason."""

    def __init__(self, return_text: str, stop_reason: str | None, raise_exc: Exception | None = None):
        self._return_text = return_text
        self.stop_reason = stop_reason
        self._raise_exc = raise_exc

    async def run(self, user_message: str) -> str:  # noqa: ARG002
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._return_text


def _make_unit(
    node_id: str = "node-1",
    goal: str = "Summarise quantum entanglement",
    context: str = "",
    tools: list | None = None,
) -> DispatchUnit:
    return DispatchUnit(node_id=node_id, goal=goal, context=context, tools=tools or [])


def _make_executor(monkeypatch, fake_agent: FakeAgent):
    """Return a minimal LoopSCIConfig-based Executor with build_agent patched."""
    from loop_sci.config.schemas import LoopSCIConfig
    from loop_sci.engine.executor import Executor

    cfg = LoopSCIConfig()
    executor = Executor(cfg=cfg)

    # Patch build_agent inside the executor module so no real LLM is contacted.
    monkeypatch.setattr(
        "loop_sci.engine.executor.build_agent",
        lambda *args, **kwargs: fake_agent,
    )
    return executor


# ---------------------------------------------------------------------------
# RED tests — these MUST fail before executor.py exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finished_maps_to_done(monkeypatch):
    """stop_reason=='finished' → status='done', summary=returned text."""
    final_text = "Quantum entanglement links two particles instantly."
    fake = FakeAgent(return_text=final_text, stop_reason="finished")
    executor = _make_executor(monkeypatch, fake)

    result = await executor.run(_make_unit())

    assert isinstance(result, ExecutorResult)
    assert result.status == "done"
    assert result.summary == final_text


@pytest.mark.asyncio
async def test_max_turns_maps_to_bounded_exit(monkeypatch):
    """stop_reason=='max_turns' → status='bounded_exit'."""
    fake = FakeAgent(return_text="Partial answer.", stop_reason="max_turns")
    executor = _make_executor(monkeypatch, fake)

    result = await executor.run(_make_unit())

    assert result.status == "bounded_exit"
    assert result.summary == "Partial answer."


@pytest.mark.asyncio
async def test_exception_maps_to_error_no_propagation(monkeypatch):
    """Exception inside agent.run → status='error', exception must NOT propagate."""
    fake = FakeAgent(
        return_text="",
        stop_reason=None,
        raise_exc=RuntimeError("network timeout"),
    )
    executor = _make_executor(monkeypatch, fake)

    # Must NOT raise — Executor.run is exception-safe
    result = await executor.run(_make_unit())

    assert result.status == "error"
    assert "network timeout" in result.summary


@pytest.mark.asyncio
async def test_llm_failure_sentinel_maps_to_error(monkeypatch):
    """LLM-failure sentinel text returned by agent.run → status='error'."""
    fake = FakeAgent(return_text=_LLM_FAILURE_SENTINEL, stop_reason="finished")
    executor = _make_executor(monkeypatch, fake)

    result = await executor.run(_make_unit())

    assert result.status == "error"
    assert _LLM_FAILURE_SENTINEL in result.summary


@pytest.mark.asyncio
async def test_score_insight_refs_none_by_default(monkeypatch):
    """Foundation skeleton: score=None, refs empty, insight may be empty string."""
    fake = FakeAgent(return_text="Found nothing special.", stop_reason="finished")
    executor = _make_executor(monkeypatch, fake)

    result = await executor.run(_make_unit())

    assert result.score is None
    assert result.refs == {}
    # insight is a str field (empty or non-empty); we only assert it's a str
    assert isinstance(result.insight, str)


@pytest.mark.asyncio
async def test_executor_run_is_exception_safe(monkeypatch):
    """Even a completely unexpected exception must not propagate to the caller."""
    fake = FakeAgent(
        return_text="",
        stop_reason=None,
        raise_exc=ValueError("unexpected internal error"),
    )
    executor = _make_executor(monkeypatch, fake)

    # This call must complete without raising
    result = await executor.run(_make_unit())
    assert result.status == "error"


@pytest.mark.asyncio
async def test_node_id_passed_to_build_agent(monkeypatch):
    """Executor must forward unit.node_id to build_agent's node_id kwarg."""
    from loop_sci.config.schemas import LoopSCIConfig
    from loop_sci.engine.executor import Executor

    captured_kwargs: dict = {}

    def fake_build_agent(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return FakeAgent(return_text="ok", stop_reason="finished")

    cfg = LoopSCIConfig()
    executor = Executor(cfg=cfg)
    monkeypatch.setattr("loop_sci.engine.executor.build_agent", fake_build_agent)

    await executor.run(_make_unit(node_id="test-node-99"))

    assert captured_kwargs.get("node_id") == "test-node-99"
