"""Tests for loop_sci/engine/agent_runtime.py and loop_sci/engine/types.py.

TDD: tests written BEFORE production code.

Contracts tested:
  1. build_agent returns a vendored Agent instance.
  2. The built agent's config.auto_git is False (HARD REQUIREMENT).
  3. tools default to an empty list when not supplied.
  4. A supplied stub provider is used (not constructed internally).
  5. An EventBus/bus is wired through to config.event_bus.
  6. DispatchUnit and ExecutorResult are importable and behave as dataclasses.
  7. hydra_cfg_to_agent_config returns an AgentConfig with auto_git=False.
"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Types: DispatchUnit and ExecutorResult
# ---------------------------------------------------------------------------


def test_dispatch_unit_importable():
    from loop_sci.engine.types import DispatchUnit
    du = DispatchUnit(node_id="n1", goal="do something")
    assert du.node_id == "n1"
    assert du.goal == "do something"
    assert du.context == ""
    assert du.tools == []


def test_dispatch_unit_with_tools():
    from loop_sci.engine.types import DispatchUnit
    tools = [{"name": "bash", "description": "run bash"}]
    du = DispatchUnit(node_id="n2", goal="run tests", context="ctx", tools=tools)
    assert du.tools == tools


def test_executor_result_importable():
    from loop_sci.engine.types import ExecutorResult
    er = ExecutorResult(status="done", summary="All good")
    assert er.status == "done"
    assert er.summary == "All good"
    assert er.score is None
    assert er.insight == ""
    assert er.refs == {}


def test_executor_result_all_fields():
    from loop_sci.engine.types import ExecutorResult
    er = ExecutorResult(
        status="bounded_exit",
        summary="Hit turn limit",
        score=0.75,
        insight="Used 20 turns",
        refs={"node": "n3"},
    )
    assert er.status == "bounded_exit"
    assert er.score == 0.75
    assert er.refs["node"] == "n3"


def test_executor_result_error_status():
    from loop_sci.engine.types import ExecutorResult
    er = ExecutorResult(status="error", summary="Provider failed")
    assert er.status == "error"


# ---------------------------------------------------------------------------
# Stub helpers
# ---------------------------------------------------------------------------


def _make_stub_provider():
    """Return a minimal stub LLMProvider (no network calls)."""
    from unittest.mock import MagicMock
    from loop_sci._vendor.arbor.llm.base import LLMProvider

    stub = MagicMock(spec=LLMProvider)
    stub.model = "qwen-stub"
    return stub


def _make_minimal_cfg():
    """Return a minimal LoopSCIConfig suitable for hydra_cfg_to_agent_config."""
    from loop_sci.config.schemas import LoopSCIConfig
    return LoopSCIConfig()  # all defaults


# ---------------------------------------------------------------------------
# engine.__init__ re-exports
# ---------------------------------------------------------------------------


def test_engine_init_exports_build_agent():
    from loop_sci.engine import build_agent  # noqa: F401


def test_engine_init_exports_types():
    from loop_sci.engine import DispatchUnit, ExecutorResult  # noqa: F401


# ---------------------------------------------------------------------------
# hydra_cfg_to_agent_config
# ---------------------------------------------------------------------------


def test_hydra_cfg_to_agent_config_auto_git_false():
    from loop_sci.engine.agent_runtime import hydra_cfg_to_agent_config
    cfg = _make_minimal_cfg()
    agent_cfg = hydra_cfg_to_agent_config(cfg)
    assert agent_cfg.auto_git is False, "auto_git MUST be False — GitManager must never run"


def test_hydra_cfg_to_agent_config_returns_agent_config():
    from loop_sci.engine.agent_runtime import hydra_cfg_to_agent_config
    from loop_sci._vendor.arbor.config import AgentConfig
    cfg = _make_minimal_cfg()
    agent_cfg = hydra_cfg_to_agent_config(cfg)
    assert isinstance(agent_cfg, AgentConfig)


def test_hydra_cfg_to_agent_config_wires_bus():
    from loop_sci.engine.agent_runtime import hydra_cfg_to_agent_config
    from loop_sci.events import NullBus
    cfg = _make_minimal_cfg()
    bus = NullBus()
    agent_cfg = hydra_cfg_to_agent_config(cfg, bus=bus)
    assert agent_cfg.event_bus is bus


def test_hydra_cfg_to_agent_config_node_id():
    from loop_sci.engine.agent_runtime import hydra_cfg_to_agent_config
    cfg = _make_minimal_cfg()
    agent_cfg = hydra_cfg_to_agent_config(cfg, node_id="node-42", agent_label="executor")
    assert agent_cfg.node_id == "node-42"
    assert agent_cfg.agent_label == "executor"


# ---------------------------------------------------------------------------
# build_agent
# ---------------------------------------------------------------------------


def test_build_agent_returns_vendor_agent():
    from loop_sci.engine.agent_runtime import build_agent
    from loop_sci._vendor.arbor.agent import Agent
    provider = _make_stub_provider()
    cfg = _make_minimal_cfg()
    agent = build_agent(cfg, provider=provider)
    assert isinstance(agent, Agent)


def test_build_agent_auto_git_false():
    """The built agent's config.auto_git MUST be False."""
    from loop_sci.engine.agent_runtime import build_agent
    provider = _make_stub_provider()
    cfg = _make_minimal_cfg()
    agent = build_agent(cfg, provider=provider)
    assert agent.config.auto_git is False


def test_build_agent_uses_supplied_provider():
    """The stub provider we supply is the one wired into the Agent."""
    from loop_sci.engine.agent_runtime import build_agent
    provider = _make_stub_provider()
    cfg = _make_minimal_cfg()
    agent = build_agent(cfg, provider=provider)
    assert agent.provider is provider


def test_build_agent_tools_default_empty():
    """When no tools are supplied, the agent's tool dict is empty."""
    from loop_sci.engine.agent_runtime import build_agent
    provider = _make_stub_provider()
    cfg = _make_minimal_cfg()
    agent = build_agent(cfg, provider=provider)
    assert agent.tools == {}


def test_build_agent_tools_supplied():
    """Supplied vendored Tool objects are wired in and accessible by name."""
    from unittest.mock import MagicMock
    from loop_sci._vendor.arbor.tools.base import Tool
    from loop_sci.engine.agent_runtime import build_agent

    stub_tool = MagicMock(spec=Tool)
    stub_tool.name = "my_tool"

    provider = _make_stub_provider()
    cfg = _make_minimal_cfg()
    agent = build_agent(cfg, provider=provider, tools=[stub_tool])
    assert "my_tool" in agent.tools
    assert agent.tools["my_tool"] is stub_tool


def test_build_agent_wires_bus():
    """An EventBus supplied to build_agent is wired through to agent.config.event_bus."""
    from loop_sci.engine.agent_runtime import build_agent
    from loop_sci.events import NullBus
    provider = _make_stub_provider()
    cfg = _make_minimal_cfg()
    bus = NullBus()
    agent = build_agent(cfg, provider=provider, bus=bus)
    assert agent.config.event_bus is bus


def test_build_agent_no_provider_raises_or_builds():
    """build_agent without a provider: either raises ValueError or builds with internal provider.

    The task brief says provider defaults to build_provider if not supplied.
    Since build_provider needs an api_key, we test that omitting provider raises
    clearly (AuthError or similar) rather than an unintelligible crash.
    This test documents the expected fail-fast behavior.
    """
    from loop_sci.engine.agent_runtime import build_agent
    cfg = _make_minimal_cfg()
    # cfg.provider.api_key is "" by default — build_provider will raise AuthError
    with pytest.raises(Exception):
        build_agent(cfg)  # no provider, no key → must raise, not hang
