"""Factory: construct an LLM provider for Qwen via Bailian (Alibaba Cloud DashScope)."""
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
    """Return a configured :class:`OpenAICompatProvider` pointing at Bailian/Qwen.

    The vendored ``OpenAICompatProvider.__init__`` accepts:
        model, api_key, base_url, max_retries, timeout
    All five kwargs are supported.  We pass ``max_retries=0`` so that the
    OpenAI SDK does NOT retry internally — retries are owned by our
    :func:`~loop_sci.provider.errors.with_retry` wrapper.
    """
    return OpenAICompatProvider(
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_retries=0,  # retries handled by our with_retry wrapper
    )
