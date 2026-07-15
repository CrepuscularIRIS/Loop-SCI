# Loop-SCI — Development Handoff (next round)

- Date: 2026-07-15
- Public `main` HEAD: `5029ef4` (origin up to date: https://github.com/CrepuscularIRIS/Loop-SCI)
- Competition: XH-202619 (AI Scientist on a domestic open-source LLM). Deliverable = the
  12-field 《科学假设与研究计划》. Submission deadline **2026-09-05**. Budget **300¥/人**.
- Purpose of this file: capture where the programme stands and define the **next development
  round** so it can be picked up cold later.

---

## 1. Where we are (the closed loop is complete end-to-end)

The core competition loop — *data/literature → verifiable 科学假设 + 研究计划* — now runs:

```
literature/data  ──#2/#3──▶  verified FactStore
                                  │
                          #4 hypothesis-engine
                                  │  ranked, adversary-tested RankedHypothesis
                                  ▼
                    #5 research-plan-assembler
                                  │  12-field 《科学假设与研究计划》
                                  ▼        (canonical JSON source-of-truth + derived Markdown)
                         gated final deliverable
```

Shipped changes (all merged public, `phase: archive`):
- **#1 arbor-qwen-skeleton** — foundation harness (coordinator/executor, idea-tree, Qwen/Bailian provider, ToolRegistry, RunSession).
- **#2/#3 literature-mining** — multi-source search + evidence-required extraction + 4-layer citation verification + verified-only FactStore.
- **#4 hypothesis-engine** — plan-grade research-os loop → ranked hypotheses with derivation-chains, diff-predictions, evidence grades, Qwen-vs-Qwen adversarial jury.
- **#5 research-plan-assembler** — this round. `loop_sci/plan/` turns one `RankedHypothesis` into the 12-field plan (JSON + Markdown), deterministic anti-fabrication gate, real-only references, Results by formula-derivation.

**Test/quality baseline on `main`:** 487 passed / 8 live-skipped (need `DASHSCOPE_API_KEY`), `loop_sci/plan` 92% coverage, ruff clean.

---

## 2. RECOMMENDED next round: `bounded-experiment-runner`

**Why this one.** It was explicitly split out of #5, and it is the single biggest remaining
scoring lever: it upgrades the **Results** field from *formula-derivation* (analytical
feasibility) to *executed evidence*. That directly targets 科学价值 → 方案可落地验证性 (0–20)
and 应用潜力 → 代码与结果可复现性 (0–10). It builds straight on the #5 seams with no new
upstream dependency.

**Scope (proposed).**
- A bounded execution runner that takes a `ResearchPlan` (or its hypothesis) and *actually
  runs* a small, budget-bounded experiment to produce a real measured result for the Results
  field — as an ALTERNATIVE path to #5's formula-derivation (PDF allows "公式推导 OR 实际执行").
- **Grader-as-contract + sorted-leaderboard** abstractions (noted in memory as the CORAL
  pieces deferred to post-#5). A frozen evidence contract (metric + accept/kill + sealed
  split) before the run; the run either VERIFIES or is killed. Mirror #4's anti-fabrication
  discipline: an executed number must pass a reality/no-op check before it can be claimed.
- Emit an *executed* Results block that slots into the existing `ResultsBlock`
  (`{derivation, conclusion, confidence}`) — e.g. an executed step graded `[paper]`-equivalent
  ("measured") with the run artifact as provenance — so the #5 gate and JSON/Markdown render
  keep working unchanged.
- Offline-testable: a `MockRunner`/synthetic known-answer task, like every prior change's
  mock seams. Live runs gated behind an opt-in marker + budget cap.

**Key seams to build on (already shipped, read these first):**
- `loop_sci/plan/schemas.py` → `ResultsBlock`, `ResearchPlan` (the target the runner feeds).
- `loop_sci/plan/executor.py` → `PlanAssemblerExecutor` control flow + resume-by-node_id +
  persist pattern to mirror (`.md`-before-`.json` sentinel, exception-safe → `status="error"`).
- `loop_sci/plan/gate.py` → the deterministic gate that must still pass with executed Results.
- Foundation: `loop_sci/engine/types.py` (`DispatchUnit`, `ExecutorResult`),
  `loop_sci/state/session.py` (`RunSession`, `session_dir`, `advance_step`),
  `loop_sci/engine/tools.py` (`ToolRegistry.register`/`dispatch`).
- #4: `loop_sci/hypothesis/ranked.py` (`RankedHypothesis`, `RankedHypothesisStore`).

**Dependencies / risks.**
- Executing *real* domain experiments needs real data → that is **`neuro-domain-pack` (#2,
  deferred)**. Mitigation: scope the first runner to synthetic / small self-contained tasks
  (known-answer worlds, tiny reproducible benchmarks) so it ships WITHOUT the domain pack;
  wire real datasets in later.
- **300¥ budget** — the runner must be hard-bounded (wall-clock / token / step caps) and
  default to the cheapest viable path; keep the default test suite offline (zero spend).
- Keep `auto_git` OFF; no shell/eval reachable from an untrusted plan (the #5 Results path is
  deliberately execution-free — the runner is the ONLY place execution is allowed, and it must
  be sandboxed/bounded).

**Non-goals for this round (defer):** real domain datasets (→ neuro-domain-pack), HITL debate
(#6), visualization (#7), a full CORAL campaign harness (only the grader-contract +
leaderboard abstractions are in scope).

**#5 ↔ runner boundary:** #5 stays the plan *assembler* and keeps its formula-derivation
Results path intact. The runner is an *optional upgrade* to the Results field for a chosen
plan — it must not change #5's public interfaces or its offline default behavior.

---

## 3. Alternative next rounds (rest of the roadmap — pick per priority)

| Change | Scope | Depends on | Pick it if… |
|--------|-------|-----------|-------------|
| **neuro-domain-pack (#2, deferred)** | Real brain-decoding datasets + literature + multimodal handling + domain specialization | #1 | You want the executed runner (or the plan) grounded in *real* domain data, and to score 多模态大模型对科学模态数据处理 (0–15). |
| **human-in-loop (#6)** | Interactive agent debate + human checkpoints over the hypothesis/plan | #4, #5 | You want to demo 超级智能体/多智能体协作 interactivity for the video/前端. |
| **visualization (#7)** | Live web dashboard + HTML export of the plan/idea-tree | #1 (parallel) | You want the optional 前端交互展示 + 10-min demo-video points; low coupling, can run anytime. |

Sequencing note: for score-per-effort, **bounded-experiment-runner** (可落地验证性) then
**visualization** (前端 + demo) is the cheapest path to the biggest scored deltas before the
09-05 deadline; **neuro-domain-pack** is the heavier investment that deepens every field but
needs real research to scope.

---

## 4. Optional micro-round: `#5` deferred cleanup (a `tweak`/`hotfix` preset)

None block anything (final whole-branch review deferred them all). Fold into the next change
or run as one small `tweak`. From `.superpowers/sdd/progress.md`:
- `loop_sci/plan/results.py`: comment-rot narrating the prose/test conflict + dead
  `isinstance(resp, object)` guard clause; module docstring still states the abandoned
  "no other support" downgrade rule (shipped rule = "last/decisive `[guess]` ⇒ low"). Also
  `results.py:174-175` (provider-missing-`get_text`) is the one uncovered branch (92%).
- `loop_sci/plan/config.py`: `min_reference_count` is inert (defined+documented, not enforced
  by the gate) — wire it into the gate or drop it.
- `loop_sci/plan/executor.py`: `assemble_for_node` does a redundant disk reload (unused by the
  hot path); `_resolve_hyp` is an O(n) scan (fine at current tree sizes).
- `loop_sci/plan/fields.py`: dataset candidate uses `entities[0]` even when that entity isn't
  the dataset-like token.
- `loop_sci/plan/references.py`: dead `or "unspecified"` evidence_span fallback; `hyp: Any`
  typing via `getattr`.
- `tests/unit/plan/test_schemas.py`: round-trip test under-verifies nested reconstruction (add
  `isinstance` asserts). `tests/live/test_plan_assembler_live.py`: redundant double-skip guard.

---

## 5. How to start the next round (Comet workflow)

1. `/comet-open <change-name>` (e.g. `bounded-experiment-runner`) — clarify → proposal/design/tasks → guard → design.
2. `/comet-design` — brainstorm → Design Doc under `docs/superpowers/specs/` → guard → build.
3. `/comet-build` — plan (subagent) → choose isolation/exec/TDD/review → subagent-driven build.
4. `/comet-verify` → `/comet-archive`.

**Standing conventions (carry forward — all validated across #3/#4/#5):**
- **Model routing:** Sonnet 4.6 implementers, Opus 4.8 per-task + final reviews (thorough
  mode), TDD; Grok rescue only if stuck.
- **Interpreter/linter:** `.venv/bin/python -m pytest …` and `.venv/bin/ruff …` — NEVER bare
  `python`/`pytest`/`ruff` (conda env lacks deps).
- **Guards on a pure-Python project:** prepend `COMET_SKIP_BUILD=1` to `comet-guard … --apply`
  after independently confirming tests+ruff green (the inferred build check returns non-zero
  for pure-Python; there is no npm/maven/cargo).
- **Comet scripts:** `/home/lingxufeng/.gemini/skills/comet/scripts/{comet-state,comet-guard,comet-handoff,comet-archive}.mjs`.
- **SDD helpers:** `/home/lingxufeng/.claude/skills/subagent-driven-development/scripts/{task-brief,review-package}`; ledger at `.superpowers/sdd/progress.md` (reset it per new change); coordinator checkpoint at `openspec/changes/<name>/.comet/subagent-progress.md`.
- **Security / hard rules:** runtime brain MUST be **Qwen via Bailian**; live tests need
  `DASHSCOPE_API_KEY`; `auto_git` stays OFF; commits carry **no** Co-Authored-By/attribution;
  the competition PDF (`PDF/XH-202619_…pdf`) is gitignored and MUST NEVER be pushed public;
  **严禁虚构** (no fabricated citations — enforced structurally via #2 verification).

---

## 6. Key reference paths

- #5 Design Doc: `docs/superpowers/specs/2026-07-14-research-plan-assembler-design.md`
- #5 Verify report: `docs/superpowers/reports/2026-07-15-research-plan-assembler-verify.md`
- #5 implementation plan: `docs/superpowers/plans/2026-07-14-research-plan-assembler.md`
- #5 package: `loop_sci/plan/` (schemas, fields, results, references, render, gate, config, executor, tools)
- #5 delta specs: `openspec/changes/research-plan-assembler/specs/{plan-field-assembly,results-derivation,reference-verification-assembly,plan-assembly-integration}/`
- #4 Design Doc: `docs/superpowers/specs/2026-07-14-hypothesis-engine-design.md`
- Deferred-follow-up ledgers: `.superpowers/sdd/progress.md`, and each change's `openspec/changes/<name>/.comet/subagent-progress.md`

> When you resume: `git -C /home/lingxufeng/cli/Loop-SCI log --oneline -5` should show `5029ef4`
> at/near HEAD with #5 merged. #1–#5 sit under `openspec/changes/` at `phase: archive` until
> you choose to run `/comet-archive` on them.
