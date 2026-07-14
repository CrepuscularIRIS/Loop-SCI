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
