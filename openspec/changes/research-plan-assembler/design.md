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
