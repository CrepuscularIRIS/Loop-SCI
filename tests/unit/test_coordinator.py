"""Tests for loop_sci/engine/coordinator.py — Coordinator observe→dispatch→record→decide.

TDD: tests written BEFORE production code (RED phase first).

Test seam: inject a StubExecutor (fake Executor) whose async run() returns
scripted ExecutorResults — no network, no real agent, no LLM.

Contracts tested:
  1. One full observe→dispatch→record cycle on a fresh stub session:
     - Dispatched node is recorded as "done".
     - Tree is persisted before session marked complete.
     - Session is marked complete after the cycle.
  2. Step-budget stops the loop after N steps even if pending nodes remain.
  3. Event subscriber receives node-updated (EXECUTOR_START/EXECUTOR_END) events.
  4. Run behavior is identical with NullBus vs a real EventBus subscriber (parity).
  5. Bootstrap: a fresh session (only pending ROOT at depth 0) still runs >=1 cycle.
"""
from __future__ import annotations

import asyncio
import pytest

from loop_sci.engine.types import DispatchUnit, ExecutorResult
from loop_sci.events import EventBus, NullBus, EXECUTOR_START, EXECUTOR_END, SESSION_START, SESSION_END
from loop_sci.state.session import RunSession
from loop_sci.state.idea_tree import Node


# ---------------------------------------------------------------------------
# Stub Executor — injectable, no network
# ---------------------------------------------------------------------------

class StubExecutor:
    """Fake Executor: returns scripted ExecutorResults in order."""

    def __init__(self, results: list[ExecutorResult] | None = None) -> None:
        # If None, always return a done result.
        self._results = results or []
        self._calls: list[DispatchUnit] = []
        self._call_index = 0

    async def run(self, unit: DispatchUnit) -> ExecutorResult:
        self._calls.append(unit)
        if self._results:
            idx = min(self._call_index, len(self._results) - 1)
            result = self._results[idx]
        else:
            result = ExecutorResult(status="done", summary="stub result")
        self._call_index += 1
        return result


class RaisingStubExecutor:
    """Fake Executor that raises on run()."""

    def __init__(self, message: str = "executor exploded") -> None:
        self._message = message
        self._calls: list[DispatchUnit] = []

    async def run(self, unit: DispatchUnit) -> ExecutorResult:
        self._calls.append(unit)
        raise RuntimeError(self._message)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(tmp_path, task: str = "test research hypothesis") -> RunSession:
    return RunSession.create(tmp_path / "runs", task=task)


def _done_result() -> ExecutorResult:
    return ExecutorResult(
        status="done",
        summary="Research completed successfully.",
        score=0.85,
        insight="Key insight from the research.",
        refs={"paper": "arxiv:1234"},
    )


# ---------------------------------------------------------------------------
# RED tests — these MUST fail before coordinator.py exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_one_full_cycle_on_fresh_session(tmp_path):
    """A fresh session with only a pending ROOT triggers >=1 cycle.

    Bootstrap choice: when get_pending_leaves() returns [] but ROOT is pending,
    dispatch ROOT itself (observe returns ROOT on the first cycle).

    After the cycle:
    - The dispatched node (ROOT or a seeded child) is recorded as 'done'.
    - Session is marked complete.
    """
    from loop_sci.engine.coordinator import Coordinator

    session = _make_session(tmp_path)
    stub = StubExecutor([_done_result()])
    coordinator = Coordinator(cfg=None, executor=stub, step_budget=5)

    await coordinator.run(session)

    assert stub._call_index >= 1, "Executor must have been called at least once"
    assert session.is_complete, "Session must be marked complete after the loop"


@pytest.mark.asyncio
async def test_dispatched_node_recorded_done(tmp_path):
    """The node that was dispatched must have status='done' recorded in the tree."""
    from loop_sci.engine.coordinator import Coordinator

    session = _make_session(tmp_path)
    stub = StubExecutor([_done_result()])
    coordinator = Coordinator(cfg=None, executor=stub, step_budget=5)

    await coordinator.run(session)

    # At least one node should be done
    all_nodes = session.tree.get_all_nodes()
    done_nodes = [n for n in all_nodes if n.status == "done"]
    assert len(done_nodes) >= 1, f"Expected >=1 done node, got {[n.status for n in all_nodes]}"


@pytest.mark.asyncio
async def test_tree_persisted_before_session_marked_complete(tmp_path):
    """Tree must be saved before session.mark_complete() is called.

    We verify this by reloading the tree from disk after the run and checking
    that the done node's status is persisted.
    """
    from loop_sci.engine.coordinator import Coordinator

    session = _make_session(tmp_path)
    stub = StubExecutor([_done_result()])
    coordinator = Coordinator(cfg=None, executor=stub, step_budget=5)

    await coordinator.run(session)

    # Reload the tree from disk
    reloaded = RunSession.load(tmp_path / "runs", session.run_id)
    all_nodes = reloaded.tree.get_all_nodes()
    done_nodes = [n for n in all_nodes if n.status == "done"]
    assert len(done_nodes) >= 1, "Tree must be persisted with at least one done node"
    assert reloaded.is_complete, "Session cursor must also be persisted as done"


@pytest.mark.asyncio
async def test_step_budget_stops_loop(tmp_path):
    """Step budget must stop the loop after N steps, even if pending nodes remain."""
    from loop_sci.engine.coordinator import Coordinator
    from loop_sci.state.idea_tree import Node

    session = _make_session(tmp_path)

    # Seed three pending children so there's always more pending work
    for i in range(3):
        child_id = session.tree.next_child_id("ROOT")
        session.tree.add_node(Node(
            id=child_id,
            parent_id="ROOT",
            hypothesis=f"Hypothesis {i+1}",
            depth=1,
            status="pending",
        ))

    # Budget = 1 means only 1 step should run
    stub = StubExecutor([
        ExecutorResult(status="done", summary="done 1"),
        ExecutorResult(status="done", summary="done 2"),
        ExecutorResult(status="done", summary="done 3"),
    ])
    coordinator = Coordinator(cfg=None, executor=stub, step_budget=1)

    await coordinator.run(session)

    assert stub._call_index == 1, f"Expected exactly 1 call, got {stub._call_index}"
    assert session.is_complete, "Session must still be marked complete on budget exhaustion"


@pytest.mark.asyncio
async def test_event_subscriber_receives_executor_events(tmp_path):
    """An EventBus subscriber must receive EXECUTOR_START and EXECUTOR_END events."""
    from loop_sci.engine.coordinator import Coordinator

    session = _make_session(tmp_path)
    stub = StubExecutor([_done_result()])

    bus = EventBus()
    received: list[str] = []

    bus.on(EXECUTOR_START, lambda e: received.append(e.type))
    bus.on(EXECUTOR_END, lambda e: received.append(e.type))

    coordinator = Coordinator(cfg=None, executor=stub, bus=bus, step_budget=5)
    await coordinator.run(session)

    assert EXECUTOR_START in received, f"Expected executor.start event, got {received}"
    assert EXECUTOR_END in received, f"Expected executor.end event, got {received}"


@pytest.mark.asyncio
async def test_session_lifecycle_events_emitted(tmp_path):
    """SESSION_START and SESSION_END events must be emitted."""
    from loop_sci.engine.coordinator import Coordinator

    session = _make_session(tmp_path)
    stub = StubExecutor([_done_result()])

    bus = EventBus()
    received: list[str] = []
    bus.on_all(lambda e: received.append(e.type))

    coordinator = Coordinator(cfg=None, executor=stub, bus=bus, step_budget=5)
    await coordinator.run(session)

    assert SESSION_START in received, f"SESSION_START missing from {received}"
    assert SESSION_END in received, f"SESSION_END missing from {received}"


@pytest.mark.asyncio
async def test_nullbus_vs_eventbus_behavior_parity(tmp_path):
    """Coordinator behavior must be identical with NullBus vs real EventBus."""
    from loop_sci.engine.coordinator import Coordinator

    # Run 1: NullBus
    session1 = _make_session(tmp_path / "s1")
    stub1 = StubExecutor([_done_result()])
    coordinator1 = Coordinator(cfg=None, executor=stub1, bus=NullBus(), step_budget=5)
    await coordinator1.run(session1)

    # Run 2: Real EventBus (with subscriber)
    session2 = _make_session(tmp_path / "s2")
    stub2 = StubExecutor([_done_result()])
    bus = EventBus()
    bus.on_all(lambda e: None)  # consume events
    coordinator2 = Coordinator(cfg=None, executor=stub2, bus=bus, step_budget=5)
    await coordinator2.run(session2)

    # Both sessions should reach the same final state
    assert session1.is_complete == session2.is_complete
    nodes1 = [n.status for n in session1.tree.get_all_nodes()]
    nodes2 = [n.status for n in session2.tree.get_all_nodes()]
    assert nodes1 == nodes2, f"Node statuses differ: {nodes1} vs {nodes2}"
    assert stub1._call_index == stub2._call_index, "Call counts must match"


@pytest.mark.asyncio
async def test_error_result_recorded_and_loop_continues(tmp_path):
    """An 'error' result must be recorded and the loop continues to next pending."""
    from loop_sci.engine.coordinator import Coordinator
    from loop_sci.state.idea_tree import Node

    session = _make_session(tmp_path)

    # Seed two pending children
    child1_id = session.tree.next_child_id("ROOT")
    session.tree.add_node(Node(id=child1_id, parent_id="ROOT",
                                hypothesis="H1", depth=1, status="pending"))
    child2_id = session.tree.next_child_id("ROOT")
    session.tree.add_node(Node(id=child2_id, parent_id="ROOT",
                                hypothesis="H2", depth=1, status="pending"))

    stub = StubExecutor([
        ExecutorResult(status="error", summary="LLM error"),
        ExecutorResult(status="done", summary="H2 done"),
    ])
    coordinator = Coordinator(cfg=None, executor=stub, step_budget=10)
    await coordinator.run(session)

    # Both children should have been processed
    assert stub._call_index >= 2, f"Expected >=2 calls, got {stub._call_index}"
    assert session.is_complete


@pytest.mark.asyncio
async def test_already_complete_session_is_noop(tmp_path):
    """If session is already complete, Coordinator.run must be a no-op."""
    from loop_sci.engine.coordinator import Coordinator

    session = _make_session(tmp_path)
    session.mark_complete()

    stub = StubExecutor([_done_result()])
    coordinator = Coordinator(cfg=None, executor=stub, step_budget=5)
    await coordinator.run(session)

    assert stub._call_index == 0, "Executor must not be called for already-complete session"


@pytest.mark.asyncio
async def test_refs_recorded_in_node(tmp_path):
    """refs from ExecutorResult must be persisted to the node."""
    from loop_sci.engine.coordinator import Coordinator

    session = _make_session(tmp_path)
    refs = {"paper": "arxiv:9999", "model": "v2.1"}
    stub = StubExecutor([ExecutorResult(
        status="done", summary="done", score=0.9, insight="insight", refs=refs
    )])
    coordinator = Coordinator(cfg=None, executor=stub, step_budget=5)
    await coordinator.run(session)

    # Reload from disk to verify refs were persisted
    reloaded = RunSession.load(tmp_path / "runs", session.run_id)
    all_nodes = reloaded.tree.get_all_nodes()
    done_nodes = [n for n in all_nodes if n.status == "done"]
    assert len(done_nodes) >= 1
    done_node = done_nodes[0]
    assert done_node.refs == refs, f"Expected refs={refs}, got {done_node.refs}"


# ---------------------------------------------------------------------------
# Regression tests — reviewer-identified bugs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_exception_does_not_escape_run(tmp_path):
    """Executor exceptions must be caught; run() still finalizes the session."""
    from loop_sci.engine.coordinator import Coordinator

    session = _make_session(tmp_path)
    stub = RaisingStubExecutor("boom")
    coordinator = Coordinator(cfg=None, executor=stub, step_budget=5)

    await coordinator.run(session)  # must NOT raise

    assert stub._calls, "Interrupted node must have been dispatched"
    interrupted = session.tree.get_node(stub._calls[0].node_id)
    assert interrupted.status == "needs_retry"
    assert session.is_complete


@pytest.mark.asyncio
async def test_resume_redispatches_interrupted_running_node(tmp_path):
    """A crash-interrupted 'running' node must be re-dispatched on resume."""
    from loop_sci.engine.coordinator import Coordinator

    session = _make_session(tmp_path)
    session.tree.update_node("ROOT", status="done")

    done_id = session.tree.next_child_id("ROOT")
    session.tree.add_node(Node(
        id=done_id, parent_id="ROOT", hypothesis="Already done", depth=1, status="done",
    ))
    running_id = session.tree.next_child_id("ROOT")
    session.tree.add_node(Node(
        id=running_id, parent_id="ROOT", hypothesis="Interrupted", depth=1, status="running",
    ))

    loaded = RunSession.load(tmp_path / "runs", session.run_id)
    stub = StubExecutor([_done_result()])
    coordinator = Coordinator(cfg=None, executor=stub, step_budget=5)
    await coordinator.run(loaded)

    assert [c.node_id for c in stub._calls] == [running_id]
    assert loaded.tree.get_node(running_id).status == "done"
    assert loaded.tree.get_node(done_id).status == "done"
    assert loaded.is_complete


@pytest.mark.asyncio
async def test_observe_picks_siblings_deterministically(tmp_path):
    """Pending sibling pick must be stable (sorted by node id)."""
    from loop_sci.engine.coordinator import Coordinator

    session = _make_session(tmp_path)
    session.tree.update_node("ROOT", status="done")

    ids = []
    for label in ("charlie", "alpha", "bravo"):
        child_id = session.tree.next_child_id("ROOT")
        ids.append(child_id)
        session.tree.add_node(Node(
            id=child_id, parent_id="ROOT", hypothesis=label, depth=1, status="pending",
        ))

    stub = StubExecutor([
        ExecutorResult(status="done", summary="first"),
        ExecutorResult(status="done", summary="second"),
        ExecutorResult(status="done", summary="third"),
    ])
    coordinator = Coordinator(cfg=None, executor=stub, step_budget=1)
    await coordinator.run(session)

    assert stub._calls[0].node_id == sorted(ids)[0]


@pytest.mark.asyncio
async def test_step_budget_kwarg_overrides_cfg(tmp_path):
    """Explicit step_budget kwarg must win over cfg.engine.step_budget."""
    from loop_sci.config.schemas import (
        AgentConf, EngineConf, LoopSCIConfig, ProviderConf, RunConf,
    )
    from loop_sci.engine.coordinator import Coordinator

    cfg = LoopSCIConfig(
        provider=ProviderConf(model="m", api_key="k", base_url="http://x"),
        agent=AgentConf(),
        engine=EngineConf(step_budget=99),
        run=RunConf(runs_root="runs", task="t"),
    )

    session = _make_session(tmp_path)
    for i in range(3):
        child_id = session.tree.next_child_id("ROOT")
        session.tree.add_node(Node(
            id=child_id, parent_id="ROOT", hypothesis=f"H{i}", depth=1, status="pending",
        ))

    stub = StubExecutor([ExecutorResult(status="done", summary="done")] * 3)
    coordinator = Coordinator(cfg=cfg, executor=stub, step_budget=1)
    await coordinator.run(session)

    assert stub._call_index == 1
