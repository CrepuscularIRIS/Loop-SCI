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
