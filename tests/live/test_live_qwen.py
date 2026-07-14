"""Live smoke test — requires DASHSCOPE_API_KEY in environment.

Run with:
    uv run pytest tests/live/test_live_qwen.py -v -m live -s

Records which Qwen tiers support native tool-calls.

These tests NEVER run in the default suite (no key → autoskip).
They are cost-cheap: short prompts, low max_tokens.
"""
from __future__ import annotations

import json
import os

import pytest

pytestmark = pytest.mark.live

# ---------------------------------------------------------------------------
# Configuration — override via environment variables when running live
# ---------------------------------------------------------------------------

BAILIAN_BASE_URL: str = os.environ.get(
    "BAILIAN_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)

# Parametrize over one or more tiers; defaults to qwen-plus.
# To test multiple tiers export: QWEN_TIERS=qwen-max,qwen-plus,qwen-turbo
_tiers_env = os.environ.get("QWEN_TIERS", os.environ.get("QWEN_MODEL", "qwen-plus"))
TIERS: list[str] = [t.strip() for t in _tiers_env.split(",") if t.strip()]


# ---------------------------------------------------------------------------
# Auto-skip fixture — applied to every test in this module
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def require_key() -> None:
    """Skip the whole module when DASHSCOPE_API_KEY is absent."""
    key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not key:
        pytest.skip("DASHSCOPE_API_KEY not set — skipping live test")


# ---------------------------------------------------------------------------
# Test A: real completion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("model", TIERS)
async def test_live_completion(model: str) -> None:
    """Real Qwen completion returns a non-empty text response.

    Validates:
    - build_provider() wires up the Bailian endpoint correctly.
    - provider.create() returns a non-empty LLMResponse.get_text().
    - Usage tokens are populated (sanity-check the SDK path).
    """
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

    text = response.get_text().strip()
    assert text, f"[{model}] got an empty text response from Qwen"

    print(f"\n[{model}] completion OK: {text[:120]}")
    print(
        f"  model_used={response.model!r}  "
        f"input_tokens={response.usage.input_tokens}  "
        f"output_tokens={response.usage.output_tokens}  "
        f"total_tokens={response.usage.total_tokens}"
    )


# ---------------------------------------------------------------------------
# Test B: native tool-call round-trip
# ---------------------------------------------------------------------------

_WEATHER_TOOL: dict = {
    "name": "get_weather",
    "description": "Get the current weather for a city.",
    "input_schema": {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "City name"},
        },
        "required": ["city"],
    },
}


@pytest.mark.asyncio
@pytest.mark.parametrize("model", TIERS)
async def test_live_native_tool_call(model: str) -> None:
    """Real Qwen native tool-call round trip.

    Records whether the tier supports native tool-calls; does NOT hard-fail
    when a tier returns text instead of a tool call — this is informational.

    Output format (printed to stdout for capture):
        [TOOL-CALL RECORD] {"model": "qwen-plus", "supports_native_tool_calls": true, ...}

    Use this output to decide whether tool_protocol: native or tool_protocol: prompt
    should be the default in conf/provider/bailian.yaml.
    """
    from loop_sci.provider.factory import build_provider

    provider = build_provider(
        model=model,
        api_key=os.environ["DASHSCOPE_API_KEY"],
        base_url=BAILIAN_BASE_URL,
        timeout=60.0,
    )

    response = await provider.create(
        system="You are a helpful assistant. Use the available tools when appropriate.",
        messages=[
            {"role": "user", "content": "What is the weather in Beijing right now?"}
        ],
        tools=[_WEATHER_TOOL],
        max_tokens=256,
    )

    tool_calls = response.get_tool_calls()
    supports_native = len(tool_calls) > 0

    record: dict = {
        "model": model,
        "supports_native_tool_calls": supports_native,
        "stop_reason": response.stop_reason,
        "tool_calls_count": len(tool_calls),
    }
    print(f"\n[TOOL-CALL RECORD] {json.dumps(record)}")

    if supports_native:
        tc = tool_calls[0]
        assert tc.name == "get_weather", (
            f"[{model}] tool name mismatch: expected 'get_weather', got {tc.name!r}"
        )
        assert "city" in tc.input, (
            f"[{model}] expected 'city' in tool input, got: {tc.input!r}"
        )
        print(f"  -> NATIVE tool-calls SUPPORTED. input={tc.input}")
    else:
        # Not a hard failure — record it and let the user update conf/provider/bailian.yaml
        fallback_text = response.get_text()[:120]
        print(
            f"  -> NATIVE tool-calls NOT supported for {model}. "
            f"Model returned text instead: {fallback_text!r}\n"
            f"  Recommendation: set tool_protocol: prompt in conf/provider/bailian.yaml"
        )

    # The test always passes — it records support status, it does not mandate it.
    # Asserting True is intentional: we want GREEN regardless of tier support.
    assert True
