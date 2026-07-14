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
