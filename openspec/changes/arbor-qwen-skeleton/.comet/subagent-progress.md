# Subagent Progress Checkpoint — arbor-qwen-skeleton

- change: arbor-qwen-skeleton
- build_mode: subagent-driven-development
- tdd_mode: tdd
- review_mode: thorough (per-task reviewer every task, max 2 fix rounds; final complete review)
- plan: docs/superpowers/plans/2026-07-14-arbor-qwen-skeleton.md
- branch: feature/20260714/arbor-qwen-skeleton
- model routing: implementers=Sonnet 4.6; task reviewers=Opus 4.8 + grok review; fixes=grok rescue / Sonnet fix agent; final review=Opus 4.8 (most capable)

## Watch-items (from pre-flight; review loop must catch)
- Task 7 `refs` monkey-patch on vendored Node does NOT survive to_dict/from_dict serialization (Node is a @dataclass with fixed fields + MUTABLE_FIELDS whitelist). If generic `refs` persistence is required, prefer a real subclass/adapter or store refs inside an existing field. Not critical for the foundation (no consumer yet).
- Task 5 `config/loader.py` uses ad-hoc `type(...)()` objects for EngineConf/RunConf instead of the dataclasses defined in schemas.py — should use the real dataclasses.
- Plan tests assume IdeaTree accessors that may not exist upstream (get_node/get_root/get_all_nodes/get_pending_leaves/next_child_id). Verify against vendored idea_tree.py; add thin wrappers in state/idea_tree.py if missing.
- Atomic write is NATIVE in vendored Arbor (`_atomic_write` at idea_tree.py); do NOT edit vendored files to add it. Spec Patch "interrupted mid-write" satisfied natively.

## Task ledger

- Total tasks: 17

## HARD GATE for Tasks 5 (config loader) & 10 (agent runtime): AgentConfig MUST set auto_git=False
Reason: vendored experiment.py `GitManager` (default auto_git=True at config.py:1150) executes `git checkout`/`git reset --hard`/`checkout -b`. Must stay dormant — never wire it live. Task 5/10 reviewers MUST verify auto_git=False.

## OpenSpec tasks.md checkoff: DEFERRED to a pre-guard batch reconciliation
Reason: open-phase tasks.md text is stale vs design (1.3 says vendor "orchestrator"; 1.4 says "flat-proxy config" — design chose Hydra & excludes orchestrator). Will fix stale text (small delta) + check all boxes + run comet-state task-checkoff right before the build guard. Per-task tracking lives in this ledger + plan step checkboxes.

### Current task
- Task 6: Tool registry (loop_sci/engine/tools.py)
- Stage: implementing
- review-fix round: 0 / 2
- risk task: yes (many files; import-closure rewriting) — expect per-task review to scrutinize vendored edits
- grok policy: grok:grok-rescue agent for fixes + second-opinion on high-risk tasks (15,16); Opus 4.8 = authoritative per-task gate

## OpenSpec tasks.md reconciliation (do before build guard)
Plan→OpenSpec mapping (loose/many-to-many; check off openspec sub-tasks as genuinely done):
- Plan T1 scaffold → osp 1.2 (HOLD: logging config lands with CLI task T14)
- Plan T2 vendor → osp 1.1, 1.3
- Plan T3 provider → osp 2.1, 2.2, 2.5
- Plan T4 ToolProtocol → osp 2.4
- Plan T5 Hydra config → osp 1.4 IS STALE ("flat-proxy"); design chose Hydra — fix osp 1.4 text at T5 (small spec incremental update)
- Plan T6 tool registry → osp 3.2
- Plan T7 idea-tree → osp 4.1, 4.2 (+ atomic-write scenario)
- Plan T8 session → osp 4.3, 4.4
- Plan T9 event bus → osp 5.1, 5.2
- Plan T10 agent runtime → osp 3.1, 3.3
- Plan T11 executor → osp 3.4
- Plan T12 coordinator → osp 3.4 (coordinator half)
- Plan T13 integration → osp 7.2
- Plan T14 CLI → osp 6.1 (+ logging → osp 1.2)
- Plan T15 live smoke → osp 2.3
- Plan T16 e2e run+resume → osp 6.2, 6.3
- Plan T17 coverage+README → osp 7.1, 7.3

### Completed
- Task 1: complete (impl 5fb5a41, review clean — Opus 4.8; 2 Minor noted for final review; 3/3 tests RED->GREEN)
- Task 2: complete (impl 65dbcb5, Opus 4.8 Approved; 2 Important ACCEPTED [auto_git=False downstream gate; .arbor kept as faithful-snapshot behavior-preserving], 1 Minor [under-covering import-smoke — add agent/context/experiment imports, for final review]; 8 import-smoke + 11/11 RED->GREEN; fork boundary held, Apache-2.0 + commit 0eae8ad recorded)
- Task 3: complete (impl 5009693, Opus 4.8 Approved; 0 Critical/Important; 3 Minor for final review: [with_retry(max_retries=0) raises None — add guard]; [add non-retryable-not-retried test]; [redact always prefixes sk- — cosmetic]; 8/8 provider + 19/19 RED->GREEN; security surface verified)
- Task 4: complete (impl 98ee1b0; Opus review found 1 IMPORTANT [non-dict JSON crash] -> grok:grok-rescue fix 6b841b7 -> Opus re-review Approved; 16/16; 1 Minor [parser doesn't validate tool name — final review])
- Task 5: complete (impl 5a9ad8c Opus Approved — 4 HARD gates verified live [auto_git=False, real dataclasses, ContextConfig.window, missing-key-no-crash]; grok hygiene fix 3dcdc74 [OmegaConf warn 11->0, drop unused os import]; 30 new/57 total, pristine, ruff clean)
