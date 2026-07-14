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

## FORWARD: Task 5 (extractor) should CLAMP confidence to [0,1] (Fact has no range check). Task 6 (verify) may narrow VerificationStatus.status to a Literal/Enum + validate layer_reached 1-4.

## FORWARD: Task 6 (verify) can narrow VerificationStatus.status to Literal/Enum + validate layer_reached 1-4 (T4 deferral). Extractor grounding min-span-length hardening = future (out of scope).
## T12 RUFF SWEEP: 3 unused-import violations in dispatch.py/test_dispatch.py (typing.Any + 2 fixable) + earlier minors (unused field import schema.py, etc.).

### Current task
- Task 6: L1 format + L2 existence + L3 metadata verification layers
- Stage: implementing
- review-fix round: 0 / 2
- NOTE: grok auth expired -> Sonnet-fallback fixes. `grok login` to restore.
- NOTE: grok auth expired -> Sonnet-fallback fixes. `grok login` to restore.
- NOTE: grok auth expired -> Sonnet-fallback fixes. `grok login` to restore.

## FINAL-REVIEW minors to flag: dispatch.py except BaseException (swallows CancelledError -> narrow to Exception, async correctness); dispatch.py O(n2) name lookup; + Task1/2 minors (unused-field-import ruff-swept? non-frozen PaperResult; bare-except in adapters).

## PRE-GUARD RUFF SWEEP (Task 12): unused `field` import in loop_sci/literature/search/schema.py (+ any others). tasks.md checkoff deferred to pre-guard batch.

### Completed
- Task 1: complete (impl c748a67 Opus Approved; REAL mockable httpx offline seam [MockTransport, async runs, no socket]; PaperResult all spec fields; leak-free async lifecycle; 13 new/146 pristine; 2 Minor [unused field import->ruff; non-frozen deliberate])
- Task 2: complete (impl eeff586 mapping/offline/PubMed-2-hop correct; Opus found 1 IMPORTANT [arXiv _strip_version corrupts external_id] -> Sonnet fix e125629 (grok down): anchored vN$ regex + 3 regression tests + malformed-skip tests all 3 adapters + defusedxml -> Opus re-review Approved no regression; 193 passed/5 skipped, ruff clean)
- Task 3: complete (impl 02553c8 Opus Approved; 3 resilience guarantees [no-propagate/no-sibling-cancel/bounded-retry] all proven by REAL tests [sibling-completion tracked, re-invocation counts]; gather return_exceptions=True + injectable backoff; 9 new/198 pristine; 2 Minor [except BaseException->Exception; O(n2) lookup - final review])
- Task 4: complete (impl 9dc8b44 Opus Approved; evidence-required 2-layer enforced + 4 independent tests; lossless round-trip nested SourceRef/VerificationStatus; grounding_scope constrained; SourceRef upgraded to typed dataclass; 17 new/219 pristine; 2 Minor deferred [confidence range->T5; status enum->T6])
- Task 5: complete (impl 6d434cf; Opus found 1 IMPORTANT [anti-fabrication crux: grounding was prompt-only, not runtime-traceable] -> Sonnet fix 08ad881: normalized span-in-text runtime drop before cap + not-in-source drop test + reflowed-keep test -> Opus re-review Approved [no false-keep loophole, no regression]; confidence clamp; bounded; invalid-JSON->[]; 232 passed/5 skipped; 1 Minor [degenerate short-span match - future])

### Completed
(none yet)
