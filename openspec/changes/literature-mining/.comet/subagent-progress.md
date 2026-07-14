# Subagent Progress Checkpoint — literature-mining

- change: literature-mining (Loop-SCI change #2, on the shipped foundation)
- build_mode: subagent-driven-development · tdd_mode: tdd · review_mode: thorough
- plan: docs/superpowers/plans/2026-07-14-literature-mining.md (12 tasks)
- branch: feature/20260714/literature-mining
- model routing: implementers=Sonnet 4.6; per-task review=Opus 4.8 (+ grok 2nd-opinion on high-risk); fixes=grok rescue; final review=Opus 4.8
- foundation reuse: Executor(cfg, *, provider=None, bus=None) cfg-first; Node.refs persisted subclass dict (NO vendored edits); ToolRegistry.register(*, name, description, schema, fn); build_provider; load_config; RunSession
- offline-default: mock SearchClient (httpx MockTransport) + mock Qwen provider; NO default-suite network; opt-in @pytest.mark.live
- OpenSpec tasks.md checkoff: DEFERRED to a pre-guard batch (like #1) — per-task tracking here + plan step checkboxes. tasks.md 5 groups map to plan T1-12: search(T1-3)->osp1; extract(T4-5)->osp2; verify(T6-7)->osp3; factbase+integration(T8-10)->osp4; e2e+docs(T11-12)->osp5.

## Watch-items (pre-flight)
- Plan T7 (L4 grounding) modifies citation.py started in T6 — implementer must read both tasks.
- Grounding thresholds (LOW 0.15 / HIGH 0.60) are tunable class attrs on GroundingVerifier — live-tune later.
- IdeaTree.add_node raises ValueError on duplicate id — executor must check before add on resume (resumability).
- httpx adapters take an injectable AsyncClient; tests use MockTransport; don't set base_url on the real client.

## Task ledger — 12 tasks

### Current task
- Task 3: Multi-source dispatch — fan-out, backoff, graceful degrade
- Stage: implementing
- review-fix round: 0 / 2
- NOTE: grok auth expired -> fixes fall back to Sonnet (Opus review still gates). `grok login` to restore.

## PRE-GUARD RUFF SWEEP (Task 12): unused `field` import in loop_sci/literature/search/schema.py (+ any others). tasks.md checkoff deferred to pre-guard batch.

### Completed
- Task 1: complete (impl c748a67 Opus Approved; REAL mockable httpx offline seam [MockTransport, async runs, no socket]; PaperResult all spec fields; leak-free async lifecycle; 13 new/146 pristine; 2 Minor [unused field import->ruff; non-frozen deliberate])
- Task 2: complete (impl eeff586 mapping/offline/PubMed-2-hop correct; Opus found 1 IMPORTANT [arXiv _strip_version corrupts external_id] -> Sonnet fix e125629 (grok down): anchored vN$ regex + 3 regression tests + malformed-skip tests all 3 adapters + defusedxml -> Opus re-review Approved no regression; 193 passed/5 skipped, ruff clean)

### Completed
(none yet)
