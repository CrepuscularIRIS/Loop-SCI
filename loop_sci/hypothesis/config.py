"""HypothesisConfig dataclass — caps, thresholds, and model names with defaults.

The Hydra YAML that loads this config (conf/hypothesis/default.yaml) is
implemented in task-10b.  This module provides the dataclass with sensible
defaults so that callers can instantiate HypothesisConfig() without any
Hydra overhead for tests and programmatic use.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HypothesisConfig:
    """Configuration for the HypothesisExecutor.

    All fields have defaults matching the OpenSpec values so that
    ``HypothesisConfig()`` produces a fully functional config for offline tests.

    Attributes:
        max_cards: Upper bound on problem-card nodes generated per round.
        max_candidates: Upper bound on hypothesis candidates per card.
        max_rounds: Maximum number of generation rounds per executor run.
        novelty_low: Lower novelty-band boundary for score_hypothesis.
        novelty_high: Upper novelty-band boundary for score_hypothesis.
        w_n: Weight for the novelty sub-score in the weighted overall score.
        w_c: Weight for the self-consistency sub-score in the weighted overall score.
        pivot_at: Stall-count threshold that triggers a PIVOT signal.
        escalate_at: Stall-count threshold that triggers an ESCALATE (stop) signal.
        region_close_threshold: Number of kills in a latent root that closes the region.
        generator_model: Model-id string identifying the generator LLM.
        reviewer_model: Model-id string identifying the reviewer LLM.
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
