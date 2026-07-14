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
- Tasks 1-9 COMPLETE. Task: 10a (HypothesisExecutor) -> osp 4.3 (+resume tail 3.5)
- Stage: task-review (fix round 1)
- Commit: 6d284b2; review CHANGES REQUIRED, 3 Important loop-enforcement gaps:
  (1) resume not idempotent on interrupted runs (fresh uuids -> re-spend); (2) region-close tracked but not enforced; (3) pivot no-op (lessons not injected).
- Fix round 1 dispatched: deterministic node ids for per-node resume skip + interrupted-resume bite-test; enforce is_closed w/ configurable threshold; inject get_constraints_block lessons on pivot; + minors (tighten never-raises test, decided_by assert, refs overall).
- Fix round: 1/2
