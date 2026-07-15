"""PlanConfig dataclass — caps, thresholds, and defaults for PlanAssemblerExecutor.

The Hydra YAML that loads this config (conf/plan/default.yaml) is wired in
task-6.  This module provides the dataclass with sensible defaults so that
callers can instantiate ``PlanConfig()`` without any Hydra overhead for tests
and programmatic use.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PlanConfig:
    """Configuration for the PlanAssemblerExecutor.

    All fields have defaults matching the OpenSpec values so that
    ``PlanConfig()`` produces a fully functional config for offline tests.

    Attributes:
        domain: Research domain string injected into LLM prompts
            (e.g. ``"natural-science"``, ``"neuroscience"``).
        call_budget: Maximum number of LLM provider calls allowed per run.
            Default is 3 (Call 1: reasoning fields, Call 2: results,
            Call 3: title/abstract).  When budget < 3, the lowest-priority
            call(s) are skipped cleanly — title/abstract (Call 3) first.
        allow_provider_refs: When ``False`` (default), the ``references``
            field is assembled from grounding facts only — zero verification
            round-trips are issued.  When ``True``, provider-proposed citations
            are routed through the ``VerificationPipeline`` and admitted only
            if they come back ``"verified"``.
        min_reference_count: Minimum number of verified references required
            for the gate to consider the references field populated.  Currently
            informational — the gate checks for a non-empty list, but callers
            may inspect this threshold for downstream policy.
    """

    domain: str = "natural-science"
    call_budget: int = 3
    allow_provider_refs: bool = False
    min_reference_count: int = 1
