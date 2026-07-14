"""HypothesisExecutor — prospect' → forge' → contract → adversary' → autopsy' loop.

Standalone executor (does NOT subclass Coordinator) that mirrors the
LitMinerExecutor pattern: constructed with its collaborators, exposes
``async def run(unit: DispatchUnit) -> ExecutorResult``.

Pipeline per round
------------------
1. prospect'  — mine problem-card nodes from FactStore
2. forge'     — generate candidate hypotheses per card
3. contract   — freeze derivation contract before verdict
4. adversary' — deterministic gate + Qwen-vs-Qwen jury
5. autopsy'   — classify kills; update StallLedger + RegionTracker

Resume (osp 3.5)
----------------
On re-run, ``VerdictLedger.accepted_node_ids()`` provides the set of already-
accepted nodes.  Any hypothesis node found in that set is skipped entirely —
no re-critique, no new verdict-ledger entry.

Node scoring
------------
``Node.score`` is set to ``w_n * novelty + w_c * self_consistency`` (the
weighted overall score).  The sub-score map is stored in ``node.refs["scores"]``.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from loop_sci.engine.types import DispatchUnit, ExecutorResult
from loop_sci.hypothesis.config import HypothesisConfig
from loop_sci.hypothesis.ledger import VerdictLedger
from loop_sci.hypothesis.scoring import score_hypothesis
from loop_sci.hypothesis.stages.adversary import run_adversary
from loop_sci.hypothesis.stages.autopsy import RegionTracker, StallLedger, classify_kill
from loop_sci.hypothesis.stages.contract import freeze_contract
from loop_sci.hypothesis.stages.forge import run_forge
from loop_sci.hypothesis.stages.prospect import run_prospect
from loop_sci.literature.factbase.store import FactStore
from loop_sci.state.idea_tree import Node
from loop_sci.state.session import RunSession

log = logging.getLogger(__name__)

__all__ = ["HypothesisExecutor"]


class HypothesisExecutor:
    """Execute the full multi-round hypothesis lifecycle for a research topic.

    Parameters
    ----------
    session:
        The active ``RunSession`` that owns the idea-tree and cursor.
    gen_provider:
        LLM provider for generation (prospect / forge / contract).
        Must expose ``await create(*, system, messages, max_tokens)``
        and a ``.model`` attribute.
    rev_provider:
        DISTINCT LLM provider for the adversarial reviewer (must differ
        from ``gen_provider.model`` to satisfy the no-self-acquit constraint).
    store_path:
        Path to the JSON ``FactStore`` file.
    config:
        ``HypothesisConfig`` dataclass with all caps, thresholds, and model
        names.  Defaults to ``HypothesisConfig()`` (all defaults).
    """

    def __init__(
        self,
        session: RunSession,
        *,
        gen_provider: Any,
        rev_provider: Any,
        store_path: Path,
        config: HypothesisConfig | None = None,
    ) -> None:
        self._session = session
        self._gen = gen_provider
        self._rev = rev_provider
        self._store = FactStore(Path(store_path))
        self._cfg = config or HypothesisConfig()
        self._ledger = VerdictLedger(
            session.session_dir / "verdict-ledger.jsonl"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self, unit: DispatchUnit) -> ExecutorResult:
        """Execute the hypothesis loop for *unit.goal* (the research topic).

        Always returns an ``ExecutorResult`` — never raises.  On internal
        failure, ``status="error"`` is returned with the exception message.

        Parameters
        ----------
        unit:
            ``DispatchUnit`` produced by the coordinator.  ``unit.node_id``
            must be ``"ROOT"`` or a valid parent node in the session tree.
            ``unit.goal`` is used as the research topic string.
        """
        try:
            return await self._run_loop(unit)
        except Exception as exc:  # noqa: BLE001
            log.exception("HypothesisExecutor: unhandled error for goal=%r", unit.goal)
            return ExecutorResult(
                status="error",
                summary=f"HypothesisExecutor failed: {exc}",
                score=None,
                insight="",
                refs={"error": str(exc)},
            )

    # ------------------------------------------------------------------
    # Internal pipeline
    # ------------------------------------------------------------------

    async def _run_loop(self, unit: DispatchUnit) -> ExecutorResult:
        """Inner loop — may raise; callers wrap in try/except."""
        cfg = self._cfg
        topic = unit.goal
        tree = self._session.tree
        facts = self._store.all()

        # ── Resume: collect already-accepted node_ids from the ledger ──────────
        accepted_ids: set[str] = self._ledger.accepted_node_ids()
        # Also sweep the tree for nodes already marked accepted (in-memory guard)
        for n in tree.get_all_nodes():
            if n.status == "accepted":
                accepted_ids.add(n.id)

        # Early-return resume: if we already have accepted hypotheses and the
        # tree already contains accepted nodes from a prior run, skip all gen
        # calls — the session's hypothesis work is done.
        if accepted_ids:
            accepted_in_tree = [n for n in tree.get_all_nodes() if n.status == "accepted"]
            if accepted_in_tree:
                log.info(
                    "resume: %d accepted nodes already in tree — skipping gen calls",
                    len(accepted_in_tree),
                )
                self._session.advance_step()
                return ExecutorResult(
                    status="done",
                    summary=(
                        f"Resume: {len(accepted_ids)} hypotheses already accepted; "
                        "no new gen calls."
                    ),
                    score=None,
                    insight=f"{len(accepted_ids)} accepted (resumed).",
                    refs={
                        "accepted_count": len(accepted_ids),
                        "new_accepted_count": 0,
                        "lessons": [],
                    },
                )

        stall = StallLedger(pivot_at=cfg.pivot_at, escalate_at=cfg.escalate_at)
        region_tracker = RegionTracker()
        lessons: list[str] = []
        total_new_accepted = 0
        final_round = 0

        for round_n in range(cfg.max_rounds):
            final_round = round_n
            log.info("hypothesis round %d  topic=%r", round_n, topic)

            # -- 1. prospect' -------------------------------------------------
            cards = await run_prospect(
                topic,
                self._store,
                self._gen,
                max_cards=cfg.max_cards,
            )
            new_accepted_this_round = 0

            for card_node_id, card_refs in cards:
                # Ensure card node exists in tree
                if card_node_id not in tree._nodes:
                    card_node = Node(
                        id=card_node_id,
                        parent_id=unit.node_id,
                        hypothesis=card_refs.get("card", {}).get("Q", ""),
                        depth=1,
                        status="pending",
                        refs=dict(card_refs),
                    )
                    tree.add_node(card_node)

                # -- 2. forge' ------------------------------------------------
                candidates = await run_forge(
                    card_node_id,
                    card_refs,
                    self._store,
                    self._gen,
                    max_candidates=cfg.max_candidates,
                )

                for hyp_node_id, hyp_refs, derivation in candidates:
                    # Resume guard: skip already-accepted hypothesis
                    if hyp_node_id in accepted_ids:
                        log.debug("skip already-accepted node %s", hyp_node_id)
                        continue

                    # Ensure hypothesis node exists in tree
                    if hyp_node_id not in tree._nodes:
                        hyp_node = Node(
                            id=hyp_node_id,
                            parent_id=card_node_id,
                            hypothesis=(hyp_refs.get("hyp") or {}).get("MECHANISM", ""),
                            depth=2,
                            status="pending",
                            refs=dict(hyp_refs),
                        )
                        tree.add_node(hyp_node)

                    # -- 3. contract ------------------------------------------
                    contract = await freeze_contract(hyp_refs, self._gen)
                    hyp_refs["contract"] = {
                        "HYPOTHESIS": contract.HYPOTHESIS,
                        "LATENT_ROOT": contract.LATENT_ROOT,
                        "ACCEPT_IF": contract.ACCEPT_IF,
                        "KILL_IF": contract.KILL_IF,
                    }

                    # -- 4. adversary' ----------------------------------------
                    verdict = await run_adversary(
                        hyp_refs,
                        derivation,
                        self._store,
                        cfg.generator_model,
                        self._rev,
                    )
                    self._ledger.append(
                        verdict.id,
                        hyp_node_id,
                        verdict.reviewer_model,
                        verdict.result,
                        round_n=round_n,
                    )
                    hyp_refs["verdict"] = {
                        "id": verdict.id,
                        "reviewer_model": verdict.reviewer_model,
                        "result": verdict.result,
                        "reasons": verdict.reasons,
                        "decided_by": verdict.decided_by,
                    }

                    # -- Scoring ----------------------------------------------
                    mechanism = (hyp_refs.get("hyp") or {}).get("MECHANISM", "")
                    scores = score_hypothesis(
                        mechanism,
                        derivation,
                        facts,
                        low=cfg.novelty_low,
                        high=cfg.novelty_high,
                    )
                    overall = cfg.w_n * scores.novelty + cfg.w_c * scores.self_consistency
                    hyp_refs["scores"] = {
                        "novelty": scores.novelty,
                        "self_consistency": scores.self_consistency,
                        "decided_by": scores.decided_by,
                    }

                    # -- Update node ------------------------------------------
                    # Persist refs directly (refs is not in MUTABLE_FIELDS)
                    node = tree._nodes.get(hyp_node_id)
                    if node is not None:
                        node.refs = dict(hyp_refs)

                    if verdict.result == "UP":
                        # Accepted: set score and status
                        tree.update_node(hyp_node_id, score=overall, status="accepted")
                        accepted_ids.add(hyp_node_id)
                        new_accepted_this_round += 1
                        total_new_accepted += 1
                        log.info(
                            "hypothesis accepted: node=%s score=%.3f", hyp_node_id, overall
                        )
                    else:
                        # -- 5. autopsy' --------------------------------------
                        autopsy = classify_kill(verdict, hyp_refs)
                        hyp_refs["autopsy"] = {
                            "outcome": autopsy.outcome,
                            "region": autopsy.region,
                            "note": autopsy.note,
                        }
                        if node is not None:
                            node.refs = dict(hyp_refs)
                        tree.update_node(
                            hyp_node_id,
                            status="pruned",
                            score=overall,
                            insight=f"KILL: {autopsy.outcome} — {autopsy.note[:80]}",
                        )
                        region_tracker.record_kill(contract.LATENT_ROOT)
                        lessons.append(f"[{autopsy.outcome}] {autopsy.note[:60]}")

                    tree.save()

            # -- Stall detection per round ------------------------------------
            action = stall.record_round(new_accepted_this_round)
            log.debug(
                "round %d done  new_accepted=%d stall_action=%s",
                round_n,
                new_accepted_this_round,
                action,
            )
            if action == "escalate":
                log.warning(
                    "hypothesis: escalating after persistent stall at round %d", round_n
                )
                break
            # pivot: log and continue to next round (lessons injected implicitly)
            if action == "pivot":
                log.info("hypothesis: pivot at round %d", round_n)

        # ── Advance session cursor ─────────────────────────────────────────────
        self._session.advance_step()

        summary = (
            f"Hypothesis engine: {total_new_accepted} new accepted "
            f"({len(accepted_ids)} total) after {final_round + 1} round(s)."
        )
        log.info(summary)

        return ExecutorResult(
            status="done",
            summary=summary,
            score=None,
            insight=(
                f"{total_new_accepted} accepted after {final_round + 1} round(s)."
            ),
            refs={
                "accepted_count": len(accepted_ids),
                "new_accepted_count": total_new_accepted,
                "lessons": lessons,
            },
        )
