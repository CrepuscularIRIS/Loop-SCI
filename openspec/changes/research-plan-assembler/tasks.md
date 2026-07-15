## 1. Plan field assembly (domain-parameterized)

- [x] 1.1 Define the 12-field plan schema (canonical JSON keys for Problem Statement, Rationale, Technical Details, Datasets, Source, Target, Paper Title, Abstract, Methods, Experiments, Results, References) + a `PlanField`/`ResearchPlan` payload with evidence-graded provenance where applicable
- [x] 1.2 Implement domain-parameterized assembly of the reasoning/context fields (Problem Statement, Rationale, Technical Details, Paper Title, Abstract, Methods, Experiments) from a `RankedHypothesis` + fact base via the Qwen provider (domain as a runtime param; retry-once→drop + isinstance guard like the #4 stages)
- [x] 1.3 Implement Datasets/Source/Target population from grounding facts as candidates (with source refs); no fabricated dataset when grounding is absent
- [ ] 1.4 Bound assembly by a per-plan Qwen call budget (field-group calls); stop cleanly
- [x] 1.5 Unit tests (offline, mock provider): all reasoning fields non-empty; Experiments carries baselines + metrics; domain parameterized (two domains, no code change); dataset/source/target candidates trace to grounding facts; no fabricated dataset

## 2. Results by formula-derivation

- [x] 2.1 Implement formula-derivation of the Results field (analytical feasibility bound/effect from mechanism + diff-prediction) with each step evidence-graded `[paper]/[inferred]/[guess]`; NO execution, no shell/eval
- [x] 2.2 Implement the load-bearing-guess downgrade (a Results conclusion resting on an ungrounded load-bearing step is marked low-confidence / non-final)
- [x] 2.3 Unit tests: Results is a graded derivation, no execution path; load-bearing `[guess]` downgrades the result; grounded derivation reaches a feasibility conclusion

## 3. Real-only reference verification

- [x] 3.1 Implement reference collection: seed from the hypothesis grounding facts' `SourceRef`s (already verified) + optional provider-proposed citations
- [x] 3.2 Route candidate references through change #2 `VerificationPipeline.verify`; include only verified, drop/flag unverifiable (严禁虚构); mockable seam (offline)
- [x] 3.3 Unit tests: only verified references appear; a fabricated/unverifiable citation is dropped; a grounded hypothesis yields real references (count ≥ distinct grounding sources)

## 4. Output, gate, and foundation integration

- [ ] 4.1 Implement canonical JSON emission (all 12 fields under stable keys) as the source of truth
- [ ] 4.2 Implement Markdown rendering derived from the canonical JSON (no independent content; the two never diverge)
- [ ] 4.3 Implement the deterministic gate (all 12 fields present + non-empty; every reference verified; no ungrounded load-bearing claim); provider-free; fail → flagged incomplete
- [ ] 4.4 Implement `PlanAssemblerExecutor` over the foundation Executor seam (consume ranked hypothesis → assemble → derive Results → verify refs → gate → record); no coordinator-interface change; `auto_git` off; resumable via `RunSession` (completed plan not re-assembled)
- [ ] 4.5 Register the `assemble` tool in the ToolRegistry wrapping the same pipeline with injected deps; structured results/errors; add the Hydra config group `conf/plan/default.yaml` (domain default, call budget, thresholds) wired into `LoopSCIConfig`
- [ ] 4.6 Unit tests: JSON + Markdown both carry all 12 fields (no divergence); gate fails on missing field / empty field / unverified reference and passes on a complete verified plan; tool exercises the pipeline offline

## 5. End-to-end, tests & docs

- [ ] 5.1 Offline integration test: the executor assembles a gated, complete 12-field plan (JSON + Markdown) from a ranked hypothesis + seeded fact base + mocked verification seam → real references, no network, no git; resume does not re-assemble a completed plan
- [ ] 5.2 Opt-in `@pytest.mark.live` e2e: real Qwen assembly over a small domain-parameterized topic on a seeded fact base (skip-verified without `DASHSCOPE_API_KEY`)
- [ ] 5.3 Coverage gate (≥80% on new code, excl. vendored) + ruff clean + README section (12-field plan overview, formula-derivation Results, real-reference verification, domain parameter, JSON+Markdown output, live-tests-need-keys)
