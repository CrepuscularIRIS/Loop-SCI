"""Tests for register_plan_tools — Task 6."""
from __future__ import annotations

import json

import pytest

from loop_sci.engine.tools import ToolRegistry
from loop_sci.plan.tools import register_plan_tools


@pytest.mark.asyncio
async def test_assemble_tool_offline_no_executor_structured_error():
    reg = ToolRegistry()
    register_plan_tools(reg, executor=None)
    out = await reg.dispatch("assemble", {"node_id": "hyp_node1"})
    assert "error" in json.loads(out)
