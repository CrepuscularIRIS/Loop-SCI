# Brainstorm Summary

- Change: hypothesis-engine (Loop-SCI change #4)
- Date: 2026-07-14

## Confirmed Technical Approach

Plan-grade research-os loop on a dedicated hypothesis idea-tree, consuming #2's `FactStore` (stable query interface, NOT tree parentage). Runtime Qwen/Bailian. #4 ends at ranked hypotheses; #5 assembles the 13-field plan.

**Tree shape:** `topic root → problem-card nodes → hypothesis nodes (+ rival siblings)`. Own `RunSession`.

**Fused schema (native Node fields + refs):**
- `Node.hypothesis` = one-sentence statement; `Node.status` = open|accepted|pruned(KILL); `Node.eval_status` = generated|critiqued|accepted (done≠accepted); `Node.insight` = MECHANISM+rationale; `Node.score` = 0.5·novelty+0.5·self_consistency (weights configurable); `Node.score_split` = {novelty, self_consistency}; `Node.grounding` = [fact_id] into FactStore.
- `Node.refs` = {kind, frame:primary|rival, topic, card{Q,WHY_NOW,PROBE_KILL,STAKES}, hyp{MECHANISM,KILL,BRACKET,DIFF_PREDICTION}, derivation[{step,grade:[paper]|[inferred]|[guess],fact_ids}], contract{HYPOTHESIS,LATENT_ROOT,ACCEPT_IF,KILL_IF}, verdict{id,reviewer_model,result,reasons}, scores{novelty,self_consistency,decided_by}, autopsy{outcome,region,note}, iteration{round,stall_count}}.

**Scoring (CONFIRMED: hybrid, mirror #2):** novelty = normalized lexical/structural distance from grounding facts, bands LOW=0.15/HIGH=0.60 (≤LOW restatement, ≥HIGH novel, band→Qwen-Plus judge 0-1). self_consistency = deterministic base (contradiction scan + evidence-grade completeness: no load-bearing [guess]) → borderline→judge. Deterministic floor doubles as anti-fabrication backstop.

**Thresholds (Hydra-configurable):** admit if STAKES≥θ and region not closed (no GPU-day gate); caps ≤5 cards · ≤4 candidates/card · ≤3 rounds; stall pivot@2 / escalate@4. Jury DOWN if any of {mechanism contradicts grounding · load-bearing [guess] · fails Check C claim-envelope · fails Check D generalization}.

**Jury (CONFIRMED):** generator=Qwen-Max, reviewer=Qwen-Plus (KILL-biased persona, higher temp+different seed). Structural no-self-acquit: UP verdict with reviewer_model==generator_model is rejected. Deterministic pre-jury gate runs first (fail⇒DOWN, no jury call).

**Stage shapes:** prospect'/forge'/adversary'/autopsy' = prompt+parse units on the Qwen provider (structured JSON, invalid→retry-once→drop, like #2's extractor). Relabeling filter deterministic (strip novel terms→re-derive diff-prediction; identical to status-quo⇒discard). autopsy' outcomes accumulate into a run-level lessons block injected into later prompts (reuse vendored get_constraints_block()).

**Control flow (CONFIRMED call C):** HypothesisExecutor.run(unit) runs the full multi-round loop internally per topic (like #2's batch executor); coordinator subclass overrides only _observe() for score-priority expansion. NO per-stage dispatch, NO coordinator-interface change, auto_git off.

**Resumability (CONFIRMED call D):** reuse RunSession (per-run dir+tree+atomic cursor). accepted ⟺ eval_status=="accepted" AND refs.verdict.result=="UP" with verdict_id. Durable append-only verdict-ledger.jsonl sidecar for fast already-accepted scan + audit. Cursor stores {round, stall_count}; resume=load tree+cursor, skip accepted nodes (LitMinerExecutor refs-skip pattern).

**Confirmed judgment calls:** A hypotheses under problem-card node (grounding by fact-id) · B deterministic pre-jury gate ships in #4 · C executor-internal loop · D verdict-ledger sidecar. Reviewer tier = Qwen-Plus.

## Key Trade-offs and Risks

- Qwen-vs-Qwen independence is family-correlated → distinct tier + persona + varied sampling + deterministic backstop; revisit substrate if too lenient.
- Novelty scoring subjective → measured vs fact base, reproducible offline, tunable bands.
- Plan-grade feasibility without runs could be hand-wavy → concrete ACCEPT-IF/KILL-IF tripwires; #5 CORAL spot-check later.
- Non-convergence → stall pivot@2/escalate@4 + region-close.
- Budget (300¥) → per-run caps; jury fires once per surviving candidate; deterministic gate avoids wasted jury calls.

## Testing Strategy

Offline-by-default: role-dispatching MockProvider serving BOTH generator+reviewer; deterministic checks tested directly. Pins: gap-cards fact-grounded · relabeling discarded · no-self-acquit · ungrounded downgraded · kill→constraint reweights · pivot@2/escalate@4 · resume-skips-accepted · ranked interface · tools offline. Integration: coordinator→HypothesisExecutor→MockProvider+seeded FactStore → ≥1 accepted scored hypothesis, ranked-retrievable, anti-fab+no-self-acquit pinned. Live @pytest.mark.live: real Max-gen+Plus-review over a small neuro topic, skip without DASHSCOPE_API_KEY. Coverage ≥80% (excl vendored), ruff clean, README section.

## Spec Patches

Two boundary clarifications to write back:
1. `hypothesis-generation` 1.3 — clarify hypotheses attach under the problem-card node (not the fact node); grounding is by fact-id reference into the FactStore.
2. `hypothesis-critique` — add a scenario: a hypothesis failing the deterministic pre-jury gate (contradiction / load-bearing [guess]) is DOWN'd without spending a jury call.
