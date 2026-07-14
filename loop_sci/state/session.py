"""RunSession: per-run directory, tree, cursor, checkpoint, resume."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from .idea_tree import IdeaTree, Node


class RunSession:
    """Owns a run directory: idea_tree.json, run.json cursor, logs/.

    Lifecycle:
        session = RunSession.create(runs_root, task="my task")
        # ... do work, advance steps, tree mutations ...
        session.advance_step()
        session.mark_complete()

        # Later: reload and resume
        loaded = RunSession.load(runs_root, run_id)
        if loaded.is_complete:
            return  # safe no-op

    Cursor persistence uses atomic temp-file-then-replace to avoid corruption
    on partial writes (power loss, signal, etc.).
    """

    def __init__(
        self,
        *,
        run_id: str,
        session_dir: Path,
        tree: IdeaTree,
        cursor: dict[str, Any],
    ) -> None:
        self.run_id = run_id
        self.session_dir = session_dir
        self.tree = tree
        self.cursor = cursor

    # ── Factory ──────────────────────────────────────────────────────────────

    @classmethod
    def create(
        cls,
        runs_root: str | Path,
        task: str,
        run_id: str | None = None,
    ) -> "RunSession":
        """Create a fresh run session directory and return the session.

        Args:
            runs_root: Parent directory that holds all run subdirectories.
            task: The top-level hypothesis / task description for this run.
            run_id: Optional explicit run identifier. Auto-generated if None.

        Returns:
            A new RunSession backed by files on disk.
        """
        rid = run_id or f"run_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        session_dir = Path(runs_root) / rid
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "logs").mkdir(exist_ok=True)

        root = Node(id="ROOT", parent_id=None, hypothesis=task, depth=0, status="pending")
        tree = IdeaTree(root=root, json_path=session_dir / "idea_tree.json")
        tree.save()

        cursor: dict[str, Any] = {"status": "running", "step": 0, "task": task}
        _write_cursor(session_dir / "run.json", cursor)

        return cls(run_id=rid, session_dir=session_dir, tree=tree, cursor=cursor)

    @classmethod
    def load(cls, runs_root: str | Path, run_id: str) -> "RunSession":
        """Load an existing session from disk.

        If the session was already marked complete, ``is_complete`` will be
        True and ``tree.get_pending_leaves()`` will return an empty list,
        making a resume a safe no-op: callers check ``is_complete`` first and
        skip re-execution.

        Args:
            runs_root: Parent directory that holds all run subdirectories.
            run_id: The run identifier to load.

        Returns:
            A RunSession reconstructed from disk state.
        """
        session_dir = Path(runs_root) / run_id
        tree = IdeaTree.load_json(session_dir / "idea_tree.json")
        cursor = json.loads((session_dir / "run.json").read_text(encoding="utf-8"))
        return cls(run_id=run_id, session_dir=session_dir, tree=tree, cursor=cursor)

    # ── Cursor ───────────────────────────────────────────────────────────────

    @property
    def is_complete(self) -> bool:
        """True when the cursor status is "done"."""
        return self.cursor.get("status") == "done"

    def advance_step(self) -> None:
        """Increment the step counter and atomically persist the cursor."""
        self.cursor["step"] = self.cursor.get("step", 0) + 1
        _write_cursor(self.session_dir / "run.json", self.cursor)

    def mark_complete(self) -> None:
        """Set cursor status to "done" and atomically persist."""
        self.cursor["status"] = "done"
        _write_cursor(self.session_dir / "run.json", self.cursor)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _write_cursor(path: Path, cursor: dict[str, Any]) -> None:
    """Atomic write of run.json cursor using temp-file + os.replace.

    Writes to a sibling .tmp file first, then uses Path.replace() (which
    calls os.replace on POSIX) to atomically swap it into place.  This
    guarantees that a reader always sees either the previous complete JSON
    or the new complete JSON — never a partial write.
    """
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cursor, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
