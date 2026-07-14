"""Unit tests for hypothesis tools (task-10b, osp 4.5).

All tests run offline — no network, no API key.

Tests pin:
- generate / critique / rank tools are registered in ToolRegistry
- Each tool returns a structured result (dict/JSON) with injected deps offline
- Bad-input call returns a structured error (no raise)
- Config: load_config yields hypothesis defaults; override works
"""
from __future__ import annotations

import json

import pytest


# ---------------------------------------------------------------------------
# Tests: tool registration and schema
# ---------------------------------------------------------------------------


class TestHypothesisToolsRegistration:
    def test_tools_registered_in_registry(self):
        """register_hypothesis_tools registers generate / critique / rank."""
        from loop_sci.engine.tools import ToolRegistry
        from loop_sci.hypothesis.tools import register_hypothesis_tools

        registry = ToolRegistry()
        register_hypothesis_tools(registry, executor=None)

        defs = registry.get_definitions()
        names = [d["name"] for d in defs]
        assert "generate" in names
        assert "critique" in names
        assert "rank" in names

    def test_tools_have_descriptions(self):
        """Each registered tool has a non-empty description."""
        from loop_sci.engine.tools import ToolRegistry
        from loop_sci.hypothesis.tools import register_hypothesis_tools

        registry = ToolRegistry()
        register_hypothesis_tools(registry, executor=None)

        for defn in registry.get_definitions():
            assert defn["description"], f"Tool {defn['name']!r} has empty description"

    def test_tools_have_schemas(self):
        """Each registered tool has an input_schema dict."""
        from loop_sci.engine.tools import ToolRegistry
        from loop_sci.hypothesis.tools import register_hypothesis_tools

        registry = ToolRegistry()
        register_hypothesis_tools(registry, executor=None)

        for defn in registry.get_definitions():
            assert isinstance(defn["input_schema"], dict), (
                f"Tool {defn['name']!r} missing input_schema"
            )


# ---------------------------------------------------------------------------
# Tests: generate tool
# ---------------------------------------------------------------------------


class TestGenerateTool:
    @pytest.mark.asyncio
    async def test_generate_with_none_executor_returns_structured_error(self):
        """generate(topic=...) with executor=None returns structured error, does not raise."""
        from loop_sci.engine.tools import ToolRegistry
        from loop_sci.hypothesis.tools import register_hypothesis_tools

        registry = ToolRegistry()
        register_hypothesis_tools(registry, executor=None)

        result_str = await registry.dispatch("generate", {"topic": "neuro"})
        result = json.loads(result_str)
        # Should be a structured error or empty result — not a Python exception
        assert isinstance(result, dict), "generate should return a dict"

    @pytest.mark.asyncio
    async def test_generate_with_none_executor_no_raise(self):
        """generate with no executor must not raise — returns JSON."""
        from loop_sci.engine.tools import ToolRegistry
        from loop_sci.hypothesis.tools import register_hypothesis_tools

        registry = ToolRegistry()
        register_hypothesis_tools(registry, executor=None)

        result_str = await registry.dispatch("generate", {"topic": "test"})
        # Must be valid JSON
        result = json.loads(result_str)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_generate_with_mock_executor_returns_structured(self, tmp_path):
        """generate with a mock executor returns structured JSON result."""
        from loop_sci.engine.tools import ToolRegistry
        from loop_sci.hypothesis.tools import register_hypothesis_tools

        class _MockExecutor:
            async def run(self, unit):
                from loop_sci.engine.types import ExecutorResult
                return ExecutorResult(
                    status="done",
                    summary="2 accepted",
                    refs={"accepted_count": 2},
                )

        registry = ToolRegistry()
        register_hypothesis_tools(registry, executor=_MockExecutor())

        result_str = await registry.dispatch("generate", {"topic": "neuro"})
        result = json.loads(result_str)
        assert isinstance(result, dict)
        # Should have some key indicating success or accepted count
        assert "error" not in result or result.get("accepted_count") is not None or \
               "status" in result or "accepted_count" in result


# ---------------------------------------------------------------------------
# Tests: critique tool
# ---------------------------------------------------------------------------


class TestCritiqueTool:
    @pytest.mark.asyncio
    async def test_critique_with_none_executor_no_raise(self):
        """critique with no executor returns structured JSON, does not raise."""
        from loop_sci.engine.tools import ToolRegistry
        from loop_sci.hypothesis.tools import register_hypothesis_tools

        registry = ToolRegistry()
        register_hypothesis_tools(registry, executor=None)

        result_str = await registry.dispatch("critique", {"node_id": "hyp_abc"})
        result = json.loads(result_str)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_critique_with_mock_executor_returns_structured(self):
        """critique with a mock executor returns structured JSON."""
        from loop_sci.engine.tools import ToolRegistry
        from loop_sci.hypothesis.tools import register_hypothesis_tools

        class _MockExecutor:
            async def run_critique(self, node_id: str) -> str:
                return "UP"

        registry = ToolRegistry()
        register_hypothesis_tools(registry, executor=_MockExecutor())

        result_str = await registry.dispatch("critique", {"node_id": "hyp_123"})
        result = json.loads(result_str)
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Tests: rank tool
# ---------------------------------------------------------------------------


class TestRankTool:
    @pytest.mark.asyncio
    async def test_rank_with_none_executor_returns_empty_list(self):
        """rank with no executor returns an empty JSON array."""
        from loop_sci.engine.tools import ToolRegistry
        from loop_sci.hypothesis.tools import register_hypothesis_tools

        registry = ToolRegistry()
        register_hypothesis_tools(registry, executor=None)

        result_str = await registry.dispatch("rank", {"topic": "neuro"})
        result = json.loads(result_str)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_rank_with_mock_executor_returns_ranked_list(self):
        """rank with a mock executor returns a list of ranked hypotheses."""
        from loop_sci.engine.tools import ToolRegistry
        from loop_sci.hypothesis.tools import register_hypothesis_tools
        from loop_sci.hypothesis.ranked import RankedHypothesis

        class _MockStore:
            def get_ranked(self, *, topic=None, status=None):
                return [
                    RankedHypothesis(
                        node_id="hyp_001",
                        problem="neuro",
                        mechanism="Glial sync",
                        derivation_chain=[],
                        diff_prediction="EEG distinct",
                        novelty=0.8,
                        self_consistency=0.7,
                        overall_score=0.75,
                    )
                ]

        class _MockExecutor:
            def ranked_store(self):
                return _MockStore()

        registry = ToolRegistry()
        register_hypothesis_tools(registry, executor=_MockExecutor())

        result_str = await registry.dispatch("rank", {"topic": "neuro", "status": "accepted"})
        result = json.loads(result_str)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["node_id"] == "hyp_001"
        assert result[0]["mechanism"] == "Glial sync"
        assert result[0]["overall_score"] == 0.75


# ---------------------------------------------------------------------------
# Tests: config (osp 4.6 — Hydra config)
# ---------------------------------------------------------------------------


class TestHypothesisConfig:
    CONF_DIR = str(__import__("pathlib").Path(__file__).parent.parent.parent.parent / "conf")

    def test_hypothesis_config_defaults(self):
        """HypothesisConfig() defaults match spec values."""
        from loop_sci.hypothesis.config import HypothesisConfig

        cfg = HypothesisConfig()
        assert cfg.max_cards == 5
        assert cfg.max_candidates == 4
        assert cfg.max_rounds == 3
        assert cfg.novelty_low == 0.15
        assert cfg.novelty_high == 0.60
        assert cfg.w_n == 0.5
        assert cfg.w_c == 0.5
        assert cfg.pivot_at == 2
        assert cfg.escalate_at == 4
        assert cfg.region_close_threshold == 2
        assert cfg.generator_model == "qwen-max"
        assert cfg.reviewer_model == "qwen-plus"

    def test_loop_sci_config_has_hypothesis_field(self):
        """LoopSCIConfig must have a hypothesis field (HypothesisConf)."""
        from loop_sci.config.schemas import LoopSCIConfig

        cfg = LoopSCIConfig()
        assert hasattr(cfg, "hypothesis"), "LoopSCIConfig must have a 'hypothesis' field"

    def test_load_config_yields_hypothesis_defaults(self):
        """load_config surfaces hypothesis defaults from conf/hypothesis/default.yaml."""
        from loop_sci.config import load_config

        cfg = load_config(config_dir=self.CONF_DIR)
        assert hasattr(cfg, "hypothesis"), "cfg must have hypothesis sub-config"
        h = cfg.hypothesis
        assert h.max_rounds == 3
        assert h.max_cards == 5
        assert h.generator_model == "qwen-max"
        assert h.reviewer_model == "qwen-plus"

    def test_load_config_hypothesis_override(self):
        """Hydra override hypothesis.max_rounds=5 is reflected in cfg.hypothesis."""
        from loop_sci.config import load_config

        cfg = load_config(config_dir=self.CONF_DIR, overrides=["hypothesis.max_rounds=5"])
        assert cfg.hypothesis.max_rounds == 5, (
            f"Expected max_rounds=5 after override, got {cfg.hypothesis.max_rounds}"
        )

    def test_load_config_hypothesis_override_max_cards(self):
        """Hydra override hypothesis.max_cards=2 is reflected."""
        from loop_sci.config import load_config

        cfg = load_config(config_dir=self.CONF_DIR, overrides=["hypothesis.max_cards=2"])
        assert cfg.hypothesis.max_cards == 2
