"""Tests for loop_sci.config — Hydra schemas and AgentConfig bridge loader.

TDD: these tests are written BEFORE implementation (RED phase).
"""
from __future__ import annotations

from pathlib import Path



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CONF_DIR = str(Path(__file__).parent.parent.parent / "conf")


# ---------------------------------------------------------------------------
# Schema dataclass tests (no Hydra, pure Python)
# ---------------------------------------------------------------------------


class TestSchemas:
    def test_provider_conf_defaults(self):
        from loop_sci.config.schemas import ProviderConf

        p = ProviderConf()
        assert p.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
        assert p.model == "qwen-plus"
        assert p.api_key == ""
        assert p.timeout == 120.0
        assert p.max_retries == 3
        assert p.tool_protocol == "native"

    def test_agent_conf_defaults(self):
        from loop_sci.config.schemas import AgentConf

        a = AgentConf()
        assert a.max_turns == 20
        assert a.context_window == 100_000
        assert a.compact_threshold == 0.85
        assert a.compact_keep_recent == 8
        assert a.max_tokens == 4096

    def test_engine_conf_defaults(self):
        from loop_sci.config.schemas import EngineConf

        e = EngineConf()
        assert e.step_budget == 10

    def test_run_conf_defaults(self):
        from loop_sci.config.schemas import RunConf

        r = RunConf()
        assert r.runs_root == "runs"
        assert r.task == ""
        assert r.run_id is None

    def test_loop_sci_config_is_real_dataclass(self):
        """LoopSCIConfig must be a real dataclass, not a dynamic type() object."""
        import dataclasses

        from loop_sci.config.schemas import LoopSCIConfig, EngineConf, RunConf

        cfg = LoopSCIConfig()
        assert dataclasses.is_dataclass(cfg)
        assert dataclasses.is_dataclass(cfg.engine)
        assert dataclasses.is_dataclass(cfg.run)
        assert isinstance(cfg.engine, EngineConf)
        assert isinstance(cfg.run, RunConf)

    def test_loop_sci_config_sub_configs_are_real_dataclasses(self):
        """engine and run must be real dataclass instances, not ad-hoc objects."""
        import dataclasses

        from loop_sci.config.schemas import LoopSCIConfig

        cfg = LoopSCIConfig()
        assert type(cfg.engine).__name__ == "EngineConf"
        assert type(cfg.run).__name__ == "RunConf"
        assert dataclasses.is_dataclass(type(cfg.engine))
        assert dataclasses.is_dataclass(type(cfg.run))


# ---------------------------------------------------------------------------
# load_config tests (Hydra)
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_load_config_returns_loop_sci_config(self):
        from loop_sci.config import load_config
        from loop_sci.config.schemas import LoopSCIConfig

        cfg = load_config(config_dir=CONF_DIR)
        assert isinstance(cfg, LoopSCIConfig)

    def test_load_config_provider_defaults(self):
        from loop_sci.config import load_config

        cfg = load_config(config_dir=CONF_DIR)
        assert cfg.provider.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
        assert cfg.provider.model == "qwen-plus"
        assert cfg.provider.timeout == 120.0
        assert cfg.provider.max_retries == 3
        assert cfg.provider.tool_protocol == "native"

    def test_load_config_agent_defaults(self):
        from loop_sci.config import load_config

        cfg = load_config(config_dir=CONF_DIR)
        assert cfg.agent.max_turns == 20
        assert cfg.agent.context_window == 100_000
        assert cfg.agent.compact_threshold == 0.85
        assert cfg.agent.compact_keep_recent == 8
        assert cfg.agent.max_tokens == 4096

    def test_load_config_engine_defaults(self):
        from loop_sci.config import load_config

        cfg = load_config(config_dir=CONF_DIR)
        assert cfg.engine.step_budget == 10

    def test_load_config_run_defaults(self):
        from loop_sci.config import load_config

        cfg = load_config(config_dir=CONF_DIR)
        assert cfg.run.runs_root == "runs"
        assert cfg.run.run_id is None

    def test_load_config_override_model(self):
        """Hydra overrides should propagate into the returned config."""
        from loop_sci.config import load_config

        cfg = load_config(config_dir=CONF_DIR, overrides=["provider.model=qwen-turbo"])
        assert cfg.provider.model == "qwen-turbo"

    def test_load_config_override_step_budget(self):
        from loop_sci.config import load_config

        cfg = load_config(config_dir=CONF_DIR, overrides=["engine.step_budget=5"])
        assert cfg.engine.step_budget == 5

    def test_load_config_engine_is_real_dataclass(self):
        """Engine conf returned by load_config must be a real EngineConf dataclass."""
        import dataclasses

        from loop_sci.config import load_config
        from loop_sci.config.schemas import EngineConf

        cfg = load_config(config_dir=CONF_DIR)
        assert isinstance(cfg.engine, EngineConf)
        assert dataclasses.is_dataclass(cfg.engine)

    def test_load_config_run_is_real_dataclass(self):
        """Run conf returned by load_config must be a real RunConf dataclass."""
        import dataclasses

        from loop_sci.config import load_config
        from loop_sci.config.schemas import RunConf

        cfg = load_config(config_dir=CONF_DIR)
        assert isinstance(cfg.run, RunConf)
        assert dataclasses.is_dataclass(cfg.run)

    def test_load_config_missing_api_key_does_not_crash(self, monkeypatch):
        """Missing DASHSCOPE_API_KEY must not raise; resolves to empty string."""
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        from loop_sci.config import load_config

        cfg = load_config(config_dir=CONF_DIR)
        assert cfg.provider.api_key == ""

    def test_load_config_env_api_key_interpolated(self, monkeypatch):
        """When DASHSCOPE_API_KEY is set in env, load_config picks it up."""
        monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key-abc")
        from loop_sci.config import load_config

        cfg = load_config(config_dir=CONF_DIR)
        assert cfg.provider.api_key == "test-key-abc"


# ---------------------------------------------------------------------------
# hydra_to_agent_config tests
# ---------------------------------------------------------------------------


class TestHydraToAgentConfig:
    def _base_cfg(self):
        from loop_sci.config.schemas import (
            AgentConf,
            EngineConf,
            LoopSCIConfig,
            ProviderConf,
            RunConf,
        )

        return LoopSCIConfig(
            provider=ProviderConf(
                model="qwen-plus",
                api_key="sk-test",
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
            agent=AgentConf(
                max_turns=20,
                context_window=100_000,
                compact_threshold=0.85,
                compact_keep_recent=8,
                max_tokens=4096,
            ),
            engine=EngineConf(step_budget=10),
            run=RunConf(runs_root="runs", task="test task"),
        )

    def test_auto_git_is_false(self):
        """HARD REQUIREMENT: auto_git MUST be False — vendored default is True."""
        from loop_sci.config import hydra_to_agent_config

        cfg = self._base_cfg()
        agent_cfg = hydra_to_agent_config(cfg)
        assert agent_cfg.auto_git is False

    def test_returns_agent_config_instance(self):
        from loop_sci._vendor.arbor.config import AgentConfig
        from loop_sci.config import hydra_to_agent_config

        cfg = self._base_cfg()
        agent_cfg = hydra_to_agent_config(cfg)
        assert isinstance(agent_cfg, AgentConfig)

    def test_model_is_mapped(self):
        from loop_sci.config import hydra_to_agent_config

        cfg = self._base_cfg()
        agent_cfg = hydra_to_agent_config(cfg)
        assert agent_cfg.llm.model == "qwen-plus"

    def test_api_key_is_mapped(self):
        from loop_sci.config import hydra_to_agent_config

        cfg = self._base_cfg()
        agent_cfg = hydra_to_agent_config(cfg)
        assert agent_cfg.llm.api_key == "sk-test"

    def test_max_tokens_is_mapped(self):
        from loop_sci.config import hydra_to_agent_config

        cfg = self._base_cfg()
        agent_cfg = hydra_to_agent_config(cfg)
        assert agent_cfg.llm.max_tokens == 4096

    def test_context_window_is_mapped(self):
        """context_window maps to AgentConfig via flat proxy (context.window)."""
        from loop_sci.config import hydra_to_agent_config

        cfg = self._base_cfg()
        agent_cfg = hydra_to_agent_config(cfg)
        assert agent_cfg.context.window == 100_000

    def test_compact_threshold_is_mapped(self):
        from loop_sci.config import hydra_to_agent_config

        cfg = self._base_cfg()
        agent_cfg = hydra_to_agent_config(cfg)
        assert agent_cfg.context.compact_threshold == 0.85

    def test_compact_keep_recent_is_mapped(self):
        from loop_sci.config import hydra_to_agent_config

        cfg = self._base_cfg()
        agent_cfg = hydra_to_agent_config(cfg)
        assert agent_cfg.context.compact_keep_recent == 8

    def test_max_turns_is_mapped(self):
        from loop_sci.config import hydra_to_agent_config

        cfg = self._base_cfg()
        agent_cfg = hydra_to_agent_config(cfg)
        assert agent_cfg.max_turns == 20

    def test_node_id_is_passed(self):
        from loop_sci.config import hydra_to_agent_config

        cfg = self._base_cfg()
        agent_cfg = hydra_to_agent_config(cfg, node_id="node-42")
        assert agent_cfg.node_id == "node-42"

    def test_event_bus_is_passed(self):
        from loop_sci.config import hydra_to_agent_config

        class FakeBus:
            pass

        cfg = self._base_cfg()
        bus = FakeBus()
        agent_cfg = hydra_to_agent_config(cfg, bus=bus)
        assert agent_cfg.event_bus is bus

    def test_base_url_is_mapped(self):
        """base_url should be propagated to llm.base_url."""
        from loop_sci.config import hydra_to_agent_config

        cfg = self._base_cfg()
        agent_cfg = hydra_to_agent_config(cfg)
        assert agent_cfg.llm.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"

    def test_agent_config_instantiation_succeeds(self):
        """Smoke test: the constructed AgentConfig actually instantiates without error."""
        from loop_sci.config import hydra_to_agent_config

        cfg = self._base_cfg()
        agent_cfg = hydra_to_agent_config(cfg)
        # Should have real LLMConfig, ContextConfig, TimeoutConfig sub-objects
        from loop_sci._vendor.arbor.config_schema import ContextConfig, LLMConfig, TimeoutConfig

        assert isinstance(agent_cfg.llm, LLMConfig)
        assert isinstance(agent_cfg.context, ContextConfig)
        assert isinstance(agent_cfg.timeout, TimeoutConfig)
