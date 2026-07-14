# Brainstorm Summary

- Change: arbor-qwen-skeleton
- Date: 2026-07-14

## Confirmed Technical Approach

Foundation harness = **vendor Arbor's engine primitives + reimplement a thin coordinator/executor**, with **Hydra+OmegaConf** as the config surface. Arbor is Apache-2.0 (fork permitted; record source commit, keep NOTICE).

- **Fork boundary:** vendor `provider (core/llm)`, `Agent`+`ContextManager`, `events` bus, `Node`/`IdeaTree` data model, `tools/base` into `loop_sci/_vendor/arbor/`. Do NOT vendor `orchestrator.py`, `convergence`, `contamination`, `branch_guard`, `git_artifacts`, or the TUI.
- **Provider:** `OpenAICompatProvider(model, api_key, base_url)` retargeted to Bailian's OpenAI-compatible endpoint + a Qwen tier. Native tool-calling already wired (`tools`/`tool_choice="auto"`). Add a `ToolProtocol` seam: `NativeToolProtocol` (default) + `PromptToolProtocol` (JSON-in-text fallback); live smoke test sets per-tier default. Credentials via env interpolation, fail-fast, redacted; `invocation_record()` helper for competition evidence. Retry/backoff + typed errors.
- **Coordinator/executor (ours, thin):** coordinator owns IdeaTree, loop observe→dispatch→record(persist)→decide (continue while pending + step budget). Executor runs one `DispatchUnit` as an Agent → typed `ExecutorResult`. No merge/convergence/worktree.
- **State:** adopt vendored Node/IdeaTree (optimization fields optional; `code_ref`→generic refs). Atomic persistence (temp + os.replace), auto-save on mutation. `RunSession` = `<runs>/<id>/{idea_tree.json, run.json, logs/}`; resume from tree + run.json cursor. Tree is source of truth across compaction.
- **Events:** vendored EventBus/NullBus (NullBus default). Dashboard (#7) subscribes later.
- **CLI:** typer `run / resume / inspect` against a neutral stub task (no domain logic).
- **Config:** Hydra structured configs materialize into vendored `AgentConfig` at construction.

## Key Trade-offs and Risks

- Arbor optimization-tree vs our plan output → keep tree generic, defer tree→13-field mapping to change #5. (Mitigated by reimplementing coordinator, not vendoring orchestrator.)
- Qwen tool-calling reliability over OpenAI-compat → ToolProtocol fallback + opt-in live smoke test decides default.
- Bailian rate-limits + 300¥ budget → retry/backoff, cheap default tier for dev, response logging.
- Fork drift → pinned snapshot, record commit, minimal surface (don't vendor what we don't use).
- Hydra↔vendored AgentConfig rewiring → small loader/adapter, contained.

## Testing Strategy

Target ≥80%. Unit: provider normalization + credential missing/redaction (mock HTTP); tool registry known/unknown; idea-tree persist/reload equality + atomic-write; resume continuation; event-bus subscriber parity. Integration: one coordinator→executor cycle vs deterministic MockProvider (no network). Live smoke (`@pytest.mark.live`, needs key): real Qwen completion + native tool-call round-trip; records tier tool-call support.

## Spec Patches

Written back to `specs/research-state/spec.md` (boundary scenarios only, no scope change):
- Persistence: "Interrupted mid-write never corrupts the tree" (atomic write).
- Run lifecycle: "Resuming an already-complete run is a safe no-op".
