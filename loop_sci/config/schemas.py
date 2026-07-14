"""Hydra structured config dataclasses.

These are the user-facing configuration schemas — not the vendored AgentConfig.
The loader bridges from here into the vendored internals.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProviderConf:
    """Provider / model settings surfaced by conf/provider/*.yaml."""

    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model: str = "qwen-plus"
    api_key: str = ""
    timeout: float = 120.0
    max_retries: int = 3
    tool_protocol: str = "native"


@dataclass
class AgentConf:
    """Agent loop settings surfaced by conf/agent/*.yaml."""

    max_turns: int = 20
    context_window: int = 100_000
    compact_threshold: float = 0.85
    compact_keep_recent: int = 8
    max_tokens: int = 4096


@dataclass
class EngineConf:
    """Execution engine settings surfaced by conf/engine/*.yaml."""

    step_budget: int = 10


@dataclass
class RunConf:
    """Per-run settings surfaced by conf/run/*.yaml."""

    runs_root: str = "runs"
    task: str = ""
    run_id: str | None = None


@dataclass
class HypothesisConf:
    """Hypothesis engine settings surfaced by conf/hypothesis/default.yaml.

    Fields mirror :class:`~loop_sci.hypothesis.config.HypothesisConfig` so
    that ``LoopSCIConfig.hypothesis`` carries the same caps, thresholds, and
    model names.  Callers may convert to a ``HypothesisConfig`` via::

        from loop_sci.hypothesis.config import HypothesisConfig
        hyp_cfg = HypothesisConfig(**{f: getattr(cfg.hypothesis, f)
                                      for f in vars(HypothesisConfig())})
    """

    max_cards: int = 5
    max_candidates: int = 4
    max_rounds: int = 3
    novelty_low: float = 0.15
    novelty_high: float = 0.60
    w_n: float = 0.5
    w_c: float = 0.5
    pivot_at: int = 2
    escalate_at: int = 4
    region_close_threshold: int = 2
    generator_model: str = "qwen-max"
    reviewer_model: str = "qwen-plus"


@dataclass
class LoopSCIConfig:
    """Top-level config composed of all sub-configs."""

    provider: ProviderConf = field(default_factory=ProviderConf)
    agent: AgentConf = field(default_factory=AgentConf)
    engine: EngineConf = field(default_factory=EngineConf)
    run: RunConf = field(default_factory=RunConf)
    hypothesis: HypothesisConf = field(default_factory=HypothesisConf)
