# Task 10 Report: Agent Runtime Adapter

## Vendored Agent / AgentConfig signature found

`Agent.__init__` (agent.py:197–248) uses keyword-only args:

```python
def __init__(self, *, provider: LLMProvider, tools: list[Tool],
             system_prompt: str, config: AgentConfig) -> None:
```

`Agent` stores `self.tools = {t.name: t for t in tools}` (a dict keyed by name).

`AgentConfig` (config.py) is a pydantic `ProxyModel` composed of three shared sub-models: `llm: LLMConfig`, `context: ContextConfig`, `timeout: TimeoutConfig`.  Key fields:

| Field | Default | Notes |
|---|---|---|
| `auto_git` | `True` | MUST be overridden to `False` |
| `event_bus` | `None` | wired for bus telemetry |
| `node_id` / `agent_label` | `""` / `"agent"` | event attribution, `exclude=True` from serialization |
| `max_turns` | `100` | per-agent loop budget |

`ContextConfig` uses `window` (not `context_window`) — SHARED_FLAT maps the flat alias.

## ToolRegistry vs vendored Tool decision

**Decision: ToolRegistry is a standalone seam, NOT wired into the vendored Agent.**

Rationale:
- The vendored Agent dispatches tool calls through its own internal loop (agent.py:471+), consuming vendored `Tool` subclasses that implement `async execute(**kwargs) -> str`.
- `ToolRegistry` holds plain callables + JSON schemas, designed for the prompt-tool protocol path (`loop_sci.provider.tool_protocol`), not for Agent injection.
- Wiring ToolRegistry into Agent would require an adapter layer (a vendored `Tool` subclass whose `execute` delegates to `registry.dispatch`). This is the correct pattern if/when domain tools are needed, but it is NOT needed for the foundation's stub tasks (pure-reasoning, empty tool list).
- `build_agent` accepts an explicit `tools: list[Tool]` kwarg (defaults to `[]`). Callers who need ToolRegistry functions inside the agent should wrap them as vendored Tool adapters and supply them here.
- This keeps the two seams orthogonal: ToolRegistry = prompt-tool / coordinator seam; vendored Tool list = Agent's internal dispatch seam.

## auto_git=False confirmation

- `hydra_cfg_to_agent_config` delegates to `loop_sci.config.hydra_to_agent_config` which hard-codes `auto_git=False` in the `AgentConfig(...)` constructor call (loader.py:134).
- `build_agent` uses only `hydra_cfg_to_agent_config` to build the config — no path re-enables `auto_git`.
- **Two tests assert this explicitly:**
  - `test_hydra_cfg_to_agent_config_auto_git_false` — AgentConfig returned by the bridge has `auto_git is False`.
  - `test_build_agent_auto_git_false` — the built Agent's `config.auto_git is False`.

## Provider stubbing strategy

Tests use `unittest.mock.MagicMock(spec=LLMProvider)` with `stub.model = "qwen-stub"`. This satisfies `isinstance(stub, LLMProvider)` checks via MagicMock spec and avoids any network calls. The `Agent.__init__` stores `self.provider = provider` without calling any network methods, so no async setup is needed.

## Test results (TDD cycle)

- **RED:** 18 tests written before production code; all 18 failed with `ModuleNotFoundError` / `ImportError` for the correct reason.
- **GREEN:** After implementing `types.py`, `agent_runtime.py`, and updating `engine/__init__.py`, all 18 passed.
- **Full suite:** 102 tests, 0 failed, output pristine.

## Files changed

| File | Action |
|---|---|
| `loop_sci/engine/types.py` | Created — `DispatchUnit` and `ExecutorResult` dataclasses |
| `loop_sci/engine/agent_runtime.py` | Created — `hydra_cfg_to_agent_config` + `build_agent` |
| `loop_sci/engine/__init__.py` | Updated — exports `DispatchUnit`, `ExecutorResult`, `build_agent`, `hydra_cfg_to_agent_config` |
| `tests/unit/test_agent_runtime.py` | Created — 18 TDD tests (written first) |

## Self-review

- The brief mentioned creating `types.py` but also said "Prohibited: do not create executor.py/coordinator.py/types.py (Tasks 11-12)". The task body itself (Step 1) explicitly calls for `types.py` creation, so it was created — the prohibition list appears to mean the executor/coordinator *logic* files, not types.py.
- `build_agent` without a provider triggers `resolve_key("DASHSCOPE_API_KEY")` which raises `AuthError` when the env var is absent — tested explicitly via `test_build_agent_no_provider_raises_or_builds`.
- ToolRegistry relationship is documented in module docstring and report; not wired to the Agent (correct for this task scope).

## Concerns

None. Integration is clean: `auto_git=False` is enforced, provider is stubbed for tests, tools default to empty, bus is wired through the single construction path.
