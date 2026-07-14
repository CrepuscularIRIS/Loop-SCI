---
comet_change: arbor-qwen-skeleton
role: technical-design
canonical_spec: openspec
---

# arbor-qwen-skeleton — Technical Design

Deep technical refinement of the open-phase `design.md`. Loop-SCI foundation harness (change #1 of 7): a domain-agnostic multi-agent harness whose runtime brain is **Qwen via Alibaba Cloud 百炼 (Bailian)**, built by vendoring Arbor's engine primitives and reimplementing a thin coordinator/executor on top. Upstream source of truth is the OpenSpec change (`proposal.md`, `design.md`, `specs/*`, `tasks.md`); this doc refines HOW, not WHAT.

## 1. Fork boundary & package layout

Arbor is **Apache-2.0** — forking permitted. We vendor a pinned snapshot (record the source commit; preserve `LICENSE`/`NOTICE`) and build our own control layer over it.

```
loop_sci/
  _vendor/arbor/           # pinned Apache-2.0 snapshot, minimal surface
    llm/                   #   base.py, openai_compat.py (+ deps)
    agent.py, context.py   #   ReAct runtime + context compaction
    tools/base.py          #   Tool base type
    events/                #   bus.py (EventBus, NullBus), types, payloads
    idea_tree.py           #   Node + IdeaTree data model
  provider/
    factory.py             # build OpenAICompatProvider → Bailian/Qwen
    credentials.py         # env/Hydra key load, fail-fast, redact, invocation_record()
    tool_protocol.py       # NativeToolProtocol | PromptToolProtocol
    errors.py              # typed errors (RateLimit/Timeout/Auth/Server)
  engine/
    agent_runtime.py       # Hydra config → AgentConfig; construct vendored Agent
    tools.py               # tool registry (Factory/Registry)
    coordinator.py         # OUR thin coordinator (observe→dispatch→record→decide)
    executor.py            # OUR generic executor (DispatchUnit → ExecutorResult)
    types.py               # DispatchUnit, ExecutorResult dataclasses
  state/
    idea_tree.py           # re-export/extend vendored IdeaTree+Node (generic refs)
    session.py             # RunSession: session dir, checkpoint/resume, cursor
  events/__init__.py       # re-export vendored EventBus/NullBus
  config/                  # Hydra structured configs + loader
  cli.py                   # typer: run / resume / inspect
tests/                     # unit + integration + opt-in live smoke
```

**Not vendored:** `orchestrator.py` (1262 lines, optimization-specific), `convergence`, `contamination`, `branch_guard`, `git_artifacts`, worktree/merge logic, the TUI dashboard. Rationale: they encode optimization-tree semantics (dev/test score, merge threshold, worktree isolation) that contradict our "tree is a generic research state, output is a plan" model, and they are the largest fork-drift surface. Specialist executors and the tree→13-field mapping arrive in later changes (#3–#5).

## 2. Provider — Qwen via Bailian (`llm-provider`)

`OpenAICompatProvider(model, api_key, base_url)` already builds an `AsyncOpenAI` client and passes `tools` + `tool_choice="auto"`. Retargeting to Bailian is **pure configuration**: `base_url` = Bailian OpenAI-compatible endpoint, `model` = a Qwen tier (`qwen-max`/`qwen-plus`/`qwen-turbo`), `api_key` from env/Hydra. Because it is OpenAI-compatible, any other Qwen host (DashScope, local vLLM) is a config-only swap.

- **`provider/factory.py`** — builds and returns a configured `LLMProvider`; the only place backend construction happens (Factory pattern).
- **`provider/credentials.py`** — resolves the key via OmegaConf env interpolation (e.g. `${oc.env:DASHSCOPE_API_KEY}`); raises a clear, named error before any request if missing; a `redact()` used in all config dumps/log previews; `invocation_record()` emits non-secret `{ts, model, endpoint_host}` JSON for the competition's credential/screenshot rule.
- **`provider/tool_protocol.py`** — a `ToolProtocol` interface decoupling "how tools are offered to the model" from the agent:
  - `NativeToolProtocol` — uses the provider's native `tools`/`tool_choice` (default; already wired).
  - `PromptToolProtocol` — injects tool schemas into the system prompt and parses a JSON tool-call block from text (fallback for tiers where native tool-calling is unreliable).
  - Config selects the active protocol; the **live smoke test** (task 2.3) determines the default per Qwen tier.
- **`provider/errors.py`** — retry-with-backoff (configurable budget) wrapping the async call; on exhaustion raises a typed error (`RateLimitError`/`TimeoutError`/`AuthError`/`ServerError`) so callers branch on cause, not string-matching.

## 3. Agent runtime & tool registry (`agent-engine`)

The vendored `Agent(provider, tools, config)` runs the ReAct loop (LLM → tool dispatch → feed result → repeat) with `ContextManager` compaction and optional `bus`. `engine/agent_runtime.py` is a thin adapter: it maps Hydra config → the vendored `AgentConfig`, wires the `bus`, and constructs the `Agent`. `engine/tools.py` is a **Factory/Registry**: tools register by `name` + JSON schema; the registry supplies definitions to the provider and dispatches by name.

- **Unknown/malformed tool-call** → returns a structured `{"error": "unknown_tool", ...}` tool result to the agent; the run continues (never an unhandled exception).
- **Step budget** → the runtime exits with a `bounded_exit=True, complete=False` result rather than looping forever.
- **Context overflow** → `ContextManager` compacts earlier turns; the idea-tree remains the durable record so no recorded outcome is lost.

## 4. Coordinator / executor (`agent-engine`)

Our own thin control layer — the deliberate replacement for Arbor's optimization orchestrator.

```
Coordinator.run(session):
  loop while (pending nodes exist) and (step_budget not exceeded):
     node   = observe(tree)                 # pick next pending node
     unit   = plan(node)                     # DispatchUnit for the executor
     result = executor.run(unit)             # Executor = one Agent over the unit
     record(tree, node, result)              # update node; ATOMIC persist BEFORE next step
     emit(node_updated)
  finalize(session)                          # mark run complete, persist cursor
```

- **`engine/types.py`** — `DispatchUnit{node_id, goal, context, tools}` and `ExecutorResult{status, summary, score?, insight?, refs?}`. These two dataclasses are the seam that later specialist executors (lit-miner, hypothesizer, adversary, planner) implement.
- **`engine/executor.py`** — builds an `Agent` for the unit's goal/tools, runs it, maps the agent's final answer + trace into a typed `ExecutorResult`.
- **Foundation scope:** the coordinator's `plan`/`observe`/`decide` are intentionally minimal (single stub node → one executor → record → stop). "Smart" selection/branching is a later change; the seam is what matters here.
- **Invariant:** an outcome is persisted to the tree **before** the coordinator makes its next decision, guaranteeing resume correctness.

## 5. Idea-tree, persistence & resume (`research-state`)

Adopt the vendored `Node`/`IdeaTree` (`id, hypothesis, status, insight?, score?, test_score?, code_ref?, related_work?`; `to_dict` omits None fields). We treat `score`/`test_score`/`code_ref` as **optional/generic** (generalize `code_ref` → a generic `refs` dict) and require none of the optimization fields.

- **Atomic persistence** — `save()` writes to a temp file in the session dir then `os.replace()` onto the canonical `idea_tree.json`; auto-called on every mutation (`add_node`/`update_node`). A kill mid-write therefore leaves either the pre- or post-mutation JSON, never a partial file (Spec Patch scenario).
- **`state/session.py` — `RunSession`** owns `<runs_root>/<run_id>/{idea_tree.json, run.json, logs/}`. `run.json` holds run metadata + a small cursor (status, step count). `resume(run_id)` loads the tree + cursor and continues from pending nodes; resuming a run with no pending work is a **safe no-op** that reports completion (Spec Patch scenario).
- The tree is the single source of truth; context compaction never loses recorded state because state lives here, not in prose.

## 6. Event bus (`research-state`)

Re-export the vendored `EventBus`/`NullBus`; `NullBus` is the default so the engine has zero overhead when nothing is subscribed. Coordinator, tree, and agent emit node-mutation and run/agent lifecycle events. This is the seam change #7 (live dashboard + HTML export) attaches to without modifying the engine. Acceptance: a subscriber receives events and a run's results are byte-for-byte identical with and without a subscriber.

## 7. CLI & end-to-end proof

`cli.py` (typer): `loop-sci run --task <stub> [--config ...]`, `loop-sci resume <run_id>`, `loop-sci inspect <run_id>`. The **stub task** is a neutral, domain-free 2–3 step reasoning task. Two end-to-end proofs (tasks 6.2/6.3): (a) a run on Qwen-via-Bailian completes ≥1 observe→dispatch→record cycle, terminates cleanly, and persists; (b) a run interrupted mid-way resumes from the last checkpoint and continues without repeating completed work.

## 8. Config (Hydra + OmegaConf)

Hydra structured configs are the user-facing surface, grouped `provider` / `agent` / `engine` / `run`. A `config/loader.py` materializes them into the vendored dataclasses (`AgentConfig`) at construction time — Hydra owns the surface, the vendored code keeps its internal objects, and the adapter is the only coupling point. Secrets are env-interpolated and redacted at dump. This keeps the project on the team's Hydra standard while minimizing edits to vendored code.

## 9. Testing strategy (target ≥80% coverage)

- **Unit:** provider response normalization + credential-missing (fail-fast) + redaction, against a mocked HTTP client; tool registry (registered dispatch, unknown/malformed handling); idea-tree persist→reload structural equality + atomic-write (kill-mid-write simulation); resume continuation + already-complete no-op; event-bus subscriber parity.
- **Integration:** one full coordinator→executor cycle against a deterministic `MockProvider` (scripted responses, no network) — exercises the whole loop offline and is the CI default.
- **Live smoke (opt-in):** `@pytest.mark.live`, skipped unless a Bailian key is present; issues a real Qwen completion and a native tool-call round-trip, and records which tiers support native tool-calls (this result sets the `ToolProtocol` default). Keeps CI hermetic while still validating the real endpoint on demand.

## 10. Risks / trade-offs

- **[Arbor tree carries optimization semantics]** → generalize fields, reimplement the coordinator, defer tree→13-field mapping to #5. Mitigated structurally by the fork boundary.
- **[Qwen native tool-calling unreliable on some tiers]** → `ToolProtocol` seam + live smoke test choose the per-tier default; no code change to switch.
- **[Bailian rate limits + 300¥ budget]** → retry/backoff, cheap default tier for dev, response/invocation logging to avoid re-spending.
- **[Fork drift from upstream]** → pinned snapshot, recorded commit, minimal vendored surface; never edit vendored files we don't need.
- **[Hydra ↔ vendored AgentConfig coupling]** → contained in one adapter (`config/loader.py`); vendored code otherwise untouched.
- **[Over-scoping the skeleton]** → the only required end-to-end proof is "loop turns + persists + resumes on Qwen" against a stub; specialist agents/decisions are explicitly out of scope.

## 11. Open questions (resolved during build)

- Exact Bailian OpenAI-compatible `base_url`, available Qwen tiers, and per-tier native tool-call support — settled by the task 2.3 smoke test.
- Precise set of vendored files (minimal transitive closure of `agent.py` + `openai_compat.py` + `idea_tree.py` + `events`) — pinned when the snapshot is taken in task 1.3.
- SFT — explicitly deferred to a later change; out of scope here.

## Spec Patches applied

Two boundary scenarios added to `openspec/changes/arbor-qwen-skeleton/specs/research-state/spec.md` (acceptance-scenario supplements only, no scope change): atomic-write crash safety under *Persistence with auto-save*, and already-complete-resume no-op under *Run lifecycle with checkpoint and resume*.
