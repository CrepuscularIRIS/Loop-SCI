"""Tests for RunSession (Task 8): checkpoint and resume."""
import pytest
from pathlib import Path
from loop_sci.state.session import RunSession


@pytest.fixture
def runs_root(tmp_path):
    return tmp_path / "runs"


def test_create_session(runs_root):
    session = RunSession.create(runs_root, task="test task")
    assert session.session_dir.exists()
    assert (session.session_dir / "idea_tree.json").exists()
    assert (session.session_dir / "run.json").exists()
    assert session.cursor["status"] == "running"
    assert session.cursor["step"] == 0


def test_load_session_equals_created(runs_root):
    session = RunSession.create(runs_root, task="test task")
    run_id = session.run_id
    loaded = RunSession.load(runs_root, run_id)
    assert loaded.run_id == run_id
    assert loaded.cursor["status"] == "running"
    assert loaded.tree.get_root().hypothesis == "test task"


def test_advance_step_persists(runs_root):
    session = RunSession.create(runs_root, task="task")
    session.advance_step()
    session.advance_step()
    loaded = RunSession.load(runs_root, session.run_id)
    assert loaded.cursor["step"] == 2


def test_mark_complete(runs_root):
    session = RunSession.create(runs_root, task="task")
    session.mark_complete()
    assert session.is_complete
    loaded = RunSession.load(runs_root, session.run_id)
    assert loaded.is_complete
    assert loaded.cursor["status"] == "done"


def test_resume_continues_from_checkpoint(runs_root):
    """Resume picks up pending nodes without restarting completed ones."""
    from loop_sci.state.idea_tree import Node
    session = RunSession.create(runs_root, task="task")
    # Add two nodes: one done, one pending
    done_id = session.tree.next_child_id("ROOT")
    session.tree.add_node(Node(id=done_id, parent_id="ROOT", hypothesis="done h", depth=1, status="done"))
    pending_id = session.tree.next_child_id("ROOT")
    session.tree.add_node(Node(id=pending_id, parent_id="ROOT", hypothesis="pending h", depth=1, status="pending"))

    loaded = RunSession.load(runs_root, session.run_id)
    pending_leaves = loaded.tree.get_pending_leaves()
    assert any(n.id == pending_id for n in pending_leaves)
    done_nodes = [n for n in loaded.tree.get_all_nodes() if n.status == "done"]
    assert any(n.id == done_id for n in done_nodes)


def test_resume_already_complete_is_noop(runs_root):
    """Resuming a complete run reports completion without re-executing work."""
    session = RunSession.create(runs_root, task="task")
    session.mark_complete()

    loaded = RunSession.load(runs_root, session.run_id)
    assert loaded.is_complete
    # No pending leaves — nothing to re-execute
    assert loaded.tree.get_pending_leaves() == []
