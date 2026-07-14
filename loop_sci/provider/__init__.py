"""loop_sci.provider — typed errors, credential helpers, retry, and provider factory."""
from .credentials import invocation_record, redact, resolve_key
from .errors import (
    AuthError,
    ProviderError,
    RateLimitError,
    ServerError,
    TimeoutError,
    with_retry,
)
from .factory import build_provider
from .tool_protocol import NativeToolProtocol, PromptToolProtocol, ToolProtocol

__all__ = [
    "build_provider",
    "resolve_key",
    "redact",
    "invocation_record",
    "ProviderError",
    "RateLimitError",
    "TimeoutError",
    "AuthError",
    "ServerError",
    "with_retry",
    "ToolProtocol",
    "NativeToolProtocol",
    "PromptToolProtocol",
]
