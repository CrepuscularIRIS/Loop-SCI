# Comet Design Handoff

- Change: arbor-qwen-skeleton
- Phase: design
- Mode: compact
- Context hash: 380cea1c653888677396f00b8b104fe6300124a53503780bdc6ae27a5968d600

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/arbor-qwen-skeleton/proposal.md

- Source: openspec/changes/arbor-qwen-skeleton/proposal.md
- Lines: 1-32
- SHA256: 01098c76cb3e948ff1b5fab02fc5706a0de9f06ac06ad980be93831a6c3d99ed

```md
## Why

Loop-SCI is our entry for the XH-202619 competition ("基于国产开源大模型的 AI Scientist"): an AI Scientist for **neuroscience / brain-decoding** that runs the closed loop *data/literature → verifiable 《科学假设与研究计划》*. Every downstream capability (literature mining, the hypothesis gate-pipeline, the 13-field research-plan assembler, human-in-loop deliberation, and the visualization dashboard) needs one thing first: a working **multi-agent harness whose runtime brain is Qwen**, called through Alibaba Cloud 百炼 (Bailian).

This change delivers that foundation and nothing else. It is change **#1 of 7** in the Loop-SCI programme; it is deliberately domain-agnostic so the neuroscience pack (#2) and the research capabilities (#3–#7) plug into a stable core. We fork/adapt Arbor's proven coordinator/executor + idea-tree + provider architecture rather than build greenfield, because the submission deadline is **2026-09-05** (~7.5 weeks) and Arbor is already a working multi-agent harness with a pluggable, OpenAI-compatible provider layer that maps cleanly onto Bailian's Qwen endpoint.

## What Changes

- **NEW** Python/uv project scaffold (repo layout, packaging, config loading, logging) adapted from Arbor's structure.
- **NEW** Pluggable LLM provider layer with a **Qwen-via-Bailian** backend (OpenAI-compatible client), model selection (Qwen-Max/Plus/Turbo), and credential handling suitable for the competition's "provide invocation credentials/screenshots" rule.
- **NEW** Multi-agent engine core: a ReAct-style agent runtime (LLM + tool execution + context management) and a **coordinator/executor** orchestration loop, forked and retargeted from Arbor.
- **NEW** Durable **idea-tree** research-state model (nodes with status/score/insight/refs), JSON persistence with auto-save on mutation, plus run session/checkpoint/**resume**.
- **NEW** An **event bus** seam (core emits, subscribers listen) so the later visualization change (#7) can attach without touching the engine.
- **NEW** A minimal CLI entry point that launches, resumes, and inspects a run against a stub research task (proves the loop turns end-to-end on Qwen).
- **Out of scope (later changes):** literature mining / citation verification (#3), the research-os hypothesis gate-pipeline (#4), the 13-field 《科学假设与研究计划》 assembler + bounded experiment runner (#5), human-in-loop deliberation UI (#6), the live web dashboard + HTML export (#7), and the neuroscience domain pack + datasets (#2). This change only establishes the harness they build on.

## Capabilities

### New Capabilities
- `llm-provider`: Pluggable LLM provider abstraction with a Qwen-via-Bailian (OpenAI-compatible) backend, model/tier selection, retry/timeout handling, and secret/credential management.
- `agent-engine`: The ReAct-style agent runtime (LLM call + tool dispatch + context management) and the coordinator/executor multi-agent orchestration loop that drives one research cycle.
- `research-state`: The durable idea-tree state model, run-session persistence with checkpoint/resume, and the event-bus seam for observers.

### Modified Capabilities
<!-- None. This is a greenfield project; no existing specs to modify. -->

## Impact

- **New codebase** at repo root (no existing code to break). Language/toolchain: **Python 3.11+, uv** (per project standards), Hydra/OmegaConf-style config.
- **New dependencies:** an OpenAI-compatible client SDK (for Bailian), Arbor source (forked/vendored), YAML/config libs, a CLI framework (typer). Test stack: pytest.
- **External systems:** Alibaba Cloud 百炼 (Bailian) API for Qwen inference; requires an API key + the 300¥/person compute credit. Provider layer must stay OpenAI-compatible so other Qwen endpoints (DashScope/local vLLM) remain drop-in for development.
- **Enables:** all six downstream Loop-SCI changes; nothing runs end-to-end scientifically until #3–#5 land, but the harness will demonstrably turn a coordinator/executor loop on Qwen and persist/resume its idea-tree.

```

## openspec/changes/arbor-qwen-skeleton/design.md

- Source: openspec/changes/arbor-qwen-skeleton/design.md
- Lines: 1-52
- SHA256: 2c47abc52e87c2316531652c09e0647e9d8beed76ec5c1416064546ed15c9632

```md
## Context

Loop-SCI (competition XH-202619) needs a multi-agent harness whose runtime brain is **Qwen via Alibaba Cloud 百炼 (Bailian)**, on top of which six downstream capabilities are built. Three reference systems inform this: **Arbor** (a working Python coordinator/executor harness with a pluggable OpenAI-compatible provider layer, a durable idea-tree, and a dashboard), **ARIS** (an unattended research pipeline with resumable state and cross-model review), and **research-os** (an elegant taste-first, gates-not-scripts hypothesis-quality model with "state lives in tools").

Hard constraints: the runtime LLM must be Qwen through Bailian (Claude Code is only our *development* harness); the deliverable is a verifiable 13-field 《科学假设与研究计划》, not a finished paper; multi-agent design and multimodal-data handling are directly scored; the submission deadline is **2026-09-05** (~7.5 weeks). This design covers only change **#1 of 7** — the domain-agnostic foundation. Deep per-module technical design is refined later in the Comet design phase.

## Goals / Non-Goals

**Goals:**
- A Python/uv codebase that boots, loads config, and turns a coordinator/executor loop end-to-end on Qwen-via-Bailian against a stub task.
- A pluggable `LLMProvider` layer with a Qwen/Bailian backend that stays OpenAI-compatible (swappable to DashScope/vLLM by config).
- A durable idea-tree with auto-save and crash-resume; an event-bus seam for the future dashboard.
- Enough seams (tool registry, tree API, event bus) that changes #2–#7 attach without reworking the core.

**Non-Goals:**
- Any scientific capability (literature mining, hypothesis gates, 13-field assembler, bounded experiments, human-in-loop UI, dashboard, neuroscience datasets) — those are changes #2–#7.
- Fine-tuning/SFT, production hosting, or multi-domain support.
- A polished CLI/UX beyond what proves the loop runs and resumes.

## Decisions

**D1 — Fork/adapt Arbor rather than greenfield or external-component.**
Chosen for the ~7.5-week deadline: Arbor already implements coordinator/executor, a pluggable provider, idea-tree persistence, and event/dashboard seams. We vendor/fork its `core/` (agent, provider, config) and `coordinator/` (orchestrator, idea-tree, tools), then reconstruct the research-os gate pipeline on top in later changes. *Alternatives:* greenfield (cleanest fit to the 13-field output, but too slow); Arbor-as-external-MCP/CLI (cleaner boundary, but integration overhead and less control over the tree schema we must extend). We first verify Arbor's license permits forking.

**D2 — Provider is OpenAI-compatible, pointed at Bailian.**
Reuse Arbor's `openai-chat` provider path; configure `base_url` to Bailian's OpenAI-compatible endpoint and `model` to a Qwen tier. This keeps Qwen as the mandated brain while letting developers point at any OpenAI-compatible Qwen host without code changes. *Alternative:* a bespoke DashScope-native client — rejected as lock-in with no upside for the competition rule (which only requires Qwen + Bailian invocation evidence).

**D3 — Multi-agent (coordinator/executor), not super-agent.**
Matches the scored "multi-agent collaboration design" sub-item and the user's goal of a solid multi-agent harness. Coordinator owns the idea-tree and decisions; executors carry single dispatched units. Later changes add specialist executors (lit-miner, hypothesizer, adversary, planner).

**D4 — State lives in tools (idea-tree), synthesis is derived.**
Follow research-os discipline: durable research state is the idea-tree JSON (auto-saved on mutation), not prose in context. Context compaction is safe because the tree is the source of truth and drives resume. This is the seam the 13-field assembler (#5) will read from.

**D5 — Event-bus seam now, dashboard later.**
Keep Arbor's event bus so the coordinator/tree/agent emit events with a NullBus default (zero overhead when unsubscribed). Change #7 (live dashboard + HTML export) subscribes without touching the engine.

**D6 — Python 3.11+ / uv / typer / pytest, config via a flat-proxy schema.**
Aligns with project standards and Arbor's structure; the flat-proxy config keeps a single source of truth with secrets redacted at dump time.

## Risks / Trade-offs

- **Arbor's idea-tree is optimization-scored (dev/test score, merge threshold); our deliverable is a research *plan*.** → Keep the tree schema generic in this change (status/score/insight/refs as optional fields); defer the tree→13-field mapping to the assembler change (#5). Do not bake optimization-merge semantics into the core.
- **Qwen tool-calling over the OpenAI-compatible endpoint may be less reliable than Anthropic/OpenAI native.** → Add an early smoke test of native tool-calls on the target Qwen tier; if flaky, fall back to a prompt-based tool protocol (JSON-in-text) behind the same tool-registry interface.
- **Bailian rate limits + the 300¥/person compute budget.** → Configurable retry/backoff, a cheap default tier (Qwen-Turbo/Plus) for development, and response logging to avoid re-spending on repeated runs.
- **Fork drift from upstream Arbor.** → Vendor a pinned snapshot; record the source commit; avoid deep edits to files we do not need, to keep the surface small.
- **Over-scoping the foundation.** → Enforce the Non-Goals; the only end-to-end proof required is "loop turns + persists + resumes on Qwen" against a stub task.

## Open Questions

- Exact Bailian OpenAI-compatible base URL, available Qwen tiers, and whether native tool-calling is supported at each tier (resolve via a smoke test in the first tasks).
- How much of Arbor to vendor vs. keep as a light dependency — settled during the Comet design phase once the fork is in hand.
- Whether SFT is worthwhile within budget (deferred to a later change; explicitly out of scope here).

```

## openspec/changes/arbor-qwen-skeleton/tasks.md

- Source: openspec/changes/arbor-qwen-skeleton/tasks.md
- Lines: 1-45
- SHA256: 8e4dfee6511695ef8fa6bee792d907c8daffe6f389472e4c82ed4799f80a5fa5

```md
## 1. Project scaffold & Arbor fork

- [ ] 1.1 Confirm Arbor's license permits forking/vendoring; record the source commit hash in the repo
- [ ] 1.2 Create the Python/uv project skeleton (pyproject, package layout, logging config, .gitignore, .env.example)
- [ ] 1.3 Vendor the needed Arbor modules (`core/` agent+provider+config, `coordinator/` orchestrator+idea_tree+tools, `events/`); prune what the foundation does not use
- [ ] 1.4 Port Arbor's flat-proxy config schema; add a `provider` block (base_url, model, api_key ref) and redact secrets at dump time

## 2. LLM provider (Qwen via Bailian)

- [ ] 2.1 Wire the OpenAI-compatible provider to Bailian's endpoint; load the API key from env/config and fail fast + redact when missing
- [ ] 2.2 Add model-tier selection (Qwen-Max/Plus/Turbo) and configurable timeout + bounded retry-with-backoff raising typed errors
- [ ] 2.3 SMOKE TEST: run a live Qwen-via-Bailian completion AND a native tool-call round trip; record which tiers support tool-calls
- [ ] 2.4 If native tool-calls are unreliable, add a prompt-based (JSON-in-text) tool protocol behind the same provider/registry interface
- [ ] 2.5 Add the non-secret invocation-record helper (timestamp/model/endpoint host) for the competition credential evidence

## 3. Agent engine

- [ ] 3.1 Port/adapt the ReAct agent runtime (LLM call → tool dispatch → feed result → repeat) with a step budget and bounded-exit result
- [ ] 3.2 Implement the tool registry (register by name+schema, pass defs to provider, dispatch by name) with structured errors for unknown/malformed tool calls
- [ ] 3.3 Port context management/compaction so long runs stay within limits while the idea-tree remains source of truth
- [ ] 3.4 Implement the coordinator (owns tree, plans, dispatches) and a generic executor (runs one unit, returns a structured result)

## 4. Research-state (idea-tree, persistence, resume)

- [ ] 4.1 Define the idea-tree node model (id, hypothesis, status, score, insight, refs) and parent/child structure with derivable unique ids
- [ ] 4.2 Implement canonical JSON persistence with auto-save on every mutation and a load that reconstructs a structurally-equal tree
- [ ] 4.3 Implement per-run session directory (tree + metadata + logs) and checkpoint/resume that continues from saved state without repeating completed work
- [ ] 4.4 Wire the coordinator to record each executor outcome into the tree before its next decision

## 5. Event-bus seam

- [ ] 5.1 Port the event bus with a NullBus default (zero overhead unsubscribed); emit node-mutation and run/agent lifecycle events
- [ ] 5.2 Verify a subscriber receives events and that run behavior/results are identical with and without a subscriber attached

## 6. CLI & end-to-end proof

- [ ] 6.1 Add a minimal typer CLI to start / resume / inspect a run against a stub research task
- [ ] 6.2 END-TO-END: start a run on Qwen-via-Bailian, complete ≥1 observe→dispatch→record cycle, terminate cleanly with persisted state
- [ ] 6.3 END-TO-END: interrupt a run mid-way and resume it; confirm it continues from the last checkpoint

## 7. Tests & docs

- [ ] 7.1 Unit tests: provider normalization + credential-missing/redaction; tool registry (known/unknown); idea-tree persist/reload equality; resume continuation
- [ ] 7.2 Integration test: one coordinator/executor cycle against a mocked provider (no live API) plus an opt-in live smoke test
- [ ] 7.3 Write a short README: setup (uv), Bailian credentials, running/resuming a stub run, and the Arbor fork provenance note

```

## openspec/changes/arbor-qwen-skeleton/specs/agent-engine/spec.md

- Source: openspec/changes/arbor-qwen-skeleton/specs/agent-engine/spec.md
- Lines: 1-41
- SHA256: d1b788e76259ab11ae7bad0c675f79e54a516489d5ab363e538310b534657112

```md
## ADDED Requirements

### Requirement: ReAct agent runtime
The system SHALL provide an agent runtime that runs a reason-act loop: call the `LLMProvider`, dispatch any requested tools, feed results back, and repeat until the agent emits a final answer or a step budget is reached. The runtime SHALL be provider-agnostic (works on any `LLMProvider`, including Qwen-via-Bailian).

#### Scenario: Loop runs to a final answer
- **WHEN** an agent is given a task solvable with its available tools
- **THEN** the runtime alternates LLM calls and tool dispatches until the agent produces a final answer, and returns that answer with the full step trace

#### Scenario: Step budget stops runaway loops
- **WHEN** an agent exceeds its configured maximum step budget without finishing
- **THEN** the runtime halts, returns a bounded-exit result marked incomplete, and does not loop indefinitely

### Requirement: Tool registry and dispatch
The system SHALL let tools be registered by name with a schema, SHALL pass registered tool definitions to the provider, and SHALL execute the tool named in a tool-call and return its result to the agent. Unknown or malformed tool calls SHALL return a structured tool error to the agent rather than crashing the run.

#### Scenario: Registered tool executes
- **WHEN** the agent issues a tool-call for a registered tool with valid arguments
- **THEN** the tool runs and its output is returned to the agent on the next turn

#### Scenario: Unknown tool is handled gracefully
- **WHEN** the agent issues a tool-call for a tool that is not registered
- **THEN** the runtime returns a structured "unknown tool" error to the agent and the run continues

### Requirement: Coordinator/executor orchestration
The system SHALL provide a coordinator agent that plans and dispatches work to one or more executor agents, and executor agents that carry out a single dispatched unit and report a structured result back to the coordinator. The coordinator SHALL record each executor outcome into research-state (the idea-tree) before deciding the next step.

#### Scenario: Coordinator dispatches an executor and records the result
- **WHEN** the coordinator dispatches a unit of work to an executor
- **THEN** the executor runs, returns a structured result, and the coordinator writes that result into the idea-tree before its next decision

#### Scenario: One research cycle turns end-to-end
- **WHEN** a run is started against a stub research task on the Qwen backend
- **THEN** the coordinator completes at least one observe→dispatch→record cycle and the run terminates cleanly with persisted state

### Requirement: Context management
The system SHALL manage each agent's context so a long run does not exceed model limits, compacting or summarizing prior turns while preserving the durable state needed to continue (the idea-tree remains the source of truth across compaction).

#### Scenario: Long run stays within context limits
- **WHEN** an agent's accumulated context approaches the configured threshold
- **THEN** the runtime compacts earlier turns and continues without a context-overflow error, and the idea-tree still reflects all recorded outcomes

```

## openspec/changes/arbor-qwen-skeleton/specs/llm-provider/spec.md

- Source: openspec/changes/arbor-qwen-skeleton/specs/llm-provider/spec.md
- Lines: 1-45
- SHA256: 5181247f188bdf99b89ed91a1377d51d36b8d99238a57643ec6441cf1e1baade

```md
## ADDED Requirements

### Requirement: Unified LLM provider interface
The system SHALL expose a single `LLMProvider` interface that all agents call, decoupling agent logic from any concrete backend. The interface SHALL accept a message list plus tool definitions and SHALL return a normalized response containing text, tool-call, and (when available) reasoning blocks.

#### Scenario: Agent calls provider without knowing the backend
- **WHEN** an agent issues a completion request through the `LLMProvider` interface
- **THEN** the request succeeds against the configured backend and returns a normalized response object whose shape does not depend on which backend served it

#### Scenario: Tool-call round trip
- **WHEN** the provider returns a tool-call block and the agent supplies the tool result on the next turn
- **THEN** the provider accepts the tool result in the message list and continues the conversation without loss of prior turns

### Requirement: Qwen-via-Bailian backend
The system SHALL provide a Qwen backend that reaches Alibaba Cloud 百炼 (Bailian) through an OpenAI-compatible endpoint, and SHALL allow selecting the model tier (Qwen-Max / Qwen-Plus / Qwen-Turbo) via configuration. Because the endpoint is OpenAI-compatible, any other OpenAI-compatible Qwen host (DashScope, local vLLM) SHALL be usable by changing only base-URL/model configuration.

#### Scenario: Configured Qwen tier is used
- **WHEN** the config selects `qwen-plus` against the Bailian base URL
- **THEN** a live completion is served by that model and the response records the model id actually used

#### Scenario: Swap endpoint without code change
- **WHEN** the base URL and model name are changed in config to another OpenAI-compatible Qwen host
- **THEN** the provider works against the new host with no source-code modification

### Requirement: Credential management
The system SHALL load the Bailian API key from environment variable or config (never hard-coded), SHALL fail fast with a clear message when the key is missing, and SHALL redact the key from all logs and config dumps. A helper SHALL emit a non-secret invocation record (timestamp, model, endpoint host) suitable for the competition's credential/screenshot evidence requirement.

#### Scenario: Missing key fails fast
- **WHEN** no Bailian API key is present in environment or config
- **THEN** startup aborts with an explicit error naming the missing variable, and no request is attempted

#### Scenario: Secrets never leak
- **WHEN** the resolved configuration is dumped or a request is logged
- **THEN** the API key is shown redacted and never appears in plaintext

### Requirement: Resilient request handling
The system SHALL apply configurable timeout and bounded retry-with-backoff to provider calls, and SHALL surface a typed error (rate-limit, timeout, auth, server) to the caller when retries are exhausted.

#### Scenario: Transient failure is retried
- **WHEN** a provider call returns a retryable error within the retry budget
- **THEN** the call is retried with backoff and, on eventual success, returns a normal response

#### Scenario: Exhausted retries raise a typed error
- **WHEN** retries are exhausted for a rate-limit condition
- **THEN** the caller receives a typed rate-limit error rather than a raw or generic exception

```

## openspec/changes/arbor-qwen-skeleton/specs/research-state/spec.md

- Source: openspec/changes/arbor-qwen-skeleton/specs/research-state/spec.md
- Lines: 1-45
- SHA256: 9eccc5fec65971b93840d51cdff11e3e531c60c1f5158434ff9ba56a9bfa85e9

```md
## ADDED Requirements

### Requirement: Idea-tree state model
The system SHALL model research state as a tree of nodes, where each node carries at least: a stable id, a hypothesis/description, a status (e.g. pending / running / done / merged / pruned), an optional score, an optional insight, and optional references (code/branch/artifact). The tree SHALL be the single durable source of truth for research progress.

#### Scenario: Node records an outcome
- **WHEN** an executor outcome is written to a node
- **THEN** the node's status, score, insight, and references reflect that outcome and are retrievable by node id

#### Scenario: Tree encodes parent/child structure
- **WHEN** a child hypothesis is added under a parent node
- **THEN** the tree exposes the parent/child relationship and the child inherits a derivable, unique id

### Requirement: Persistence with auto-save
The system SHALL persist the idea-tree to a canonical JSON file within the run's session directory and SHALL auto-save on every mutation, so an interrupted process never loses more than the in-flight mutation.

#### Scenario: Mutation is durable immediately
- **WHEN** a node is added or updated
- **THEN** the canonical JSON on disk reflects the change without requiring an explicit save call

#### Scenario: Reload reconstructs the tree
- **WHEN** the canonical JSON is loaded in a fresh process
- **THEN** the reconstructed tree is structurally equal to the tree that was saved

#### Scenario: Interrupted mid-write never corrupts the tree
- **WHEN** the process is killed while a mutation is being persisted
- **THEN** the on-disk canonical JSON is either the pre-mutation or the post-mutation state and is always valid JSON (writes are atomic — temp file plus replace)

### Requirement: Run lifecycle with checkpoint and resume
The system SHALL create a per-run session directory holding the idea-tree, run metadata, and logs, and SHALL support resuming an interrupted run from its last checkpoint so the coordinator continues from saved state rather than restarting.

#### Scenario: Resume continues from saved state
- **WHEN** a run is interrupted after recording some outcomes and is then resumed
- **THEN** the coordinator loads the existing idea-tree and continues from the last checkpoint without repeating completed work

#### Scenario: Resuming an already-complete run is a safe no-op
- **WHEN** resume is invoked on a run whose work is already complete
- **THEN** no completed work is re-executed and the run terminates cleanly reporting completion

### Requirement: Event-bus seam for observers
The system SHALL emit run/tree/agent events onto a decoupled event bus that observers can subscribe to, and the engine SHALL incur no behavioral change when no subscriber is attached. This seam exists so the later visualization change can attach live without modifying the engine.

#### Scenario: Observer receives events without affecting the engine
- **WHEN** a subscriber is attached to the event bus during a run
- **THEN** it receives node-mutation and lifecycle events, and the run's behavior and results are identical to a run with no subscriber

```
