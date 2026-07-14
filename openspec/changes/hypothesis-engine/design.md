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
