"""loop_sci.plan — research plan assembly package.

Public exports from Tasks 1–6:
- Schema dataclasses: ResearchPlan, Candidate, Reference, ResultsBlock,
  ExperimentsBlock, GateResult, PLAN_JSON_KEYS
- PlanConfig: configuration dataclass for the plan assembler.
- PlanAssemblerExecutor: full pipeline executor (Task 6).
- register_plan_tools: ToolRegistry registration helper (Task 6).
"""
from loop_sci.plan.config import PlanConfig
from loop_sci.plan.executor import PlanAssemblerExecutor
from loop_sci.plan.schemas import (
    PLAN_JSON_KEYS,
    Candidate,
    ExperimentsBlock,
    GateResult,
    Reference,
    ResearchPlan,
    ResultsBlock,
)
from loop_sci.plan.tools import register_plan_tools

__all__ = [
    # config
    "PlanConfig",
    # executor
    "PlanAssemblerExecutor",
    # tools
    "register_plan_tools",
    # schemas
    "ResearchPlan",
    "Candidate",
    "Reference",
    "ResultsBlock",
    "ExperimentsBlock",
    "GateResult",
    "PLAN_JSON_KEYS",
]
