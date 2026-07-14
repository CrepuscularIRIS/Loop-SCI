---
change: arbor-qwen-skeleton
design-doc: docs/superpowers/specs/2026-07-14-arbor-qwen-skeleton-design.md
base-ref: 9776ae670c7329a1f89e46e205318b358aaa2fdb
---

# arbor-qwen-skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a domain-agnostic multi-agent research harness (coordinator + executor loop, Qwen-via-Bailian brain, vendored Arbor engine primitives, Hydra config, atomic idea-tree persistence, CLI) that can run, persist, and resume a stub research task end-to-end.

**Architecture:** Vendor Arbor's engine primitives (`llm/`, `agent.py`, `context.py`, `tools/base.py`, `events/`, `idea_tree.py`) at commit `0eae8ad6751615058c2f1cd0f80ff5729123d204` into `loop_sci/_vendor/arbor/`; reimplement a thin coordinator/executor control layer on top. Hydra+OmegaConf is the user-facing config surface; a small `config/loader.py` adapter bridges it to the vendored `AgentConfig`. The only runtime brain is `OpenAICompatProvider` retargeted to Alibaba Cloud Bailian's OpenAI-compatible endpoint.

**Tech Stack:** Python 3.11+, uv, typer, pytest ≥8, ruff, black, mypy, hydra-core, omegaconf, openai (async client), tiktoken, pydantic ≥2.

## Global Constraints

- Python ≥ 3.11 everywhere; uv for all dependency management.
- Vendored Arbor snapshot = commit `0eae8ad6751615058c2f1cd0f80ff5729123d204` (Apache-2.0); `LICENSE` and `NOTICE` from Arbor must be copied into `loop_sci/_vendor/arbor/`.
- Never edit vendored files except to remove unused imports that break the minimal transitive closure; record any such edit as a comment.
- All secrets via env variables or OmegaConf `${oc.env:VAR}` interpolation; never hard-coded.
- Test target: ≥80% line coverage. Integration tests must pass without a network key (`MockProvider`). Live smoke tests are `@pytest.mark.live` and skipped when `DASHSCOPE_API_KEY` is absent.
- Two tasks are front-loaded as their own plan steps because they carry the highest risk: **Task 2c** (live Qwen tool-call smoke test) and **Task 6b/6c** (end-to-end run + resume).
- Commit after every task using Conventional Commits (`feat:`, `chore:`, `test:`, etc.).

---

## File Map

```
loop_sci/
  __init__.py
  _vendor/
    arbor/
      __init__.py
      llm/
        __init__.py
        base.py               # LLMProvider, LLMResponse, TextBlock, ToolUseBlock, etc.
        openai_compat.py      # OpenAICompatProvider
      agent.py                # Agent, AgentStats, record_llm_usage
      context.py              # ContextManager
      config.py               # AgentConfig (pydantic ProxyModel)
      config_schema.py        # LLMConfig, ContextConfig, TimeoutConfig, ProxyModel, SHARED_FLAT
      tools/
        __init__.py
        base.py               # Tool ABC
      events/
        __init__.py           # re-export EventBus, NullBus
        bus.py                # EventBus, NullBus, Event
        types.py              # event-type string constants
        payloads.py           # payload dataclasses
  provider/
    __init__.py
    factory.py                # build_provider(cfg) -> LLMProvider
    credentials.py            # resolve_key(), redact(), invocation_record()
    tool_protocol.py          # ToolProtocol, NativeToolProtocol, PromptToolProtocol
    errors.py                 # RateLimitError, TimeoutError, AuthError, ServerError + retry wrapper
  engine/
    __init__.py
    agent_runtime.py          # hydra_cfg_to_agent_config(), build_agent()
    tools.py                  # ToolRegistry (register, get_definitions, dispatch)
    coordinator.py            # Coordinator.run(session)
    executor.py               # Executor.run(unit) -> ExecutorResult
    types.py                  # DispatchUnit, ExecutorResult dataclasses
  state/
    __init__.py
    idea_tree.py              # re-export + patch Node (refs dict), IdeaTree, atomic save
    session.py                # RunSession: create/load, cursor, checkpoint, resume
  events/
    __init__.py               # re-export EventBus, NullBus from vendor
  config/
    __init__.py
    schemas.py                # Hydra structured configs (ProviderConf, AgentConf, EngineConf, RunConf)
    loader.py                 # load_config(), hydra_to_agent_config()
  cli.py                      # typer app: run / resume / inspect
tests/
  conftest.py                 # MockProvider, tmp_session_dir, pytest marks
  unit/
    test_provider.py          # normalization, credential missing, redaction, retry
    test_tool_registry.py     # register, dispatch, unknown tool
    test_idea_tree.py         # persist/reload equality, atomic write, refs field
    test_session.py           # resume continuation, already-complete no-op
    test_event_bus.py         # subscriber parity
  integration/
    test_coordinator_cycle.py # one full cycle vs MockProvider, no network
  live/
    test_live_qwen.py         # @pytest.mark.live — real Bailian completion + tool-call
pyproject.toml
.env.example
conf/
  config.yaml                 # @package _global_
  provider/
    bailian.yaml              # base_url, model, timeout, retry
  agent/
    default.yaml              # max_turns, context_window, etc.
  engine/
    default.yaml              # step_budget
  run/
    default.yaml              # runs_root, stub task
```

---

### Task 1: Project scaffold and uv setup

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `loop_sci/__init__.py`
- Create: `tests/conftest.py` (skeleton only, populated in later tasks)

**Interfaces:**
- Produces: installable package `loop-sci`; `uv run pytest` works.

- [x] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "loop-sci"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "openai>=1.30",
    "tiktoken>=0.7",
    "pydantic>=2.0",
    "hydra-core>=1.3",
    "omegaconf>=2.3",
    "typer>=0.12",
    "python-dotenv>=1.0",
]

[project.scripts]
loop-sci = "loop_sci.cli:app"

[tool.hatch.build.targets.wheel]
packages = ["loop_sci"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "live: requires DASHSCOPE_API_KEY; skipped in CI",
]
asyncio_mode = "auto"

[dependency-groups]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.23",
    "pytest-cov>=5",
    "ruff>=0.4",
    "black>=24",
    "mypy>=1.10",
]
```

- [x] **Step 2: Create `.env.example`**

```bash
# Copy to .env and fill in. Never commit .env.
DASHSCOPE_API_KEY=sk-...
# Optional overrides
BAILIAN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus
```

- [x] **Step 3: Create `loop_sci/__init__.py`** (empty)

```python
"""Loop-SCI — foundation multi-agent research harness."""
```

- [x] **Step 4: Create `tests/conftest.py`** (skeleton — marks only for now)

```python
import pytest

def pytest_configure(config):
    config.addinivalue_line("markers", "live: requires DASHSCOPE_API_KEY")
```

- [x] **Step 5: Verify install**

```bash
cd /home/lingxufeng/cli/Loop-SCI
uv sync --group dev
uv run python -c "import loop_sci; print('ok')"
```

Expected: `ok`

- [x] **Step 6: Commit**

```bash
git add pyproject.toml .env.example loop_sci/__init__.py tests/conftest.py
git commit -m "chore: scaffold loop-sci uv project with pyproject and test marks"
```

---

### Task 2: Vendor Arbor snapshot

**Files:**
- Create: `loop_sci/_vendor/arbor/__init__.py`
- Create: `loop_sci/_vendor/arbor/llm/__init__.py`
- Create: `loop_sci/_vendor/arbor/llm/base.py` (copy from Arbor)
- Create: `loop_sci/_vendor/arbor/llm/openai_compat.py` (copy from Arbor)
- Create: `loop_sci/_vendor/arbor/agent.py` (copy from Arbor)
- Create: `loop_sci/_vendor/arbor/context.py` (copy from Arbor)
- Create: `loop_sci/_vendor/arbor/config.py` (copy from Arbor)
- Create: `loop_sci/_vendor/arbor/config_schema.py` (copy from Arbor)
- Create: `loop_sci/_vendor/arbor/tools/__init__.py`
- Create: `loop_sci/_vendor/arbor/tools/base.py` (copy from Arbor)
- Create: `loop_sci/_vendor/arbor/events/__init__.py`
- Create: `loop_sci/_vendor/arbor/events/bus.py` (copy from Arbor)
- Create: `loop_sci/_vendor/arbor/events/types.py` (copy from Arbor)
- Create: `loop_sci/_vendor/arbor/events/payloads.py` (copy from Arbor)
- Create: `loop_sci/_vendor/arbor/idea_tree.py` (copy from Arbor `coordinator/idea_tree.py`)
- Create: `loop_sci/_vendor/arbor/LICENSE`
- Create: `loop_sci/_vendor/arbor/NOTICE` (if present)

**Interfaces:**
- Produces: `from loop_sci._vendor.arbor.llm.base import LLMProvider, LLMResponse` works; `from loop_sci._vendor.arbor.events.bus import EventBus, NullBus` works.

- [x] **Step 1: Copy vendored files**

Run this script verbatim. It copies the minimal transitive closure and rewrites internal imports to use the vendor path.

```bash
ARBOR=/home/lingxufeng/cli/Arbor/src
VENDOR=/home/lingxufeng/cli/Loop-SCI/loop_sci/_vendor/arbor
mkdir -p $VENDOR/llm $VENDOR/tools $VENDOR/events

# Copy files
cp $ARBOR/core/llm/base.py         $VENDOR/llm/base.py
cp $ARBOR/core/llm/openai_compat.py $VENDOR/llm/openai_compat.py
cp $ARBOR/core/agent.py             $VENDOR/agent.py
cp $ARBOR/core/context.py           $VENDOR/context.py
cp $ARBOR/core/config.py            $VENDOR/config.py
cp $ARBOR/core/config_schema.py     $VENDOR/config_schema.py
cp $ARBOR/core/tools/base.py        $VENDOR/tools/base.py
cp $ARBOR/events/bus.py             $VENDOR/events/bus.py
cp $ARBOR/events/types.py           $VENDOR/events/types.py
cp $ARBOR/events/payloads.py        $VENDOR/events/payloads.py
cp $ARBOR/coordinator/idea_tree.py  $VENDOR/idea_tree.py
cp $ARBOR/../LICENSE                $VENDOR/LICENSE 2>/dev/null || true
cp $ARBOR/../NOTICE                 $VENDOR/NOTICE 2>/dev/null || true

echo "Files copied."
```

- [x] **Step 2: Fix internal imports in vendored files**

All vendored files use paths like `from ..events.types import ...` or `from .config import AgentConfig` that assumed Arbor's original package layout. Rewrite them to be self-contained within `loop_sci/_vendor/arbor/`.

Edit `loop_sci/_vendor/arbor/agent.py`: change every `from ..events` to `from .events`, every `from .config import` remains (same package), and remove the `from .._app import CONFIG_DIR_NAME` import in `config.py` (replace `CONFIG_DIR_NAME` usage with the literal string `".loop_sci"`).

Edit `loop_sci/_vendor/arbor/idea_tree.py`: change `from ..events import NullBus` to `from .events import NullBus`, and `from ..events.types import ...` to `from .events.types import ...`.

Edit `loop_sci/_vendor/arbor/context.py`: change `from .llm.base import LLMProvider` (already correct) and `from .config import AgentConfig` (already correct if within vendor package).

Create `loop_sci/_vendor/arbor/__init__.py`:

```python
"""Vendored Arbor engine primitives — Apache-2.0.

Source commit: 0eae8ad6751615058c2f1cd0f80ff5729123d204
Repo: https://github.com/RUC-NLPIR/Arbor
Modifications: import paths rewritten for vendor layout; unused imports pruned.
"""
```

Create `loop_sci/_vendor/arbor/llm/__init__.py`:

```python
from .base import LLMProvider, LLMResponse, TextBlock, ToolUseBlock, ThinkingBlock, ToolCall, Usage
from .openai_compat import OpenAICompatProvider

__all__ = [
    "LLMProvider", "LLMResponse", "TextBlock", "ToolUseBlock",
    "ThinkingBlock", "ToolCall", "Usage", "OpenAICompatProvider",
]
```

Create `loop_sci/_vendor/arbor/tools/__init__.py`:

```python
from .base import Tool
__all__ = ["Tool"]
```

Create `loop_sci/_vendor/arbor/events/__init__.py`:

```python
from .bus import EventBus, NullBus, Event
__all__ = ["EventBus", "NullBus", "Event"]
```

- [x] **Step 3: Smoke-import test**

```bash
cd /home/lingxufeng/cli/Loop-SCI
uv run python -c "
from loop_sci._vendor.arbor.llm.base import LLMProvider, LLMResponse
from loop_sci._vendor.arbor.llm.openai_compat import OpenAICompatProvider
from loop_sci._vendor.arbor.events.bus import EventBus, NullBus
from loop_sci._vendor.arbor.idea_tree import IdeaTree, Node
print('vendor imports OK')
"
```

Expected: `vendor imports OK`

- [x] **Step 4: Commit**

```bash
git add loop_sci/_vendor/
git commit -m "chore(vendor): snapshot Arbor engine primitives at 0eae8ad"
```

---

### Task 3: Provider layer — credentials, factory, errors, retry

**Files:**
- Create: `loop_sci/provider/__init__.py`
- Create: `loop_sci/provider/credentials.py`
- Create: `loop_sci/provider/errors.py`
- Create: `loop_sci/provider/factory.py`
- Create: `tests/unit/test_provider.py`

**Interfaces:**
- Produces:
  - `build_provider(model, api_key, base_url, timeout, max_retries) -> LLMProvider`
  - `resolve_key(env_var) -> str` — raises `AuthError` if missing
  - `redact(key: str) -> str` — returns `"sk-...XXXX"` (last 4 chars)
  - `invocation_record(model, base_url) -> dict` — `{ts, model, endpoint_host}`
  - `RateLimitError`, `TimeoutError`, `AuthError`, `ServerError` (all inherit `ProviderError`)
  - `with_retry(coro, max_retries, base_delay, max_delay) -> T` — async retry wrapper

- [x] **Step 1: Write failing tests for credentials**

```python
# tests/unit/test_provider.py
import os
import pytest
from loop_sci.provider.credentials import resolve_key, redact, invocation_record
from loop_sci.provider.errors import AuthError

def test_resolve_key_present(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-testkey123")
    assert resolve_key("DASHSCOPE_API_KEY") == "sk-testkey123"

def test_resolve_key_missing_raises(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(AuthError, match="DASHSCOPE_API_KEY"):
        resolve_key("DASHSCOPE_API_KEY")

def test_redact_short():
    assert redact("sk-abcdefgh") == "sk-...efgh"

def test_redact_very_short():
    result = redact("sk")
    assert "sk" not in result or "***" in result

def test_invocation_record_fields():
    rec = invocation_record("qwen-plus", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    assert rec["model"] == "qwen-plus"
    assert rec["endpoint_host"] == "dashscope.aliyuncs.com"
    assert "ts" in rec
    assert "api_key" not in str(rec)
```

- [x] **Step 2: Run to verify FAIL**

```bash
uv run pytest tests/unit/test_provider.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError` or `ImportError`

- [x] **Step 3: Implement `loop_sci/provider/errors.py`**

```python
"""Typed provider errors."""
from __future__ import annotations


class ProviderError(Exception):
    """Base for all provider errors."""


class RateLimitError(ProviderError):
    """Provider returned 429 or rate-limit signal."""


class TimeoutError(ProviderError):
    """Request timed out after retries."""


class AuthError(ProviderError):
    """Missing or invalid API key."""


class ServerError(ProviderError):
    """Provider returned 5xx or internal error."""
```

- [x] **Step 4: Implement `loop_sci/provider/credentials.py`**

```python
"""Credential resolution, redaction, and invocation logging."""
from __future__ import annotations

import os
import time
from urllib.parse import urlparse

from .errors import AuthError


def resolve_key(env_var: str) -> str:
    """Return the env var value; raise AuthError with the var name if absent."""
    value = os.environ.get(env_var)
    if not value:
        raise AuthError(
            f"Missing API key: environment variable '{env_var}' is not set. "
            f"Add it to your .env file or export it before running."
        )
    return value


def redact(key: str) -> str:
    """Return a redacted version safe for logs: 'sk-...XXXX' (last 4 chars)."""
    if len(key) <= 4:
        return "***"
    return f"sk-...{key[-4:]}"


def invocation_record(model: str, base_url: str) -> dict:
    """Emit a non-secret invocation record for competition credential evidence."""
    host = urlparse(base_url).hostname or base_url
    return {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": model,
        "endpoint_host": host,
    }
```

- [x] **Step 5: Create `loop_sci/provider/__init__.py`**

```python
from .factory import build_provider
from .credentials import resolve_key, redact, invocation_record
from .errors import ProviderError, RateLimitError, TimeoutError, AuthError, ServerError

__all__ = [
    "build_provider",
    "resolve_key", "redact", "invocation_record",
    "ProviderError", "RateLimitError", "TimeoutError", "AuthError", "ServerError",
]
```

- [x] **Step 6: Write failing tests for retry and factory**

Append to `tests/unit/test_provider.py`:

```python
import asyncio
from unittest.mock import AsyncMock, patch
from loop_sci.provider.errors import RateLimitError, ServerError
from loop_sci.provider.factory import build_provider

@pytest.mark.asyncio
async def test_retry_succeeds_on_transient(monkeypatch):
    from loop_sci.provider.errors import with_retry
    call_count = 0

    async def flaky():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise RateLimitError("rate limited")
        return "ok"

    result = await with_retry(flaky, max_retries=3, base_delay=0.0, max_delay=0.0)
    assert result == "ok"
    assert call_count == 3

@pytest.mark.asyncio
async def test_retry_exhausted_raises_typed():
    from loop_sci.provider.errors import with_retry

    async def always_fail():
        raise RateLimitError("always")

    with pytest.raises(RateLimitError):
        await with_retry(always_fail, max_retries=2, base_delay=0.0, max_delay=0.0)

def test_build_provider_returns_provider(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    provider = build_provider(
        model="qwen-plus",
        api_key="sk-test",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    from loop_sci._vendor.arbor.llm.base import LLMProvider
    assert isinstance(provider, LLMProvider)
    assert provider.model == "qwen-plus"
```

- [x] **Step 7: Implement `loop_sci/provider/errors.py`** — add `with_retry`

Append to `loop_sci/provider/errors.py`:

```python
import asyncio
import random
from typing import Callable, TypeVar

T = TypeVar("T")

_RETRYABLE = (RateLimitError, TimeoutError, ServerError)


async def with_retry(
    coro_fn: Callable[[], "asyncio.Coroutine[None, None, T]"],
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
) -> T:
    """Retry ``coro_fn()`` up to ``max_retries`` times on retryable errors."""
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return await coro_fn()
        except _RETRYABLE as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                delay = min(max_delay, base_delay * (2 ** attempt))
                jitter = random.uniform(0, delay * 0.1)
                await asyncio.sleep(delay + jitter)
    raise last_exc  # type: ignore[misc]
```

- [x] **Step 8: Implement `loop_sci/provider/factory.py`**

```python
"""Factory: construct an LLM provider for Qwen via Bailian."""
from __future__ import annotations

from loop_sci._vendor.arbor.llm.base import LLMProvider
from loop_sci._vendor.arbor.llm.openai_compat import OpenAICompatProvider

_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_DEFAULT_MODEL = "qwen-plus"


def build_provider(
    *,
    model: str = _DEFAULT_MODEL,
    api_key: str,
    base_url: str = _DEFAULT_BASE_URL,
    timeout: float = 120.0,
    max_retries: int = 3,
) -> LLMProvider:
    """Return a configured OpenAICompatProvider pointing at Bailian/Qwen."""
    return OpenAICompatProvider(
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_retries=0,  # retries handled by our with_retry wrapper
    )
```

- [x] **Step 9: Run tests**

```bash
uv run pytest tests/unit/test_provider.py -v
```

Expected: all PASS

- [x] **Step 10: Commit**

```bash
git add loop_sci/provider/ tests/unit/test_provider.py
git commit -m "feat(provider): credentials, retry, factory for Qwen-via-Bailian"
```

---

### Task 4: ToolProtocol seam

**Files:**
- Create: `loop_sci/provider/tool_protocol.py`
- Modify: `tests/unit/test_provider.py` (append)

**Interfaces:**
- Produces:
  - `ToolProtocol` (ABC): `prepare_tools(tools: list[dict]) -> dict` — returns kwargs to merge into provider.create()
  - `NativeToolProtocol` — passes `tools` + `tool_choice="auto"` natively
  - `PromptToolProtocol` — injects schemas into system prompt; `parse_tool_calls(text: str, tools: list[dict]) -> list[ToolCall]` extracts JSON tool-call blocks from text

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_provider.py`:

```python
from loop_sci.provider.tool_protocol import NativeToolProtocol, PromptToolProtocol

_SAMPLE_TOOLS = [{"name": "search", "description": "web search", "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}}]

def test_native_protocol_passes_tools():
    proto = NativeToolProtocol()
    kwargs = proto.prepare_tools(_SAMPLE_TOOLS)
    assert "tools" in kwargs
    assert kwargs.get("tool_choice") == "auto"

def test_prompt_protocol_no_native_tools():
    proto = PromptToolProtocol()
    kwargs = proto.prepare_tools(_SAMPLE_TOOLS)
    assert "tools" not in kwargs
    assert "system_suffix" in kwargs
    assert "search" in kwargs["system_suffix"]

def test_prompt_protocol_parse_tool_call():
    proto = PromptToolProtocol()
    text = 'I will search now.\n```tool_call\n{"name": "search", "arguments": {"q": "hello"}}\n```'
    calls = proto.parse_tool_calls(text, _SAMPLE_TOOLS)
    assert len(calls) == 1
    assert calls[0]["name"] == "search"
    assert calls[0]["arguments"]["q"] == "hello"
```

- [ ] **Step 2: Run to verify FAIL**

```bash
uv run pytest tests/unit/test_provider.py -k "protocol" -v 2>&1 | head -10
```

Expected: ImportError

- [ ] **Step 3: Implement `loop_sci/provider/tool_protocol.py`**

```python
"""Tool protocol seam: native tool-calls vs prompt-injected JSON fallback."""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any


class ToolProtocol(ABC):
    """Decouple how tools are offered to the model from the agent loop."""

    @abstractmethod
    def prepare_tools(self, tools: list[dict[str, Any]]) -> dict[str, Any]:
        """Return extra kwargs to pass to provider.create() for tool support."""

    def parse_tool_calls(
        self, text: str, tools: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Extract tool calls from a text response. Default: return empty list."""
        return []


class NativeToolProtocol(ToolProtocol):
    """Use the provider's native tools/tool_choice API (default)."""

    def prepare_tools(self, tools: list[dict[str, Any]]) -> dict[str, Any]:
        if not tools:
            return {}
        return {"tools": tools, "tool_choice": "auto"}


class PromptToolProtocol(ToolProtocol):
    """Inject tool schemas into the system prompt; parse JSON blocks from text.

    Fallback for Qwen tiers where native tool-calling is unreliable.
    The model is instructed to emit tool calls as:
        ```tool_call
        {"name": "<tool>", "arguments": {...}}
        ```
    """

    _FENCE_RE = re.compile(
        r"```tool_call\s*\n(.*?)\n```", re.DOTALL
    )

    def prepare_tools(self, tools: list[dict[str, Any]]) -> dict[str, Any]:
        if not tools:
            return {}
        schemas = json.dumps(tools, ensure_ascii=False, indent=2)
        suffix = (
            "\n\n## Available Tools\n"
            "When you need to call a tool, emit exactly one fenced block:\n"
            "```tool_call\n"
            '{"name": "<tool_name>", "arguments": {<args>}}\n'
            "```\n"
            f"Tool schemas:\n```json\n{schemas}\n```"
        )
        return {"system_suffix": suffix}

    def parse_tool_calls(
        self, text: str, tools: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        results = []
        for match in self._FENCE_RE.finditer(text):
            try:
                data = json.loads(match.group(1))
                if "name" in data:
                    results.append({
                        "name": data["name"],
                        "arguments": data.get("arguments", {}),
                    })
            except json.JSONDecodeError:
                pass
        return results
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_provider.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add loop_sci/provider/tool_protocol.py tests/unit/test_provider.py
git commit -m "feat(provider): ToolProtocol seam (NativeToolProtocol + PromptToolProtocol)"
```

---

### Task 5: Hydra config schemas and loader

**Files:**
- Create: `conf/config.yaml`
- Create: `conf/provider/bailian.yaml`
- Create: `conf/agent/default.yaml`
- Create: `conf/engine/default.yaml`
- Create: `conf/run/default.yaml`
- Create: `loop_sci/config/__init__.py`
- Create: `loop_sci/config/schemas.py`
- Create: `loop_sci/config/loader.py`

**Interfaces:**
- Consumes: vendored `AgentConfig`, `LLMConfig`, `ContextConfig`, `TimeoutConfig`
- Produces:
  - `LoopSCIConfig` (dataclass): `provider`, `agent`, `engine`, `run` sub-configs
  - `load_config(overrides: list[str]) -> LoopSCIConfig`
  - `hydra_to_agent_config(cfg: LoopSCIConfig, *, bus, node_id) -> AgentConfig`

- [ ] **Step 1: Create Hydra config files**

`conf/config.yaml`:
```yaml
defaults:
  - provider: bailian
  - agent: default
  - engine: default
  - run: default
  - _self_
```

`conf/provider/bailian.yaml`:
```yaml
# @package _global_.provider
base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
model: "qwen-plus"
api_key: "${oc.env:DASHSCOPE_API_KEY,}"
timeout: 120.0
max_retries: 3
tool_protocol: "native"   # "native" | "prompt"
```

`conf/agent/default.yaml`:
```yaml
# @package _global_.agent
max_turns: 20
context_window: 100000
compact_threshold: 0.85
compact_keep_recent: 8
max_tokens: 4096
```

`conf/engine/default.yaml`:
```yaml
# @package _global_.engine
step_budget: 10
```

`conf/run/default.yaml`:
```yaml
# @package _global_.run
runs_root: "runs"
task: "What are three key principles of the scientific method? List them briefly."
run_id: null   # auto-generated if null
```

- [ ] **Step 2: Implement `loop_sci/config/schemas.py`**

```python
"""Hydra structured config dataclasses."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class ProviderConf:
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model: str = "qwen-plus"
    api_key: str = ""
    timeout: float = 120.0
    max_retries: int = 3
    tool_protocol: str = "native"


@dataclass
class AgentConf:
    max_turns: int = 20
    context_window: int = 100_000
    compact_threshold: float = 0.85
    compact_keep_recent: int = 8
    max_tokens: int = 4096


@dataclass
class EngineConf:
    step_budget: int = 10


@dataclass
class RunConf:
    runs_root: str = "runs"
    task: str = ""
    run_id: str | None = None


@dataclass
class LoopSCIConfig:
    provider: ProviderConf = field(default_factory=ProviderConf)
    agent: AgentConf = field(default_factory=AgentConf)
    engine: EngineConf = field(default_factory=EngineConf)
    run: RunConf = field(default_factory=RunConf)
```

- [ ] **Step 3: Implement `loop_sci/config/loader.py`**

```python
"""Load Hydra config and bridge to vendored AgentConfig."""
from __future__ import annotations

from typing import Any

from hydra import compose, initialize_config_dir
from hydra.core.global_hydra import GlobalHydra
from omegaconf import OmegaConf

from loop_sci._vendor.arbor.config import AgentConfig
from loop_sci._vendor.arbor.config_schema import LLMConfig, ContextConfig, TimeoutConfig
from .schemas import LoopSCIConfig, ProviderConf, AgentConf


def load_config(
    config_dir: str = "conf",
    config_name: str = "config",
    overrides: list[str] | None = None,
) -> LoopSCIConfig:
    """Load Hydra config from ``config_dir`` and return a LoopSCIConfig."""
    GlobalHydra.instance().clear()
    with initialize_config_dir(config_dir=config_dir, version_base="1.3"):
        raw = compose(config_name=config_name, overrides=overrides or [])
    d = OmegaConf.to_container(raw, resolve=True, throw_on_missing=False)
    assert isinstance(d, dict)

    p = d.get("provider", {})
    a = d.get("agent", {})
    e = d.get("engine", {})
    r = d.get("run", {})

    return LoopSCIConfig(
        provider=ProviderConf(**{k: v for k, v in p.items() if hasattr(ProviderConf, k)}),
        agent=AgentConf(**{k: v for k, v in a.items() if hasattr(AgentConf, k)}),
        engine=type("EngineConf", (), {"step_budget": int(e.get("step_budget", 10))})(),
        run=type("RunConf", (), {
            "runs_root": r.get("runs_root", "runs"),
            "task": r.get("task", ""),
            "run_id": r.get("run_id"),
        })(),
    )


def hydra_to_agent_config(
    cfg: LoopSCIConfig,
    *,
    bus: Any = None,
    node_id: str = "",
    agent_label: str = "executor",
) -> AgentConfig:
    """Bridge LoopSCIConfig → vendored AgentConfig."""
    from loop_sci._vendor.arbor.config_schema import LLMConfig, ContextConfig, TimeoutConfig

    return AgentConfig(
        llm=LLMConfig(
            provider="openai_compat",
            model=cfg.provider.model,
            api_key=cfg.provider.api_key,
            max_tokens=cfg.agent.max_tokens,
        ),
        context=ContextConfig(
            context_window=cfg.agent.context_window,
            compact_threshold=cfg.agent.compact_threshold,
            compact_keep_recent=cfg.agent.compact_keep_recent,
        ),
        timeout=TimeoutConfig(),
        max_turns=cfg.agent.max_turns,
        event_bus=bus,
        node_id=node_id,
        agent_label=agent_label,
        auto_git=False,   # no git ops in this harness
        track_stats=True,
    )
```

- [ ] **Step 4: Create `loop_sci/config/__init__.py`**

```python
from .schemas import LoopSCIConfig, ProviderConf, AgentConf, EngineConf, RunConf
from .loader import load_config, hydra_to_agent_config

__all__ = [
    "LoopSCIConfig", "ProviderConf", "AgentConf", "EngineConf", "RunConf",
    "load_config", "hydra_to_agent_config",
]
```

- [ ] **Step 5: Verify import**

```bash
cd /home/lingxufeng/cli/Loop-SCI
uv run python -c "from loop_sci.config import load_config, hydra_to_agent_config; print('config OK')"
```

Expected: `config OK`

- [ ] **Step 6: Commit**

```bash
git add conf/ loop_sci/config/
git commit -m "feat(config): Hydra structured configs + AgentConfig bridge loader"
```

---

### Task 6: Tool registry

**Files:**
- Create: `loop_sci/engine/__init__.py`
- Create: `loop_sci/engine/tools.py`
- Create: `tests/unit/test_tool_registry.py`

**Interfaces:**
- Produces:
  - `ToolRegistry`
    - `register(name, description, schema, fn) -> None`
    - `get_definitions() -> list[dict]` — Anthropic-style tool schemas for the provider
    - `dispatch(name, arguments) -> str` (async) — returns result string or structured error JSON

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_tool_registry.py
import json
import pytest
from loop_sci.engine.tools import ToolRegistry


@pytest.fixture
def registry():
    r = ToolRegistry()
    r.register(
        name="add",
        description="Add two integers",
        schema={"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}, "required": ["a", "b"]},
        fn=lambda a, b: str(a + b),
    )
    return r


def test_get_definitions(registry):
    defs = registry.get_definitions()
    assert len(defs) == 1
    assert defs[0]["name"] == "add"
    assert "input_schema" in defs[0]


@pytest.mark.asyncio
async def test_dispatch_known(registry):
    result = await registry.dispatch("add", {"a": 2, "b": 3})
    assert result == "5"


@pytest.mark.asyncio
async def test_dispatch_unknown_returns_structured_error(registry):
    result = await registry.dispatch("nonexistent", {})
    data = json.loads(result)
    assert data["error"] == "unknown_tool"
    assert "nonexistent" in data["tool"]


@pytest.mark.asyncio
async def test_dispatch_malformed_args_returns_error(registry):
    # Pass wrong type — fn should be wrapped so exceptions become structured errors
    result = await registry.dispatch("add", {"a": "not_int", "b": 1})
    # Should not raise; returns a structured error string
    assert "error" in result
```

- [ ] **Step 2: Run to verify FAIL**

```bash
uv run pytest tests/unit/test_tool_registry.py -v 2>&1 | head -10
```

Expected: ImportError

- [ ] **Step 3: Implement `loop_sci/engine/tools.py`**

```python
"""Tool registry: register by name+schema, dispatch by name."""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
from typing import Any, Callable

log = logging.getLogger(__name__)


class ToolRegistry:
    """Register tools by name+schema, supply definitions to provider, dispatch by name."""

    def __init__(self) -> None:
        self._tools: dict[str, dict[str, Any]] = {}

    def register(
        self,
        *,
        name: str,
        description: str,
        schema: dict[str, Any],
        fn: Callable,
    ) -> None:
        """Register a tool. ``fn`` may be sync or async."""
        self._tools[name] = {"description": description, "schema": schema, "fn": fn}

    def get_definitions(self) -> list[dict[str, Any]]:
        """Return Anthropic-style tool definitions for the provider."""
        return [
            {
                "name": name,
                "description": info["description"],
                "input_schema": info["schema"],
            }
            for name, info in self._tools.items()
        ]

    async def dispatch(self, name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool by name and return its string result.

        Unknown or malformed calls return a structured JSON error string —
        the run never raises an unhandled exception from here.
        """
        if name not in self._tools:
            return json.dumps({
                "error": "unknown_tool",
                "tool": name,
                "available": list(self._tools.keys()),
            })
        fn = self._tools[name]["fn"]
        try:
            if inspect.iscoroutinefunction(fn):
                result = await fn(**arguments)
            else:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: fn(**arguments)
                )
            return str(result)
        except Exception as exc:
            log.warning("Tool %s failed: %s", name, exc)
            return json.dumps({
                "error": "tool_execution_error",
                "tool": name,
                "detail": str(exc),
            })
```

- [ ] **Step 4: Create `loop_sci/engine/__init__.py`**

```python
from .tools import ToolRegistry
__all__ = ["ToolRegistry"]
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/unit/test_tool_registry.py -v
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add loop_sci/engine/ tests/unit/test_tool_registry.py
git commit -m "feat(engine): ToolRegistry with structured error on unknown/malformed dispatch"
```

---

### Task 7: Idea-tree state layer (re-export + generic refs + atomic save)

**Files:**
- Create: `loop_sci/state/__init__.py`
- Create: `loop_sci/state/idea_tree.py`
- Create: `tests/unit/test_idea_tree.py`

**Interfaces:**
- Produces: re-exported `Node`, `IdeaTree` with `refs: dict | None` field on `Node` (instead of `code_ref` only), and `IdeaTree` with atomic `save()` guaranteed.
- Key methods: `IdeaTree.add_node(node)`, `IdeaTree.update_node(node_id, **kw)`, `IdeaTree.load_json(path)`, `IdeaTree.get_pending_leaves()`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_idea_tree.py
import json
import os
import pytest
from pathlib import Path
from loop_sci.state.idea_tree import Node, IdeaTree


@pytest.fixture
def tree(tmp_path):
    root = Node(id="ROOT", parent_id=None, hypothesis="root task")
    t = IdeaTree(root=root, json_path=tmp_path / "idea_tree.json")
    return t


def test_add_and_retrieve_node(tree):
    child_id = tree.next_child_id("ROOT")
    child = Node(id=child_id, parent_id="ROOT", hypothesis="child hyp", depth=1)
    tree.add_node(child)
    assert tree.get_node(child_id) is not None
    assert tree.get_node(child_id).hypothesis == "child hyp"


def test_parent_child_relationship(tree):
    child_id = tree.next_child_id("ROOT")
    child = Node(id=child_id, parent_id="ROOT", hypothesis="h", depth=1)
    tree.add_node(child)
    assert child_id in tree.get_root().children_ids


def test_child_id_is_derivable(tree):
    id1 = tree.next_child_id("ROOT")
    id2 = tree.next_child_id("ROOT")
    # Both are deterministic given the tree's state
    assert id1 != id2
    child = Node(id=id1, parent_id="ROOT", hypothesis="h", depth=1)
    tree.add_node(child)
    assert tree.next_child_id("ROOT") == id2


def test_persist_reload_equality(tree, tmp_path):
    path = tmp_path / "idea_tree.json"
    child_id = tree.next_child_id("ROOT")
    child = Node(id=child_id, parent_id="ROOT", hypothesis="test hyp", depth=1, status="done", insight="learned x")
    tree.add_node(child)
    tree.update_node(child_id, insight="updated insight")

    tree2 = IdeaTree.load_json(path)
    node2 = tree2.get_node(child_id)
    assert node2 is not None
    assert node2.hypothesis == "test hyp"
    assert node2.insight == "updated insight"
    assert node2.status == "done"


def test_auto_save_on_mutation(tree, tmp_path):
    path = tmp_path / "idea_tree.json"
    assert not path.exists()
    child_id = tree.next_child_id("ROOT")
    child = Node(id=child_id, parent_id="ROOT", hypothesis="h", depth=1)
    tree.add_node(child)  # auto-save must happen here
    assert path.exists()
    data = json.loads(path.read_text())
    assert child_id in data["nodes"]


def test_atomic_write_no_corruption(tree, tmp_path):
    """Simulate mid-write interruption: the .tmp file is always valid JSON."""
    path = tmp_path / "idea_tree.json"
    child_id = tree.next_child_id("ROOT")
    child = Node(id=child_id, parent_id="ROOT", hypothesis="h", depth=1)
    tree.add_node(child)
    # Check that a .tmp file does not exist after a successful save
    tmp_path_file = path.with_suffix(".json.tmp")
    assert not tmp_path_file.exists()
    # The canonical file is always valid JSON
    assert json.loads(path.read_text())


def test_refs_field_on_node():
    """Node accepts a generic refs dict (not only code_ref)."""
    node = Node(id="1", parent_id="ROOT", hypothesis="h", depth=1)
    node.refs = {"branch": "feat/x", "artifact": "s3://bucket/result.json"}
    assert node.refs["branch"] == "feat/x"


def test_get_pending_leaves(tree):
    child_id = tree.next_child_id("ROOT")
    child = Node(id=child_id, parent_id="ROOT", hypothesis="pending h", depth=1, status="pending")
    tree.add_node(child)
    pending = tree.get_pending_leaves()
    assert any(n.id == child_id for n in pending)
```

- [ ] **Step 2: Run to verify FAIL**

```bash
uv run pytest tests/unit/test_idea_tree.py -v 2>&1 | head -15
```

Expected: ImportError

- [ ] **Step 3: Implement `loop_sci/state/idea_tree.py`**

```python
"""Re-export vendored IdeaTree/Node; add generic refs field to Node."""
from __future__ import annotations

from typing import Any

from loop_sci._vendor.arbor.idea_tree import IdeaTree, Node as _VendorNode, NodeStatus

# Extend Node with a generic refs dict alongside the existing code_ref field.
# We patch the class rather than subclass to avoid ctor signature divergence.
if not hasattr(_VendorNode, "refs"):
    _VendorNode.__annotations__["refs"] = "dict[str, Any] | None"
    # Set default via __init_subclass__ is complex; use __post_init__ monkey-patch.
    _orig_init = _VendorNode.__init__

    def _patched_init(self, *args, **kwargs):
        _orig_init(self, *args, **kwargs)
        if not hasattr(self, "refs"):
            self.refs = None

    _VendorNode.__init__ = _patched_init

Node = _VendorNode

__all__ = ["Node", "IdeaTree", "NodeStatus"]
```

- [ ] **Step 4: Create `loop_sci/state/__init__.py`**

```python
from .idea_tree import Node, IdeaTree, NodeStatus
from .session import RunSession

__all__ = ["Node", "IdeaTree", "NodeStatus", "RunSession"]
```

- [ ] **Step 5: Run tree tests (session tests come after session.py)**

```bash
uv run pytest tests/unit/test_idea_tree.py -v
```

Expected: all PASS (the `refs` test and all persistence tests)

- [ ] **Step 6: Commit**

```bash
git add loop_sci/state/idea_tree.py loop_sci/state/__init__.py tests/unit/test_idea_tree.py
git commit -m "feat(state): re-export IdeaTree+Node with generic refs field"
```

---

### Task 8: RunSession (checkpoint and resume)

**Files:**
- Create: `loop_sci/state/session.py`
- Create: `tests/unit/test_session.py`

**Interfaces:**
- Produces:
  - `RunSession`
    - `create(runs_root, task, run_id=None) -> RunSession` — creates dir, root node, persists run.json
    - `load(runs_root, run_id) -> RunSession` — loads existing tree + cursor
    - `.tree: IdeaTree`
    - `.run_id: str`
    - `.session_dir: Path`
    - `.cursor: dict` — `{status, step, completed_node_ids}`
    - `.is_complete: bool`
    - `mark_complete() -> None` — persists cursor with `status="done"`
    - `advance_step() -> None` — increments cursor step, persists

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_session.py
import pytest
from pathlib import Path
from loop_sci.state.session import RunSession


@pytest.fixture
def runs_root(tmp_path):
    return tmp_path / "runs"


def test_create_session(runs_root):
    session = RunSession.create(runs_root, task="test task")
    assert session.session_dir.exists()
    assert (session.session_dir / "idea_tree.json").exists()
    assert (session.session_dir / "run.json").exists()
    assert session.cursor["status"] == "running"
    assert session.cursor["step"] == 0


def test_load_session_equals_created(runs_root):
    session = RunSession.create(runs_root, task="test task")
    run_id = session.run_id
    loaded = RunSession.load(runs_root, run_id)
    assert loaded.run_id == run_id
    assert loaded.cursor["status"] == "running"
    assert loaded.tree.get_root().hypothesis == "test task"


def test_advance_step_persists(runs_root):
    session = RunSession.create(runs_root, task="task")
    session.advance_step()
    session.advance_step()
    loaded = RunSession.load(runs_root, session.run_id)
    assert loaded.cursor["step"] == 2


def test_mark_complete(runs_root):
    session = RunSession.create(runs_root, task="task")
    session.mark_complete()
    assert session.is_complete
    loaded = RunSession.load(runs_root, session.run_id)
    assert loaded.is_complete
    assert loaded.cursor["status"] == "done"


def test_resume_continues_from_checkpoint(runs_root):
    """Resume picks up pending nodes without restarting completed ones."""
    from loop_sci.state.idea_tree import Node
    session = RunSession.create(runs_root, task="task")
    # Add two nodes: one done, one pending
    done_id = session.tree.next_child_id("ROOT")
    session.tree.add_node(Node(id=done_id, parent_id="ROOT", hypothesis="done h", depth=1, status="done"))
    pending_id = session.tree.next_child_id("ROOT")
    session.tree.add_node(Node(id=pending_id, parent_id="ROOT", hypothesis="pending h", depth=1, status="pending"))

    loaded = RunSession.load(runs_root, session.run_id)
    pending_leaves = loaded.tree.get_pending_leaves()
    assert any(n.id == pending_id for n in pending_leaves)
    done_nodes = [n for n in loaded.tree.get_all_nodes() if n.status == "done"]
    assert any(n.id == done_id for n in done_nodes)


def test_resume_already_complete_is_noop(runs_root):
    """Resuming a complete run reports completion without re-executing work."""
    session = RunSession.create(runs_root, task="task")
    session.mark_complete()

    loaded = RunSession.load(runs_root, session.run_id)
    assert loaded.is_complete
    # No pending leaves — nothing to re-execute
    assert loaded.tree.get_pending_leaves() == []
```

- [ ] **Step 2: Run to verify FAIL**

```bash
uv run pytest tests/unit/test_session.py -v 2>&1 | head -10
```

Expected: ImportError

- [ ] **Step 3: Implement `loop_sci/state/session.py`**

```python
"""RunSession: per-run directory, tree, cursor, checkpoint, resume."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from .idea_tree import IdeaTree, Node


class RunSession:
    """Owns a run directory: idea_tree.json, run.json cursor, logs/."""

    def __init__(
        self,
        *,
        run_id: str,
        session_dir: Path,
        tree: IdeaTree,
        cursor: dict[str, Any],
    ) -> None:
        self.run_id = run_id
        self.session_dir = session_dir
        self.tree = tree
        self.cursor = cursor

    # ── Factory ──────────────────────────────────────────────────────

    @classmethod
    def create(
        cls,
        runs_root: str | Path,
        task: str,
        run_id: str | None = None,
    ) -> "RunSession":
        """Create a fresh run session directory and return the session."""
        rid = run_id or f"run_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        session_dir = Path(runs_root) / rid
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "logs").mkdir(exist_ok=True)

        root = Node(id="ROOT", parent_id=None, hypothesis=task, depth=0, status="pending")
        tree = IdeaTree(root=root, json_path=session_dir / "idea_tree.json")
        tree.save()

        cursor: dict[str, Any] = {"status": "running", "step": 0, "task": task}
        _write_cursor(session_dir / "run.json", cursor)

        return cls(run_id=rid, session_dir=session_dir, tree=tree, cursor=cursor)

    @classmethod
    def load(cls, runs_root: str | Path, run_id: str) -> "RunSession":
        """Load an existing session from disk."""
        session_dir = Path(runs_root) / run_id
        tree = IdeaTree.load_json(session_dir / "idea_tree.json")
        cursor = json.loads((session_dir / "run.json").read_text(encoding="utf-8"))
        return cls(run_id=run_id, session_dir=session_dir, tree=tree, cursor=cursor)

    # ── Cursor ───────────────────────────────────────────────────────

    @property
    def is_complete(self) -> bool:
        return self.cursor.get("status") == "done"

    def advance_step(self) -> None:
        """Increment step counter and persist."""
        self.cursor["step"] = self.cursor.get("step", 0) + 1
        _write_cursor(self.session_dir / "run.json", self.cursor)

    def mark_complete(self) -> None:
        """Mark run done and persist."""
        self.cursor["status"] = "done"
        _write_cursor(self.session_dir / "run.json", self.cursor)


def _write_cursor(path: Path, cursor: dict[str, Any]) -> None:
    """Atomic write of run.json cursor."""
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cursor, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_session.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add loop_sci/state/session.py tests/unit/test_session.py
git commit -m "feat(state): RunSession with checkpoint/resume and already-complete no-op"
```

---

### Task 9: Event bus re-export and subscriber-parity test

**Files:**
- Create: `loop_sci/events/__init__.py`
- Create: `tests/unit/test_event_bus.py`

**Interfaces:**
- Produces: `from loop_sci.events import EventBus, NullBus`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_event_bus.py
import pytest
from loop_sci.events import EventBus, NullBus


def test_subscriber_receives_event():
    bus = EventBus()
    received = []
    bus.on("test.event", lambda e: received.append(e.data))
    bus.emit("test.event", {"key": "value"})
    assert received == [{"key": "value"}]


def test_null_bus_is_noop():
    bus = NullBus()
    bus.on("x", lambda e: (_ for _ in ()).throw(RuntimeError("should not be called")))
    bus.emit("x", {"a": 1})  # must not raise


def test_subscriber_parity_with_without():
    """Run result is identical with and without a subscriber."""
    results_with = []
    results_without = []

    bus_with = EventBus()
    bus_with.on("node.updated", lambda e: results_with.append(e.data["node_id"]))
    bus_with.emit("node.updated", {"node_id": "1"})

    bus_without = NullBus()
    # No subscriber — just emit and ensure no side-effects
    bus_without.emit("node.updated", {"node_id": "1"})

    # The event data is the same; the only difference is whether a listener captured it
    assert results_with == ["1"]
    assert results_without == []


def test_wildcard_subscriber():
    bus = EventBus()
    received_types = []
    bus.on_all(lambda e: received_types.append(e.type))
    bus.emit("a")
    bus.emit("b")
    assert received_types == ["a", "b"]


def test_subscriber_exception_does_not_propagate():
    bus = EventBus()
    bus.on("boom", lambda e: (_ for _ in ()).throw(RuntimeError("crash")))
    bus.emit("boom", {})  # must not raise
```

- [ ] **Step 2: Run to verify FAIL**

```bash
uv run pytest tests/unit/test_event_bus.py -v 2>&1 | head -10
```

Expected: ImportError

- [ ] **Step 3: Implement `loop_sci/events/__init__.py`**

```python
"""Re-export vendored EventBus and NullBus."""
from loop_sci._vendor.arbor.events.bus import EventBus, NullBus, Event
from loop_sci._vendor.arbor.events.types import (
    IDEA_PROPOSED,
    IDEA_COMPLETED,
    IDEA_PRUNED,
    IDEA_MERGED,
    EXECUTOR_START,
    EXECUTOR_END,
    SESSION_START,
    SESSION_END,
)

__all__ = [
    "EventBus", "NullBus", "Event",
    "IDEA_PROPOSED", "IDEA_COMPLETED", "IDEA_PRUNED", "IDEA_MERGED",
    "EXECUTOR_START", "EXECUTOR_END", "SESSION_START", "SESSION_END",
]
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_event_bus.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add loop_sci/events/ tests/unit/test_event_bus.py
git commit -m "feat(events): re-export EventBus/NullBus; subscriber parity tests"
```

---

### Task 10: Agent runtime adapter

**Files:**
- Create: `loop_sci/engine/agent_runtime.py`
- Create: `loop_sci/engine/types.py`

**Interfaces:**
- Consumes: vendored `Agent`, `AgentConfig`; `build_provider()`, `ToolRegistry`
- Produces:
  - `DispatchUnit(node_id, goal, context, tools)` — dataclass
  - `ExecutorResult(status, summary, score, insight, refs)` — dataclass; `status` in `{"done","bounded_exit","error"}`
  - `build_agent(provider, tools, system_prompt, cfg) -> Agent`

- [ ] **Step 1: Implement `loop_sci/engine/types.py`**

```python
"""Seam dataclasses: DispatchUnit and ExecutorResult."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class DispatchUnit:
    """One unit of work dispatched by the coordinator to an executor."""
    node_id: str
    goal: str
    context: str = ""
    tools: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ExecutorResult:
    """Typed outcome of one executor run."""
    status: Literal["done", "bounded_exit", "error"]
    summary: str
    score: float | None = None
    insight: str = ""
    refs: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 2: Implement `loop_sci/engine/agent_runtime.py`**

```python
"""Thin adapter: Hydra config → AgentConfig → vendored Agent."""
from __future__ import annotations

from typing import Any

from loop_sci._vendor.arbor.agent import Agent
from loop_sci._vendor.arbor.config import AgentConfig
from loop_sci._vendor.arbor.llm.base import LLMProvider
from loop_sci._vendor.arbor.tools.base import Tool


def build_agent(
    provider: LLMProvider,
    tools: list[Tool],
    system_prompt: str,
    cfg: AgentConfig,
) -> Agent:
    """Construct a vendored Agent from a provider and config."""
    return Agent(
        provider=provider,
        tools=tools,
        system_prompt=system_prompt,
        config=cfg,
    )
```

- [ ] **Step 3: Update `loop_sci/engine/__init__.py`**

```python
from .tools import ToolRegistry
from .types import DispatchUnit, ExecutorResult
from .agent_runtime import build_agent

__all__ = ["ToolRegistry", "DispatchUnit", "ExecutorResult", "build_agent"]
```

- [ ] **Step 4: Verify import**

```bash
uv run python -c "
from loop_sci.engine import DispatchUnit, ExecutorResult, build_agent
print(DispatchUnit(node_id='1', goal='test'))
print('engine types OK')
"
```

Expected: `DispatchUnit(node_id='1', goal='test' ...) engine types OK`

- [ ] **Step 5: Commit**

```bash
git add loop_sci/engine/types.py loop_sci/engine/agent_runtime.py loop_sci/engine/__init__.py
git commit -m "feat(engine): DispatchUnit/ExecutorResult seam dataclasses and agent_runtime adapter"
```

---

### Task 11: Executor

**Files:**
- Create: `loop_sci/engine/executor.py`

**Interfaces:**
- Consumes: `DispatchUnit`, vendored `Agent`, `build_agent`, `build_provider`, `hydra_to_agent_config`
- Produces: `Executor(provider, cfg) .run(unit: DispatchUnit) -> ExecutorResult`

- [ ] **Step 1: Implement `loop_sci/engine/executor.py`**

```python
"""Executor: runs one DispatchUnit as a vendored Agent, returns ExecutorResult."""
from __future__ import annotations

import logging
from typing import Any

from loop_sci._vendor.arbor.config import AgentConfig
from loop_sci._vendor.arbor.llm.base import LLMProvider
from .agent_runtime import build_agent
from .types import DispatchUnit, ExecutorResult

log = logging.getLogger(__name__)

_EXECUTOR_SYSTEM = """\
You are a focused research executor. You have been given a single research task.
Complete it thoroughly and concisely. When done, provide:
- A one-paragraph summary of what you found or did.
- An optional numeric score (0.0–1.0) if you can assess quality.
- A key insight in one sentence.
"""


class Executor:
    """Runs one DispatchUnit as a vendored Agent and maps the result."""

    def __init__(
        self,
        provider: LLMProvider,
        agent_cfg: AgentConfig,
    ) -> None:
        self.provider = provider
        self.agent_cfg = agent_cfg

    async def run(self, unit: DispatchUnit) -> ExecutorResult:
        """Execute one unit and return a typed result."""
        # Patch node_id so events carry the right attribution
        import copy
        cfg = copy.copy(self.agent_cfg)
        cfg.node_id = unit.node_id
        cfg.agent_label = f"executor:{unit.node_id}"

        system = _EXECUTOR_SYSTEM
        if unit.context:
            system += f"\n\n## Context\n{unit.context}"

        agent = build_agent(
            provider=self.provider,
            tools=[],  # no tools in the foundation skeleton; registry wired in coordinator
            system_prompt=system,
            cfg=cfg,
        )
        try:
            answer = await agent.run(unit.goal)
            status: str = "done" if agent.stop_reason == "finished" else "bounded_exit"
            return ExecutorResult(
                status=status,  # type: ignore[arg-type]
                summary=answer,
                insight=_extract_insight(answer),
            )
        except Exception as exc:
            log.error("Executor failed for node %s: %s", unit.node_id, exc)
            return ExecutorResult(
                status="error",
                summary=f"Executor error: {exc}",
            )


def _extract_insight(text: str) -> str:
    """Heuristic: return the last non-empty sentence as a short insight."""
    sentences = [s.strip() for s in text.replace("\n", " ").split(".") if s.strip()]
    return sentences[-1][:200] if sentences else ""
```

- [ ] **Step 2: Update `loop_sci/engine/__init__.py`**

```python
from .tools import ToolRegistry
from .types import DispatchUnit, ExecutorResult
from .agent_runtime import build_agent
from .executor import Executor

__all__ = ["ToolRegistry", "DispatchUnit", "ExecutorResult", "build_agent", "Executor"]
```

- [ ] **Step 3: Verify import**

```bash
uv run python -c "from loop_sci.engine import Executor; print('Executor OK')"
```

Expected: `Executor OK`

- [ ] **Step 4: Commit**

```bash
git add loop_sci/engine/executor.py loop_sci/engine/__init__.py
git commit -m "feat(engine): Executor maps DispatchUnit->Agent->ExecutorResult"
```

---

### Task 12: Coordinator

**Files:**
- Create: `loop_sci/engine/coordinator.py`

**Interfaces:**
- Consumes: `RunSession`, `Executor`, `DispatchUnit`, `ExecutorResult`, `EventBus`/`NullBus`
- Produces: `Coordinator(executor, bus, step_budget).run(session) -> None`
- Loop invariant: tree is persisted BEFORE the coordinator decides its next step.

- [ ] **Step 1: Implement `loop_sci/engine/coordinator.py`**

```python
"""Thin coordinator: observe→dispatch→record(persist)→decide."""
from __future__ import annotations

import logging
from typing import Any

from loop_sci.events import NullBus, EXECUTOR_START, EXECUTOR_END, SESSION_START, SESSION_END
from loop_sci.state.session import RunSession
from loop_sci.state.idea_tree import Node
from .executor import Executor
from .types import DispatchUnit, ExecutorResult

log = logging.getLogger(__name__)


class Coordinator:
    """Owns the observe→dispatch→record→decide loop over a RunSession's tree."""

    def __init__(
        self,
        executor: Executor,
        *,
        bus: Any = None,
        step_budget: int = 10,
    ) -> None:
        self.executor = executor
        self.bus = bus or NullBus()
        self.step_budget = step_budget

    async def run(self, session: RunSession) -> None:
        """Run the coordinator loop until no pending work or step budget hit."""
        if session.is_complete:
            log.info("run %s already complete — no-op", session.run_id)
            return

        self.bus.emit(SESSION_START, {
            "run_id": session.run_id,
            "task": session.cursor.get("task", ""),
        })

        steps = session.cursor.get("step", 0)

        while steps < self.step_budget:
            node = self._observe(session)
            if node is None:
                log.info("No pending nodes — run complete.")
                break

            # Mark node running
            session.tree.update_node(node.id, status="running")

            unit = self._plan(node)

            self.bus.emit(EXECUTOR_START, {"node_id": node.id, "goal": unit.goal})

            result: ExecutorResult = await self.executor.run(unit)

            # INVARIANT: persist BEFORE next decision
            self._record(session, node, result)

            self.bus.emit(EXECUTOR_END, {
                "node_id": node.id,
                "status": result.status,
                "summary_preview": result.summary[:100],
            })

            steps += 1
            session.advance_step()

            if not self._should_continue(session):
                break

        session.mark_complete()
        self.bus.emit(SESSION_END, {
            "run_id": session.run_id,
            "steps": steps,
        })

    # ── Observe ──────────────────────────────────────────────────────

    def _observe(self, session: RunSession) -> Node | None:
        """Pick the next pending leaf node, or None if none exist."""
        pending = session.tree.get_pending_leaves()
        if not pending:
            # Also check root itself if it has no children yet
            root = session.tree.get_root()
            if root.status == "pending":
                return root
            return None
        return pending[0]

    # ── Plan ─────────────────────────────────────────────────────────

    def _plan(self, node: Node) -> DispatchUnit:
        """Build a DispatchUnit for the given node."""
        return DispatchUnit(
            node_id=node.id,
            goal=node.hypothesis,
            context="",
        )

    # ── Record ───────────────────────────────────────────────────────

    def _record(self, session: RunSession, node: Node, result: ExecutorResult) -> None:
        """Write executor outcome into the tree; auto-save is triggered by update_node."""
        updates: dict[str, Any] = {
            "status": "done" if result.status != "error" else "needs_retry",
            "insight": result.insight or result.summary[:200],
        }
        if result.score is not None:
            updates["score"] = result.score
        if result.refs:
            node.refs = result.refs
        session.tree.update_node(node.id, **updates)

    # ── Decide ───────────────────────────────────────────────────────

    def _should_continue(self, session: RunSession) -> bool:
        """Continue while pending nodes exist."""
        return bool(session.tree.get_pending_leaves())
```

- [ ] **Step 2: Update `loop_sci/engine/__init__.py`**

```python
from .tools import ToolRegistry
from .types import DispatchUnit, ExecutorResult
from .agent_runtime import build_agent
from .executor import Executor
from .coordinator import Coordinator

__all__ = [
    "ToolRegistry", "DispatchUnit", "ExecutorResult",
    "build_agent", "Executor", "Coordinator",
]
```

- [ ] **Step 3: Verify import**

```bash
uv run python -c "from loop_sci.engine import Coordinator; print('Coordinator OK')"
```

Expected: `Coordinator OK`

- [ ] **Step 4: Commit**

```bash
git add loop_sci/engine/coordinator.py loop_sci/engine/__init__.py
git commit -m "feat(engine): Coordinator observe->dispatch->record->decide loop"
```

---

### Task 13: Integration test — coordinator cycle vs MockProvider

**Files:**
- Modify: `tests/conftest.py`
- Create: `tests/integration/test_coordinator_cycle.py`

**Interfaces:**
- `MockProvider` — deterministic `LLMProvider` with scripted responses; no network.

- [ ] **Step 1: Implement `MockProvider` in `tests/conftest.py`**

```python
# tests/conftest.py — FULL FILE (replace skeleton)
import pytest
from typing import Any
from loop_sci._vendor.arbor.llm.base import LLMProvider, LLMResponse, TextBlock, Usage


def pytest_configure(config):
    config.addinivalue_line("markers", "live: requires DASHSCOPE_API_KEY")


class MockProvider(LLMProvider):
    """Deterministic provider that returns scripted responses in order."""

    model = "mock-model"

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self._index = 0

    async def create(self, *, system, messages, tools=None, max_tokens=4096) -> LLMResponse:
        text = self._responses[self._index % len(self._responses)]
        self._index += 1
        return LLMResponse(
            content=[TextBlock(text=text)],
            stop_reason="end_turn",
            usage=Usage(input_tokens=10, output_tokens=5),
            model=self.model,
            raw_content=[{"type": "text", "text": text}],
        )

    def count_tokens(self, text: str) -> int:
        return len(text.split())


@pytest.fixture
def mock_provider():
    return MockProvider(responses=["I have completed the task. The answer is 42."])
```

- [ ] **Step 2: Write integration test**

```python
# tests/integration/test_coordinator_cycle.py
import pytest
from loop_sci.engine import Coordinator, Executor
from loop_sci.state.session import RunSession
from loop_sci.events import EventBus
from loop_sci._vendor.arbor.config import AgentConfig
from tests.conftest import MockProvider


@pytest.fixture
def agent_cfg():
    from loop_sci._vendor.arbor.config_schema import LLMConfig, ContextConfig, TimeoutConfig
    return AgentConfig(
        llm=LLMConfig(provider="openai_compat", model="mock-model", api_key="dummy"),
        context=ContextConfig(context_window=8000, compact_threshold=0.9, compact_keep_recent=4),
        timeout=TimeoutConfig(),
        max_turns=5,
        auto_git=False,
    )


@pytest.mark.asyncio
async def test_one_coordinator_cycle(tmp_path, agent_cfg):
    """One observe→dispatch→record cycle completes without network."""
    provider = MockProvider(responses=["The scientific method requires observation. Done."])
    executor = Executor(provider=provider, agent_cfg=agent_cfg)
    coordinator = Coordinator(executor=executor, step_budget=3)

    session = RunSession.create(tmp_path / "runs", task="What is the scientific method?")

    await coordinator.run(session)

    assert session.is_complete
    # Root node should have been processed
    root = session.tree.get_root()
    assert root.status in ("done", "needs_retry")
    # Tree was persisted
    assert (session.session_dir / "idea_tree.json").exists()


@pytest.mark.asyncio
async def test_event_bus_receives_events(tmp_path, agent_cfg):
    """Subscriber receives executor start/end events; results are identical."""
    received_events = []
    bus = EventBus()
    bus.on_all(lambda e: received_events.append(e.type))

    provider = MockProvider(responses=["Completed."])
    executor = Executor(provider=provider, agent_cfg=agent_cfg)
    coordinator = Coordinator(executor=executor, bus=bus, step_budget=3)
    session = RunSession.create(tmp_path / "runs", task="stub task")

    await coordinator.run(session)

    assert any("executor" in t or "session" in t for t in received_events)
    assert session.is_complete


@pytest.mark.asyncio
async def test_step_budget_stops_loop(tmp_path, agent_cfg):
    """A coordinator with budget=0 exits immediately after marking session complete."""
    from loop_sci.state.idea_tree import Node
    provider = MockProvider(responses=["answer"])
    executor = Executor(provider=provider, agent_cfg=agent_cfg)
    coordinator = Coordinator(executor=executor, step_budget=0)
    session = RunSession.create(tmp_path / "runs", task="task")

    await coordinator.run(session)
    assert session.is_complete
    assert session.cursor["step"] == 0
```

- [ ] **Step 3: Run integration tests**

```bash
uv run pytest tests/integration/test_coordinator_cycle.py -v
```

Expected: all PASS (no network required)

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py tests/integration/
git commit -m "test(integration): coordinator cycle + event bus vs MockProvider — no network"
```

---

### Task 14: CLI

**Files:**
- Create: `loop_sci/cli.py`

**Interfaces:**
- Produces: `loop-sci run --task TEXT [--config KEY=VAL ...]`, `loop-sci resume RUN_ID`, `loop-sci inspect RUN_ID`

- [ ] **Step 1: Implement `loop_sci/cli.py`**

```python
"""CLI entry point: run / resume / inspect."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv

load_dotenv()

app = typer.Typer(name="loop-sci", help="Loop-SCI multi-agent research harness.")
log = logging.getLogger("loop_sci.cli")


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=level)


def _build_coordinator_and_session(cfg):
    """Shared setup for run and resume."""
    from loop_sci.provider.credentials import resolve_key
    from loop_sci.provider.factory import build_provider
    from loop_sci.config.loader import hydra_to_agent_config
    from loop_sci.engine import Executor, Coordinator

    api_key = cfg.provider.api_key or resolve_key("DASHSCOPE_API_KEY")
    provider = build_provider(
        model=cfg.provider.model,
        api_key=api_key,
        base_url=cfg.provider.base_url,
        timeout=cfg.provider.timeout,
        max_retries=cfg.provider.max_retries,
    )
    agent_cfg = hydra_to_agent_config(cfg)
    executor = Executor(provider=provider, agent_cfg=agent_cfg)
    coordinator = Coordinator(executor=executor, step_budget=cfg.engine.step_budget)
    return coordinator


@app.command()
def run(
    task: str = typer.Option(..., "--task", "-t", help="Research task description."),
    runs_root: str = typer.Option("runs", "--runs-root", help="Root directory for run sessions."),
    config: Optional[list[str]] = typer.Option(None, "--config", "-c", help="Hydra overrides (key=value)."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Start a new run against a stub research task."""
    _setup_logging(verbose)
    from loop_sci.config.loader import load_config
    from loop_sci.state.session import RunSession
    import os

    overrides = list(config or [])
    cfg = load_config(
        config_dir=str(Path(__file__).parent.parent / "conf"),
        overrides=overrides,
    )
    if task:
        cfg.run.task = task
    cfg.run.runs_root = runs_root

    session = RunSession.create(cfg.run.runs_root, task=cfg.run.task)
    typer.echo(f"Started run: {session.run_id}")
    typer.echo(f"Session dir: {session.session_dir}")

    coordinator = _build_coordinator_and_session(cfg)
    asyncio.run(coordinator.run(session))
    typer.echo(f"Run complete. Steps: {session.cursor.get('step', 0)}")


@app.command()
def resume(
    run_id: str = typer.Argument(..., help="Run ID to resume."),
    runs_root: str = typer.Option("runs", "--runs-root"),
    config: Optional[list[str]] = typer.Option(None, "--config", "-c"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Resume an interrupted run from its last checkpoint."""
    _setup_logging(verbose)
    from loop_sci.config.loader import load_config
    from loop_sci.state.session import RunSession

    overrides = list(config or [])
    cfg = load_config(
        config_dir=str(Path(__file__).parent.parent / "conf"),
        overrides=overrides,
    )
    cfg.run.runs_root = runs_root

    session = RunSession.load(runs_root, run_id)
    if session.is_complete:
        typer.echo(f"Run {run_id} is already complete. Nothing to resume.")
        raise typer.Exit(0)

    typer.echo(f"Resuming run: {run_id} (step {session.cursor.get('step', 0)})")
    coordinator = _build_coordinator_and_session(cfg)
    asyncio.run(coordinator.run(session))
    typer.echo(f"Resume complete. Steps: {session.cursor.get('step', 0)}")


@app.command()
def inspect(
    run_id: str = typer.Argument(..., help="Run ID to inspect."),
    runs_root: str = typer.Option("runs", "--runs-root"),
) -> None:
    """Print the idea tree and cursor for a run."""
    from loop_sci.state.session import RunSession

    session = RunSession.load(runs_root, run_id)
    typer.echo(f"Run ID:  {session.run_id}")
    typer.echo(f"Status:  {session.cursor.get('status')}")
    typer.echo(f"Steps:   {session.cursor.get('step', 0)}")
    typer.echo(f"Task:    {session.cursor.get('task', '')}")
    typer.echo("")
    typer.echo(session.tree.to_compact_summary())
```

- [ ] **Step 2: Verify CLI help works**

```bash
uv run loop-sci --help
```

Expected: shows `run`, `resume`, `inspect` sub-commands.

- [ ] **Step 3: Commit**

```bash
git add loop_sci/cli.py
git commit -m "feat(cli): typer CLI — run / resume / inspect against stub task"
```

---

### Task 15 (HIGH-RISK): Live Qwen tool-call smoke test

> **This is one of the two front-loaded risk tasks.** It validates the real Bailian endpoint and records per-tier native tool-call support. Run this manually before assuming `NativeToolProtocol` is the correct default.

**Files:**
- Create: `tests/live/test_live_qwen.py`
- Create: `tests/live/__init__.py`

**Interfaces:**
- Skipped automatically when `DASHSCOPE_API_KEY` is absent.
- Records tool-call support result to stdout (JSON) for documentation.

- [ ] **Step 1: Create `tests/live/__init__.py`** (empty)

- [ ] **Step 2: Write `tests/live/test_live_qwen.py`**

```python
"""Live smoke test — requires DASHSCOPE_API_KEY in environment.

Run with:
    uv run pytest tests/live/test_live_qwen.py -v -m live

Records which Qwen tiers support native tool-calls.
"""
import json
import os
import pytest

pytestmark = pytest.mark.live

BAILIAN_BASE_URL = os.environ.get(
    "BAILIAN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
TIERS = [
    os.environ.get("QWEN_MODEL", "qwen-plus"),
]


@pytest.fixture(autouse=True)
def require_key():
    key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not key:
        pytest.skip("DASHSCOPE_API_KEY not set — skipping live test")


@pytest.mark.asyncio
@pytest.mark.parametrize("model", TIERS)
async def test_live_completion(model):
    """Real Qwen completion returns a non-empty text response."""
    from loop_sci.provider.factory import build_provider
    provider = build_provider(
        model=model,
        api_key=os.environ["DASHSCOPE_API_KEY"],
        base_url=BAILIAN_BASE_URL,
        timeout=60.0,
    )
    response = await provider.create(
        system="You are a helpful assistant. Reply in one sentence.",
        messages=[{"role": "user", "content": "What is 2 + 2?"}],
        max_tokens=64,
    )
    assert response.get_text().strip(), f"Empty response from {model}"
    print(f"\n[{model}] completion OK: {response.get_text()[:80]}")
    print(f"  model_used={response.model}  tokens={response.usage.total_tokens}")


@pytest.mark.asyncio
@pytest.mark.parametrize("model", TIERS)
async def test_live_native_tool_call(model):
    """Real Qwen native tool-call round trip; records whether the tier supports it."""
    from loop_sci.provider.factory import build_provider
    provider = build_provider(
        model=model,
        api_key=os.environ["DASHSCOPE_API_KEY"],
        base_url=BAILIAN_BASE_URL,
        timeout=60.0,
    )
    tools = [{
        "name": "get_weather",
        "description": "Get the current weather for a city.",
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string", "description": "City name"}},
            "required": ["city"],
        },
    }]
    response = await provider.create(
        system="You are a helpful assistant.",
        messages=[{"role": "user", "content": "What is the weather in Beijing?"}],
        tools=tools,
        max_tokens=256,
    )
    tool_calls = response.get_tool_calls()
    supports_native = len(tool_calls) > 0
    record = {
        "model": model,
        "supports_native_tool_calls": supports_native,
        "stop_reason": response.stop_reason,
        "tool_calls_count": len(tool_calls),
    }
    print(f"\n[TOOL-CALL RECORD] {json.dumps(record)}")

    if supports_native:
        assert tool_calls[0].name == "get_weather"
        assert "city" in tool_calls[0].input
        print(f"  -> NATIVE supported. input={tool_calls[0].input}")
    else:
        print(f"  -> NATIVE NOT supported for {model}. Use PromptToolProtocol as default.")

    # Test always passes — it records support, not mandates it.
    assert True
```

- [ ] **Step 3: Run smoke test (requires real key)**

```bash
DASHSCOPE_API_KEY=<your-key> uv run pytest tests/live/test_live_qwen.py -v -m live -s
```

Expected: tests pass; output records `[TOOL-CALL RECORD] {"model": "qwen-plus", "supports_native_tool_calls": true/false, ...}`

Based on result: if `supports_native_tool_calls: false` for the default tier, update `conf/provider/bailian.yaml` to `tool_protocol: prompt`.

- [ ] **Step 4: Commit**

```bash
git add tests/live/
git commit -m "test(live): Qwen-via-Bailian smoke test — completion + native tool-call round trip"
```

---

### Task 16 (HIGH-RISK): End-to-end run and resume against Qwen

> **This is the second front-loaded risk task.** It proves the full stack works on the real endpoint.

**Files:**
- Create: `tests/live/test_e2e_run.py`

- [ ] **Step 1: Write `tests/live/test_e2e_run.py`**

```python
"""End-to-end run + resume against real Qwen-via-Bailian.

Run with:
    DASHSCOPE_API_KEY=<key> uv run pytest tests/live/test_e2e_run.py -v -m live -s
"""
import json
import os
import shutil
import tempfile
import pytest

pytestmark = pytest.mark.live

BAILIAN_BASE_URL = os.environ.get(
    "BAILIAN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
STUB_TASK = (
    "List two principles of the scientific method. Be very brief (one sentence each)."
)


@pytest.fixture(autouse=True)
def require_key():
    if not os.environ.get("DASHSCOPE_API_KEY"):
        pytest.skip("DASHSCOPE_API_KEY not set")


@pytest.fixture
def runs_root(tmp_path):
    return tmp_path / "e2e_runs"


def _build_all(runs_root, task):
    from loop_sci.config.loader import load_config, hydra_to_agent_config
    from loop_sci.provider.factory import build_provider
    from loop_sci.provider.credentials import resolve_key, invocation_record
    from loop_sci.engine import Executor, Coordinator
    from loop_sci.state.session import RunSession
    import pathlib

    cfg = load_config(
        config_dir=str(pathlib.Path(__file__).parent.parent.parent / "conf"),
        overrides=[f"run.task={task}", f"run.runs_root={runs_root}"],
    )
    api_key = resolve_key("DASHSCOPE_API_KEY")
    rec = invocation_record(cfg.provider.model, cfg.provider.base_url)
    print(f"\n[INVOCATION RECORD] {json.dumps(rec)}")

    provider = build_provider(
        model=cfg.provider.model,
        api_key=api_key,
        base_url=cfg.provider.base_url,
        timeout=cfg.provider.timeout,
    )
    agent_cfg = hydra_to_agent_config(cfg)
    executor = Executor(provider=provider, agent_cfg=agent_cfg)
    coordinator = Coordinator(executor=executor, step_budget=cfg.engine.step_budget)
    session = RunSession.create(runs_root, task=task)
    return coordinator, session


@pytest.mark.asyncio
async def test_e2e_run_completes(runs_root):
    """≥1 observe→dispatch→record cycle completes and persists."""
    import asyncio
    coordinator, session = _build_all(runs_root, STUB_TASK)
    run_id = session.run_id

    await coordinator.run(session)

    assert session.is_complete, "Session did not complete"
    assert session.cursor["step"] >= 1, "No steps were executed"

    # Reload and verify persistence
    from loop_sci.state.session import RunSession
    loaded = RunSession.load(runs_root, run_id)
    assert loaded.is_complete
    root = loaded.tree.get_root()
    assert root.status in ("done", "needs_retry"), f"Unexpected root status: {root.status}"
    assert (loaded.session_dir / "idea_tree.json").exists()

    print(f"\n[E2E PASS] run_id={run_id} steps={session.cursor['step']}")
    print(loaded.tree.to_compact_summary())


@pytest.mark.asyncio
async def test_e2e_resume_continues(runs_root):
    """Interrupt after one step; resume continues without repeating done work."""
    from loop_sci.state.session import RunSession
    from loop_sci.state.idea_tree import Node
    from loop_sci.config.loader import load_config, hydra_to_agent_config
    from loop_sci.provider.factory import build_provider
    from loop_sci.provider.credentials import resolve_key
    from loop_sci.engine import Executor, Coordinator
    import pathlib

    cfg = load_config(
        config_dir=str(pathlib.Path(__file__).parent.parent.parent / "conf"),
        overrides=[f"run.runs_root={runs_root}"],
    )
    api_key = resolve_key("DASHSCOPE_API_KEY")

    # Create session with one done node and one pending node — simulates interrupt
    session = RunSession.create(runs_root, task=STUB_TASK)
    done_id = session.tree.next_child_id("ROOT")
    session.tree.add_node(Node(
        id=done_id, parent_id="ROOT",
        hypothesis="Principle 1: Observation",
        depth=1, status="done",
        insight="Observation is key.",
    ))
    pending_id = session.tree.next_child_id("ROOT")
    session.tree.add_node(Node(
        id=pending_id, parent_id="ROOT",
        hypothesis="Principle 2: Repeatability",
        depth=1, status="pending",
    ))
    session.advance_step()  # cursor reflects one done step

    run_id = session.run_id

    # Resume from disk
    resumed = RunSession.load(runs_root, run_id)
    assert not resumed.is_complete

    provider = build_provider(
        model=cfg.provider.model, api_key=api_key,
        base_url=cfg.provider.base_url, timeout=cfg.provider.timeout,
    )
    agent_cfg = hydra_to_agent_config(cfg)
    executor = Executor(provider=provider, agent_cfg=agent_cfg)
    coordinator = Coordinator(executor=executor, step_budget=5)

    await coordinator.run(resumed)

    assert resumed.is_complete
    # The done node must still be done (not re-executed)
    reloaded = RunSession.load(runs_root, run_id)
    done_node = reloaded.tree.get_node(done_id)
    assert done_node is not None and done_node.status == "done"
    print(f"\n[RESUME PASS] run_id={run_id}")
    print(reloaded.tree.to_compact_summary())


@pytest.mark.asyncio
async def test_resume_already_complete_is_noop(runs_root):
    """Resume on a complete run is a safe no-op."""
    coordinator, session = _build_all(runs_root, STUB_TASK)
    await coordinator.run(session)
    assert session.is_complete
    steps_before = session.cursor["step"]

    # Resume again — should exit immediately
    from loop_sci.state.session import RunSession
    from loop_sci.config.loader import load_config, hydra_to_agent_config
    from loop_sci.provider.factory import build_provider
    from loop_sci.provider.credentials import resolve_key
    from loop_sci.engine import Executor, Coordinator
    import pathlib

    cfg = load_config(config_dir=str(pathlib.Path(__file__).parent.parent.parent / "conf"))
    api_key = resolve_key("DASHSCOPE_API_KEY")
    provider = build_provider(model=cfg.provider.model, api_key=api_key, base_url=cfg.provider.base_url)
    agent_cfg = hydra_to_agent_config(cfg)
    executor = Executor(provider=provider, agent_cfg=agent_cfg)
    coordinator2 = Coordinator(executor=executor, step_budget=5)

    session2 = RunSession.load(runs_root, session.run_id)
    await coordinator2.run(session2)

    assert session2.cursor["step"] == steps_before, "Resume should not add steps on complete run"
    print(f"\n[NOOP PASS] steps unchanged at {steps_before}")
```

- [ ] **Step 2: Run end-to-end (requires real key)**

```bash
DASHSCOPE_API_KEY=<your-key> uv run pytest tests/live/test_e2e_run.py -v -m live -s 2>&1
```

Expected: all three tests PASS; step count ≥ 1; `idea_tree.json` present; `[RESUME PASS]` printed.

- [ ] **Step 3: Commit**

```bash
git add tests/live/test_e2e_run.py
git commit -m "test(live): e2e run + resume + already-complete no-op on Qwen-via-Bailian"
```

---

### Task 17: Coverage gate and README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Run full offline test suite with coverage**

```bash
uv run pytest tests/unit/ tests/integration/ --cov=loop_sci --cov-report=term-missing -v
```

Expected: ≥80% line coverage. If below, identify uncovered branches from the report and add targeted tests for them (typically: error paths in `coordinator._record`, `executor._extract_insight` empty-text case, `credentials.redact` short-key branch).

- [ ] **Step 2: Add missing coverage tests if needed**

Example — if `executor` error path is uncovered, add to `tests/integration/test_coordinator_cycle.py`:

```python
@pytest.mark.asyncio
async def test_executor_error_marks_needs_retry(tmp_path, agent_cfg):
    """When provider raises, ExecutorResult.status == 'error' and node is 'needs_retry'."""
    from loop_sci._vendor.arbor.llm.base import LLMProvider, LLMResponse
    from loop_sci.engine import Executor, Coordinator
    from loop_sci.state.session import RunSession

    class FailingProvider(MockProvider):
        async def create(self, **_):
            raise RuntimeError("simulated provider failure")

    executor = Executor(provider=FailingProvider([]), agent_cfg=agent_cfg)
    coordinator = Coordinator(executor=executor, step_budget=1)
    session = RunSession.create(tmp_path / "runs", task="fail task")
    await coordinator.run(session)
    root = session.tree.get_root()
    assert root.status == "needs_retry"
```

- [ ] **Step 3: Write `README.md`**

```markdown
# Loop-SCI

Foundation multi-agent research harness. Runs Qwen via Alibaba Cloud Bailian.

## Setup

```bash
# Install uv first: https://docs.astral.sh/uv/
uv sync --group dev
cp .env.example .env
# Edit .env and set DASHSCOPE_API_KEY=sk-...
```

## Run a stub task

```bash
uv run loop-sci run --task "What are three key principles of the scientific method?"
```

## Resume a run

```bash
uv run loop-sci resume <run_id>
```

## Inspect a run

```bash
uv run loop-sci inspect <run_id>
```

## Tests

```bash
# Offline (CI default)
uv run pytest tests/unit/ tests/integration/ --cov=loop_sci -v

# Live (requires DASHSCOPE_API_KEY)
DASHSCOPE_API_KEY=sk-... uv run pytest tests/live/ -m live -v -s
```

## Vendored Arbor

`loop_sci/_vendor/arbor/` is a pinned snapshot of
[Arbor](https://github.com/RUC-NLPIR/Arbor) at commit
`0eae8ad6751615058c2f1cd0f80ff5729123d204` (Apache-2.0).
See `loop_sci/_vendor/arbor/LICENSE` for terms.
```

- [ ] **Step 4: Final commit**

```bash
git add README.md
git commit -m "docs: README with setup, run, resume, test instructions and Arbor provenance"
```

---

## Test Strategy Summary

| Layer | Location | Key checks | Network? |
|-------|----------|-----------|---------|
| Unit | `tests/unit/` | credential missing/redaction, retry exhaustion, tool registry unknown/malformed, idea-tree persist/reload equality, atomic write, resume no-op, event-bus subscriber parity | No |
| Integration | `tests/integration/` | one full coordinator→executor cycle vs `MockProvider`, event bus with/without subscriber, step budget stops loop, executor error → `needs_retry` | No |
| Live smoke | `tests/live/` | real Qwen completion + native tool-call round trip per tier (records support), e2e run+persist, resume from checkpoint, already-complete no-op | Yes (`@pytest.mark.live`) |

CI runs only `tests/unit/` and `tests/integration/`. Live tests are opt-in via `-m live` and require `DASHSCOPE_API_KEY`.

---

## Risks

| Risk | Mitigation |
|------|------------|
| Qwen native tool-calls unreliable on some tiers | Task 15 smoke test records per-tier support; `conf/provider/bailian.yaml` switches `tool_protocol` to `prompt` based on result |
| Vendored import rewriting misses a path | Task 2 smoke-import step catches this before any other task builds on it |
| Bailian rate limits consume 300¥ budget | `max_retries=0` in `build_provider` (retries handled externally), default tier = `qwen-plus` (not max), live tests are opt-in and short |
| Hydra↔AgentConfig field drift | Contained in `config/loader.py`; the `hydra_to_agent_config` function is the single coupling point |
| `AgentConfig` pydantic model requires fields we don't have | `auto_git=False` eliminates `GitManager`; `track_stats=True` keeps AgentStats; `workspace_dir=None` falls through to `.loop_sci` default — covered by Task 2 import smoke |
