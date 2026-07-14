"""Shared test fixtures and helpers.

MockProvider implements the vendored LLMProvider ABC and returns deterministic,
scripted responses — no network, no API key required.
"""
from __future__ import annotations

import pytest
from loop_sci._vendor.arbor.llm.base import LLMProvider, LLMResponse, TextBlock, Usage


def pytest_configure(config):
    config.addinivalue_line("markers", "live: requires DASHSCOPE_API_KEY")


class MockProvider(LLMProvider):
    """Deterministic LLMProvider that returns scripted responses in order.

    Implements ALL abstract methods from LLMProvider ABC:
    - create()         (abstract)
    - count_tokens()   (abstract)
    create_streaming() has a default fallback in the ABC so is not overridden.
    """

    model = "mock-model"

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self._index = 0

    async def create(
        self,
        *,
        system: str,
        messages: list,
        tools: list | None = None,
        max_tokens: int = 16384,
    ) -> LLMResponse:
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
