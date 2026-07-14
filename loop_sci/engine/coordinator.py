"""Thin coordinator: observe → dispatch → record (persist) → decide.

Bootstrap choice:
    A fresh session has only a pending ROOT at depth 0.
    get_pending_leaves() EXCLUDES depth-0 nodes, so it returns [].
    Strategy (a): when get_pending_leaves() is empty but ROOT is still
    pending, dispatch ROOT itself. This guarantees >=1 cycle on any
    fresh session without seeding extra nodes.
    After ROOT is recorded the loop checks get_pending_leaves() again;
    if children were added during execution they will be dispatched next.

Record / persist approach:
    update_node(status, score, insight) auto-saves the tree.
    refs is NOT in _VendorNode.MUTABLE_FIELDS, so we set node.refs
    directly then call session.tree.save() explicitly. This gives us
    persist-before-decide without touching the vendored whitelist.

Step budget:
    Loop exits after cfg.engine.step_budget (or the constructor's
    step_budget kwarg) steps, even if pending nodes remain.
    Bounded_exit and error results are recorded and the loop
    continues to the next pending node until budget is exhausted.

Event emission:
    SESSION_START / SESSION_END and one EXECUTOR_START + EXECUTOR_END
    pair per cycle are emitted on the bus. NullBus silently drops all
    events so no behavior change when no subscriber is wired.
"""
from __future__ import annotations

import logging
from typing import Any

from loop_sci.events import NullBus, EXECUTOR_START, EXECUTOR_END, SESSION_START, SESSION_END
from loop_sci.state.session import RunSession
from loop_sci.state.idea_tree import Node
from .types import DispatchUnit, ExecutorResult

log = logging.getLogger(__name__)


class Coordinator:
    """Owns the observe → dispatch → record → decide loop over a RunSession's tree.

    Parameters
    ----------
    cfg:
        Top-level Loop-SCI config (LoopSCIConfig). May be None when an
        executor is explicitly injected (e.g. in tests).
    executor:
        An Executor-compatible object (must have ``async run(unit) -> ExecutorResult``).
        If None, a real Executor is constructed from cfg.
    bus:
        Optional EventBus. Defaults to NullBus (no-op).
    step_budget:
        Maximum number of dispatch cycles before the loop exits. Also
        honoured from cfg.engine.step_budget if cfg is provided and no
        explicit value is given.
    """

    def __init__(
        self,
        cfg: Any = None,
        *,
        executor: Any = None,
        bus: Any = None,
        step_budget: int | None = None,
    ) -> None:
        # Explicit kwarg wins; fall back to cfg.engine.step_budget, then 10.
        if step_budget is None:
            step_budget = 10
            if cfg is not None:
                try:
                    step_budget = cfg.engine.step_budget
                except AttributeError:
                    pass  # cfg has no engine.step_budget; keep default

        if executor is not None:
            self.executor = executor
        else:
            # Build a real Executor from cfg when none is injected
            from .executor import Executor
            self.executor = Executor(cfg)

        self.bus = bus or NullBus()
        self.step_budget = step_budget

    # ── Public API ────────────────────────────────────────────────────

    async def run(self, session: RunSession) -> None:
        """Run the coordinator loop until no pending work or step budget hit."""
        if session.is_complete:
            log.info("run %s already complete — no-op", session.run_id)
            return

        self.bus.emit(SESSION_START, {
            "run_id": session.run_id,
            "task": session.cursor.get("task", ""),
        })

        steps = 0

        while steps < self.step_budget:
            node = self._observe(session)
            if node is None:
                log.info("No pending nodes — run complete.")
                break

            # Mark node running (update_node auto-saves)
            session.tree.update_node(node.id, status="running")

            unit = self._plan(node)

            self.bus.emit(EXECUTOR_START, {
                "node_id": node.id,
                "goal": unit.goal,
            })

            try:
                result: ExecutorResult = await self.executor.run(unit)
            except Exception as exc:
                log.exception("executor.run failed for node %s", node.id)
                result = ExecutorResult(status="error", summary=str(exc))

            # INVARIANT: persist BEFORE next decision
            self._record(session, node, result)

            self.bus.emit(EXECUTOR_END, {
                "node_id": node.id,
                "status": result.status,
                "summary_preview": result.summary[:100] if result.summary else "",
            })

            steps += 1
            session.advance_step()

        session.mark_complete()
        self.bus.emit(SESSION_END, {
            "run_id": session.run_id,
            "steps": steps,
        })

    # ── Observe ───────────────────────────────────────────────────────

    def _observe(self, session: RunSession) -> Node | None:
        """Pick the next dispatchable leaf node, or ROOT when bootstrapping.

        Bootstrap: get_pending_leaves() excludes depth-0 nodes. If the tree
        has no pending leaves but ROOT is still pending, return ROOT itself
        so that the first cycle always dispatches something.

        Resume: stale ``running`` leaves (crash-interrupted mid-dispatch) are
        re-observed and re-dispatched. Completed ``done`` nodes are never
        returned.
        """
        pending = session.tree.get_pending_leaves()
        if pending:
            return sorted(pending, key=lambda n: n.id)[0]

        root = session.tree.get_root()
        if root.status == "pending":
            return root

        running = [
            n for n in session.tree.get_all_nodes()
            if n.status == "running"
            and not n.children_ids
            and n.depth > 0
        ]
        if running:
            return sorted(running, key=lambda n: n.id)[0]

        if root.status == "running":
            return root

        return None

    # ── Plan ──────────────────────────────────────────────────────────

    def _plan(self, node: Node) -> DispatchUnit:
        """Build a DispatchUnit for the given node."""
        return DispatchUnit(
            node_id=node.id,
            goal=node.hypothesis,
            context="",
            tools=[],
        )

    # ── Record ────────────────────────────────────────────────────────

    def _record(self, session: RunSession, node: Node, result: ExecutorResult) -> None:
        """Write executor outcome into the tree.

        update_node() auto-saves the tree for the mutable fields.
        refs is not in MUTABLE_FIELDS, so we set it directly and call
        session.tree.save() to ensure persistence BEFORE the next decision.
        """
        # Map ExecutorResult.status → node status
        if result.status == "done":
            node_status = "done"
        elif result.status == "bounded_exit":
            node_status = "needs_retry"
        else:  # "error"
            node_status = "needs_retry"

        updates: dict[str, Any] = {
            "status": node_status,
            "insight": result.insight or result.summary[:200] if result.summary else "",
        }
        if result.score is not None:
            updates["score"] = result.score

        # update_node applies MUTABLE_FIELDS-whitelisted fields and saves
        session.tree.update_node(node.id, **updates)

        # refs is NOT in the vendor MUTABLE_FIELDS whitelist; set directly
        if result.refs:
            node.refs = result.refs
            session.tree.save()  # explicit save to persist refs
