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
        # Mock executor returns status="done" and refs={"accepted_count": 2}
        assert result["status"] == "done", f"Expected status='done', got {result.get('status')!r}"
        assert result["accepted_count"] == 2, (
            f"Expected accepted_count=2, got {result.get('accepted_count')!r}"
        )


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
        # Mock executor returns "UP"; the critique tool must propagate it as verdict
        assert result["verdict"] == "UP", (
            f"Expected verdict='UP' from mock executor, got {result.get('verdict')!r}"
        )


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


# ---------------------------------------------------------------------------
# Targeted coverage tests — uncovered edge-cases in tools.py
# ---------------------------------------------------------------------------


class TestToolEdgeCases:
    """Cover remaining uncovered branches in loop_sci/hypothesis/tools.py."""

    @pytest.mark.asyncio
    async def test_generate_invalid_topic_empty_string_returns_error(self):
        """generate with empty topic returns invalid_input error (line 53)."""
        from loop_sci.engine.tools import ToolRegistry
        from loop_sci.hypothesis.tools import register_hypothesis_tools

        registry = ToolRegistry()
        register_hypothesis_tools(registry, executor=object())  # non-None executor

        result_str = await registry.dispatch("generate", {"topic": ""})
        result = json.loads(result_str)
        assert result.get("error") == "invalid_input", (
            f"Empty topic must yield invalid_input error, got {result!r}"
        )

    @pytest.mark.asyncio
    async def test_generate_executor_raises_returns_tool_error(self):
        """generate where executor.run raises returns tool_error JSON (lines 66-68)."""
        from loop_sci.engine.tools import ToolRegistry
        from loop_sci.hypothesis.tools import register_hypothesis_tools

        class _BrokenExecutor:
            async def run(self, unit):
                raise RuntimeError("simulated executor crash")

        registry = ToolRegistry()
        register_hypothesis_tools(registry, executor=_BrokenExecutor())

        result_str = await registry.dispatch("generate", {"topic": "neuro"})
        result = json.loads(result_str)
        assert result.get("error") == "tool_error", (
            f"Executor crash must yield tool_error, got {result!r}"
        )

    @pytest.mark.asyncio
    async def test_critique_invalid_node_id_returns_error(self):
        """critique with empty node_id returns invalid_input error (line 96)."""
        from loop_sci.engine.tools import ToolRegistry
        from loop_sci.hypothesis.tools import register_hypothesis_tools

        registry = ToolRegistry()
        register_hypothesis_tools(registry, executor=object())  # non-None executor

        result_str = await registry.dispatch("critique", {"node_id": ""})
        result = json.loads(result_str)
        assert result.get("error") == "invalid_input", (
            f"Empty node_id must yield invalid_input error, got {result!r}"
        )

    @pytest.mark.asyncio
    async def test_critique_executor_raises_returns_tool_error(self):
        """critique where executor.run_critique raises returns tool_error (lines 102-104)."""
        from loop_sci.engine.tools import ToolRegistry
        from loop_sci.hypothesis.tools import register_hypothesis_tools

        class _CrashExecutor:
            async def run_critique(self, node_id: str) -> str:
                raise RuntimeError("critique crash")

        registry = ToolRegistry()
        register_hypothesis_tools(registry, executor=_CrashExecutor())

        result_str = await registry.dispatch("critique", {"node_id": "hyp_123"})
        result = json.loads(result_str)
        assert result.get("error") == "tool_error", (
            f"Critique crash must yield tool_error, got {result!r}"
        )

    @pytest.mark.asyncio
    async def test_rank_executor_without_ranked_store_returns_empty(self):
        """rank when executor has no ranked_store method returns [] (line 136)."""
        from loop_sci.engine.tools import ToolRegistry
        from loop_sci.hypothesis.tools import register_hypothesis_tools

        class _NoStoreExecutor:
            pass  # no ranked_store method

        registry = ToolRegistry()
        register_hypothesis_tools(registry, executor=_NoStoreExecutor())

        result_str = await registry.dispatch("rank", {"topic": "neuro"})
        result = json.loads(result_str)
        assert result == [], (
            f"rank with no ranked_store must return [], got {result!r}"
        )

    @pytest.mark.asyncio
    async def test_rank_executor_ranked_store_raises_returns_tool_error(self):
        """rank where ranked_store().get_ranked raises returns tool_error (lines 150-152)."""
        from loop_sci.engine.tools import ToolRegistry
        from loop_sci.hypothesis.tools import register_hypothesis_tools

        class _CrashStore:
            def get_ranked(self, **kwargs):
                raise RuntimeError("rank crash")

        class _CrashExecutor:
            def ranked_store(self):
                return _CrashStore()

        registry = ToolRegistry()
        register_hypothesis_tools(registry, executor=_CrashExecutor())

        result_str = await registry.dispatch("rank", {"topic": "neuro"})
        result = json.loads(result_str)
        assert result.get("error") == "tool_error", (
            f"rank crash must yield tool_error, got {result!r}"
        )


# ---------------------------------------------------------------------------
# BLOCKER 1 bite-test: critique and rank tools against REAL HypothesisExecutor
# ---------------------------------------------------------------------------


class TestCritiqueAndRankWithRealExecutor:
    """BLOCKER 1: tools must work against the real HypothesisExecutor.

    Before the fix, HypothesisExecutor had neither run_critique nor ranked_store,
    so calling the tools against the real executor would always yield a tool_error
    (for critique) or an empty list (for rank, via the hasattr guard).

    This test suite builds a real HypothesisExecutor with MockProviders and a
    seeded FactStore, populates a hypothesis node directly (bypassing the full
    pipeline for speed), then drives critique and rank through the ToolRegistry.
    """

    @staticmethod
    def _make_executor(tmp_path):
        """Build a real HypothesisExecutor with minimal deps."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parents[3]))
        sys.path.insert(0, str(Path(__file__).parents[3] / "tests"))

        from tests.conftest import MockProvider
        from loop_sci.hypothesis.config import HypothesisConfig
        from loop_sci.hypothesis.executor import HypothesisExecutor
        from loop_sci.literature.extract.fact import Fact, SourceRef
        from loop_sci.literature.factbase.store import FactStore
        from loop_sci.state.session import RunSession

        store_path = tmp_path / "facts.json"
        store = FactStore(store_path)
        f = Fact(
            claim="Neurons fire action potentials.",
            source_ref=SourceRef(source="s2", external_id="x0"),
            evidence_span="Neurons fire action potentials.",
            confidence=0.9,
            grounding_scope="abstract",
        )
        f.fact_id = "fact_0"
        store.add(f)

        session = RunSession.create(tmp_path / "runs", task="test-topic")
        gen = MockProvider(
            responses=["{}"] * 20,
            model="qwen-max",
        )
        rev = MockProvider(
            responses=[json.dumps({"result": "UP", "reasons": ["grounded"]})],
            model="qwen-plus",
        )
        cfg = HypothesisConfig(max_rounds=1, max_cards=1, max_candidates=1)
        return HypothesisExecutor(
            session,
            gen_provider=gen,
            rev_provider=rev,
            store_path=store_path,
            config=cfg,
        )

    @staticmethod
    def _plant_hypothesis_node(executor, node_id: str) -> None:
        """Insert a hypothesis node into the executor's tree with a derivation."""
        from loop_sci.state.idea_tree import Node

        refs = {
            "kind": "hypothesis",
            "topic": "test-topic",
            "hyp": {
                "MECHANISM": "Glial sync drives fear",
                "KILL": "No signal",
                "BRACKET": "plausible",
                "DIFF_PREDICTION": "Distinct BOLD",
            },
            "frame": "primary",
            "grounding_fact_ids": ["fact_0"],
            "derivation": [
                {"step": "literature grounding", "grade": "[paper]", "fact_ids": ["fact_0"]}
            ],
        }
        node = Node(
            id=node_id,
            parent_id="ROOT",
            hypothesis="Glial sync drives fear",
            depth=2,
            status="accepted",
            score=0.75,
            refs=refs,
        )
        executor._session.tree.add_node(node)

    @pytest.mark.asyncio
    async def test_blocker1_critique_tool_against_real_executor(self, tmp_path) -> None:
        """critique tool must return a structured result from the REAL executor.

        Before the fix: executor.run_critique does not exist → tool_error.
        After the fix: returns structured dict with result/reviewer_model/decided_by.
        """
        executor = self._make_executor(tmp_path)
        node_id = "hyp_test_001"
        self._plant_hypothesis_node(executor, node_id)

        from loop_sci.engine.tools import ToolRegistry
        from loop_sci.hypothesis.tools import register_hypothesis_tools

        registry = ToolRegistry()
        register_hypothesis_tools(registry, executor=executor)

        result_str = await registry.dispatch("critique", {"node_id": node_id})
        result = json.loads(result_str)

        assert isinstance(result, dict), f"Expected dict result, got {type(result)}"
        assert "error" not in result or result.get("error") != "tool_error", (
            f"critique tool must NOT return tool_error against real executor. "
            f"Got: {result}"
        )
        # The structured result must carry result/decided_by/reviewer_model
        assert "result" in result, (
            f"Structured critique result must have 'result' key. Got: {result}"
        )
        assert result["result"] in ("UP", "DOWN"), (
            f"result must be UP or DOWN, got {result['result']!r}"
        )
        assert "decided_by" in result, (
            f"Structured critique result must have 'decided_by'. Got: {result}"
        )
        assert "reviewer_model" in result, (
            f"Structured critique result must have 'reviewer_model'. Got: {result}"
        )

    @pytest.mark.asyncio
    async def test_blocker1_critique_unknown_node_returns_error_not_exception(
        self, tmp_path
    ) -> None:
        """critique on an unknown node_id must return structured error, not raise."""
        executor = self._make_executor(tmp_path)

        from loop_sci.engine.tools import ToolRegistry
        from loop_sci.hypothesis.tools import register_hypothesis_tools

        registry = ToolRegistry()
        register_hypothesis_tools(registry, executor=executor)

        result_str = await registry.dispatch("critique", {"node_id": "nonexistent_node"})
        result = json.loads(result_str)
        assert isinstance(result, dict)
        # Should be an error dict with "error" key, not a Python exception
        assert "error" in result, (
            f"Unknown node_id must return a structured error dict. Got: {result}"
        )

    @pytest.mark.asyncio
    async def test_blocker1_rank_tool_against_real_executor(self, tmp_path) -> None:
        """rank tool must use the REAL ranked_store method on the executor.

        Before the fix: executor has no ranked_store → hasattr guard returns []
        even when hypothesis nodes exist.
        After the fix: returns non-empty ranked list reflecting tree contents.
        """
        executor = self._make_executor(tmp_path)
        node_id = "hyp_test_002"
        self._plant_hypothesis_node(executor, node_id)

        from loop_sci.engine.tools import ToolRegistry
        from loop_sci.hypothesis.tools import register_hypothesis_tools

        registry = ToolRegistry()
        register_hypothesis_tools(registry, executor=executor)

        result_str = await registry.dispatch("rank", {"status": "accepted"})
        result = json.loads(result_str)

        assert isinstance(result, list), f"rank must return a list, got {type(result)}"
        assert len(result) >= 1, (
            "rank must return ≥1 item when accepted hypothesis nodes exist in the tree. "
            f"Got: {result}"
        )
        assert result[0]["node_id"] == node_id, (
            f"Top ranked item must be the planted node {node_id!r}. Got: {result[0]}"
        )
