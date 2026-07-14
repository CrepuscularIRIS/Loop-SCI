## 1. Hypothesis generation (prospect' + forge')

- [x] 1.1 Define the hypothesis schema (problem card `{Q, WHY-NOW, PROBE/KILL, STAKES}`; hypothesis `{MECHANISM, KILL, BRACKET, DIFF-PREDICTION}`; evidence-graded derivation step; scores) and its `Node.refs` payload layout
- [x] 1.2 Implement `prospect'`: mine gap/contradiction cards from the fact base via its stable query interface (no new fetching, no idea-tree internals); drop cards citing non-existent facts
- [x] 1.3 Implement `forge'`: Qwen-driven induction+deduction from a card into candidate hypotheses with rival-frame siblings; record as idea-tree nodes under fact node(s)
- [x] 1.4 Implement the relabeling filter (strip-the-new-words ⇒ discard when no distinct diff-prediction survives)
- [x] 1.5 Bound generation by a per-run cap (cards × candidates); stop cleanly at the cap
- [x] 1.6 Unit tests (offline, mock provider): gap cards derived + fact-grounded; hypotheses carry mechanism/kill/bracket/diff-prediction + rival frame; relabeling discarded; per-run bound respected

## 2. Hypothesis critique (derivation contract + Qwen-vs-Qwen jury + anti-fabrication)

- [x] 2.1 Implement the derivation contract (HYPOTHESIS/LATENT-ROOT/ACCEPT-IF/KILL-IF as derivation tripwires, no `eval_cmd`); freeze on the node before any verdict
- [x] 2.2 Implement the adversarial jury: generator vs a distinct reviewer configuration (different Qwen tier, KILL-biased persona, varied sampling); route verdicts so the generator configuration cannot issue an accept
- [x] 2.3 Implement `adversary'` Checks C/D (claim decomposition → each step needs an artifact; generalization test) as the plan-grade critique
- [x] 2.4 Implement evidence-grade annotation `[paper]/[inferred]/[guess]` + "no artifact/fact ⇒ downgrade to hypothesis" grounded in the fact base
- [x] 2.5 Unit tests: incoherent hypothesis DOWN-verdicted; no self-acquittal (generator-issued accept rejected, reviewer config differs); ungrounded citation downgraded; grounded step carries `[paper]`/`[inferred]` + fact id

## 3. Iteration and metabolism (autopsy' + stall ledger + resume)

- [ ] 3.1 Implement `autopsy'`: convert each kill into CONSTRAINT/CANDIDATE/REGION-CLOSE; prune killed node retaining reason; feed outcome back into ranking
- [ ] 3.2 Implement region-close (≥2 mechanisms killed by same root ⇒ stop generating in that region within the run)
- [ ] 3.3 Implement the multi-round loop with the stall ledger: track new findings per round; structural pivot at stale≥2; escalate (stop nudging) at stale≥4
- [x] 3.4 Implement the acceptance ledger (`done`≠`accepted` with durable verdict ids) + a recovery anchor for resumability
- [ ] 3.5 Unit tests: kill → constraint reweights queue; region-close halts re-exploration; pivot@2 and escalate@4; resume skips accepted nodes without re-critique or re-spend

## 4. Ranking, output interface, and foundation integration

- [x] 4.1 Implement novelty + self-consistency scoring on `Node.score` + `Node.refs` subscore map (novelty measured against the fact base); reproducible offline
- [ ] 4.2 Implement the stable ranked-hypothesis query interface (retrieve-all ranked, filter by topic/status) returning problem + derivation chain w/ evidence grades + diff-prediction + scores + grounding refs, without exposing idea-tree internals
- [ ] 4.3 Implement `HypothesisExecutor` over the foundation Executor seam (consume fact base → generate → critique → iterate → record); no coordinator-interface change; `auto_git` stays off
- [ ] 4.4 Implement the score-priority coordinator subclass (`_observe()` score-sorted expansion, `_plan()` fact-base context injection)
- [ ] 4.5 Register `generate`/`critique`/`rank` tools in the ToolRegistry wrapping the same pipeline with injected deps; structured results/errors
- [ ] 4.6 Unit tests: scores recorded + novelty ordering; ranked interface returns required fields best-first; tools exercise the pipeline offline

## 5. End-to-end, tests & docs

- [ ] 5.1 Offline integration test: coordinator dispatches `HypothesisExecutor` against a mock provider + populated fact base → ≥1 accepted, scored hypothesis in the idea-tree, retrievable via the ranked interface; no network, no git; anti-fabrication (ungrounded downgraded) and no-self-acquit pinned
- [ ] 5.2 Opt-in `@pytest.mark.live` e2e: real Qwen generator + real Qwen reviewer over a small neuro topic on a seeded fact base (skip-verified without `DASHSCOPE_API_KEY`)
- [ ] 5.3 Coverage gate (≥80% on new code, excl. vendored) + ruff clean + README section (pipeline overview, Qwen-vs-Qwen jury, budget/env, ranked output for #5, live-tests-need-keys)
