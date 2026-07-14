"""Typed provider errors and async retry wrapper."""
from __future__ import annotations

import asyncio
import random
from typing import Callable, Coroutine, TypeVar

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Typed errors
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Retry wrapper
# ---------------------------------------------------------------------------

_RETRYABLE = (RateLimitError, TimeoutError, ServerError)


async def with_retry(
    coro_fn: Callable[[], Coroutine[None, None, T]],
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
) -> T:
    """Retry ``coro_fn()`` up to ``max_retries`` times on retryable errors.

    Uses bounded exponential backoff with jitter. Only :data:`_RETRYABLE`
    errors are retried; others propagate immediately.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return await coro_fn()
        except _RETRYABLE as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                delay = min(max_delay, base_delay * (2 ** attempt))
                jitter = random.uniform(0, delay * 0.1) if delay > 0 else 0
                await asyncio.sleep(delay + jitter)
    raise last_exc  # type: ignore[misc]
