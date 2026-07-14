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

## HARD GATE for Task 9 (executor): WIRE L3 expected metadata. Currently expected_year/expected_authors are ad-hoc test-only attrs -> L3 INERT in production (all resolving facts pass to pending_l4). Task 9 MUST pass the source PaperResult's authors/year/venue as the expected values to VerificationPipeline (or extend SourceRef to carry them), with an INTEGRATION TEST proving L3 catches a real metadata mismatch on a real fact. Else 4-layer silently becomes 3-layer (rubric 可验证性 risk). Final review must verify L3 is exercised in the real flow.
## Task 6 minors (final review): year-check false-passes when resolved paper.year is None; surname heuristic=longest-token (loose, false-pass leaning); DOI-fallback to fetch_by_id unverified vs real adapters.

## FORWARD Task 11 (integration tests): HARDEN the L3-mismatch test to assert VerificationStatus.layer_reached==3 explicitly (currently asserts verified_count==0 — non-vacuous only because L4 would verify; make it robust to L4/fixture changes).

### Current task
- Task 11: Offline integration tests — anti-fabrication + resume-no-reverify (+ HARDEN L3 assert layer_reached==3 per T9 fwd note)
- Stage: implementing
- review-fix round: 0 / 2
- NOTE: grok auth expired -> Sonnet-fallback fixes. `grok login` to restore.
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
- Task 6: complete (impl ea34a36 Opus Approved; CORE holds [L2 rejects hallucinated via real adapter lookup - tested; short-circuit call-count proven]; pending_l4 hook clean; VerificationStatus tightened [Literal status + layer 1-4]; 17 new/FULL 249 passed/5 skipped; 1 IMPORTANT [L3 expected-metadata unwired -> INERT in prod -> HARD GATE for T9] + 3 Minor final-review)
- Task 7: complete (impl 5db0e5a L4 hybrid grounding [lexical HIGH/LOW->no Qwen, borderline->Qwen judge; genuinely cost-controlled, tested _index==0/==1]; misattributed->reject@L4; Opus found 1 IMPORTANT [double-resolve 2x fetch/fact] -> Sonnet fix d26cb78 resolve-once reuse L2 paper + fetch==1 test -> Opus re-review Approved [byte-identical L1-L3, zero regression]; 265 passed/5 skipped. FULL 4-LAYER VERIFICATION DONE. 1 Minor [L123 block dup])
- Task 8: complete (impl 23e1133 Opus Approved; ONLY-verified guard airtight [persist_fact guards before any write; rejected/pending/None -> NEITHER tree nor store, all tested]; root->paper->fact nodes + Node.refs payload round-trips disk; JSON store retrieve-all/filter lossless; same-paper dedup test present; 26 new/291 passed/5 skipped; 1 Minor [store.add unguarded - use persist_fact in T9])
- Task 9: complete (impl 7bc3551 INDEPENDENT Opus Approved [impl self-review NOT trusted]; ALL 3 HARD REQS met — L3 WIRED [expected_year/authors from PaperResult] + test MUTATION-VERIFIED non-vacuous [reviewer: no-wiring->verified@4, wiring->rejected@3]; dedup one-paper-node keyed external_id; persist_fact guarded no store.add; resume durable via tree refs; 6 offline tests; 297 passed/5 skipped; 2 Minor [assert layer_reached==3 explicit->T11; advance_step no mark_complete intentional])
- Task 10: complete (impl ecdc329 Opus Approved; 4 tools [lit_search/fetch/extract/verify] real schemas + async dispatch->JSON string + structured errors from real registry; genuine Task1-9 wrap w/ injected deps offline; 2 shortcuts PROVABLY BENIGN [verify never reads confidence; extract only reads abstract; L3-noop is hint-gated by design]; 15 new/312 passed/5 skipped; 2 Minor [DOI provenance in _extract; 1 under-asserting test])

### Completed
(none yet)
