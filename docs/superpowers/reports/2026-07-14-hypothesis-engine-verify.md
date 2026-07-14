---
comet_change: hypothesis-engine
role: verification-report
verify_mode: full
verdict: pass
---

# Verification Report: hypothesis-engine (Loop-SCI change #4)

Full verification (scale: 25 tasks · 4 delta-spec capabilities · 43 changed files). Independent Opus verification via the OpenSpec verify-change methodology (Completeness / Correctness / Coherence). Read-only — no files modified during verification.

## Summary scorecard

| Dimension | Status |
|-----------|--------|
| **Completeness** | 25/25 tasks checked `[x]`; 12/12 requirements implemented |
| **Correctness** | 18/18 delta-spec scenarios covered by real offline tests |
| **Coherence** | Followed — design.md, Design Doc, proposal, and both Spec Patches all reflected in implementation; no drift |

## Fresh evidence (HEAD `bbc8430`, via `.venv`)

- Full suite: **449 passed / 7 skipped** (7 = live tests, skip cleanly without `DASHSCOPE_API_KEY`).
- ruff: **All checks passed**.
- Coverage `loop_sci/hypothesis/`: **95%** (every module ≥80%; `scoring.py` at exactly 80%).
- No hardcoded secrets in `loop_sci/hypothesis/` or `conf/hypothesis/`.

## Completeness

All 25 task lines in `tasks.md` checked, 0 unchecked. Every Requirement across the 4 delta specs maps to a concrete implementation (`stages/prospect.py`, `stages/forge.py`, `stages/contract.py`, `stages/adversary.py`, `stages/autopsy.py`, `scoring.py`, `ledger.py`, `ranked.py`, `executor.py`, `coordinator.py`, `tools.py`, `config.py` + `conf/hypothesis/default.yaml`). No requirement unimplemented.

## Correctness — every scenario pinned by a real test

All 18 `#### Scenario:` entries across the 4 capabilities have a covering offline test. Load-bearing coverage highlights:

- **No self-acquit** (structural): `test_adversary.py::test_no_self_acquit_rejects_up_when_reviewer_equals_generator`, `::test_blocker2_...`, `test_executor.py::test_executor_no_self_acquit_honored`, integration `test_no_self_acquit_accepted_verdict_has_distinct_reviewer`. Verdict compares the **real** generator provider identity (not a config string).
- **Deterministic pre-jury gate DOWNs without a jury call** (Spec Patch #2): `test_adversary.py::test_deterministic_gate_downs_load_bearing_guess_without_jury_call`, `::test_deterministic_gate_downs_contradicting_mechanism_without_jury_call`, `::test_paper_step_with_absent_fact_id_downed_without_jury` (all assert reviewer call-count 0).
- **Anti-fabrication**: ungrounded `[paper]`/`[inferred]` citation (fact-id not resolvable in `FactStore`, incl. falsy ids) is DOWN'd at the gate; `[guess]` floored in scoring. integration `test_anti_fabrication_absent_fact_id_never_accepted`.
- **Hypotheses under problem-card node, grounding by fact-id** (Spec Patch #1): `test_forge.py::test_hypothesis_nodes_are_children_and_siblings_of_card_node`, `test_ranked.py::test_grounding_fact_ids_sourced_from_derivation_not_native_grounding`.
- **Resume skips accepted (no re-critique/re-spend)**: deterministic SHA-1 node ids + `VerdictLedger.accepted_node_ids`; integration `test_resume_across_disk_reload_skips_accepted` reloads the session from disk and asserts no new ledger entries / no duplicate nodes.
- **Bounds**: region-close ≥2 (`test_executor_region_close_stops_generation`), stall pivot@2/escalate@4, per-run caps.

## Coherence

- **design.md**: plan-grade research-os spine; Qwen-Max-vs-Qwen-Plus non-self-acquitting jury; idea-tree hypothesis space reusing vendored primitives (no new primitives); coordinator subclass overrides only `_observe`/`_plan`; `auto_git` off; #4 ends at ranked hypotheses. All honored.
- **Design Doc**: fused Node schema + `refs` payload; `accepted` = jury UP + verdict_id; hybrid scoring bands LOW=0.15/HIGH=0.60 + deterministic anti-fab floor; deterministic pre-jury gate ships in #4; executor-internal multi-round loop; RunSession + `verdict-ledger.jsonl` resume. All present.
- **proposal.md**: consumes #2 `FactStore` read-only; defers executed experiments / 13-field assembly / cron+monitor to #5/#6/#7. Honored.
- **Drift**: none. Both Spec Patches reflected in code.

## Build-phase review trail

Built via subagent-driven-development (Sonnet 4.6 implementers, Opus 4.8 per-task + final whole-branch reviews, thorough mode, TDD). The review layer caught and fixed **7 real bugs** unit-green code would have shipped: (1) anti-fabrication ungrounded-`[paper]`-citation hole, (2) ranked grounding read from wrong field, (3) interrupted-resume re-spend, (4) cross-module `refs["scores"]` deserialize crash (found by integration test), and the final whole-branch review's 3 cross-task coherence gaps — (5) dead `critique`/`rank` tool endpoints, (6) no-self-acquit comparing a config string vs the real generator identity, (7) falsy fact-id filter — all fixed with bite-tests verified fail-against-old.

## Deferred follow-ups (accepted, non-blocking; recorded for #5/cleanup)

- autopsy substring keyword classify (`dead`→`deadline`) → word-boundary match.
- Consolidate duplicate `HypothesisConf` (config/schemas) vs `HypothesisConfig` (hypothesis/config) dataclasses.
- Hoist `DispatchUnit` import out of `tools._generate`.
- Document that `refs["scores"]` is a superset of the `Scores` dataclass (tolerant deserialize is intentional).

## Final assessment

**PASS — READY FOR ARCHIVE.** No CRITICAL / IMPORTANT / WARNING issues. All acceptance scenarios implemented and tested offline; live path gated on `DASHSCOPE_API_KEY`.
