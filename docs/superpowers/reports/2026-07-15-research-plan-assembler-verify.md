# Verification Report — research-plan-assembler (change #5)

- Date: 2026-07-15
- Change: `research-plan-assembler` (Loop-SCI #5)
- Branch: `feature/20260714/research-plan-assembler` (17 commits, `f0efc95..204ad53`)
- Verify mode: **full** (20 tasks, 4 delta capabilities, 34 files changed)
- Result: **PASS**

## Scope

A new `loop_sci/plan/` package that turns one change-#4 `RankedHypothesis` into the
12-field 《科学假设与研究计划》 (the competition deliverable), emitted as canonical JSON
(source of truth) + derived Markdown, gated by a deterministic provider-free
completeness/anti-fabrication gate. 3 Qwen calls/plan; Datasets/Source/Target
deterministic from grounding facts as candidates; References real-only (grounding-seeded,
optional verify()-gated extras via change #2); `PlanAssemblerExecutor` + `assemble` tool
over the foundation seam; resumable by node_id; `auto_git` off.

## Full-verification checklist (openspec-verify-change methodology)

| # | Check | Result |
|---|-------|--------|
| 1 | All `tasks.md` tasks `[x]` | PASS — 0 unchecked (20/20) |
| 2 | Implementation matches open-phase `design.md` high-level decisions | PASS — all 10 decisions present (domain-parameterized, formula-derivation, VerificationPipeline reuse, canonical JSON, deterministic gate, executor+tool) |
| 3 | Implementation matches Design Doc (`docs/superpowers/specs/2026-07-14-research-plan-assembler-design.md`) | PASS — 3-call decomposition, grounding-only-refs default, JSON source-of-truth + derived MD, node_id-keyed resume, provider-free gate all as designed |
| 4 | All capability spec scenarios pass | PASS — 18/18 scenarios mapped to real backing tests (below); full suite green |
| 5 | `proposal.md` goals satisfied | PASS — 12-field plan, domain-general, real refs (严禁虚构), formula-derivation path all delivered; deferred items (bounded-execution, domain-pack, HITL, viz) correctly out of scope |
| 6 | No delta-spec ↔ Design Doc contradiction | PASS — see "Spec/design consistency" below |
| 7 | Design Doc locatable | PASS — file exists (11.9 KB), links this change |

## Scenario → test mapping (18/18)

**plan-field-assembly**
- 12-field reasoning fields → `test_reasoning_fields_nonempty_and_experiments_has_baselines_and_metrics`
- domain parameterized (not hard-coded) → `test_domain_is_parameterized_no_code_change`
- DST candidates trace to grounding → `test_dst_candidates_trace_to_grounding_facts`
- no fabricated dataset when grounding absent → `test_no_fabricated_dataset_when_grounding_absent`

**results-derivation**
- formula-derivation with graded steps → `test_derive_results_is_graded_derivation_no_execution`
- no execution path → same + module grep (0 subprocess/eval/os.system/shell calls in code)
- load-bearing guess downgrades → `test_load_bearing_guess_downgrades_to_low`, `test_downgrade_when_load_bearing_step_is_guess`, `test_final_when_load_bearing_grounded`

**reference-verification-assembly**
- only verified references appear → `test_grounded_hypothesis_yields_real_refs_count_ge_distinct_sources`, `test_verified_provider_ref_admitted`
- fabricated citation dropped → `test_fabricated_citation_dropped`
- grounded hypothesis yields real refs → `test_grounded_hypothesis_yields_real_refs_count_ge_distinct_sources`

**plan-assembly-integration**
- both output forms, all 12 fields → `test_markdown_contains_all_12_field_titles`, `test_parity_holds_for_complete_plan`, `test_to_dict_carries_all_12_keys_plus_provenance`
- incomplete/unverified fails gate → `test_gate_fails_on_empty_field`, `test_gate_fails_on_unverified_reference`, `test_gate_fails_on_ungrounded_load_bearing_claim`
- complete verified passes gate → `test_gate_passes_on_complete_verified_plan`
- executor e2e offline → `test_executor_assembles_gated_12_field_plan`, `test_e2e_offline_gated_complete_plan_and_resume`
- tool wraps pipeline → `test_assemble_tool_with_executor_success`, `test_assemble_tool_offline_no_executor_structured_error`
- **completed plan not re-assembled on resume (Spec Patch)** → `test_resume_does_not_reassemble` + e2e resume assertion

## Spec/design consistency

- The Design Doc defines load-bearing = the **last/decisive** derivation step and states a
  load-bearing `[guess]` forces `confidence != final`. The shipped rule ("last step
  `[guess]` ⇒ low, unconditionally") matches this and is a **safe superset** (stricter) of
  the `results-derivation` delta-spec scenario. **No contradiction.** (The abandoned "no
  other support" phrasing lived only in the plan brief — a build artifact, not the
  canonical delta spec or Design Doc — so no design-doc drift; adjudicated at build time.)
- The one Spec Patch (resume acceptance scenario on `plan-assembly-integration`) is present
  and backed by a real test.

## Evidence (fresh, coordinator-run)

- `.venv/bin/python -m pytest -q` → **487 passed, 8 skipped** (live tests, need `DASHSCOPE_API_KEY`).
- `.venv/bin/ruff check` (plan pkg + config + tests) → **All checks passed**.
- `loop_sci/plan` coverage **92%** (≥ 80% gate; vendored excluded).
- Security: no hardcoded secrets in `loop_sci/plan/`; live provider reads `DASHSCOPE_API_KEY` from env only.

## Build-phase review lineage

Built subagent-driven (Sonnet 4.6 implementers, Opus 4.8 per-task + final reviews,
thorough mode, TDD). One **Important** caught + fixed (Task 6 partial-persist window:
`.json` written before `.md` vs `.json`-only resume sentinel → reordered `.md`-first,
bite-tested RED-against-old/GREEN-after). Final whole-branch Opus review: **READY TO
MERGE** — anti-fabrication verified sound end-to-end (3 fabricated paths all blocked by
composing guards), 0 Critical/Important. Deferred Minors recorded in
`.superpowers/sdd/progress.md` (cosmetic/test-strength only).

## Conclusion

**PASS.** The change is spec-complete, design-consistent, anti-fabrication-sound, and
fully tested offline. Ready for branch handling.
