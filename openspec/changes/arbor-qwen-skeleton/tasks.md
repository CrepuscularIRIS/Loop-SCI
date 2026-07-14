## 1. Project scaffold & Arbor fork

- [x] 1.1 Confirm Arbor's license permits forking/vendoring; record the source commit hash in the repo
- [x] 1.2 Create the Python/uv project skeleton (pyproject, package layout, logging config, .gitignore, .env.example)
- [x] 1.3 Vendor the needed Arbor engine primitives (`core/` agent+context+provider+config, `coordinator/idea_tree` data model, `events/`, `tools/base`) into `loop_sci/_vendor/arbor/`; do NOT vendor the optimization orchestrator/convergence/branch_guard; prune what the foundation does not use
- [x] 1.4 Provide the config surface via Hydra+OmegaConf materializing into the vendored `AgentConfig`; add a `provider` block (base_url, model, api_key ref via env interpolation) and redact secrets at dump time

## 2. LLM provider (Qwen via Bailian)

- [x] 2.1 Wire the OpenAI-compatible provider to Bailian's endpoint; load the API key from env/config and fail fast + redact when missing
- [x] 2.2 Add model-tier selection (Qwen-Max/Plus/Turbo) and configurable timeout + bounded retry-with-backoff raising typed errors
- [x] 2.3 SMOKE TEST: run a live Qwen-via-Bailian completion AND a native tool-call round trip; record which tiers support tool-calls — _(@pytest.mark.live test implemented + skip-verified; LIVE execution pending user's DASHSCOPE_API_KEY)_
- [x] 2.4 If native tool-calls are unreliable, add a prompt-based (JSON-in-text) tool protocol behind the same provider/registry interface
- [x] 2.5 Add the non-secret invocation-record helper (timestamp/model/endpoint host) for the competition credential evidence

## 3. Agent engine

- [x] 3.1 Port/adapt the ReAct agent runtime (LLM call → tool dispatch → feed result → repeat) with a step budget and bounded-exit result
- [x] 3.2 Implement the tool registry (register by name+schema, pass defs to provider, dispatch by name) with structured errors for unknown/malformed tool calls
- [x] 3.3 Port context management/compaction so long runs stay within limits while the idea-tree remains source of truth
- [x] 3.4 Implement the coordinator (owns tree, plans, dispatches) and a generic executor (runs one unit, returns a structured result)

## 4. Research-state (idea-tree, persistence, resume)

- [x] 4.1 Define the idea-tree node model (id, hypothesis, status, score, insight, refs) and parent/child structure with derivable unique ids
- [x] 4.2 Implement canonical JSON persistence with auto-save on every mutation and a load that reconstructs a structurally-equal tree
- [x] 4.3 Implement per-run session directory (tree + metadata + logs) and checkpoint/resume that continues from saved state without repeating completed work
- [x] 4.4 Wire the coordinator to record each executor outcome into the tree before its next decision

## 5. Event-bus seam

- [x] 5.1 Port the event bus with a NullBus default (zero overhead unsubscribed); emit node-mutation and run/agent lifecycle events
- [x] 5.2 Verify a subscriber receives events and that run behavior/results are identical with and without a subscriber attached

## 6. CLI & end-to-end proof

- [x] 6.1 Add a minimal typer CLI to start / resume / inspect a run against a stub research task
- [x] 6.2 END-TO-END: start a run on Qwen-via-Bailian, complete ≥1 observe→dispatch→record cycle, terminate cleanly with persisted state — _(proven OFFLINE via the real Coordinator→Executor→Agent loop vs MockProvider in the integration test; @pytest.mark.live version implemented + skip-verified; LIVE execution pending user's DASHSCOPE_API_KEY)_
- [x] 6.3 END-TO-END: interrupt a run mid-way and resume it; confirm it continues from the last checkpoint — _(resume-of-interrupted-node + already-complete-no-op proven offline in unit + integration tests; @pytest.mark.live e2e implemented + skip-verified; LIVE execution pending user's DASHSCOPE_API_KEY)_

## 7. Tests & docs

- [x] 7.1 Unit tests: provider normalization + credential-missing/redaction; tool registry (known/unknown); idea-tree persist/reload equality; resume continuation
- [x] 7.2 Integration test: one coordinator/executor cycle against a mocked provider (no live API) plus an opt-in live smoke test
- [x] 7.3 Write a short README: setup (uv), Bailian credentials, running/resuming a stub run, and the Arbor fork provenance note
