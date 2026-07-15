# Brainstorm Summary

- Change: research-plan-assembler (Loop-SCI change #5)
- Date: 2026-07-14

## Confirmed Technical Approach

Plan-grade assembler: #4 `RankedHypothesis` → 12-field 《科学假设与研究计划》. Domain-general (participant's-choice domain per PDF §3; threaded as a runtime param into every prompt). Runtime Qwen/Bailian.

**Field-group decomposition — 3 Qwen calls/plan (budget-safe, caps Hydra-configurable):**
- Call 1 (reasoning fields): {Problem Statement, Rationale, Technical Details, Methods, Experiments[Baselines+Metrics]} — structured JSON, anchored to the hypothesis problem/mechanism/derivation/diff-prediction + domain param.
- Call 2 (Results): evidence-graded formula-derivation (steps graded `[paper]/[inferred]/[guess]` + conclusion), then a DETERMINISTIC downgrade check (load-bearing `[guess]` ⇒ confidence=low/non-final). No execution, no shell/eval.
- Call 3 (Title + Abstract): runs last (needs the assembled plan as context).
- Datasets/Source/Target: DETERMINISTIC from grounding facts (data/dataset mentions in fact claims/entities + source refs) as candidates; no fabricated dataset when grounding absent. Source = historical data the derivation rests on; Target = to-be-collected data features the diff-prediction implies. Generic (no domain templates).
- References: DETERMINISTIC assembly + #2 verify().

**References (grounding-only by default, verify()-gated for extras):** grounding-derived refs come from ALREADY-VERIFIED facts (the #2 fact base only admits verified facts) → real by construction, seed the list. Optional provider-proposed citations (config flag, OFF by default) are wrapped as a `Fact` (source_ref+claim) and must pass `VerificationPipeline.verify(fact) -> status=="verified"`; unverifiable dropped/flagged. 严禁虚构 = structural.

**Cross-change seam confirmed:** `VerificationPipeline(search_clients, grounding_provider=None).verify(fact: Fact) -> VerificationStatus{layer_reached 1-4, status: failed|rejected|pending_l4|verified}`. Verifies a `Fact` (has `source_ref` {source,external_id,doi} + claim + evidence_span), not a bare string. Mockable via `MockSearchClient` (offline, like #2's own tests).

**Canonical JSON schema:** `ResearchPlan` with 12 stable keys + provenance. `Results = {derivation:[{step,grade}], conclusion, confidence: final|low}`. `References = [{source, external_id, doi, verified: bool, fact_id?}]`. Datasets/Source/Target carry `candidate` flags. JSON is the source of truth; Markdown is DERIVED from it (never divergent content).

**PlanAssemblerExecutor.run(unit)** (mirrors HypothesisExecutor/LitMinerExecutor standalone class, `async run(unit)->ExecutorResult`, exception-safe→status="error"): resolve ranked hypothesis (node_id via unit) → Call1 + deterministic datasets/source/target → Call2 Results + downgrade → Call3 title/abstract → collect+verify references → build canonical JSON + render Markdown → DETERMINISTIC gate → persist `session_dir/plans/<node_id>.{json,md}` + record. `assemble` tool wraps same pipeline w/ injected deps (structured results/errors). No coordinator-interface change; auto_git off. Hydra `conf/plan/default.yaml` (domain default, call budget, thresholds) wired into LoopSCIConfig.

**Resume keyed by hypothesis node_id** (stable SHA-1 from #4): if `plans/<node_id>.json` exists ⇒ skip re-assembly (mirror #4 accepted-skip / #2 refs-skip). RunSession-backed.

**Deterministic gate (provider-free):** all 12 fields present+non-empty · every reference verified · no ungrounded load-bearing claim. Fail ⇒ flagged incomplete (not final). No Qwen critique-revise loop (deferred).

## Key Trade-offs and Risks

- Plan-grade Results could read thin → concrete evidence-graded derivation steps + load-bearing-`[guess]` downgrade; bounded-execution change later spot-checks.
- Domain-general could be generic → every prompt anchored to the concrete mechanism/diff-prediction/grounding facts + domain param.
- Reference verify offline → mock the #2 verification/search seam (MockSearchClient); default suite network-free. Grounding-only default = zero fabrication risk.
- Budget (300¥) → 3 Qwen calls/plan; gate/render/refs deterministic.
- Field-contract drift → 12 fields pinned in delta specs + canonical JSON keys; completeness gate fails any missing field.

## Testing Strategy

Offline generator `MockProvider` + mocked verification seam + seeded FactStore + a `RankedHypothesis`. Pins: 12 fields non-empty · Experiments carries baselines+metrics · domain parameterized (two domains, no code change) · dataset/source/target candidates trace to grounding · no fabricated dataset · Results graded + load-bearing-`[guess]` downgrade · references verified-only + fabricated dropped + grounded yields ≥ distinct-sources refs · JSON↔Markdown parity (all 12, no divergence) · gate fail (missing/empty field, unverified ref) + pass · tool offline · resume skips completed plan (persisted `plans/<node_id>.json`). Integration: executor end-to-end offline → gated complete plan, no network/git, resume-no-reassemble. Live `@pytest.mark.live` real Qwen assembly, skip w/o DASHSCOPE_API_KEY. Coverage ≥80% (excl vendored), ruff clean, README section.

## Spec Patches

1. `plan-assembly-integration` — add a `#### Scenario` for resume: a completed plan (persisted under `plans/<node_id>.json`) is NOT re-assembled on a second executor run for the same hypothesis node_id (no re-spend). The requirement text already states resumability; this adds the missing acceptance scenario.
