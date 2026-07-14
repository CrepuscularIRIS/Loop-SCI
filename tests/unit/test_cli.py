"""Tests for loop_sci/cli.py — CLI commands: run / resume / inspect.

TDD: tests written BEFORE production code (RED phase first).

Test strategy:
  - All tests are offline (no network, no DASHSCOPE_API_KEY required).
  - MockProvider from conftest.py is injected via monkeypatching build_provider
    so that the `run` happy-path is offline too.
  - `inspect` creates a session in-test via RunSession.create() and verifies
    that the CLI output shows run_id, root task, and status.
  - `resume` on a pre-created COMPLETE session verifies it exits 0 and reports
    completion without running anything.
  - `run` MISSING-KEY path: monkeypatches DASHSCOPE_API_KEY away and verifies
    a nonzero exit with a readable message (not a raw traceback).
  - `run` happy path: monkeypatches build_provider to return MockProvider so
    no real API key is required.

Logging note: tests suppress all log output via capfd / the logging
NullHandler so the test output is pristine.
"""
from __future__ import annotations

import asyncio
import logging
import os

import pytest
from typer.testing import CliRunner

# Silence all logging during tests to keep output pristine.
logging.disable(logging.CRITICAL)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_runner() -> CliRunner:
    return CliRunner()


def _make_session(tmp_path, task: str = "test hypothesis"):
    """Create a fresh RunSession on disk."""
    from loop_sci.state.session import RunSession
    return RunSession.create(str(tmp_path / "runs"), task=task)


# ---------------------------------------------------------------------------
# inspect — reads an existing session, prints summary, no coordinator run
# ---------------------------------------------------------------------------


def test_inspect_shows_run_id_and_task(tmp_path):
    """inspect on a session created in-test shows run_id, task, and status."""
    from loop_sci.cli import app

    session = _make_session(tmp_path, task="test hypothesis for inspect")
    runner = _make_runner()

    result = runner.invoke(
        app,
        ["inspect", session.run_id, "--runs-root", str(tmp_path / "runs")],
    )

    assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}.\nOutput:\n{result.output}"
    assert session.run_id in result.output, f"run_id not in output: {result.output}"
    assert "test hypothesis for inspect" in result.output, f"task not in output: {result.output}"
    assert "running" in result.output, f"status 'running' not in output: {result.output}"


def test_inspect_shows_status_field(tmp_path):
    """inspect output contains a Status: line."""
    from loop_sci.cli import app

    session = _make_session(tmp_path, task="some task")
    runner = _make_runner()

    result = runner.invoke(
        app,
        ["inspect", session.run_id, "--runs-root", str(tmp_path / "runs")],
    )

    assert result.exit_code == 0
    assert "Status:" in result.output, f"'Status:' label missing. Output:\n{result.output}"


def test_inspect_on_complete_session(tmp_path):
    """inspect on a completed session shows 'done' status."""
    from loop_sci.cli import app
    from loop_sci.state.session import RunSession

    session = _make_session(tmp_path, task="completed task")
    session.mark_complete()

    runner = _make_runner()
    result = runner.invoke(
        app,
        ["inspect", session.run_id, "--runs-root", str(tmp_path / "runs")],
    )

    assert result.exit_code == 0
    assert "done" in result.output, f"'done' not found. Output:\n{result.output}"


# ---------------------------------------------------------------------------
# resume — pre-created COMPLETE session: exits 0, reports "already complete"
# ---------------------------------------------------------------------------


def test_resume_already_complete_session_exits_0(tmp_path):
    """resume on an already-complete session reports completion and exits 0."""
    from loop_sci.cli import app

    session = _make_session(tmp_path, task="completed research")
    session.mark_complete()

    runner = _make_runner()
    result = runner.invoke(
        app,
        ["resume", session.run_id, "--runs-root", str(tmp_path / "runs")],
    )

    assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}.\nOutput:\n{result.output}"
    assert "complete" in result.output.lower(), (
        f"Expected 'complete' in output. Got:\n{result.output}"
    )


def test_resume_incomplete_session_with_stub(tmp_path, monkeypatch):
    """resume on an incomplete session runs the coordinator and exits 0."""
    from loop_sci.cli import app

    session = _make_session(tmp_path, task="incomplete research")
    runs_root = str(tmp_path / "runs")
    run_id = session.run_id

    # Inject a stub coordinator so no real provider is needed.
    class _DoneCoordinator:
        async def run(self, session):
            session.mark_complete()

    import loop_sci.cli as cli_mod
    monkeypatch.setattr(cli_mod, "_build_coordinator_and_session", lambda cfg: _DoneCoordinator())

    runner = _make_runner()
    result = runner.invoke(
        app,
        ["resume", run_id, "--runs-root", runs_root],
    )

    assert result.exit_code == 0, f"Expected exit 0. Output:\n{result.output}"
    # After resume completes, output should mention completion.
    assert "complete" in result.output.lower() or run_id in result.output, (
        f"Unexpected output:\n{result.output}"
    )


# ---------------------------------------------------------------------------
# run — MISSING-KEY path: AuthError → clean error + nonzero exit
# ---------------------------------------------------------------------------


def test_run_missing_api_key_exits_nonzero(tmp_path, monkeypatch):
    """run with DASHSCOPE_API_KEY unset must exit nonzero with a clear message."""
    from loop_sci.cli import app

    # Ensure key is absent.
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    runner = _make_runner()
    result = runner.invoke(
        app,
        ["run", "--task", "test task", "--runs-root", str(tmp_path / "runs")],
    )

    assert result.exit_code != 0, (
        f"Expected nonzero exit when API key is missing, got 0.\nOutput:\n{result.output}"
    )
    # Output should contain a human-readable message, NOT a raw Python traceback.
    assert "DASHSCOPE_API_KEY" in result.output or "API key" in result.output.lower(), (
        f"Expected clear missing-key message. Got:\n{result.output}"
    )
    # Verify no raw traceback leaks (no "Traceback (most recent call last)")
    assert "Traceback (most recent call last)" not in result.output, (
        f"Raw traceback leaked to user. Got:\n{result.output}"
    )


# ---------------------------------------------------------------------------
# run — happy path with MockProvider injection (offline)
# ---------------------------------------------------------------------------


def test_run_happy_path_with_mock_provider(tmp_path, monkeypatch):
    """run with a mocked provider completes and prints run_id."""
    from loop_sci.cli import app
    from tests.conftest import MockProvider

    # Ensure key is absent so we rely purely on the mock.
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    # Patch build_provider in cli module to return MockProvider.
    import loop_sci.cli as cli_mod

    def _stub_coordinator(cfg):
        """Return a stub coordinator that immediately marks session complete."""
        class _DoneCoordinator:
            async def run(self, session):
                session.mark_complete()
        return _DoneCoordinator()

    monkeypatch.setattr(cli_mod, "_build_coordinator_and_session", _stub_coordinator)

    runner = _make_runner()
    result = runner.invoke(
        app,
        ["run", "--task", "offline test task", "--runs-root", str(tmp_path / "runs")],
    )

    assert result.exit_code == 0, f"Expected exit 0. Output:\n{result.output}"
    # Output should contain "Started run:" and a run_id.
    assert "Started run:" in result.output, f"'Started run:' missing. Output:\n{result.output}"
