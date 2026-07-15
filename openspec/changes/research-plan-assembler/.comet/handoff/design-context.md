# Comet Design Handoff

- Change: research-plan-assembler
- Phase: design
- Mode: compact
- Context hash: 2ca1a095e253e313463c99ba3633958281440c9b6ababa4056a7356bbd667ca5

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/research-plan-assembler/proposal.md

- Source: openspec/changes/research-plan-assembler/proposal.md
- Lines: 1-32
- SHA256: 11627c6d855f60cf7833cd6336a8b5c7c2660b9ae4d50acf2644091b9b9d518f

```md
## Why

Loop-SCI can now mine facts (change #2) and turn them into ranked, adversary-tested hypotheses (change #4) — but nothing yet produces the **actual competition deliverable**. Challenge XH-202619 is scored on a standardized document, the 《科学假设与研究计划》, whose §4 fixes **12 required fields** (Problem Statement, Rationale, Technical Details, Datasets, Source, Target, Paper Title, Abstract, Methods, Experiments, Results, References). This change builds the assembler that turns one ranked hypothesis into that 12-field plan — the artifact experts and AI-assisted review actually grade (科学价值 40 / 应用潜力 30).

Two constraints from the PDF shape the design. First, the domain is the **participant's choice** — 自然科学 *or* 人文社科 — and 跨学科技术迁移 (cross-disciplinary transfer) is itself a scored capability; so the assembler must stay **domain-general and parameterizable**, not hard-wired to one vertical. Second, References must be a **real** literature list (严禁虚构), and Results may be produced **via formula-derivation OR execution**. This change takes the plan-grade path (formula-derivation), reusing #2's citation-verification to guarantee every reference is real, and defers the heavier bounded-execution runner to a later change.

## What Changes

- **Field assembly** — consume #4's `RankedHypothesis` (read-only) and assemble the 12 standardized fields via the Qwen provider, driven by the hypothesis + the #2 fact base. The **domain is a parameter**, not a constant; Datasets/Source/Target are drawn from grounding facts as **candidates** (real dataset resolution is deferred to the neuro-domain-pack).
- **Results by formula-derivation** — the Results field is an analytical feasibility argument derived from the hypothesis mechanism + diff-prediction, with each derivation step **evidence-graded** (`[paper]/[inferred]/[guess]`) exactly as in #4; no experiments are executed here.
- **Real references** — candidate references are routed through change #2's `VerificationPipeline.verify`; only verified citations appear in the plan, unverifiable ones are dropped/flagged (严禁虚构).
- **Output + gate** — a canonical JSON (12 fields) plus a rendered Markdown 《科学假设与研究计划》; a **deterministic gate** enforces that all 12 fields are present and non-empty, every reference is verified, and no load-bearing claim is ungrounded.
- **Integration** — a `PlanAssemblerExecutor` over the foundation Executor seam plus an `assemble` tool in the ToolRegistry; offline-testable with a `MockProvider`, resumable via `RunSession`. No coordinator-interface change; `auto_git` stays off.

## Capabilities

### New Capabilities
- `plan-field-assembly`: assemble the reasoning/context fields (Problem Statement, Rationale, Technical Details, Datasets, Source, Target, Paper Title, Abstract, Methods, Experiments) of the 12-field plan from a ranked hypothesis + fact base via Qwen, domain-parameterized, with Datasets/Source/Target grounded as candidates from the fact base.
- `results-derivation`: produce the Results field by formula-derivation — an analytical feasibility argument (bound/effect) derived from the hypothesis, with evidence-graded steps and no ungrounded load-bearing claim; no experiment execution.
- `reference-verification-assembly`: produce the References field as a real-only list by routing every candidate citation through the literature-mining verification pipeline; unverifiable references are dropped/flagged (严禁虚构).
- `plan-assembly-integration`: emit the assembled plan as canonical JSON (12 fields) + rendered Markdown, enforce a deterministic completeness + anti-fabrication gate, and integrate as a `PlanAssemblerExecutor` + `assemble` tool over the foundation, resumable and offline-testable.

### Modified Capabilities
<!-- None. This change consumes the change #4 ranked-hypothesis interface and the change #2 verification pipeline / fact base through their stable public surfaces; it does not change any existing capability's requirements. -->

## Impact

- **New code**: a `loop_sci/plan/` package (field assembly, results derivation, reference verification adapter, output rendering + gate, executor, tool, config) + a Hydra config group `conf/plan/default.yaml`.
- **Consumes (read-only)**: change #4 `RankedHypothesis` / `RankedHypothesisStore`; change #2 `VerificationPipeline`, `FactStore`, `Fact`/`SourceRef`; foundation `Executor`/`DispatchUnit`/`ExecutorResult`/`ToolRegistry`, `RunSession`, idea-tree `Node`.
- **Runtime**: Qwen via Alibaba Cloud Bailian (mandated); offline tests inject a `MockProvider`; live tests gated on `DASHSCOPE_API_KEY`.
- **Deferred (not in scope)**: bounded execution runner for the Results field (→ a later change); real dataset resolution + domain specialization (→ neuro-domain-pack #2); human-in-loop review (#6); visualization / HTML export (#7); a Qwen critique-revise loop over the assembled plan.
- **Budget**: Qwen calls bounded per assembly (field-group calls × one plan) to respect the 300¥/person cap, mirroring #2/#4 bounding.

```

## openspec/changes/research-plan-assembler/design.md

- Source: openspec/changes/research-plan-assembler/design.md
- Lines: 1-44
- SHA256: 6a54eab1171674c6bbff2e98248af54c1aacb7d471c65db07a43f672c273ddd2

```md
## Context

Change #5 sits on the shipped foundation (#1: coordinator/executor + idea-tree + Qwen/Bailian provider + ToolRegistry), the verified fact base + citation-verification (#2), and the ranked-hypothesis engine (#4). It builds the **deliverable producer**: `RankedHypothesis → 12-field 《科学假设与研究计划》`. This is the artifact the competition grades (科学价值 40 / 应用潜力 30), so correctness of the field contract, the reality of references (严禁虚构), and plan-grade feasibility (Results by formula-derivation) are the priorities.

The competition PDF (§3–§4) fixes two framing constraints: the **domain is the participant's choice** (自然科学 or 人文社科, with cross-disciplinary transfer explicitly scored), so the assembler is **domain-parameterized**, not vertical-locked; and Results may be produced **via formula-derivation OR execution** — this change takes the plan-grade (formula-derivation) path and defers a bounded execution runner to a later change.

## Goals / Non-Goals

**Goals:**
- Assemble the 12 standardized fields from one ranked hypothesis + the fact base, domain-parameterized, reproducible offline.
- Guarantee References are real by reusing #2's `VerificationPipeline`; drop/flag anything unverifiable.
- Produce Results by formula-derivation with evidence-graded steps; no execution, no fabricated measurement.
- Emit canonical JSON (source of truth) + rendered Markdown; enforce a deterministic completeness + anti-fabrication gate.
- Integrate as a `PlanAssemblerExecutor` + `assemble` tool over the foundation seam; resumable; no coordinator-interface change; `auto_git` off.

**Non-Goals (deferred):**
- Bounded execution runner for Results (executed experiments, graders, leaderboards) → a later change.
- Real dataset resolution + domain specialization → neuro-domain-pack (#2, deferred).
- Human-in-loop debate/checkpoints (#6); visualization / HTML export (#7).
- A Qwen critique-revise loop over the assembled plan (the gate here is deterministic, not a jury).

## Decisions

- **Domain-parameterized assembler, not a vertical.** The domain (and topic) is a runtime parameter threaded into every Qwen prompt; the fact base (#2) is already domain-agnostic. This directly serves the PDF's cross-disciplinary-transfer scoring and keeps neuroscience specialization deferred. *Alternative rejected:* neuroscience-templated fields (would forfeit generality + the cross-disciplinary score, and couple #5 to the deferred domain pack).
- **Results = formula-derivation, evidence-graded (reuse #4's grading spine).** The Results field is an analytical feasibility argument whose steps carry `[paper]/[inferred]/[guess]`; a load-bearing `[guess]` downgrades the conclusion. This mirrors #4's anti-fabrication discipline and honors the PDF's "公式推导或实际执行" option without an execution environment. *Alternative rejected:* stub/execute now (pulls in a runtime + grader + real datasets that depend on the deferred domain pack — the scope the user split out).
- **References via #2's `VerificationPipeline` (real-only).** References are seeded from the hypothesis grounding facts' `SourceRef`s (already verified) and any provider-proposed citations are routed through `verify(...)`; unverifiable ones are excluded/flagged. This makes 严禁虚构 a structural guarantee, not a prompt hope. *Alternative rejected:* trust Qwen's citations (fabrication risk that the competition explicitly penalizes).
- **Datasets/Source/Target as fact-base candidates.** Populated from grounding facts (with source refs), marked as candidates; no fabricated dataset. Real resolution defers to the domain pack. *Alternative rejected:* Qwen-invented datasets (fabrication) or hard placeholders (loses the grounding signal).
- **Canonical JSON + derived Markdown.** JSON is the machine source of truth (consumed by #6/#7); Markdown is rendered from it so the two can never diverge. *Alternative rejected:* Markdown-only (forces re-parsing downstream) or JSON-only (defers all rendering to #7, leaving #5 without a human-readable deliverable).
- **Deterministic gate, not a jury.** Completeness (12 fields non-empty) + references-all-verified + no ungrounded load-bearing claim, all provider-free. Keeps #5 focused and cheap; a Qwen critique-revise loop is deferred. *Alternative rejected:* a full self-review jury (scope + budget; #4 already supplies the adversarial rigor upstream on the hypothesis).
- **Executor + tool over the foundation seam.** A `PlanAssemblerExecutor` mirrors `HypothesisExecutor`/`LitMinerExecutor` (standalone class with `async run(unit) -> ExecutorResult`, resumable via `RunSession`); an `assemble` tool wraps the same pipeline with injected deps. No new vendored primitives, no coordinator-interface change, `auto_git` off. *Alternative rejected:* a bespoke pipeline outside the seam (needless; the foundation already gives dispatch, persistence, tools, resume).

## Risks / Trade-offs

- **[Plan-grade Results could read as hand-wavy]** → require concrete evidence-graded derivation steps and downgrade load-bearing `[guess]`; the bounded-execution change later can spot-check the winner.
- **[Domain-general assembly may produce generic fields]** → thread the domain + the hypothesis's concrete mechanism/diff-prediction/grounding into every prompt; the fields are anchored to real facts, not free text.
- **[Reference verification needs the #2 seams offline]** → inject a mock verification/search seam in tests (as #2's own tests do); default suite stays network-free.
- **[Budget (300¥)]** → bound Qwen calls per assembly (field-group calls × one plan); the gate and rendering are deterministic and provider-free.
- **[Field-contract drift]** → the 12 fields + their PDF semantics are pinned in the delta specs and the canonical JSON keys; a completeness gate fails any missing field.

## Open Questions

- Exact field-group decomposition for Qwen calls (one call per field vs grouped) — resolved in the design phase against budget/quality.
- Whether Source/Target benefit from light domain-aware templating or stay fully generic (kept generic here; revisit if quality demands it).
- Whether provider-proposed references (beyond grounding) are worth the extra verification round-trips, or References should be grounding-only by default (resolved in design; verification path exists either way).

```

## openspec/changes/research-plan-assembler/tasks.md

- Source: openspec/changes/research-plan-assembler/tasks.md
- Lines: 1-34
- SHA256: b53448304b52797abc4ccbcd0cf9ac7268abdabe57ce8d6f607a8202740a4e00

```md
## 1. Plan field assembly (domain-parameterized)

- [ ] 1.1 Define the 12-field plan schema (canonical JSON keys for Problem Statement, Rationale, Technical Details, Datasets, Source, Target, Paper Title, Abstract, Methods, Experiments, Results, References) + a `PlanField`/`ResearchPlan` payload with evidence-graded provenance where applicable
- [ ] 1.2 Implement domain-parameterized assembly of the reasoning/context fields (Problem Statement, Rationale, Technical Details, Paper Title, Abstract, Methods, Experiments) from a `RankedHypothesis` + fact base via the Qwen provider (domain as a runtime param; retry-once→drop + isinstance guard like the #4 stages)
- [ ] 1.3 Implement Datasets/Source/Target population from grounding facts as candidates (with source refs); no fabricated dataset when grounding is absent
- [ ] 1.4 Bound assembly by a per-plan Qwen call budget (field-group calls); stop cleanly
- [ ] 1.5 Unit tests (offline, mock provider): all reasoning fields non-empty; Experiments carries baselines + metrics; domain parameterized (two domains, no code change); dataset/source/target candidates trace to grounding facts; no fabricated dataset

## 2. Results by formula-derivation

- [ ] 2.1 Implement formula-derivation of the Results field (analytical feasibility bound/effect from mechanism + diff-prediction) with each step evidence-graded `[paper]/[inferred]/[guess]`; NO execution, no shell/eval
- [ ] 2.2 Implement the load-bearing-guess downgrade (a Results conclusion resting on an ungrounded load-bearing step is marked low-confidence / non-final)
- [ ] 2.3 Unit tests: Results is a graded derivation, no execution path; load-bearing `[guess]` downgrades the result; grounded derivation reaches a feasibility conclusion

## 3. Real-only reference verification

- [ ] 3.1 Implement reference collection: seed from the hypothesis grounding facts' `SourceRef`s (already verified) + optional provider-proposed citations
- [ ] 3.2 Route candidate references through change #2 `VerificationPipeline.verify`; include only verified, drop/flag unverifiable (严禁虚构); mockable seam (offline)
- [ ] 3.3 Unit tests: only verified references appear; a fabricated/unverifiable citation is dropped; a grounded hypothesis yields real references (count ≥ distinct grounding sources)

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

```

## openspec/changes/research-plan-assembler/specs/plan-assembly-integration/spec.md

- Source: openspec/changes/research-plan-assembler/specs/plan-assembly-integration/spec.md
- Lines: 1-34
- SHA256: b30c8e55c3ca71dbba2496878f98c2608e5d48eb77e94b4a056f011a4fe1b6bc

```md
## ADDED Requirements

### Requirement: Canonical JSON + rendered Markdown output
The system SHALL emit the assembled plan in two forms: a **canonical JSON** object carrying all 12 standardized fields (Problem Statement, Rationale, Technical Details, Datasets, Source, Target, Paper Title, Abstract, Methods, Experiments, Results, References) under stable keys, and a **rendered Markdown** 《科学假设与研究计划》 derived from the same JSON. The JSON SHALL be the machine-consumable source of truth for downstream review/visualization; the Markdown SHALL be derived from it (no independent content).

#### Scenario: Both output forms produced with all 12 fields
- **WHEN** a plan is assembled
- **THEN** the canonical JSON contains all 12 fields under their stable keys, and the rendered Markdown presents the same 12 fields as a readable document with no field present in one form but missing in the other

### Requirement: Deterministic completeness and anti-fabrication gate
The system SHALL apply a **deterministic gate** before a plan is emitted as final: all 12 fields present and non-empty; every entry in References verified (real); and no load-bearing claim ungrounded (consistent with results-derivation). A plan failing the gate SHALL be rejected/flagged as incomplete rather than emitted as a final deliverable. The gate SHALL require no provider call.

#### Scenario: Incomplete or unverified plan fails the gate
- **WHEN** an assembled plan is missing a field, has an empty field, or contains an unverified reference
- **THEN** the deterministic gate marks the plan as failing (not final), identifying the failed check, without invoking the provider

#### Scenario: Complete verified plan passes the gate
- **WHEN** an assembled plan has all 12 fields non-empty, all references verified, and no ungrounded load-bearing claim
- **THEN** the deterministic gate passes and the plan is emitted as final

### Requirement: Specialist executor and tool integration
The system SHALL provide a `PlanAssemblerExecutor` over the foundation Executor seam (it consumes a ranked hypothesis, assembles the fields, derives Results, verifies References, gates, and records the plan) and SHALL register an `assemble` tool in the ToolRegistry wrapping the same pipeline with injected dependencies. Integration SHALL require no change to the coordinator interface, SHALL keep `auto_git` disabled, and SHALL be resumable via `RunSession` (a completed plan is not re-assembled on resume).

#### Scenario: Executor assembles a plan end-to-end offline
- **WHEN** the executor is dispatched for a ranked hypothesis against a mock provider, a seeded fact base, and a mocked verification seam
- **THEN** it produces a gated, complete 12-field plan (JSON + Markdown) with real references and no network calls or git operations, retrievable through the plan record

#### Scenario: Tool wraps the same pipeline
- **WHEN** the `assemble` tool is invoked through the registry with injected dependencies
- **THEN** it exercises the same underlying assembly pipeline and returns a structured result (or a structured error), offline

#### Scenario: Completed plan is not re-assembled on resume
- **WHEN** the executor is dispatched a second time for a hypothesis whose plan was already assembled and persisted under `plans/<node_id>.json`
- **THEN** the existing plan is returned without re-invoking the provider or re-running verification (no re-spend), and the persisted plan is left unchanged

```

## openspec/changes/research-plan-assembler/specs/plan-field-assembly/spec.md

- Source: openspec/changes/research-plan-assembler/specs/plan-field-assembly/spec.md
- Lines: 1-23
- SHA256: 9e4c1aa07ba8a3bba1ee08ffd0cf2c19e00861d8eb22511c48e6d88d8a126bde

```md
## ADDED Requirements

### Requirement: Domain-parameterized field assembly from a ranked hypothesis
The system SHALL assemble the reasoning/context fields of the 《科学假设与研究计划》 — Problem Statement, Rationale, Technical Details, Paper Title, Abstract, Methods, Experiments — from a single ranked hypothesis (change #4 `RankedHypothesis`) plus the verified fact base, via the Qwen provider. The scientific **domain SHALL be a runtime parameter** (e.g. natural-science or humanities/social-science topic), not hard-coded; the same assembler SHALL produce a plan for any domain without code change. Assembly SHALL be reproducible offline with a mock provider.

#### Scenario: Twelve-field reasoning fields produced from a hypothesis
- **WHEN** the assembler is given a ranked hypothesis (problem, mechanism, evidence-graded derivation chain, diff-prediction, grounding fact-ids) and a target domain
- **THEN** it produces non-empty Problem Statement, Rationale, Technical Details, Paper Title, Abstract, Methods, and Experiments fields, where Rationale reflects the hypothesis's derivation chain and Experiments contains both baseline comparison and evaluation metrics

#### Scenario: Domain is parameterized, not hard-coded
- **WHEN** the assembler is invoked twice with the same hypothesis-shaped input but two different domain parameters (e.g. a neuroscience topic and a non-neuroscience topic)
- **THEN** both runs succeed and produce a full field set with no code change, and the domain parameter is reflected in the assembled content

### Requirement: Datasets, Source, and Target grounded as fact-base candidates
The system SHALL populate the Datasets, Source (the historical data the hypothesis derivation rests on), and Target (the to-be-collected data features the validation experiment needs) fields from the hypothesis's grounding facts, presented as **candidates** carrying their source references. The assembler SHALL NOT fabricate a dataset with no basis in the fact base; real dataset resolution is out of scope (deferred to the domain pack).

#### Scenario: Dataset/Source/Target candidates trace to grounding facts
- **WHEN** a hypothesis grounded in verified facts is assembled
- **THEN** the Datasets, Source, and Target fields reference dataset/data candidates drawn from those grounding facts (with their source references), and each candidate is marked as a candidate rather than a resolved dataset

#### Scenario: No fabricated dataset when grounding is absent
- **WHEN** a hypothesis has no grounding fact that mentions a dataset
- **THEN** the Datasets/Source/Target fields are populated conservatively (candidate/pending) without inventing a concrete dataset that does not appear in the fact base

```

## openspec/changes/research-plan-assembler/specs/reference-verification-assembly/spec.md

- Source: openspec/changes/research-plan-assembler/specs/reference-verification-assembly/spec.md
- Lines: 1-19
- SHA256: 48a99919dc7e9279842e7c17e05d8c379bf289e683c0a2e61a7b67abae555812

```md
## ADDED Requirements

### Requirement: Real-only References via the verification pipeline
The system SHALL produce the References field as a list of **real** citations only, by routing every candidate reference through the literature-mining verification pipeline (change #2 `VerificationPipeline`). A candidate reference that does not verify SHALL be excluded from the References field (or explicitly flagged as unverified), enforcing the 严禁虚构 constraint. Verification SHALL be reproducible offline with mocked seams (no network in the default test suite).

#### Scenario: Only verified references appear
- **WHEN** the assembler collects candidate references (from the hypothesis grounding facts and any provider-proposed citations) and routes them through the verification pipeline
- **THEN** the References field contains only citations that passed verification, each carrying its source reference (source/id/DOI), and no unverifiable citation is presented as real

#### Scenario: Fabricated citation dropped
- **WHEN** a provider-proposed reference cannot be verified (fails existence/metadata/grounding)
- **THEN** it is excluded from the References field (or flagged as unverified), and it never appears as a real reference in the assembled plan

### Requirement: Grounding facts seed the reference list
The system SHALL seed the References field from the hypothesis's grounding facts' source references — which are already verified facts from the fact base — so that a hypothesis grounded in real literature yields real references without introducing new unverified citations.

#### Scenario: Grounded hypothesis yields real references
- **WHEN** a hypothesis grounded in verified facts is assembled
- **THEN** the References field includes the source references of those grounding facts, and the reference count is at least the number of distinct grounding sources

```

## openspec/changes/research-plan-assembler/specs/results-derivation/spec.md

- Source: openspec/changes/research-plan-assembler/specs/results-derivation/spec.md
- Lines: 1-19
- SHA256: 4f4b422600e97395f5c71c7ff2aabdb2229c8daf528224194f4b05925c30b704

```md
## ADDED Requirements

### Requirement: Results by formula-derivation with evidence-graded steps
The system SHALL produce the Results field by **formula-derivation** — an analytical feasibility argument (an expected bound, effect size, or derivation showing the experiment is feasible within a stated range) derived from the hypothesis mechanism and diff-prediction. Each derivation step SHALL carry an evidence grade drawn from `[paper] | [inferred] | [guess]`, consistent with change #4. The system SHALL NOT execute any experiment, run any command, or fabricate a measured result.

#### Scenario: Formula-derivation Results with graded steps
- **WHEN** the assembler derives the Results field for a hypothesis with a mechanism and a diff-prediction
- **THEN** it produces an analytical feasibility argument whose steps are each annotated `[paper]`, `[inferred]`, or `[guess]`, and it does not report any executed-experiment measurement

#### Scenario: No execution path
- **WHEN** the Results field is produced
- **THEN** no experiment is run and no shell/eval command is invoked; the feasibility claim is derivational only

### Requirement: No ungrounded load-bearing result claim
The system SHALL NOT allow a load-bearing step of the Results derivation to rest solely on a `[guess]`. A feasibility conclusion whose supporting chain is load-bearing on an ungrounded step SHALL be downgraded (marked non-final / low-confidence), never presented as an established result.

#### Scenario: Load-bearing guess downgrades the result
- **WHEN** the Results derivation's decisive step is graded `[guess]` with no `[paper]`/`[inferred]` support
- **THEN** the Results field is marked as low-confidence / non-final rather than asserting feasibility as established

```
