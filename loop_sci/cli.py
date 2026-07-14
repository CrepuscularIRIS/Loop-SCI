"""CLI entry point: run / resume / inspect.

Entry point registered as ``loop-sci`` in pyproject.toml:
    [project.scripts]
    loop-sci = "loop_sci.cli:app"

Commands
--------
run --task TEXT [--config KEY=VAL ...] [--runs-root DIR] [-v]
    Load config, build provider, create a RunSession, build a Coordinator,
    run the loop, print a short result summary.  Fail fast (nonzero + clean
    message) when DASHSCOPE_API_KEY is missing.

resume RUN_ID [--config KEY=VAL ...] [--runs-root DIR] [-v]
    Load the existing RunSession and continue the coordinator.  No-op when
    the session is already complete.

inspect RUN_ID [--runs-root DIR]
    Load the session and print the idea-tree/status WITHOUT running anything.

Async note
----------
Coordinator.run is async.  Each command that calls it wraps with
``asyncio.run(coordinator.run(session))``.

Logging
-------
``_setup_logging()`` is called per-command so that the module-level import
never pollutes the root logger (keeps tests pristine).  Callers that want
structured output use typer.echo(); diagnostics use the module-level ``log``.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv

load_dotenv()

app = typer.Typer(name="loop-sci", help="Loop-SCI multi-agent research harness.")
log = logging.getLogger("loop_sci.cli")


# ---------------------------------------------------------------------------
# Logging setup — called per command, never at module import time
# ---------------------------------------------------------------------------


def _setup_logging(verbose: bool = False) -> None:
    """Configure root logger.  Safe to call multiple times (idempotent)."""
    if logging.root.handlers:
        return  # already configured (e.g. during pytest)
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=level,
        stream=sys.stderr,
    )


# ---------------------------------------------------------------------------
# Shared setup helper — builds Coordinator from cfg
# ---------------------------------------------------------------------------


def _build_coordinator_and_session(cfg):  # type: ignore[no-untyped-def]
    """Build and return a Coordinator wired to the resolved provider.

    Raises
    ------
    typer.Exit
        If DASHSCOPE_API_KEY is missing (AuthError from resolve_key).
    """
    from loop_sci.provider.credentials import resolve_key
    from loop_sci.provider.errors import AuthError
    from loop_sci.provider.factory import build_provider
    from loop_sci.engine import Coordinator, Executor

    # Resolve the API key; fail fast with a clean error if absent.
    try:
        api_key = cfg.provider.api_key or resolve_key("DASHSCOPE_API_KEY")
    except AuthError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    provider = build_provider(
        model=cfg.provider.model,
        api_key=api_key,
        base_url=cfg.provider.base_url,
        timeout=cfg.provider.timeout,
        max_retries=cfg.provider.max_retries,
    )

    executor = Executor(cfg, provider=provider)
    coordinator = Coordinator(cfg=cfg, executor=executor, step_budget=cfg.engine.step_budget)
    return coordinator


# ---------------------------------------------------------------------------
# Helper: load config
# ---------------------------------------------------------------------------


def _load_cfg(overrides: list[str]):
    from loop_sci.config.loader import load_config

    return load_config(
        config_dir=str(Path(__file__).parent.parent / "conf"),
        overrides=overrides,
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command()
def run(
    task: str = typer.Option(..., "--task", "-t", help="Research task description."),
    runs_root: str = typer.Option("runs", "--runs-root", help="Root directory for run sessions."),
    config: Optional[list[str]] = typer.Option(
        None, "--config", "-c", help="Hydra overrides (key=value)."
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Start a new run against the given task."""
    _setup_logging(verbose)
    from loop_sci.state.session import RunSession

    overrides = list(config or [])
    cfg = _load_cfg(overrides)
    cfg.run.task = task
    cfg.run.runs_root = runs_root

    session = RunSession.create(cfg.run.runs_root, task=cfg.run.task)
    typer.echo(f"Started run: {session.run_id}")
    typer.echo(f"Session dir: {session.session_dir}")

    coordinator = _build_coordinator_and_session(cfg)
    asyncio.run(coordinator.run(session))

    typer.echo(f"Run complete.")
    typer.echo(f"  run_id : {session.run_id}")
    typer.echo(f"  status : {session.cursor.get('status')}")
    typer.echo(f"  steps  : {session.cursor.get('step', 0)}")


@app.command()
def resume(
    run_id: str = typer.Argument(..., help="Run ID to resume."),
    runs_root: str = typer.Option("runs", "--runs-root"),
    config: Optional[list[str]] = typer.Option(None, "--config", "-c"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Resume an interrupted run from its last checkpoint."""
    _setup_logging(verbose)
    from loop_sci.state.session import RunSession

    overrides = list(config or [])
    cfg = _load_cfg(overrides)
    cfg.run.runs_root = runs_root

    session = RunSession.load(runs_root, run_id)
    if session.is_complete:
        typer.echo(f"Run {run_id} is already complete. Nothing to resume.")
        raise typer.Exit(0)

    typer.echo(f"Resuming run: {run_id} (step {session.cursor.get('step', 0)})")
    coordinator = _build_coordinator_and_session(cfg)
    asyncio.run(coordinator.run(session))

    typer.echo(f"Resume complete.")
    typer.echo(f"  run_id : {session.run_id}")
    typer.echo(f"  status : {session.cursor.get('status')}")
    typer.echo(f"  steps  : {session.cursor.get('step', 0)}")


@app.command()
def inspect(
    run_id: str = typer.Argument(..., help="Run ID to inspect."),
    runs_root: str = typer.Option("runs", "--runs-root"),
) -> None:
    """Print the idea tree and cursor for a run WITHOUT running anything."""
    from loop_sci.state.session import RunSession

    session = RunSession.load(runs_root, run_id)
    typer.echo(f"Run ID:  {session.run_id}")
    typer.echo(f"Status:  {session.cursor.get('status')}")
    typer.echo(f"Steps:   {session.cursor.get('step', 0)}")
    typer.echo(f"Task:    {session.cursor.get('task', '')}")
    typer.echo("")
    typer.echo(session.tree.to_compact_summary())
