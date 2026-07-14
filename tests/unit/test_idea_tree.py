"""Tests for loop_sci/state/idea_tree.py — TDD RED before implementation."""
from __future__ import annotations

import json
import pytest
from loop_sci.state.idea_tree import Node, IdeaTree, NodeStatus


@pytest.fixture
def tree(tmp_path):
    root = Node(id="ROOT", parent_id=None, hypothesis="root task")
    t = IdeaTree(root=root, json_path=tmp_path / "idea_tree.json")
    return t


def test_add_and_retrieve_node(tree):
    child_id = tree.next_child_id("ROOT")
    child = Node(id=child_id, parent_id="ROOT", hypothesis="child hyp", depth=1)
    tree.add_node(child)
    assert tree.get_node(child_id) is not None
    assert tree.get_node(child_id).hypothesis == "child hyp"


def test_parent_child_relationship(tree):
    child_id = tree.next_child_id("ROOT")
    child = Node(id=child_id, parent_id="ROOT", hypothesis="h", depth=1)
    tree.add_node(child)
    assert child_id in tree.get_root().children_ids


def test_child_id_is_derivable(tree):
    # next_child_id is deterministic: same call on the same tree state gives same id.
    id1 = tree.next_child_id("ROOT")
    assert tree.next_child_id("ROOT") == id1  # idempotent before mutation

    # After adding child with id1, the next id must be different (incremented).
    child = Node(id=id1, parent_id="ROOT", hypothesis="h", depth=1)
    tree.add_node(child)
    id2 = tree.next_child_id("ROOT")
    assert id2 != id1  # advanced by one
    # Calling again without mutation returns the same next id.
    assert tree.next_child_id("ROOT") == id2


def test_persist_reload_equality(tree, tmp_path):
    path = tmp_path / "idea_tree.json"
    child_id = tree.next_child_id("ROOT")
    child = Node(
        id=child_id,
        parent_id="ROOT",
        hypothesis="test hyp",
        depth=1,
        status="done",
        insight="learned x",
    )
    tree.add_node(child)
    tree.update_node(child_id, insight="updated insight")

    tree2 = IdeaTree.load_json(path)
    node2 = tree2.get_node(child_id)
    assert node2 is not None
    assert node2.hypothesis == "test hyp"
    assert node2.insight == "updated insight"
    assert node2.status == "done"


def test_auto_save_on_mutation(tree, tmp_path):
    path = tmp_path / "idea_tree.json"
    assert not path.exists()
    child_id = tree.next_child_id("ROOT")
    child = Node(id=child_id, parent_id="ROOT", hypothesis="h", depth=1)
    tree.add_node(child)  # auto-save must happen here
    assert path.exists()
    data = json.loads(path.read_text())
    assert child_id in data["nodes"]


def test_atomic_write_no_corruption(tree, tmp_path):
    """After a successful save, the canonical file is valid JSON and no .tmp remains."""
    path = tmp_path / "idea_tree.json"
    child_id = tree.next_child_id("ROOT")
    child = Node(id=child_id, parent_id="ROOT", hypothesis="h", depth=1)
    tree.add_node(child)
    # _atomic_write uses path.with_suffix(path.suffix + ".tmp") →
    # for idea_tree.json that is idea_tree.json.tmp
    tmp_file = path.with_suffix(path.suffix + ".tmp")  # idea_tree.json.tmp
    assert not tmp_file.exists(), f"Temp file {tmp_file} should not exist after save"
    # Canonical file is valid JSON
    parsed = json.loads(path.read_text())
    assert isinstance(parsed, dict)


def test_refs_field_round_trips(tmp_path):
    """Node.refs must survive a save → load_json round trip (not just attribute-set)."""
    root = Node(id="ROOT", parent_id=None, hypothesis="root")
    path = tmp_path / "tree.json"
    tree = IdeaTree(root=root, json_path=path)

    child_id = tree.next_child_id("ROOT")
    child = Node(id=child_id, parent_id="ROOT", hypothesis="h", depth=1)
    child.refs = {"branch": "feat/x", "artifact": "s3://bucket/result.json"}
    tree.add_node(child)

    tree2 = IdeaTree.load_json(path)
    node2 = tree2.get_node(child_id)
    assert node2 is not None
    assert node2.refs is not None, "refs must survive save→reload"
    assert node2.refs["branch"] == "feat/x"
    assert node2.refs["artifact"] == "s3://bucket/result.json"


def test_refs_default_is_none():
    """Nodes without refs set have refs=None."""
    node = Node(id="1", parent_id="ROOT", hypothesis="h", depth=1)
    assert node.refs is None


def test_get_pending_leaves(tree):
    child_id = tree.next_child_id("ROOT")
    child = Node(
        id=child_id, parent_id="ROOT", hypothesis="pending h", depth=1, status="pending"
    )
    tree.add_node(child)
    pending = tree.get_pending_leaves()
    assert any(n.id == child_id for n in pending)


def test_node_status_type_exported():
    """NodeStatus is exported from state.idea_tree."""
    assert NodeStatus is not None
