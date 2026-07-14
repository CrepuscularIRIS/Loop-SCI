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
