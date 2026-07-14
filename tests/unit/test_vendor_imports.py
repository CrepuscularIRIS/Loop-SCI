"""Smoke-import test for vendored Arbor engine primitives.

TDD: this test is written BEFORE the vendor files are copied.
It must fail RED first, then pass GREEN after vendoring.
"""

from loop_sci._vendor.arbor.llm.base import LLMProvider, LLMResponse
from loop_sci._vendor.arbor.llm.openai_compat import OpenAICompatProvider
from loop_sci._vendor.arbor.events.bus import EventBus, NullBus
from loop_sci._vendor.arbor.idea_tree import IdeaTree, Node


def test_llm_base_symbols_importable() -> None:
    """LLMProvider and LLMResponse are importable from the vendor package."""
    assert LLMProvider is not None
    assert LLMResponse is not None


def test_openai_compat_provider_importable() -> None:
    """OpenAICompatProvider is importable from the vendor package."""
    assert OpenAICompatProvider is not None


def test_event_bus_symbols_importable() -> None:
    """EventBus and NullBus are importable from the vendor package."""
    assert EventBus is not None
    assert NullBus is not None


def test_idea_tree_symbols_importable() -> None:
    """IdeaTree and Node are importable from the vendor package."""
    assert IdeaTree is not None
    assert Node is not None


def test_null_bus_is_usable() -> None:
    """NullBus can be instantiated and methods can be called without error."""
    bus = NullBus()
    bus.emit("test.event", {"key": "value"})
    bus.on("test.event", lambda e: None)


def test_event_bus_is_usable() -> None:
    """EventBus can be instantiated and used as a pub/sub channel."""
    bus = EventBus()
    received = []
    bus.on("test.event", lambda e: received.append(e.data))
    bus.emit("test.event", {"hello": "world"})
    assert received == [{"hello": "world"}]


def test_node_construction() -> None:
    """Node can be constructed with required fields."""
    node = Node(id="ROOT", parent_id=None)
    assert node.id == "ROOT"
    assert node.status == "pending"


def test_idea_tree_construction() -> None:
    """IdeaTree can be constructed with a root node."""
    root = Node(id="ROOT", parent_id=None)
    tree = IdeaTree(root=root)
    assert tree.get_root().id == "ROOT"
