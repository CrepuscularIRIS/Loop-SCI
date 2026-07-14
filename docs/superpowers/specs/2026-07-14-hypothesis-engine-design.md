---
comet_change: hypothesis-engine
role: technical-design
canonical_spec: openspec
---

# Hypothesis Engine — Technical Design

Loop-SCI change #4. Deepens `openspec/changes/hypothesis-engine/design.md` (the high-level framework) with the concrete schema, thresholds, jury mechanics, stage shapes, resumability keying, and test strategy confirmed during the design-phase brainstorming. The OpenSpec proposal / delta specs / tasks remain canonical; this doc does not restate requirements, it specifies *how* they are met.

## 1. Scope recap (boundaries only)

The engine consumes the verified fact base from change #2 (`FactStore`, read through its **stable query interface**, never through idea-tree parentage) and emits **ranked candidate hypotheses** for the #5 plan-assembler. It runs a plan-grade adaptation of the research-os loop (`prospect' → forge' → [contract] → adversary' → autopsy'`) on a **dedicated hypothesis idea-tree**, with a Qwen-vs-Qwen non-self-acquitting jury. Runtime brain is Qwen via Alibaba Cloud Bailian. Everything past ranked hypotheses (13-field assembly, executed experiments, CORAL, cron/monitor) is deferred to #5/#6/#7 per the proposal's Non-Goals.

## 2. Tree shape and ownership

The engine builds and owns its own idea-tree per run:

```
topic root
 ├─ problem-card node (frame: primary)
 │   ├─ hypothesis node (frame: primary)
 │   ├─ hypothesis node (frame: rival)      ← rival framings are siblings
 │   └─ …
 ├─ problem-card node
 │   └─ …
 └─ …
```

- Fact-base facts are **not** tree nodes here. A hypothesis references facts by **fact-id** (`Node.grounding`), resolved through `FactStore`'s stable query interface. This is the confirmed Spec Patch #1 boundary: hypotheses attach under the **problem-card node**, grounding is by fact-id reference.
- The tree is the vendored Arbor idea-tree via the Loop-SCI `Node.refs` subclass — reusing `add_node` / `update_node` / `prune_node` / `async_update_node`, `get_constraints_block()` (inject pruned-lessons into later prompts), and `get_best_done_node()`. **No new vendored primitives.**

## 3. Fused hypothesis schema

Native `Node` fields carry the ranking-critical, queryable state; `Node.refs` carries the structured research-os payload.

### 3.1 Native `Node` fields

| Field | Meaning |
|-------|---------|
| `hypothesis` | one-sentence candidate statement |
| `status` | `open` \| `accepted` \| `pruned` (pruned = KILL) |
| `eval_status` | `generated` \| `critiqued` \| `accepted` (done ≠ accepted) |
| `insight` | MECHANISM + one-line rationale |
| `score` | overall = `w_n·novelty + w_c·self_consistency` (default `w_n=w_c=0.5`, Hydra-configurable) |
| `score_split` | `{novelty, self_consistency}` |
| `grounding` | `[fact_id]` into `FactStore` |

`accepted` is the conjunction: `eval_status == "accepted"` **AND** `refs.verdict.result == "UP"` with a `verdict_id`. No node reaches `accepted` on the generator's own say-so (see §5).

### 3.2 `Node.refs` payload layout

```jsonc
{
  "kind": "problem-card" | "hypothesis",
  "frame": "primary" | "rival",
  "topic": "<topic string>",
  "card": { "Q": "...", "WHY_NOW": "...", "PROBE_KILL": "...", "STAKES": "..." },
  "hyp":  { "MECHANISM": "...", "KILL": "...", "BRACKET": "...", "DIFF_PREDICTION": "..." },
  "derivation": [
    { "step": "...", "grade": "[paper]" | "[inferred]" | "[guess]", "fact_ids": ["..."] }
  ],
  "contract": { "HYPOTHESIS": "...", "LATENT_ROOT": "...", "ACCEPT_IF": "...", "KILL_IF": "..." },
  "verdict":  { "id": "...", "reviewer_model": "...", "result": "UP" | "DOWN",
                "reasons": ["..."], "decided_by": "jury" | "deterministic-gate" },
  "scores":   { "novelty": 0.0, "self_consistency": 0.0, "decided_by": "deterministic" | "judge" },
  "autopsy":  { "outcome": "CONSTRAINT" | "CANDIDATE" | "REGION_CLOSE", "region": "...", "note": "..." },
  "iteration": { "round": 0, "stall_count": 0 }
}
```

`card` is populated on problem-card nodes; `hyp`/`derivation`/`contract`/`verdict`/`scores`/`autopsy` on hypothesis nodes. Round-trips via the existing `to_dict`/`from_dict` (mirrors #2's `refs` usage).

## 4. Thresholds and scoring (hybrid, mirrors #2)

All thresholds are Hydra-configurable; defaults below.

- **Admit (prospect'):** a problem card is admitted if `STAKES ≥ θ_stakes` **and** its region is not already closed. No GPU-day / compute gate (plan-grade).
- **Caps:** `≤ 5` cards · `≤ 4` candidates/card · `≤ 3` rounds. Generation stops cleanly at the cap.
- **Novelty** = normalized lexical/structural distance of the hypothesis mechanism from its grounding facts, banded like #2's grounding: `≤ LOW (0.15)` ⇒ restatement (low novelty); `≥ HIGH (0.60)` ⇒ novel; **in-band ⇒ Qwen-Plus judge returns 0–1**. Measured against the fact base ⇒ reproducible offline.
- **Self-consistency** = deterministic base (contradiction scan across derivation steps + evidence-grade completeness: no *load-bearing* `[guess]`) ⇒ borderline cases escalate to the judge. The deterministic floor doubles as the **anti-fabrication backstop**.
- **Jury DOWN** if any of: mechanism contradicts grounding · a load-bearing step is `[guess]` · fails adversary Check C (claim-envelope: each decomposed claim needs an artifact/fact) · fails Check D (generalization test).

## 5. Qwen-vs-Qwen jury mechanics

- **Generator:** Qwen-Max. **Reviewer:** Qwen-Plus (distinct tier) with a **KILL-biased adversarial persona**, higher temperature, and a different seed.
- **Deterministic pre-jury gate runs first.** If it fails (mechanism contradicts a grounding fact, or a load-bearing derivation step is `[guess]`), the candidate is DOWN-verdicted by the gate with `decided_by: "deterministic-gate"` and **no reviewer call is spent** (confirmed Spec Patch #2). This is the confirmed decision that the deterministic evidence-grade/contradiction backstop **ships in #4**, not deferred.
- **Structural no-self-acquit:** an UP verdict whose `reviewer_model == generator_model` is rejected at the routing layer — the generator configuration structurally cannot grant the accept. This satisfies research-os's / ARIS's "a verdict that helps the proposer if gamed must never be granted by the proposer," within the Qwen mandate.
- The jury fires **once per surviving candidate** (post-gate), not per token — bounds budget.

## 6. Stage shapes (prompt + control flow)

Each research-os stage is a prompt+parse unit on the Qwen provider returning structured JSON; invalid JSON ⇒ retry-once ⇒ drop (identical discipline to #2's extractor).

- **prospect'** — reads facts via the query interface, emits problem cards `{Q, WHY_NOW, PROBE_KILL, STAKES}`; drops any card citing a non-existent fact-id before ranking.
- **forge'** — induction + deduction from a card ⇒ candidate hypotheses `{MECHANISM, KILL, BRACKET, DIFF_PREDICTION}` + ≥1 rival sibling, recorded under the problem-card node.
- **relabeling filter** (deterministic) — strip novel terms, re-derive the diff-prediction; if identical to the status quo ⇒ discard as relabeling.
- **contract** — freeze `{HYPOTHESIS, LATENT_ROOT, ACCEPT_IF, KILL_IF}` on the node before any verdict; ACCEPT-IF/KILL-IF are derivation tripwires, no `eval_cmd`.
- **adversary'** — deterministic pre-jury gate → Qwen-Plus jury (§5); Checks C/D as the plan-grade critique.
- **autopsy'** — convert each kill into `CONSTRAINT` / `CANDIDATE` / `REGION_CLOSE`; prune the killed node retaining its reason; outcomes accumulate into a run-level lessons block injected into later prompts via `get_constraints_block()`.

### Control flow (confirmed call C)

`HypothesisExecutor.run(unit)` runs the **full multi-round loop internally per topic** (like #2's batch executor). The score-priority **coordinator subclass overrides only `_observe()`** (score-sorted expansion) and `_plan()` (fact-base context injection). No per-stage dispatch, no coordinator-interface change, `auto_git` stays off.

### Iteration & metabolism

- **Region-close:** ≥2 mechanisms killed by the same latent root ⇒ stop generating in that region for the run.
- **Stall ledger:** track new findings per round; **structural pivot at stale ≥ 2**, **escalate (stop nudging) at stale ≥ 4**.

## 7. Resumability (confirmed call D)

Rides on the existing `RunSession` (per-run dir + tree + atomic cursor via `os.replace`) plus a durable sidecar:

- **`verdict-ledger.jsonl`** — append-only; one line per issued verdict `{verdict_id, node_id, reviewer_model, result, round}`. Enables a fast already-accepted scan and an audit trail without re-parsing the tree.
- **Cursor** stores `{round, stall_count}`.
- **Resume** = load tree + cursor, skip nodes already `accepted` (the LitMinerExecutor `refs`-skip pattern) — no re-critique, no re-spend.

## 8. Ranking & output interface

- Scores land on `Node.score` + `Node.score_split`; novelty ordering is reproducible offline.
- The **stable ranked-hypothesis query interface** returns items best-first, filterable by topic/status, each carrying: problem, derivation chain (with evidence grades), diff-prediction, novelty + self-consistency, and grounding fact-ids — **without exposing idea-tree internals** (the #5 contract).
- `generate` / `critique` / `rank` tools registered in the ToolRegistry wrap the same pipeline with injected deps; structured results/errors, offline-capable.

## 9. Testing strategy

**Offline-by-default.** A role-dispatching `MockProvider` serves **both** generator and reviewer roles; deterministic checks are tested directly.

Unit pins: gap-cards fact-grounded · relabeling discarded · no-self-acquit (generator-issued UP rejected) · ungrounded step downgraded to `[guess]` · deterministic gate DOWN's without a jury call · kill → constraint reweights the queue · region-close halts re-exploration · pivot@2 / escalate@4 · resume skips accepted nodes · ranked interface returns required fields best-first · tools exercise the pipeline offline.

Integration: coordinator → `HypothesisExecutor` → `MockProvider` + seeded `FactStore` ⇒ ≥1 accepted, scored hypothesis, ranked-retrievable; anti-fabrication + no-self-acquit pinned; no network, no git.

Live (`@pytest.mark.live`): real Qwen-Max generator + Qwen-Plus reviewer over a small neuro topic on a seeded fact base; skip-verified without `DASHSCOPE_API_KEY`.

Gates: coverage ≥ 80% on new code (excl. vendored), ruff clean, README section (pipeline overview · Qwen-vs-Qwen jury · budget/env · ranked output for #5 · live-tests-need-keys).

## 10. Key risks / trade-offs

- **Qwen-vs-Qwen independence is family-correlated** → distinct tier + adversarial persona + varied sampling + the deterministic backstop; revisit the reviewer substrate if the jury proves too lenient.
- **Novelty is subjective** → measured against the fact base, reproducible offline, tunable bands.
- **Plan-grade feasibility without runs could be hand-wavy** → concrete ACCEPT-IF/KILL-IF tripwires; #5's CORAL path spot-checks the winner later.
- **Non-convergence** → stall pivot@2 / escalate@4 + region-close.
- **Budget (≈300¥)** → per-run caps; jury fires once per surviving candidate; deterministic gate avoids wasted jury calls.

## 11. Spec Patches applied

Written back into the OpenSpec delta specs (source of truth):

1. `specs/hypothesis-generation/spec.md` — clarified that hypotheses attach under the **problem-card node** (not a fact node) and grounding is by **fact-id reference** into the fact base's stable query interface; added a matching scenario.
2. `specs/hypothesis-critique/spec.md` — added a scenario: a candidate failing the **deterministic pre-jury gate** (mechanism contradicts a grounding fact, or a load-bearing `[guess]`) is DOWN-verdicted **without spending a jury call**.
