# Comet Design Handoff

- Change: hypothesis-engine
- Phase: design
- Mode: compact
- Context hash: b7ec2d8318a7cdb0de5c8ab462a2434db13624b6ab6cbe82678629d7689da62d

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/hypothesis-engine/proposal.md

- Source: openspec/changes/hypothesis-engine/proposal.md
- Lines: 1-34
- SHA256: be5ec0c89f62e5dca62c0dd1eff01a3d8fce55f41ba180013924131ea6359f2d

```md
## Why

Loop-SCI now has a foundation (change #1) and a verified fact base (change #2), but nothing yet turns facts into science. The competition (XH-202619) scores 核心假设创新性与自治性 (hypothesis novelty + self-consistency) and 方案可落地验证性 (feasibility) — capability 二 (逻辑驱动的假设生成) and 三 (论证可行与多轮迭代). This change builds the engine that consumes the fact base and produces **ranked, adversary-tested, self-consistent candidate hypotheses** — the reasoning core the plan-assembler (#5) turns into the final 《科学假设与研究计划》.

The design deliberately adapts the research-os model of research (prospect → forge → prereg → adversary → autopsy) to a **plan-grade** setting: the structural gates (taste modeling, mechanism/kill/diff-prediction, evidence-grade grounding, negative metabolism) run over reasoning and the fact base; the execution gates (running experiments, multi-seed statistics) are deferred to #5, not imported as dead machinery.

## What Changes

- **New `loop_sci/hypothesis/` package**: a plan-grade research-os loop over the Arbor idea-tree, driven by Qwen/Bailian.
- **Hypothesis generation** — `prospect'` mines gap/contradiction cards `{Q, WHY-NOW, PROBE/KILL, STAKES}` from the fact base; `forge'` runs induction+deduction into hypotheses `{MECHANISM, KILL, BRACKET, DIFF-PREDICTION}` with rival frames as sibling nodes; the "strip-the-new-words ⇒ relabeling, discard" filter.
- **Hypothesis critique (anti-fabrication)** — a derivation-contract (HYPOTHESIS / LATENT-ROOT / ACCEPT-IF / KILL-IF, no `eval_cmd`) plus `adversary'` Checks C/D adjudicated by a **Qwen-vs-Qwen jury** (generator ≠ reviewer; a different Qwen tier with a KILL-biased adversarial persona and varied sampling; **never self-acquits**). Evidence-grade annotation `[paper]/[inferred]/[guess]` and a "no artifact ⇒ downgrade to hypothesis" rule over #2's verified facts enforce 严禁虚构.
- **Iteration and metabolism** — `autopsy'` converts each kill into CONSTRAINT / CANDIDATE / REGION-CLOSE feeding re-ranking; multi-round refinement bounded by a stall ledger (`done` ≠ `accepted` with durable verdict IDs; pivot at stale ≥ 2, escalate at stale ≥ 4); resumable via a recovery anchor.
- **Ranking and output** — novelty + self-consistency scores on `Node.score` / `Node.refs`; a **stable ranked-hypothesis query interface** the #5 assembler consumes without touching idea-tree internals; a `HypothesisExecutor` over the foundation Executor seam plus `generate`/`critique`/`rank` tools in the ToolRegistry.
- **No new vendored primitives and no coordinator-interface change**: a thin executor + a score-priority coordinator subclass ride entirely on already-vendored idea-tree ops. `auto_git` stays off.

## Capabilities

### New Capabilities
- `hypothesis-generation`: mine gap cards from the verified fact base and generate logic-driven (induction+deduction) candidate hypotheses with rival frames, mechanism, kill condition, and a discriminating diff-prediction; discard relabelings.
- `hypothesis-critique`: adjudicate each candidate through a derivation-contract and a Qwen-vs-Qwen adversarial jury that never self-acquits; annotate evidence grades and downgrade any claim not grounded in the fact base (anti-fabrication).
- `hypothesis-iteration`: metabolize killed hypotheses into constraints/candidates/region-closes, refine over bounded multi-round iteration with stall detection, and resume without re-critiquing accepted nodes.
- `hypothesis-ranking`: score candidates by novelty and self-consistency, expose a stable ranked-hypothesis query interface for the downstream plan-assembler, and integrate as a specialist executor + tools over the foundation.

### Modified Capabilities
<!-- None. This change consumes the literature-mining fact base through its stable query interface; it does not change any existing capability's requirements. -->

## Impact

- **New code**: `loop_sci/hypothesis/` (generate / critique / iterate / rank / executor / tools) + tests (`tests/unit/hypothesis/`, `tests/integration/`, `tests/live/`).
- **Consumes**: change #2 `FactStore` + idea-tree fact nodes (read-only, via the stable query interface).
- **Reuses (no edits)**: foundation provider (Qwen/Bailian), `Executor`/`Coordinator` seam, idea-tree (`Node.refs`), `RunSession`, `ToolRegistry`, event bus; vendored Arbor tree ops.
- **Dependencies**: no new runtime deps expected (reuses httpx/Qwen provider). Offline-by-default tests via `MockProvider`; opt-in `@pytest.mark.live` needs `DASHSCOPE_API_KEY`.
- **Deferred (not in scope)**: executed experiments / exp-verify / multi-seed / beat-the-baseline and CORAL bounded runs (→ #5); 13-field document assembly (→ #5); cron/overnight orchestration + monitor UI (→ #6/#7).
- **Budget**: Qwen calls bounded per run (candidates × rounds × jury) to respect the 300¥ cap, mirroring #2's bounding.

```

## openspec/changes/hypothesis-engine/design.md

- Source: openspec/changes/hypothesis-engine/design.md
- Lines: 1-43
- SHA256: 64e35ff2e6880ea407d3a7df45ed01cb4a16902348f8ef98788581bf3a5487e4

```md
## Context

Change #4 sits on the shipped foundation (change #1: coordinator/executor + idea-tree + Qwen/Bailian provider + ToolRegistry + event bus) and the verified fact base (change #2: `FactStore` + per-fact idea-tree nodes). It builds the reasoning core of the AI-Scientist: fact base → ranked candidate hypotheses. It targets competition capability 二 (逻辑驱动的假设生成) and the reasoning half of 三 (论证可行与多轮迭代), which feed the scored 核心假设创新性与自治性 dimension. The runtime brain is mandated to be Qwen via Alibaba Cloud Bailian.

The approach is a **plan-grade adaptation of research-os** (prospect → forge → prereg → adversary → autopsy), chosen after a deep review of research-os, ARIS, Arbor, and CORAL. research-os is the right spine because it models research *taste*, *novelty/surprise*, and *negative metabolism* better than a bespoke pipeline — but ~35% of it (exp-verify, multi-seed statistics, beat-the-baseline, merge gates) assumes executed experiments and is deferred to the plan-assembler/experiment-runner (#5), not imported here.

## Goals / Non-Goals

**Goals:**
- Consume the fact base and emit ranked, adversary-tested, self-consistent candidate hypotheses with auditable, fact-grounded derivations (no fabrication).
- Model hypotheses as Arbor idea-tree nodes (fact nodes → hypothesis children; rival frames = siblings; KILL = prune; scores on `Node.score`/`Node.refs`), reusing vendored ops with no new primitives and no coordinator-interface change.
- Enforce a non-self-acquitting critique via a Qwen-vs-Qwen adversarial jury.
- Bound multi-round iteration with stall detection and make runs resumable.
- Expose a stable ranked-hypothesis interface for the #5 plan-assembler.

**Non-Goals:**
- Executed experiments, exp-verify, multi-seed statistics, beat-the-baseline, CORAL bounded runs → deferred to #5.
- 13-field 《科学假设与研究计划》 document assembly → #5.
- Cron/overnight orchestration + monitor UI → #6/#7.
- New literature fetching → consumes #2 (may request more facts through #2's tools, does not reimplement search).

## Decisions

- **research-os as a plan-grade spine (adapt, don't raid; don't import dead machinery).** ABSORB: prospect cards `{Q, WHY-NOW, PROBE/KILL, STAKES}`, forge `{MECHANISM, KILL, BRACKET, DIFF-PREDICTION}` + relabeling filter, abduce evidence-grade taxonomy, autopsy CONVERSION LAW, admit taste rubric. LOWER-THRESHOLD: prereg → derivation contract (no `eval_cmd`), adversary Checks C/D. DEFER to #5: exp-verify, adversary A/B, CORAL, SEEDS≥3, merge gates. DROP: "documents are not progress" and the campaign session-protocol (rebuild orchestration around the idea-tree). *Alternative rejected:* full-loop absorption (imports experiment machinery that stays inert at plan-grade); thin-subset-only (loses the taste + anti-fabrication rigor that scores 自治性).
- **Qwen-vs-Qwen adversarial jury.** Generator = Qwen-Max; reviewer = a different Qwen tier with a KILL-biased persona + varied sampling; the generator configuration cannot issue the accept verdict. Satisfies both research-os's and ARIS's "a verdict that helps the proposer if gamed must never be granted by the proposer," while staying fully within the Qwen mandate. *Alternative rejected:* non-Qwen adversary (stronger independence, competition-compliance risk); rule-only checker (misses subtle incoherence — kept as an optional deterministic backstop instead).
- **Idea-tree as the hypothesis space.** Reuse `add_node`/`update_node`/`prune_node`/`async_update_node`, `get_constraints_block()` (inject pruned-lessons into prompts), `get_best_done_node()`, and the Loop-SCI `Node.refs` subclass for the hypothesis payload. A `HypothesisExecutor` slots into the existing `Coordinator` with no interface change; a coordinator subclass overrides only `_observe()` (score-priority expansion) and `_plan()` (inject fact-base context). *Alternative rejected:* a bespoke store (needless; the tree already gives branching, pruning, scoring, persistence, and events).
- **ARIS async/long-horizon primitives, minus the desktop machinery.** Adopt the `done`≠`accepted` acceptance ledger (durable verdict ids), `iteration_log` stall detection (pivot@2 / escalate@4), and a `REVIEW_STATE`-style recovery anchor for resumability. Defer the cron/watchdog/monitor cadence to #6/#7.
- **CORAL is complementary, not core.** Borrow only its grader-as-evidence-contract + direction-sorted-leaderboard abstractions for ranking; wire the real bounded-run engine in #5.
- **Offline-by-default testing.** All unit/integration tests inject a `MockProvider` for both generator and reviewer roles; opt-in `@pytest.mark.live` needs `DASHSCOPE_API_KEY`. Per-run Qwen bounding (cards × candidates × rounds × jury) respects the 300¥ cap.

## Risks / Trade-offs

- **[Qwen-vs-Qwen independence is family-correlated]** → distinct tier + adversarial persona + varied sampling + an optional deterministic evidence-grade/contradiction backstop; revisit reviewer substrate if the jury proves too lenient.
- **[Novelty scoring is subjective]** → measure novelty against the fact base (mechanism absent from facts scores higher) with tunable thresholds like #2's grounding; make it reproducible offline.
- **[Plan-grade "feasibility" without runs could be hand-wavy]** → the derivation contract's ACCEPT-IF/KILL-IF must be concrete tripwires; the #5 CORAL path later spot-checks the winner.
- **[Iteration never converging]** → stall ledger forces pivot@2 and escalate@4; region-close halts dead-space re-exploration.
- **[Budget blow-up from jury calls]** → per-run bounds; the jury fires once per surviving candidate, not per token.

## Open Questions

- Exact fused hypothesis schema and `Node.refs` layout (resolved in the design phase Design Doc).
- Concrete lowered thresholds (admit trigger, iteration cap, jury DOWN criteria) and whether to seed a small ledger lesson-prior file.
- Whether the deterministic evidence-grade checker ships in #4 or is deferred.

```

## openspec/changes/hypothesis-engine/tasks.md

- Source: openspec/changes/hypothesis-engine/tasks.md
- Lines: 1-39
- SHA256: d9eea527255f93bd89a4a67a794dd6611bc2541f39e36f055f92856c4a33a2cd

```md
## 1. Hypothesis generation (prospect' + forge')

- [ ] 1.1 Define the hypothesis schema (problem card `{Q, WHY-NOW, PROBE/KILL, STAKES}`; hypothesis `{MECHANISM, KILL, BRACKET, DIFF-PREDICTION}`; evidence-graded derivation step; scores) and its `Node.refs` payload layout
- [ ] 1.2 Implement `prospect'`: mine gap/contradiction cards from the fact base via its stable query interface (no new fetching, no idea-tree internals); drop cards citing non-existent facts
- [ ] 1.3 Implement `forge'`: Qwen-driven induction+deduction from a card into candidate hypotheses with rival-frame siblings; record as idea-tree nodes under fact node(s)
- [ ] 1.4 Implement the relabeling filter (strip-the-new-words ⇒ discard when no distinct diff-prediction survives)
- [ ] 1.5 Bound generation by a per-run cap (cards × candidates); stop cleanly at the cap
- [ ] 1.6 Unit tests (offline, mock provider): gap cards derived + fact-grounded; hypotheses carry mechanism/kill/bracket/diff-prediction + rival frame; relabeling discarded; per-run bound respected

## 2. Hypothesis critique (derivation contract + Qwen-vs-Qwen jury + anti-fabrication)

- [ ] 2.1 Implement the derivation contract (HYPOTHESIS/LATENT-ROOT/ACCEPT-IF/KILL-IF as derivation tripwires, no `eval_cmd`); freeze on the node before any verdict
- [ ] 2.2 Implement the adversarial jury: generator vs a distinct reviewer configuration (different Qwen tier, KILL-biased persona, varied sampling); route verdicts so the generator configuration cannot issue an accept
- [ ] 2.3 Implement `adversary'` Checks C/D (claim decomposition → each step needs an artifact; generalization test) as the plan-grade critique
- [ ] 2.4 Implement evidence-grade annotation `[paper]/[inferred]/[guess]` + "no artifact/fact ⇒ downgrade to hypothesis" grounded in the fact base
- [ ] 2.5 Unit tests: incoherent hypothesis DOWN-verdicted; no self-acquittal (generator-issued accept rejected, reviewer config differs); ungrounded citation downgraded; grounded step carries `[paper]`/`[inferred]` + fact id

## 3. Iteration and metabolism (autopsy' + stall ledger + resume)

- [ ] 3.1 Implement `autopsy'`: convert each kill into CONSTRAINT/CANDIDATE/REGION-CLOSE; prune killed node retaining reason; feed outcome back into ranking
- [ ] 3.2 Implement region-close (≥2 mechanisms killed by same root ⇒ stop generating in that region within the run)
- [ ] 3.3 Implement the multi-round loop with the stall ledger: track new findings per round; structural pivot at stale≥2; escalate (stop nudging) at stale≥4
- [ ] 3.4 Implement the acceptance ledger (`done`≠`accepted` with durable verdict ids) + a recovery anchor for resumability
- [ ] 3.5 Unit tests: kill → constraint reweights queue; region-close halts re-exploration; pivot@2 and escalate@4; resume skips accepted nodes without re-critique or re-spend

## 4. Ranking, output interface, and foundation integration

- [ ] 4.1 Implement novelty + self-consistency scoring on `Node.score` + `Node.refs` subscore map (novelty measured against the fact base); reproducible offline
- [ ] 4.2 Implement the stable ranked-hypothesis query interface (retrieve-all ranked, filter by topic/status) returning problem + derivation chain w/ evidence grades + diff-prediction + scores + grounding refs, without exposing idea-tree internals
- [ ] 4.3 Implement `HypothesisExecutor` over the foundation Executor seam (consume fact base → generate → critique → iterate → record); no coordinator-interface change; `auto_git` stays off
- [ ] 4.4 Implement the score-priority coordinator subclass (`_observe()` score-sorted expansion, `_plan()` fact-base context injection)
- [ ] 4.5 Register `generate`/`critique`/`rank` tools in the ToolRegistry wrapping the same pipeline with injected deps; structured results/errors
- [ ] 4.6 Unit tests: scores recorded + novelty ordering; ranked interface returns required fields best-first; tools exercise the pipeline offline

## 5. End-to-end, tests & docs

- [ ] 5.1 Offline integration test: coordinator dispatches `HypothesisExecutor` against a mock provider + populated fact base → ≥1 accepted, scored hypothesis in the idea-tree, retrievable via the ranked interface; no network, no git; anti-fabrication (ungrounded downgraded) and no-self-acquit pinned
- [ ] 5.2 Opt-in `@pytest.mark.live` e2e: real Qwen generator + real Qwen reviewer over a small neuro topic on a seeded fact base (skip-verified without `DASHSCOPE_API_KEY`)
- [ ] 5.3 Coverage gate (≥80% on new code, excl. vendored) + ruff clean + README section (pipeline overview, Qwen-vs-Qwen jury, budget/env, ranked output for #5, live-tests-need-keys)

```

## openspec/changes/hypothesis-engine/specs/hypothesis-critique/spec.md

- Source: openspec/changes/hypothesis-engine/specs/hypothesis-critique/spec.md
- Lines: 1-34
- SHA256: 92b958ba8046b808dec86dc62978acd91ef437cc6469e3a624be76b0b8c9bf7a

```md
## ADDED Requirements

### Requirement: Derivation contract before critique
The system SHALL freeze a derivation contract for each candidate hypothesis before adversarial critique, containing at least HYPOTHESIS, LATENT-ROOT, ACCEPT-IF, and KILL-IF fields. The contract SHALL be plan-grade: ACCEPT-IF / KILL-IF are stated as derivation tripwires (logical or formula-derived conditions), not executable run commands.

#### Scenario: Contract frozen before verdict
- **WHEN** a candidate hypothesis enters critique
- **THEN** a derivation contract with HYPOTHESIS, LATENT-ROOT, ACCEPT-IF, and KILL-IF is recorded on the node before any verdict is produced

### Requirement: Cross-model adversarial jury (never self-acquit)
The system SHALL adjudicate each candidate through an adversarial jury in which the reviewer is a distinct model configuration from the generator — a different Qwen tier with a KILL-biased adversarial persona and varied sampling. A candidate SHALL NOT be able to grant its own passing verdict; the generator's configuration MUST NOT produce the accept verdict.

#### Scenario: Incoherent hypothesis is DOWN-verdicted
- **WHEN** a candidate whose mechanism contradicts its grounding facts is critiqued
- **THEN** the jury returns a DOWN verdict, the node is not marked accepted, and the reviewer configuration differs from the generator configuration

#### Scenario: No self-acquittal
- **WHEN** the generator configuration is asked to adjudicate its own candidate
- **THEN** the system routes the verdict to the distinct reviewer configuration instead, and an accept verdict issued by the generator configuration is rejected

#### Scenario: Deterministic pre-jury gate rejects without spending a jury call
- **WHEN** a candidate fails a deterministic pre-jury check (its mechanism contradicts a grounding fact, or a load-bearing derivation step is graded `[guess]`) before the reviewer is invoked
- **THEN** the candidate receives a DOWN verdict from the deterministic gate, no jury (Qwen reviewer) call is made for it, and the recorded reason identifies the failed deterministic check

### Requirement: Evidence-grade anti-fabrication
The system SHALL annotate each derivation step with an evidence grade drawn from `[paper] | [inferred] | [guess]`. Any claim or citation not grounded in a fact present in the fact base SHALL be downgraded to an ungrounded hypothesis (never promoted to accepted), enforcing the no-fabrication constraint.

#### Scenario: Ungrounded citation downgraded
- **WHEN** a candidate cites a source or asserts an artifact that does not resolve to a fact in the fact base
- **THEN** that step is graded `[guess]` (or the claim is downgraded to hypothesis) and the candidate cannot reach accepted status on the strength of that step

#### Scenario: Grounded steps carry paper-grade evidence
- **WHEN** a derivation step is supported by a verified fact
- **THEN** the step is annotated `[paper]` (or `[inferred]` when logically derived from paper-grade facts) with a reference to the supporting fact id

```

## openspec/changes/hypothesis-engine/specs/hypothesis-generation/spec.md

- Source: openspec/changes/hypothesis-engine/specs/hypothesis-generation/spec.md
- Lines: 1-34
- SHA256: 7d73fa06fcb60bb8bf9377a47f6d072bf62947ca656036c314a08cc78164b0fd

```md
## ADDED Requirements

### Requirement: Gap mining from the verified fact base
The system SHALL mine candidate research gaps from the verified fact base (produced by literature-mining) and represent each as a problem card with the fields `{Q, WHY-NOW, PROBE/KILL, STAKES}`. Gap mining SHALL read facts through the fact base's stable query interface and SHALL NOT fetch new literature or read idea-tree internals directly.

#### Scenario: Gap cards derived from facts
- **WHEN** the engine is given a topic whose fact base contains verified facts (including at least one pair of tension/contradiction between facts)
- **THEN** it produces one or more problem cards, each carrying a question `Q`, a `WHY-NOW`, a `PROBE/KILL`, and `STAKES`, and each card references the fact ids it was derived from

#### Scenario: No fabricated gaps
- **WHEN** a proposed gap card cites supporting facts
- **THEN** every cited fact id resolves to a fact present in the fact base, and a card citing a non-existent fact is dropped before ranking

### Requirement: Logic-driven hypothesis generation
The system SHALL generate candidate hypotheses from a problem card using both inductive and deductive reasoning over the grounding facts, via the Qwen provider. Each hypothesis SHALL carry `{MECHANISM, KILL, BRACKET, DIFF-PREDICTION}` and SHALL be recorded as an idea-tree node descending from the problem-card node it was forged from, with rival framings recorded as sibling nodes. Grounding into the fact base SHALL be by fact-id reference (recorded on the node), not by making a fact node the tree parent; the hypothesis engine builds its own tree (`topic root → problem-card nodes → hypothesis nodes`) and reads the fact base only through its stable query interface.

#### Scenario: Hypotheses with mechanism and discriminating prediction
- **WHEN** the engine forges hypotheses from a problem card
- **THEN** each candidate node states a mechanism, an explicit kill condition, a plausibility bracket, and a diff-prediction that would distinguish it from the status quo, and at least one rival-frame sibling is produced

#### Scenario: Hypotheses attach under the problem-card node, grounded by fact-id
- **WHEN** a candidate hypothesis is recorded
- **THEN** its idea-tree parent is the originating problem-card node (not a fact node), and its grounding is a list of fact-id references that each resolve in the fact base's stable query interface

#### Scenario: Relabeling is discarded
- **WHEN** a candidate's diff-prediction does not survive the "strip-the-new-words" test (removing the novel terminology leaves no distinct prediction)
- **THEN** the candidate is classified as relabeling and discarded, not recorded as a live hypothesis

### Requirement: Bounded generation
The system SHALL bound generation by a per-run cap (cards × candidates) so that Qwen usage stays within the configured budget.

#### Scenario: Per-run bound respected
- **WHEN** generation runs with a configured cap
- **THEN** the number of problem cards and candidate hypotheses produced does not exceed the cap, and generation stops cleanly when the cap is reached

```

## openspec/changes/hypothesis-engine/specs/hypothesis-iteration/spec.md

- Source: openspec/changes/hypothesis-engine/specs/hypothesis-iteration/spec.md
- Lines: 1-30
- SHA256: a856c373e2c6ef796e32c9b10852d56873422d22f7f26218189e2a796268eb96

```md
## ADDED Requirements

### Requirement: Kill metabolism
The system SHALL convert each killed (DOWN-verdicted or falsified) hypothesis into at least one of a CONSTRAINT, a CANDIDATE, or a REGION-CLOSE, and SHALL feed that outcome back into ranking so that the open hypothesis queue is reweighted. A pruned hypothesis node SHALL retain its kill reason.

#### Scenario: A kill produces a constraint that reweights the queue
- **WHEN** a candidate is killed during critique
- **THEN** the engine records a CONSTRAINT / CANDIDATE / REGION-CLOSE derived from the kill, the killed node is pruned with its reason retained, and the outcome updates the ranking of remaining open hypotheses

#### Scenario: Region-close halts dead-space re-exploration
- **WHEN** two or more mechanisms are killed by the same root cause
- **THEN** the engine marks that region closed and does not generate further candidates in the closed region within the run

### Requirement: Bounded multi-round iteration with stall detection
The system SHALL iterate generation → critique → metabolism over multiple rounds, tracking new findings per round. It SHALL trigger a structural pivot when the stall count reaches 2 and escalate (stop nudging, surface for human attention) when the stall count reaches 4. Iteration SHALL terminate rather than loop indefinitely.

#### Scenario: Pivot on stall
- **WHEN** two consecutive rounds add no new accepted findings
- **THEN** the engine performs a structural pivot (changes frame / objective / grounding) rather than repeating the same generation

#### Scenario: Escalate on persistent stall
- **WHEN** four consecutive rounds add no new accepted findings
- **THEN** the engine stops iterating and surfaces the run for human attention instead of continuing to spend budget

### Requirement: Resumable iteration
The system SHALL distinguish a `done` (self-reported) phase from an `accepted` (jury-verdicted, with a durable verdict id) phase, and SHALL persist a recovery anchor so a resumed run continues without re-critiquing already-accepted nodes or re-spending on completed work.

#### Scenario: Resume skips accepted nodes
- **WHEN** a run is resumed after interruption
- **THEN** hypotheses already marked accepted (with a verdict id) are not re-critiqued, and iteration continues from the recovery anchor without duplicating work

```

## openspec/changes/hypothesis-engine/specs/hypothesis-ranking/spec.md

- Source: openspec/changes/hypothesis-engine/specs/hypothesis-ranking/spec.md
- Lines: 1-30
- SHA256: 891102b48ca5c344cfcc6bb40d488e9041453c82a7d0570b3ca8bb56c8e2c4cf

```md
## ADDED Requirements

### Requirement: Novelty and self-consistency scoring
The system SHALL score each surviving hypothesis on at least novelty and self-consistency, recording the scores on the idea-tree node (`Node.score` and a subscore map in `Node.refs`). Scoring SHALL be reproducible offline with a mock provider.

#### Scenario: Scores recorded on the node
- **WHEN** a hypothesis passes critique
- **THEN** its node carries a numeric overall score plus a subscore map including `novelty` and `self_consistency`, persisted with the tree

#### Scenario: Novelty measured against the fact base
- **WHEN** two candidates are scored, one restating an existing verified fact and one proposing a mechanism absent from the fact base
- **THEN** the mechanism-proposing candidate receives the higher novelty subscore

### Requirement: Stable ranked-hypothesis query interface
The system SHALL expose a stable interface returning hypotheses ranked by score (retrieve-all ranked, filter by topic/status) that the downstream plan-assembler consumes without touching idea-tree internals. Each returned item SHALL carry problem, derivation chain with evidence grades, diff-prediction, novelty and self-consistency scores, and grounding fact/reference ids.

#### Scenario: Downstream consumes ranked output
- **WHEN** a consumer requests the ranked hypotheses for a topic
- **THEN** it receives them ordered best-first with all required fields, and does not need to import or traverse idea-tree node structures

### Requirement: Specialist executor and tools integration
The system SHALL provide a `HypothesisExecutor` over the foundation Executor seam (search-free: it consumes the fact base, generates, critiques, iterates, and records) and SHALL register `generate` / `critique` / `rank` tools in the ToolRegistry for agent-driven use. Integration SHALL require no change to the coordinator interface and SHALL keep `auto_git` disabled.

#### Scenario: Executor runs the loop end-to-end offline
- **WHEN** the coordinator dispatches the `HypothesisExecutor` for a topic against a mock provider and a populated fact base
- **THEN** it produces at least one accepted, scored hypothesis recorded in the idea-tree and retrievable through the ranked query interface, with no network calls and no git operations

#### Scenario: Tools wrap the same pipeline
- **WHEN** the `generate` / `critique` / `rank` tools are invoked through the registry
- **THEN** they exercise the same underlying pipeline with injected dependencies and return structured results (or structured errors), offline

```
