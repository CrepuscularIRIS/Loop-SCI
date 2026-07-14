"""Seam dataclasses: DispatchUnit and ExecutorResult."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class DispatchUnit:
    """One unit of work dispatched by the coordinator to an executor."""

    node_id: str
    goal: str
    context: str = ""
    tools: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ExecutorResult:
    """Typed outcome of one executor run."""

    status: Literal["done", "bounded_exit", "error"]
    summary: str
    score: float | None = None
    insight: str = ""
    refs: dict[str, Any] = field(default_factory=dict)
