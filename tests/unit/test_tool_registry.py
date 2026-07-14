"""Tests for ToolRegistry — written BEFORE implementation (TDD RED phase)."""
import json

import pytest

from loop_sci.engine.tools import ToolRegistry


@pytest.fixture
def registry():
    r = ToolRegistry()
    r.register(
        name="add",
        description="Add two integers",
        schema={
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
        },
        fn=lambda a, b: str(a + b),
    )
    return r


def test_get_definitions(registry):
    defs = registry.get_definitions()
    assert len(defs) == 1
    assert defs[0]["name"] == "add"
    assert "input_schema" in defs[0]


@pytest.mark.asyncio
async def test_dispatch_known(registry):
    result = await registry.dispatch("add", {"a": 2, "b": 3})
    assert result == "5"


@pytest.mark.asyncio
async def test_dispatch_unknown_returns_structured_error(registry):
    result = await registry.dispatch("nonexistent", {})
    data = json.loads(result)
    assert data["error"] == "unknown_tool"
    assert "nonexistent" in data["tool"]


@pytest.mark.asyncio
async def test_dispatch_malformed_args_returns_error(registry):
    # Pass wrong type — fn should be wrapped so exceptions become structured errors
    result = await registry.dispatch("add", {"a": "not_int", "b": 1})
    # Should not raise; returns a structured error string
    assert "error" in result


@pytest.mark.asyncio
async def test_dispatch_async_fn(registry):
    """Async tool functions must also be supported."""

    async def async_multiply(x: int, y: int) -> str:
        return str(x * y)

    registry.register(
        name="multiply",
        description="Multiply two integers",
        schema={
            "type": "object",
            "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
            "required": ["x", "y"],
        },
        fn=async_multiply,
    )
    result = await registry.dispatch("multiply", {"x": 3, "y": 4})
    assert result == "12"


@pytest.mark.asyncio
async def test_dispatch_unknown_includes_available_tools(registry):
    """Unknown-tool error must list available tool names."""
    result = await registry.dispatch("ghost", {})
    data = json.loads(result)
    assert data["error"] == "unknown_tool"
    assert "add" in data["available"]
