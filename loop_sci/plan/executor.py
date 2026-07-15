"""PlanAssemblerExecutor — full plan-assembly pipeline + resume + persist.

Standalone executor (does NOT subclass Coordinator) that mirrors the
HypothesisExecutor pattern: constructed with its collaborators, exposes
``async def run(unit: DispatchUnit) -> ExecutorResult``.

Pipeline (per run)
------------------
1. Resolve ``RankedHypothesis`` by ``unit.node_id`` from the ranked store.
   If none found → ``ExecutorResult(status="error", ...)``.
2. RESUME: if ``session_dir/plans/<node_id>.json`` already exists → load and
   return with NO provider call, NO verification.
3. Call 1  — ``assemble_reasoning_fields`` + ``build_dst_candidates``.
4. Call 2  — ``derive_results``.
5. Call 3  — ``assemble_title_abstract``.
   (Calls are skipped cleanly when ``config.call_budget < 3``.)
6. ``collect_references`` (extras only if ``config.allow_provider_refs``).
7. Build ``ResearchPlan``, run ``run_gate``, set ``plan.gate``.
8. ``render_markdown`` + ``assert_json_markdown_parity``.
9. mkdir ``plans/``, write ``<node_id>.json`` and ``<node_id>.md``.
   Advance session cursor via ``session.advance_step()``.
10. Return ``ExecutorResult(status="done", ...)``.

Exception safety: ``run`` wraps ``_assemble`` in a try/except so that ANY
unhandled exception returns ``ExecutorResult(status="error", ...)`` rather
than propagating.  A partial plan is NEVER persisted on error.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from loop_sci.engine.types import DispatchUnit, ExecutorResult
from loop_sci.hypothesis.ranked import RankedHypothesis, RankedHypothesisStore
from loop_sci.literature.factbase.store import FactStore
from loop_sci.plan.config import PlanConfig
from loop_sci.plan.fields import (
    assemble_reasoning_fields,
    assemble_title_abstract,
    build_dst_candidates,
)
from loop_sci.plan.gate import run_gate
from loop_sci.plan.references import collect_references
from loop_sci.plan.render import assert_json_markdown_parity, render_markdown
from loop_sci.plan.results import derive_results
from loop_sci.plan.schemas import (
    ExperimentsBlock,
    GateResult,
    ResearchPlan,
    ResultsBlock,
)
from loop_sci.state.session import RunSession

log = logging.getLogger(__name__)

__all__ = ["PlanAssemblerExecutor"]


class PlanAssemblerExecutor:
    """Execute the full plan-assembly pipeline for a ranked hypothesis node.

    Parameters
    ----------
    session:
        The active ``RunSession`` that owns the idea-tree and cursor.
    provider:
        LLM provider for all three assembly calls.  Must expose
        ``await create(*, system, messages, max_tokens) -> LLMResponse``
        with a ``.get_text()`` method on the response.
    ranked_store:
        A ``RankedHypothesisStore`` backed by the session tree.  Used to
        resolve the target hypothesis by ``unit.node_id``.
    fact_store:
        The ``FactStore`` holding grounding facts for reference assembly.
    verification_pipeline:
        Optional ``VerificationPipeline`` for provider-proposed references.
        Only consulted when ``config.allow_provider_refs=True``.
    config:
        ``PlanConfig`` dataclass with domain, call_budget, and flags.
        Defaults to ``PlanConfig()`` (all defaults).
    """

    def __init__(
        self,
        session: RunSession,
        *,
        provider: Any,
        ranked_store: RankedHypothesisStore,
        fact_store: FactStore,
        verification_pipeline: Any | None = None,
        config: PlanConfig | None = None,
    ) -> None:
        self._session = session
        self._provider = provider
        self._ranked_store = ranked_store
        self._fact_store = fact_store
        self._pipeline = verification_pipeline
        self._cfg = config or PlanConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self, unit: DispatchUnit) -> ExecutorResult:
        """Execute the plan-assembly pipeline for *unit.node_id*.

        Always returns an ``ExecutorResult`` — never raises.  On any internal
        failure, ``status="error"`` is returned with the exception message and
        no partial plan is persisted.

        Parameters
        ----------
        unit:
            ``DispatchUnit`` produced by the coordinator.  ``unit.node_id``
            must match a ranked hypothesis node in the session tree.
        """
        try:
            return await self._assemble(unit)
        except Exception as exc:  # noqa: BLE001
            log.exception(
                "PlanAssemblerExecutor: unhandled error for node_id=%r", unit.node_id
            )
            return ExecutorResult(
                status="error",
                summary=f"PlanAssemblerExecutor failed: {exc}",
                score=None,
                insight="",
                refs={"error": str(exc), "node_id": unit.node_id},
            )

    async def assemble_for_node(self, node_id: str) -> ResearchPlan:
        """Assemble and return a ``ResearchPlan`` for *node_id*.

        This is a helper for callers that want the plan object directly rather
        than an ``ExecutorResult``.  May raise on failure (not exception-safe).
        """
        result = await self._assemble(DispatchUnit(node_id=node_id, goal=""))
        if result.status != "done":
            raise RuntimeError(
                f"assemble_for_node failed: {result.summary}"
            )
        plan_path = self._plans_dir() / f"{node_id}.json"
        d = json.loads(plan_path.read_text(encoding="utf-8"))
        return ResearchPlan.from_dict(d)

    # ------------------------------------------------------------------
    # Internal pipeline
    # ------------------------------------------------------------------

    def _plans_dir(self) -> Path:
        return self._session.session_dir / "plans"

    async def _assemble(self, unit: DispatchUnit) -> ExecutorResult:
        """Inner pipeline — may raise; callers wrap in try/except."""
        node_id = unit.node_id
        cfg = self._cfg

        # ── Step 1: Resolve RankedHypothesis by node_id ──────────────────────
        hyp: RankedHypothesis | None = self._resolve_hyp(node_id)
        if hyp is None:
            log.warning("PlanAssemblerExecutor: unknown node_id=%r", node_id)
            return ExecutorResult(
                status="error",
                summary=f"unknown node: {node_id!r} not found in ranked store",
                score=None,
                insight="",
                refs={"node_id": node_id, "error": "unknown_node"},
            )

        # ── Step 2: Resume — return existing plan without re-assembling ───────
        plan_path = self._plans_dir() / f"{node_id}.json"
        if plan_path.exists():
            log.info("PlanAssemblerExecutor: resuming from %s", plan_path)
            d = json.loads(plan_path.read_text(encoding="utf-8"))
            plan = ResearchPlan.from_dict(d)
            return ExecutorResult(
                status="done",
                summary=f"resumed plan for node {node_id!r} from disk",
                score=None,
                insight="",
                refs={
                    "node_id": node_id,
                    "gate_passed": plan.gate.passed,
                    "resumed": True,
                },
            )

        facts = self._fact_store.all()

        # ── Step 3: Call 1 — reasoning fields + DST candidates ───────────────
        reasoning: dict[str, Any] = {}
        experiments = ExperimentsBlock(baselines=[], metrics=[], design="")
        if cfg.call_budget >= 1:
            reasoning = await assemble_reasoning_fields(
                hyp, facts, self._provider, domain=cfg.domain
            )
            experiments = reasoning.get("experiments", experiments)

        dst = build_dst_candidates(hyp, facts)

        # ── Step 4: Call 2 — derive results ──────────────────────────────────
        results_block = ResultsBlock(derivation=[], conclusion="", confidence="low")
        if cfg.call_budget >= 2:
            results_block = await derive_results(
                hyp, self._provider, domain=cfg.domain
            )

        # ── Step 5: Call 3 — title + abstract ────────────────────────────────
        title_abstract: dict[str, str] = {"paper_title": "", "abstract": ""}
        if cfg.call_budget >= 3:
            plan_context: dict[str, Any] = {
                "problem_statement": reasoning.get("problem_statement", ""),
                "rationale": reasoning.get("rationale", ""),
                "technical_details": reasoning.get("technical_details", ""),
                "methods": reasoning.get("methods", ""),
                "mechanism": hyp.mechanism,
                "diff_prediction": hyp.diff_prediction,
            }
            title_abstract = await assemble_title_abstract(
                plan_context, self._provider, domain=cfg.domain
            )

        # ── Step 6: Collect references ────────────────────────────────────────
        refs_list = await collect_references(
            hyp,
            facts,
            allow_provider_refs=cfg.allow_provider_refs,
            pipeline=self._pipeline if cfg.allow_provider_refs else None,
        )

        # ── Step 7: Build ResearchPlan, run gate ──────────────────────────────
        plan = ResearchPlan(
            problem_statement=reasoning.get("problem_statement", ""),
            rationale=reasoning.get("rationale", ""),
            technical_details=reasoning.get("technical_details", ""),
            datasets=dst.get("datasets", []),
            source=dst.get("source", []),
            target=dst.get("target", []),
            paper_title=title_abstract.get("paper_title", ""),
            abstract=title_abstract.get("abstract", ""),
            methods=reasoning.get("methods", ""),
            experiments=experiments,
            results=results_block,
            references=refs_list,
            node_id=node_id,
            gate=GateResult(passed=False, failures=[]),
        )
        gate_result = run_gate(plan)
        plan.gate = gate_result

        # ── Step 8: Render Markdown + assert parity ───────────────────────────
        md = render_markdown(plan)
        assert_json_markdown_parity(plan)

        # ── Step 9: Persist plan files ────────────────────────────────────────
        # Write .md FIRST, then .json.  The resume guard keys on .json alone,
        # so .json is the sentinel.  Writing it last guarantees: if the .md write
        # fails the sentinel never exists and the next run re-assembles cleanly;
        # whenever .json exists, .md is already present.
        plans_dir = self._plans_dir()
        plans_dir.mkdir(parents=True, exist_ok=True)

        md_path = plans_dir / f"{node_id}.md"
        md_path.write_text(md, encoding="utf-8")

        json_path = plans_dir / f"{node_id}.json"
        json_path.write_text(
            json.dumps(plan.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        self._session.advance_step()

        log.info(
            "PlanAssemblerExecutor: plan assembled for node %r  gate_passed=%s",
            node_id,
            gate_result.passed,
        )

        return ExecutorResult(
            status="done",
            summary=(
                f"Plan assembled for node {node_id!r}; "
                f"gate_passed={gate_result.passed}."
            ),
            score=None,
            insight="",
            refs={"node_id": node_id, "gate_passed": gate_result.passed},
        )

    def _resolve_hyp(self, node_id: str) -> RankedHypothesis | None:
        """Resolve a RankedHypothesis by node_id from the ranked store.

        ``get_ranked()`` returns all ranked hypotheses ordered best-first.
        Scan the list to find the one whose ``node_id`` matches.

        Args:
            node_id: The target tree node identifier.

        Returns:
            The matching :class:`RankedHypothesis`, or ``None`` if not found.
        """
        all_ranked = self._ranked_store.get_ranked()
        for r in all_ranked:
            if r.node_id == node_id:
                return r
        return None
