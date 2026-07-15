"""Tests for PlanConf Hydra config group — Task 6."""
from __future__ import annotations

from loop_sci.config import load_config


def test_plan_config_group_loads_with_defaults():
    cfg = load_config(config_dir="conf")
    assert cfg.plan.domain
    assert cfg.plan.call_budget == 3
    assert cfg.plan.allow_provider_refs is False
