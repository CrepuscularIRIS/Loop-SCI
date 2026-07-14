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

## FORWARD NOTE for Tasks 11/12: build_agent is CFG-FIRST: build_agent(cfg, *, provider=None, tools=None, bus=..., node_id="", agent_label=..., system_prompt=...). types.py: DispatchUnit(node_id, goal, context, tools); ExecutorResult(status, summary, score, insight, refs) with status Literal {"done","bounded_exit","error"}. (types.py already created in Task 10.)
## FORWARD NOTE for Task 12 (coordinator): to update refs via tree.update_node, first override on subclass: Node.MUTABLE_FIELDS = _VendorNode.MUTABLE_FIELDS | {"refs"} (else ValueError). Or set node.refs directly (persists). status/score/insight ARE already mutable. Check is_complete before trusting get_pending_leaves after mark_complete.

## CRITICAL for Task 12 (coordinator): stub session starts with ONLY a pending ROOT at depth 0. get_pending_leaves() EXCLUDES depth 0 -> returns []. So coordinator MUST bootstrap: either (a) dispatch ROOT itself on the first cycle when no pending leaves exist and ROOT is pending, OR (b) seed a child node under ROOT (depth 1) and dispatch that. Ensure >=1 observe->dispatch->record cycle runs on the stub, then session.mark_complete(). Executor is Executor(cfg, *, provider, bus); executor.run(unit) is async -> Coordinator.run is async. Record outcome into node BEFORE next decision (update_node status/score/insight auto-saves; refs via node.refs direct or MUTABLE_FIELDS override). Emit node/lifecycle events via bus.

### Current task
- Task 15 (HIGH-RISK): Live Qwen tool-call smoke test (@pytest.mark.live)
- Stage: implementing
- review-fix round: 0 / 2
- note: .superpowers/ now gitignored. Earlier task-7/9/10/12 reports still TRACKED -> git rm --cached in pre-guard cleanup.

## PRE-GUARD CLEANUP TODO: (1) add `.superpowers/` to .gitignore (SDD report/diff scratch committed) + git rm --cached tracked scratch; (2) sweep ruff (unused `import pytest` in test_event_bus.py, any others) — Task 17 lint gate.
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
- Task 6: complete (impl d59d028 Opus Approved; dispatch provably fail-closed on all escape paths; asyncio.to_thread sync path; 63 passed pristine; 2 Minor [BaseException exclusion is by-design; stronger malformed-args assertion — final review])
- Task 7: complete (impl cea9e0d Opus Approved; refs = REAL persisted subclass field, round-trip verified; load_json faithfully duplicated; no vendored edits; 10/10 new, 73/73 pristine; 3 Minor [keep-in-sync comment on load_json; refs->MUTABLE_FIELDS for Task12; import json placement — final review])
- Task 8: complete (impl 920143d Opus Approved; atomic cursor write [tmp+Path.replace]; resume + already-complete-no-op proven by real tests; subclass tree so refs survives resume; 6/6 new, 79/79 pristine; 3 Minor [completed_node_ids YAGNI ok; mark_complete/is_complete contract note for Task12; temp-name cosmetic — final review])
- Task 9: complete (impl c0ad2da Opus Approved; faithful pure re-export EventBus/NullBus/Event+types; NullBus genuine no-op; exception-swallow test matches vendored; 5/5 new, 84/84 pristine; 2 Minor [tighter parity test; unused pytest import ruff-sweep — final review/T17])
- Task 10: complete (impl 000b508 Opus Approved; build_agent constructs vendored Agent w/ real sig; auto_git=False doubly-asserted; ToolRegistry orthogonal seam no dup dispatch; types.py minimal; 18 new, 102 pristine; deliberate cfg-first build_agent signature; 2 Minor final-review)
- Task 11: complete (impl 529be18 Opus Approved; status mapping complete [finished->done/max_turns->bounded_exit/sentinel|exc->error]; airtight exception safety no propagation; FakeAgent stub no network; 7/7 new, 109/109 pristine; 3 Minor [sentinel string-match+xref comment; tools dict->Tool fwd for T12; None stop_reason sane])
- Task 12: complete (KEYSTONE; DUAL review. impl 8effdeb -> Opus Approved but GROK 2nd-opinion caught 2 IMPORTANT [executor-exc escapes run; resume orphans "running" nodes] -> grok fix ac0b3b4 (all 4 fixes + regressions) -> Opus re-review Approved (Fix-2 re-observe-running proven bounded: _record moves node out of running each cycle -> needs_retry not re-selected + step budget; happy path untouched); 14 coordinator + 123 full-suite pristine; bootstrap strategy (a); refs node.refs+tree.save)
- Task 13: complete (impl cb963f8 REAL end-to-end integration [Coordinator->Executor->vendored Agent vs MockProvider, offline]; Opus found 1 IMPORTANT [assertion too weak] -> grok fix 7f25183 tightened to ==done + mock answer asserted in live+reloaded insight; strict done passes deterministically => NO production bug; 4 integration + 127 full-suite pristine. [accepted fix w/o separate re-review: reviewer's exact prescription followed + strict assert passes])
- Task 14: complete (impl 2779b10 CLI run/resume/inspect; Opus found 1 IMPORTANT [bad run_id raw traceback] -> grok fix 1363b16 clean not-found+Exit(1)+regression tests + 2 Minor fixed [orphan dir; f-strings] -> Opus re-review Approved [guard scoped tight, no over-swallow; happy+missing-key preserved]; 10 CLI + 137 full-suite pristine; async wrap; logging non-polluting)
