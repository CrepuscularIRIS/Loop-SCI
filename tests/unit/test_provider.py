"""Tests for loop_sci/provider/ — credentials, errors, retry, factory.

TDD: all tests written before any production code.
"""
from __future__ import annotations

import os
import pytest

# ---------------------------------------------------------------------------
# Credentials tests
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Retry tests
# ---------------------------------------------------------------------------

import asyncio
import pytest
from loop_sci.provider.errors import RateLimitError, ServerError, with_retry


@pytest.mark.asyncio
async def test_retry_succeeds_on_transient(monkeypatch):
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
    async def always_fail():
        raise RateLimitError("always")

    with pytest.raises(RateLimitError):
        await with_retry(always_fail, max_retries=2, base_delay=0.0, max_delay=0.0)


# ---------------------------------------------------------------------------
# Factory test
# ---------------------------------------------------------------------------

def test_build_provider_returns_provider(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    from loop_sci.provider.factory import build_provider
    provider = build_provider(
        model="qwen-plus",
        api_key="sk-test",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    from loop_sci._vendor.arbor.llm.base import LLMProvider
    assert isinstance(provider, LLMProvider)
    assert provider.model == "qwen-plus"


# ---------------------------------------------------------------------------
# ToolProtocol tests
# ---------------------------------------------------------------------------

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


def test_prompt_protocol_parse_malformed_json_skipped():
    proto = PromptToolProtocol()
    text = '```tool_call\n{bad json!!}\n```\n```tool_call\n{"name": "search", "arguments": {"q": "ok"}}\n```'
    calls = proto.parse_tool_calls(text, _SAMPLE_TOOLS)
    assert len(calls) == 1
    assert calls[0]["name"] == "search"


def test_prompt_protocol_parse_no_name_key_skipped():
    proto = PromptToolProtocol()
    text = '```tool_call\n{"action": "search", "arguments": {}}\n```'
    calls = proto.parse_tool_calls(text, _SAMPLE_TOOLS)
    assert len(calls) == 0


def test_native_protocol_empty_tools():
    proto = NativeToolProtocol()
    kwargs = proto.prepare_tools([])
    assert kwargs == {}


def test_prompt_protocol_empty_tools():
    proto = PromptToolProtocol()
    kwargs = proto.prepare_tools([])
    assert kwargs == {}
