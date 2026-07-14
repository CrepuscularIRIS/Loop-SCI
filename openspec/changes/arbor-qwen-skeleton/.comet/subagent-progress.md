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

### Current task
- Task 2: Vendor Arbor snapshot
- Stage: implementing
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
