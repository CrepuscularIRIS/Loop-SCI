# Subagent-Driven Development — Coordinator Checkpoint

- Change: hypothesis-engine (Loop-SCI #4)
- Branch: feature/20260714/hypothesis-engine
- Plan: docs/superpowers/plans/2026-07-14-hypothesis-engine.md (11 tasks)
- base-ref: cb26804f5b61e84acd40ba16b30a7ecc2d11f1bd
- review_mode: thorough (per-task Opus review every task + final complete review)
- tdd_mode: tdd (RED/GREEN evidence required)
- Routing: Sonnet 4.6 implementers, Opus 4.8 reviews, Grok rescue

## Task → OpenSpec mapping
- T1 Schemas/refs → osp 1.1
- T2 Scoring → osp 4.1
- T3 Verdict ledger → osp 3.4
- T4 prospect' → osp 1.2
- T5 forge'+relabel+cap → osp 1.3,1.4,1.5,1.6
- T6 contract freeze → osp 2.1
- T7 adversary' gate+jury → osp 2.2,2.3,2.4,2.5
- T8 autopsy'+stall+region → osp 3.1,3.2,3.3,3.5
- T9 ranked interface → osp 4.2
- T10 executor+coordinator+tools+config → osp 4.3,4.4,4.5,4.6
- T11 integration+live+README+coverage → osp 5.1,5.2,5.3

## Env note
- Interpreter: `.venv/bin/python` (hydra 1.3.4, ruff 0.15.21). Bare python=conda (no deps). All implementer/fix dispatches MUST use `.venv/bin/python -m pytest` + `.venv/bin/ruff`.

## Current
- Tasks 1-6 COMPLETE. Task: 7 (adversary' jury) -> osp 2.2,2.3,2.4,2.5 [CRITICAL]
- Stage: task-review (fix round 1)
- Commit: c1c01c1; adversarial review: 2.2 & 2.3 VERIFIED unbreakable; 2.4 FAIL (real anti-fab hole: ungrounded [paper] w/ absent fact_id passes gate).
- Fix round 1 dispatched: add deterministic id-resolution gate branch ([paper]/[inferred] must cite ≥1 resolvable fact_id else DOWN, no jury call) + absent-fact-id tests; dedup anti-fab helper w/ scoring; hoist stopwords; guard reasons.
- Fix round: 1/2
