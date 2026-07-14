"""Integration test: real Coordinator → Executor → vendored Agent vs MockProvider.

All tests run OFFLINE (no network, no API key) by injecting MockProvider.
Default suite (no @pytest.mark.live) — must pass in CI.

Wiring:
    - LoopSCIConfig constructed directly (no Hydra file I/O).
    - MockProvider returns deterministic scripted responses.
    - Executor is the REAL production Executor, not a stub.
    - Coordinator is the REAL production Coordinator, not a stub.
    - RunSession is created in tmp_path (cleaned up by pytest).
"""
from __future__ import annotations

import pytest
from tests.conftest import MockProvider

from loop_sci.config.schemas import (
    LoopSCIConfig,
    ProviderConf,
    AgentConf,
    EngineConf,
    RunConf,
)
from loop_sci.engine import Coordinator, Executor
from loop_sci.events import EventBus
from loop_sci.state.session import RunSession


# ---------------------------------------------------------------------------
# Shared fixture: minimal LoopSCIConfig (no API key required)
# ---------------------------------------------------------------------------

@pytest.fixture
def loop_cfg() -> LoopSCIConfig:
    """Minimal LoopSCIConfig with safe defaults; no real API key needed."""
    return LoopSCIConfig(
        provider=ProviderConf(
            base_url="http://localhost:1",   # unreachable — never called with MockProvider
            model="mock-model",
            api_key="dummy-key",
        ),
        agent=AgentConf(
            max_turns=5,
            context_window=8000,
            compact_threshold=0.9,
            compact_keep_recent=4,
            max_tokens=512,
        ),
        engine=EngineConf(step_budget=3),
        run=RunConf(runs_root="runs", task=""),
    )


# ---------------------------------------------------------------------------
# Test 1: one observe → dispatch → record cycle completes without network
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_one_coordinator_cycle(tmp_path, loop_cfg):
    """One full observe→dispatch→record cycle completes offline.

    Assertions:
    - session.is_complete is True after coordinator.run().
    - ROOT node status is strictly "done" (MockProvider returns end_turn → Agent
      finishes → Executor returns status="done").
    - Mock answer text is recorded in root.insight (in-memory and after reload).
    - idea_tree.json exists on disk and reflects the outcome.
    """
    mock_answer = "The scientific method requires observation. Done."
    provider = MockProvider(responses=[mock_answer])
    executor = Executor(loop_cfg, provider=provider)
    coordinator = Coordinator(executor=executor, step_budget=3)

    session = RunSession.create(tmp_path / "runs", task="What is the scientific method?")

    await coordinator.run(session)

    # Session must be complete
    assert session.is_complete, "coordinator.run() must mark session complete"

    # Root node should have been processed and recorded "done"
    root = session.tree.get_root()
    assert root.status == "done", (
        f"ROOT node status expected 'done', got {root.status!r}"
    )
    assert mock_answer in root.insight, (
        f"Mock answer must be recorded in root.insight, got {root.insight!r}"
    )

    # Tree was persisted to disk
    tree_path = session.session_dir / "idea_tree.json"
    assert tree_path.exists(), "idea_tree.json must be written to disk"

    # Reload tree from disk and verify consistency
    from loop_sci.state.idea_tree import IdeaTree
    reloaded_tree = IdeaTree.load_json(tree_path)
    reloaded_root = reloaded_tree.get_root()
    assert reloaded_root.status == root.status, (
        "Reloaded tree status must match in-memory status"
    )
    assert mock_answer in reloaded_root.insight, (
        f"Mock answer must persist in reloaded root.insight, got {reloaded_root.insight!r}"
    )


# ---------------------------------------------------------------------------
# Test 2: event-bus subscriber receives lifecycle events
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_event_bus_receives_events(tmp_path, loop_cfg):
    """EventBus subscriber receives session/executor lifecycle events.

    Assertions:
    - At least one event with "executor" or "session" in its type is received.
    - session.is_complete is True (result is identical to NullBus run).
    """
    received_events: list[str] = []
    bus = EventBus()
    bus.on_all(lambda e: received_events.append(e.type))

    provider = MockProvider(responses=["Completed."])
    executor = Executor(loop_cfg, provider=provider)
    coordinator = Coordinator(executor=executor, bus=bus, step_budget=3)

    session = RunSession.create(tmp_path / "runs", task="stub task for event bus test")
    await coordinator.run(session)

    # Must have received at least one session/executor lifecycle event
    assert received_events, "No events received at all — EventBus subscription broken"
    lifecycle_events = [t for t in received_events if "executor" in t or "session" in t]
    assert lifecycle_events, (
        f"Expected at least one 'executor.*' or 'session.*' event, got: {received_events}"
    )

    # Result parity: session is complete regardless of bus
    assert session.is_complete, "session must be complete even with a real EventBus"


# ---------------------------------------------------------------------------
# Test 3: event-bus parity — NullBus vs real bus produce same outcome
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_event_bus_parity_with_null_bus(tmp_path, loop_cfg):
    """Wiring a real EventBus must not change coordinator outcomes.

    Both runs get the same scripted answer; both must end complete with the
    root node in the same terminal status.
    """
    answer = "Same answer either way."

    # Run 1: NullBus (default when no bus passed)
    p1 = MockProvider(responses=[answer])
    e1 = Executor(loop_cfg, provider=p1)
    c1 = Coordinator(executor=e1, step_budget=3)
    s1 = RunSession.create(tmp_path / "null_bus_run", task="parity task")
    await c1.run(s1)

    # Run 2: real EventBus with a subscriber
    events_seen: list[str] = []
    bus = EventBus()
    bus.on_all(lambda e: events_seen.append(e.type))
    p2 = MockProvider(responses=[answer])
    e2 = Executor(loop_cfg, provider=p2)
    c2 = Coordinator(executor=e2, bus=bus, step_budget=3)
    s2 = RunSession.create(tmp_path / "real_bus_run", task="parity task")
    await c2.run(s2)

    assert s1.is_complete and s2.is_complete, "Both sessions must complete"
    assert s1.tree.get_root().status == s2.tree.get_root().status, (
        f"Root status must match: NullBus={s1.tree.get_root().status}, "
        f"RealBus={s2.tree.get_root().status}"
    )
    assert events_seen, "Real bus must have received events"


# ---------------------------------------------------------------------------
# Test 4: step_budget=0 exits immediately and marks session complete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_step_budget_zero_exits_immediately(tmp_path, loop_cfg):
    """A coordinator with step_budget=0 exits immediately.

    It must still call mark_complete() and leave the session in a
    well-defined state (is_complete=True, step counter at 0).
    """
    provider = MockProvider(responses=["answer"])
    executor = Executor(loop_cfg, provider=provider)
    coordinator = Coordinator(executor=executor, step_budget=0)
    session = RunSession.create(tmp_path / "runs", task="budget zero task")

    await coordinator.run(session)

    assert session.is_complete, "Session must be complete even with step_budget=0"
    assert session.cursor["step"] == 0, (
        f"No steps should have run; cursor step={session.cursor['step']}"
    )
