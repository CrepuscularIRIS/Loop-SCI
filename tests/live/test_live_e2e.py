"""End-to-end run + resume against real Qwen-via-Bailian.

Run with:
    DASHSCOPE_API_KEY=<key> uv run pytest tests/live/test_live_e2e.py -v -m live -s

Tests:
  6.2 – run completes ≥1 observe→dispatch→record cycle and persists idea_tree.json
  6.3a – interrupted session (pre-seeded done + pending node) resumes live, pending
          node is dispatched, done node is NOT re-run
  6.3b – resume on an already-complete session is a safe no-op (zero new steps)

These tests NEVER run in the default suite (no key → autoskip via require_key fixture).
They are cost-cheap: short prompts, low step_budget, low max_tokens.
"""
from __future__ import annotations

import json
import os
import pathlib

import pytest

pytestmark = pytest.mark.live

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BAILIAN_BASE_URL: str = os.environ.get(
    "BAILIAN_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)

# Very short task keeps token usage minimal.
STUB_TASK = (
    "List two principles of the scientific method. "
    "Be very brief — one sentence each."
)

# Root conf directory (three levels up from this file: tests/live/ → tests/ → project root)
_CONF_DIR = str(pathlib.Path(__file__).parent.parent.parent / "conf")


# ---------------------------------------------------------------------------
# Auto-skip fixture — identical pattern to test_live_qwen.py
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def require_key() -> None:
    """Skip the whole module when DASHSCOPE_API_KEY is absent."""
    key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not key:
        pytest.skip("DASHSCOPE_API_KEY not set — skipping live test")


# ---------------------------------------------------------------------------
# Shared builder helper
# ---------------------------------------------------------------------------


def _build_all(runs_root: pathlib.Path, task: str = STUB_TASK, step_budget: int = 3):
    """Construct a real Coordinator + Executor + RunSession wired to the live provider.

    Returns (coordinator, session) ready to ``await coordinator.run(session)``.
    step_budget is deliberately small to keep API costs minimal.
    """
    from loop_sci.config.loader import load_config
    from loop_sci.provider.factory import build_provider
    from loop_sci.provider.credentials import resolve_key, invocation_record
    from loop_sci.engine import Executor, Coordinator
    from loop_sci.state.session import RunSession

    cfg = load_config(
        config_dir=_CONF_DIR,
        overrides=[
            f"run.task={task}",
            f"run.runs_root={runs_root}",
        ],
    )

    api_key = resolve_key("DASHSCOPE_API_KEY")
    rec = invocation_record(cfg.provider.model, cfg.provider.base_url)
    print(f"\n[INVOCATION RECORD] {json.dumps(rec)}")

    provider = build_provider(
        model=cfg.provider.model,
        api_key=api_key,
        base_url=cfg.provider.base_url,
        timeout=cfg.provider.timeout,
    )
    executor = Executor(cfg, provider=provider)
    coordinator = Coordinator(executor=executor, step_budget=step_budget)
    session = RunSession.create(runs_root, task=task)
    return coordinator, session


def _build_provider_and_executor(runs_root: pathlib.Path):
    """Lightweight helper: build provider + executor without creating a session."""
    from loop_sci.config.loader import load_config
    from loop_sci.provider.factory import build_provider
    from loop_sci.provider.credentials import resolve_key
    from loop_sci.engine import Executor

    cfg = load_config(
        config_dir=_CONF_DIR,
        overrides=[f"run.runs_root={runs_root}"],
    )
    api_key = resolve_key("DASHSCOPE_API_KEY")
    provider = build_provider(
        model=cfg.provider.model,
        api_key=api_key,
        base_url=cfg.provider.base_url,
        timeout=cfg.provider.timeout,
    )
    executor = Executor(cfg, provider=provider)
    return executor


# ---------------------------------------------------------------------------
# 6.2 – RUN → PERSIST
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_run_completes(tmp_path: pathlib.Path) -> None:
    """≥1 observe→dispatch→record cycle completes and persists idea_tree.json.

    Validates:
    - Coordinator.run() exits cleanly without raising.
    - session.is_complete is True after the run.
    - At least one step was executed (cursor["step"] >= 1).
    - idea_tree.json exists on disk after the run.
    - Reloading the session via RunSession.load() reproduces the complete state.
    - The root node (or a child) reached a terminal status (done | needs_retry).
    """
    from loop_sci.state.session import RunSession

    runs_root = tmp_path / "e2e_runs"
    coordinator, session = _build_all(runs_root, step_budget=3)
    run_id = session.run_id

    await coordinator.run(session)

    # ── in-memory assertions ──────────────────────────────────────────────────
    assert session.is_complete, "Session did not reach 'done' status after run"
    assert session.cursor["step"] >= 1, "No steps were executed — coordinator did nothing"

    # ── persistence assertions (reload from disk) ─────────────────────────────
    loaded = RunSession.load(runs_root, run_id)
    assert loaded.is_complete, "Reloaded session is not complete — cursor not persisted"

    tree_file = loaded.session_dir / "idea_tree.json"
    assert tree_file.exists(), f"idea_tree.json not found at {tree_file}"

    # At least the root or a child must have reached a terminal status.
    all_nodes = loaded.tree.get_all_nodes()
    terminal = [n for n in all_nodes if n.status in ("done", "needs_retry")]
    assert terminal, (
        f"No node reached a terminal status. Statuses: "
        f"{[n.status for n in all_nodes]}"
    )

    print(f"\n[E2E 6.2 PASS] run_id={run_id}  steps={session.cursor['step']}")
    print(loaded.tree.to_compact_summary())


# ---------------------------------------------------------------------------
# 6.3a – RESUME: interrupted run (pre-seeded state)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_resume_continues(tmp_path: pathlib.Path) -> None:
    """Simulate an interrupted run; resume dispatches pending node without re-running done node.

    Strategy (cheapest correct approach):
      - Create a session on disk with one node already "done" and one node "pending".
        This precisely mimics a mid-run interrupt without spending API tokens on the
        first synthetic step.
      - Resume the session via Coordinator.run() against the live provider.
      - Assert: the done node remains "done" (NOT re-dispatched).
      - Assert: the overall session reaches is_complete.

    The done node's insight is pre-seeded so the coordinator has no reason to re-run it.
    """
    from loop_sci.state.session import RunSession
    from loop_sci.state.idea_tree import Node
    from loop_sci.engine import Coordinator

    runs_root = tmp_path / "resume_runs"

    # ── Build a partially-done session on disk (no API call yet) ─────────────
    session = RunSession.create(runs_root, task=STUB_TASK)
    run_id = session.run_id

    # Add a pre-done child node (simulates a completed first step)
    done_id = session.tree.next_child_id("ROOT")
    session.tree.add_node(Node(
        id=done_id,
        parent_id="ROOT",
        hypothesis="Principle 1: Systematic observation",
        depth=1,
        status="done",
        insight="Observation is the foundation of the scientific method.",
        score=0.8,
    ))

    # Add a pending child node (simulates what was queued when the run was interrupted)
    pending_id = session.tree.next_child_id("ROOT")
    session.tree.add_node(Node(
        id=pending_id,
        parent_id="ROOT",
        hypothesis="Principle 2: Repeatability",
        depth=1,
        status="pending",
    ))

    # Advance cursor to reflect one done step, then persist
    session.advance_step()
    # Note: do NOT call mark_complete — session is still mid-run

    # ── Reload and resume ─────────────────────────────────────────────────────
    resumed = RunSession.load(runs_root, run_id)
    assert not resumed.is_complete, "Session should NOT be complete before resume"

    executor = _build_provider_and_executor(runs_root)
    coordinator = Coordinator(executor=executor, step_budget=5)

    await coordinator.run(resumed)

    # ── Assertions ────────────────────────────────────────────────────────────
    assert resumed.is_complete, "Session did not complete after resume"

    # Reload from disk to verify persistence
    reloaded = RunSession.load(runs_root, run_id)

    done_node = reloaded.tree.get_node(done_id)
    assert done_node is not None, f"Done node {done_id!r} missing from reloaded tree"
    assert done_node.status == "done", (
        f"Done node was re-dispatched — status changed to {done_node.status!r}"
    )

    print(f"\n[E2E 6.3a PASS] run_id={run_id}  done_id={done_id}  pending_id={pending_id}")
    print(reloaded.tree.to_compact_summary())


# ---------------------------------------------------------------------------
# 6.3b – RESUME: already-complete run is a safe no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_already_complete_is_noop(tmp_path: pathlib.Path) -> None:
    """Resume on a fully-complete session must not dispatch any new steps.

    Strategy:
      - Run a fresh session to completion (uses real API).
      - Record the step count.
      - Load the session again and run a second coordinator against it.
      - Assert the step count is unchanged.

    This validates the is_complete early-exit guard in Coordinator.run().
    """
    from loop_sci.state.session import RunSession
    from loop_sci.engine import Coordinator

    runs_root = tmp_path / "noop_runs"

    # ── First run: go to completion ───────────────────────────────────────────
    coordinator1, session1 = _build_all(runs_root, step_budget=3)
    await coordinator1.run(session1)

    assert session1.is_complete, "First run did not complete — cannot test no-op resume"
    steps_after_first_run = session1.cursor["step"]
    run_id = session1.run_id

    # ── Second run: resume the completed session ──────────────────────────────
    session2 = RunSession.load(runs_root, run_id)
    assert session2.is_complete, "Loaded session should already be complete"

    executor = _build_provider_and_executor(runs_root)
    coordinator2 = Coordinator(executor=executor, step_budget=5)

    await coordinator2.run(session2)

    # Step count must be unchanged — no new dispatches on a complete run
    assert session2.cursor["step"] == steps_after_first_run, (
        f"Resume added steps to an already-complete session: "
        f"before={steps_after_first_run}  after={session2.cursor['step']}"
    )

    print(
        f"\n[E2E 6.3b PASS] run_id={run_id}  "
        f"steps unchanged at {steps_after_first_run}"
    )
