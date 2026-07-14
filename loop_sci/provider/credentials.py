"""Credential resolution, redaction, and invocation logging."""
from __future__ import annotations

import os
import time
from urllib.parse import urlparse

from .errors import AuthError


def resolve_key(env_var: str) -> str:
    """Return the env var value; raise :class:`AuthError` with the var name if absent."""
    value = os.environ.get(env_var)
    if not value:
        raise AuthError(
            f"Missing API key: environment variable '{env_var}' is not set. "
            f"Add it to your .env file or export it before running."
        )
    return value


def redact(key: str) -> str:
    """Return a redacted version safe for logs: ``'sk-...XXXX'`` (last 4 chars).

    If the key is too short to redact meaningfully, returns ``'***'``.
    """
    if len(key) <= 4:
        return "***"
    return f"sk-...{key[-4:]}"


def invocation_record(model: str, base_url: str) -> dict:
    """Emit a non-secret invocation record for competition credential evidence.

    The returned dict intentionally contains no api_key or secret material.
    """
    host = urlparse(base_url).hostname or base_url
    return {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": model,
        "endpoint_host": host,
    }
