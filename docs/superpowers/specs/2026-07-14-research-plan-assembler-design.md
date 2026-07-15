---
comet_change: research-plan-assembler
role: technical-design
canonical_spec: openspec
---

# Research Plan Assembler — Technical Design

Deep design for Loop-SCI change #5. Refines the open-phase `design.md` (high-level
framework) into implementation-level decisions: the Qwen call decomposition, the
canonical schema, the executor control flow, resume keying, the deterministic gate,
and the offline test seams. The OpenSpec delta specs remain canonical; this document
does not restate requirements, it decides *how* they are met.

## 1. Scope Recap (what this change ships)

`RankedHypothesis` (from #4) → a single 12-field 《科学假设与研究计划》, emitted as
canonical JSON (source of truth) plus a derived Markdown rendering. Domain-general
(participant's-choice domain per PDF §3, threaded as a runtime parameter). Runtime
brain is Qwen via Bailian. References are real-only by reusing #2's
`VerificationPipeline`. Results is produced by evidence-graded formula-derivation (no
execution). A provider-free deterministic gate decides final vs. incomplete.

**The 12 fields** (PDF §4, pinned): Problem Statement, Rationale, Technical Details,
Datasets, Source, Target, Paper Title, Abstract, Methods, Experiments
(Baselines+Metrics inside one field), Results, References.

Deferred (non-goals, unchanged from `design.md`): bounded execution runner for Results;
real dataset resolution + domain specialization (neuro-pack); human-in-loop (#6);
visualization/HTML (#7); any Qwen critique-revise loop over the assembled plan.

## 2. Field-Group Decomposition — 3 Qwen calls per plan

One-call-per-field is too many round-trips for the 300¥ budget; one-call-for-everything
loses the ability to ground Results and to write the Title/Abstract against the finished
plan. The chosen middle ground is **three provider calls**, each producing a bounded,
schema-validated JSON block. The per-plan call budget is Hydra-configurable
(`conf/plan/default.yaml`), defaulting to 3; deterministic steps make no call.

- **Call 1 — reasoning/context fields.** Produces `{Problem Statement, Rationale,
  Technical Details, Methods, Experiments}`. Every prompt is anchored to the concrete
  hypothesis (`problem`, `mechanism`, `derivation_chain`, `diff_prediction`) plus the
  domain parameter, so fields are pinned to real structure rather than free text.
  `Experiments` must carry both baselines and metrics (single field, per PDF).
- **Call 2 — Results by formula-derivation.** Produces an evidence-graded derivation:
  a list of `{step, grade}` where `grade ∈ {[paper], [inferred], [guess]}`, plus a
  `conclusion`. No execution, no shell, no `eval`. A **deterministic** post-check
  (provider-free) then downgrades: if a *load-bearing* step is `[guess]`, the Results
  `confidence` is set to `low`/non-final. This mirrors #4's anti-fabrication spine.
- **Call 3 — Title + Abstract.** Runs last because a faithful title/abstract needs the
  assembled plan as context.

**Deterministic (no call): Datasets / Source / Target.** Populated from the hypothesis
grounding facts as *candidates* (each carrying its source ref), never invented:
- `Source` = the historical data the derivation rests on (grounding facts' claims/refs).
- `Target` = the to-be-collected data features implied by `diff_prediction`.
- `Datasets` = dataset/data mentions surfaced in grounding fact claims/entities.
When grounding is absent, the field is an explicit empty/candidate marker — **no
fabricated dataset**. Kept generic (no domain templates); revisit only if quality demands.

**Retry/robustness per call:** each provider call follows the #4-stage discipline —
retry-once then drop, `isinstance` guard on the parsed JSON shape — so a malformed
provider response degrades to a gate failure, never a crash or a fabricated field.

## 3. References — grounding-only by default, verify()-gated for extras

References are assembled deterministically and are **real by construction**:

- **Seed (default):** the `SourceRef`s of the hypothesis grounding facts. The #2 fact
  base only admits already-verified facts, so these are real without any new round-trip.
  The reference count is therefore ≥ the number of distinct grounding sources.
- **Optional extras (config flag, OFF by default):** provider-proposed citations are
  each wrapped as a `Fact` (`source_ref` + `claim`) and routed through
  `VerificationPipeline.verify(fact) -> VerificationStatus`. Only `status == "verified"`
  is admitted; anything else is dropped (or flagged `verified: false`, never presented
  as real). This makes 严禁虚构 a structural guarantee, not a prompt hope.

Cross-change seam (confirmed): `VerificationPipeline(search_clients,
grounding_provider=None).verify(fact: Fact) -> VerificationStatus{layer_reached 1-4,
status: failed|rejected|pending_l4|verified}`. It verifies a `Fact` (with `source_ref`
`{source, external_id, doi}` + `claim` + `evidence_span`), not a bare string. In tests
it is driven fully offline via `MockSearchClient` (as #2's own tests do). With the flag
OFF, the default path performs **zero** verification round-trips.

## 4. Canonical Schema — `ResearchPlan`

JSON is the machine source of truth (consumed by #6/#7); Markdown is *rendered from it*
so the two can never diverge. 12 stable keys + provenance:

```
ResearchPlan
  problem_statement : str
  rationale         : str
  technical_details : str
  datasets          : [ {value, source_ref?, candidate: bool} ]
  source            : [ {value, source_ref?, candidate: bool} ]
  target            : [ {value, candidate: bool} ]
  paper_title       : str
  abstract          : str
  methods           : str
  experiments       : {baselines: [...], metrics: [...], design: str}
  results           : {derivation: [ {step, grade} ], conclusion, confidence: final|low}
  references         : [ {source, external_id, doi, verified: bool, fact_id?} ]
  # provenance
  node_id           : str          # hypothesis node id this plan derives from
  gate              : {passed: bool, failures: [...]}
```

`grade ∈ {[paper], [inferred], [guess]}`. `Datasets/Source/Target` carry `candidate`
flags. Markdown rendering walks these keys in PDF field order; a completeness assertion
guarantees every JSON field appears in the Markdown and vice-versa.

## 5. `PlanAssemblerExecutor` — control flow

Mirrors `HypothesisExecutor` / `LitMinerExecutor`: a standalone class with
`async run(unit: DispatchUnit) -> ExecutorResult`, exception-safe (any raise →
`status="error"` with a structured summary, never a partial persisted plan). No
coordinator-interface change; `auto_git` stays off. Steps:

1. **Resolve** the ranked hypothesis by node id (from the dispatch unit / ranked store).
2. **Resume check:** if `session_dir/plans/<node_id>.json` exists → load and return it,
   **no provider call, no verification** (mirrors #4 accepted-skip / #2 refs-skip).
3. **Call 1** (reasoning fields) + **deterministic** Datasets/Source/Target.
4. **Call 2** (Results derivation) + deterministic load-bearing-`[guess]` downgrade.
5. **Call 3** (Title + Abstract) against the assembled plan.
6. **References:** seed from grounding facts; if the extras flag is on, verify()-gate
   provider-proposed citations.
7. **Build** canonical JSON + **render** Markdown from it.
8. **Deterministic gate** (§6). Persist `plans/<node_id>.{json,md}` and record via
   `RunSession`. A gate-failing plan is persisted but flagged non-final (not emitted as
   a final deliverable).

The `assemble` **tool** wraps this same pipeline with injected dependencies (provider,
fact store, ranked store, verification seam), returning structured results/errors —
so the pipeline is exercisable both through the executor seam and the tool registry.
Hydra `conf/plan/default.yaml` (domain default, call budget, extras flag, thresholds)
is wired into `LoopSCIConfig`.

## 6. Deterministic Gate (provider-free)

Runs with no provider call. A plan is **final** iff all hold:
- all 12 fields present and non-empty (Datasets/Source/Target satisfied by ≥1 candidate
  *or* an explicit grounding-absent marker — an empty-because-ungrounded field is a
  recorded state, not a silent blank);
- every entry in References is `verified: true`;
- no ungrounded load-bearing claim (a load-bearing Results step graded `[guess]` forces
  `confidence != final` and fails the gate).

Failure → the plan is flagged incomplete with the specific failed checks, **not** emitted
as final. No Qwen critique-revise loop (deferred).

## 7. Resume Keying

Keyed by the hypothesis **node_id** (stable SHA-1 from #4). Presence of
`plans/<node_id>.json` ⇒ skip re-assembly. This is the acceptance scenario added by the
Spec Patch below and is asserted by an offline integration test (second run → no
provider/verify calls, persisted plan unchanged).

## 8. Testing Strategy

Fully offline default suite: `MockProvider` (generator) + mocked verification/search
seam (`MockSearchClient`) + a seeded `FactStore` + a `RankedHypothesis`. Pins:

- all reasoning fields non-empty; Experiments carries baselines + metrics;
- domain parameterized (two domains, no code change) → fields reflect the domain;
- Datasets/Source/Target candidates trace to grounding facts; no fabricated dataset when
  grounding absent;
- Results is a graded derivation with no execution path; a load-bearing `[guess]`
  downgrades to non-final; a grounded derivation reaches a feasibility conclusion;
- References verified-only; a fabricated/unverifiable citation is dropped; a grounded
  hypothesis yields real refs (count ≥ distinct grounding sources);
- JSON↔Markdown parity (all 12 fields, no divergence);
- gate fails on missing/empty field and on an unverified reference; passes on a complete
  verified plan; the tool runs offline;
- **resume:** a completed plan persisted under `plans/<node_id>.json` is not re-assembled
  on a second executor run (no re-spend).

Integration: executor end-to-end offline → gated complete 12-field plan (JSON+Markdown),
real references, no network, no git; resume-no-reassemble. Opt-in `@pytest.mark.live`:
real Qwen assembly over a small domain-parameterized topic on a seeded fact base, skipped
without `DASHSCOPE_API_KEY`. Coverage ≥80% on new code (vendored excluded), ruff clean,
README section (12-field overview, formula-derivation Results, real-reference
verification, domain parameter, JSON+Markdown output, live-tests-need-keys).

## 9. Risks / Trade-offs (deltas from open-phase design.md)

- **Plan-grade Results reads thin** → concrete evidence-graded steps + load-bearing
  `[guess]` downgrade; the later bounded-execution change spot-checks the winner.
- **Domain-general is generic** → every prompt anchored to the concrete
  mechanism/diff-prediction/grounding + domain param.
- **Offline verification fidelity** → mock the #2 seam exactly as #2's tests do; the
  grounding-only default path is zero-fabrication-risk by construction.
- **Budget (300¥)** → 3 calls/plan; gate, rendering, DST, and default references are all
  deterministic.
- **Field-contract drift** → 12 keys pinned in the delta specs + canonical JSON; the
  completeness gate fails any missing field.

## 10. Spec Patch (written back to OpenSpec delta spec)

One patch, to `specs/plan-assembly-integration/spec.md` — adds the missing acceptance
scenario for resume under the existing "Specialist executor and tool integration"
requirement (which already states resumability in prose):

> **Scenario: Completed plan is not re-assembled on resume** — a second executor dispatch
> for a hypothesis whose plan is already persisted under `plans/<node_id>.json` returns
> the existing plan without re-invoking the provider or verification (no re-spend), and
> leaves the persisted plan unchanged.

No other delta-spec structure or scope is changed.
