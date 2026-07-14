"""Multi-source dispatch: fan-out, per-source backoff, graceful degradation.

Design
------
``dispatch`` fans a query out to all configured sources concurrently via
``asyncio.gather(..., return_exceptions=True)``.  That ensures no single
source failure cancels siblings.

Per-source retry / backoff
~~~~~~~~~~~~~~~~~~~~~~~~~~
When ``retry_on`` exceptions are caught, the source is retried up to
``max_retries`` times with ``backoff_delay`` seconds between attempts
(default 1 s, but tests inject 0.0 so no real sleeps occur).
After exhausting retries the source is recorded as a ``SourceError``.

Graceful degradation
~~~~~~~~~~~~~~~~~~~~
Any exception that is not in ``retry_on``, and any source that exhausts
its retries, results in a ``SourceError`` being appended to the *errors*
list.  The successful sources' ``PaperResult`` objects are always returned.

Return value
~~~~~~~~~~~~
- ``return_errors=False`` (default): returns ``list[PaperResult]``
- ``return_errors=True``: returns ``tuple[list[PaperResult], list[SourceError]]``
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from .schema import PaperResult

log = logging.getLogger(__name__)


@dataclass
class SourceError:
    """Records a source that failed to return results.

    Attributes:
        source: The name key used in the *sources* dict passed to ``dispatch``.
        reason: Human-readable description of why the source failed.
    """

    source: str
    reason: str


async def _query_with_backoff(
    name: str,
    client: Any,
    query: str,
    *,
    max_results: int,
    retry_on: tuple[type[BaseException], ...],
    max_retries: int,
    backoff_delay: float,
) -> tuple[list[PaperResult], SourceError | None]:
    """Call ``client.search`` with bounded retry/backoff for throttle errors.

    Returns (results, None) on success, ([], SourceError) on final failure.
    The function never raises — all exceptions are captured and converted to
    a ``SourceError`` so siblings are never cancelled.
    """
    attempt = 0

    while True:
        try:
            results = await client.search(query, max_results=max_results)
            return results, None
        except Exception as exc:
            if retry_on and isinstance(exc, retry_on) and attempt < max_retries:
                attempt += 1
                log.warning(
                    "Source %r throttled (attempt %d/%d): %s — backing off %.2fs",
                    name,
                    attempt,
                    max_retries,
                    exc,
                    backoff_delay,
                )
                if backoff_delay > 0:
                    await asyncio.sleep(backoff_delay)
                continue  # retry
            # Non-retryable exception or retries exhausted
            if retry_on and isinstance(exc, retry_on):
                reason = f"exhausted {max_retries} retries after rate-limit: {exc}"
            else:
                reason = str(exc)
            log.warning("Source %r failed permanently: %s", name, reason)
            return [], SourceError(source=name, reason=reason)


async def dispatch(
    query: str,
    sources: dict[str, Any],  # name -> SearchClient-compatible object
    *,
    max_results_per_source: int = 10,
    retry_on: tuple[type[BaseException], ...] = (),
    max_retries: int = 3,
    backoff_delay: float = 1.0,
    return_errors: bool = False,
) -> list[PaperResult] | tuple[list[PaperResult], list[SourceError]]:
    """Fan a query out to all configured sources concurrently.

    Parameters
    ----------
    query:
        Free-text search query forwarded verbatim to every adapter.
    sources:
        Mapping of *name* → adapter.  The name is used for logging and
        ``SourceError.source``; it need not match ``PaperResult.source``
        (which is set by the adapter itself).
    max_results_per_source:
        Passed through to each adapter's ``search`` call.
    retry_on:
        Tuple of exception types that trigger the backoff-retry loop.
        Typically ``(RateLimitError,)`` or ``(httpx.HTTPStatusError,)``.
        Empty tuple (default) disables retry for all exceptions.
    max_retries:
        Maximum number of retry attempts per source before giving up.
    backoff_delay:
        Seconds to wait between retry attempts.  Pass ``0.0`` in tests
        so no real sleeps occur.
    return_errors:
        When ``True``, return ``(papers, errors)`` instead of just ``papers``.

    Returns
    -------
    ``list[PaperResult]``
        (when *return_errors* is ``False``) Merged results from all sources
        that succeeded.
    ``tuple[list[PaperResult], list[SourceError]]``
        (when *return_errors* is ``True``) Merged results plus a list of
        per-source failure records.
    """
    tasks = [
        _query_with_backoff(
            name,
            client,
            query,
            max_results=max_results_per_source,
            retry_on=retry_on,
            max_retries=max_retries,
            backoff_delay=backoff_delay,
        )
        for name, client in sources.items()
    ]

    # return_exceptions=True ensures one failure never cancels sibling coroutines
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    papers: list[PaperResult] = []
    errors: list[SourceError] = []

    for name_idx, outcome in enumerate(outcomes):
        name = list(sources.keys())[name_idx]
        if isinstance(outcome, BaseException):
            # Defensive: _query_with_backoff already catches everything internally,
            # but if somehow an uncaught exception reaches here, record it too.
            err = SourceError(source=name, reason=f"unexpected: {outcome}")
            log.error("Unexpected uncaught exception from source %r: %s", name, outcome)
            errors.append(err)
        else:
            result_list, err = outcome
            papers.extend(result_list)
            if err is not None:
                errors.append(err)

    if return_errors:
        return papers, errors
    return papers
