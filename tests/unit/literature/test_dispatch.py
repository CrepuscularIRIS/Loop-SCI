"""Tests for multi-source dispatch — fan-out, backoff, graceful degradation.

All tests are OFFLINE: no real network calls, no real sleeps.
Delays are injected via a zero-second backoff strategy.
"""
from __future__ import annotations

import asyncio

import pytest

from loop_sci.literature.search.schema import PaperResult

# dispatch.py doesn't exist yet — these imports will fail (RED phase)
from loop_sci.literature.search.dispatch import dispatch, SourceError


# ---------------------------------------------------------------------------
# Helpers / stub adapters
# ---------------------------------------------------------------------------


def _make_paper(source: str, n: int) -> PaperResult:
    return PaperResult(
        source=source,
        external_id=f"{source}:{n}",
        title=f"Paper {n}",
        authors=["A"],
        year=2024,
        venue=None,
        abstract="abs",
        url=None,
    )


class OkClient:
    """Stub adapter that always succeeds, returning one result tagged with source."""

    def __init__(self, source: str) -> None:
        self._source = source

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        return [_make_paper(self._source, 1)]

    async def fetch_by_id(self, eid: str) -> PaperResult | None:
        return None


class FailClient:
    """Stub adapter that always raises RuntimeError."""

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        raise RuntimeError("API unavailable")

    async def fetch_by_id(self, eid: str) -> PaperResult | None:
        return None


class ThrottleClient:
    """Stub adapter that raises 429-like RateLimitError twice then succeeds.

    Uses a call counter to simulate transient throttling without any real sleep.
    """

    def __init__(self, source: str, fail_times: int = 2) -> None:
        self._source = source
        self._calls = 0
        self._fail_times = fail_times

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        self._calls += 1
        if self._calls <= self._fail_times:
            raise RateLimitError("429 Too Many Requests")
        return [_make_paper(self._source, 1)]

    async def fetch_by_id(self, eid: str) -> PaperResult | None:
        return None


class RateLimitError(Exception):
    """Simulated 429 / rate-limit exception raised by ThrottleClient."""


# ---------------------------------------------------------------------------
# Tests — multi-source fan-out
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_multi_source_all_succeed() -> None:
    """Querying multiple OK sources returns merged results tagged by source."""
    sources = {
        "ss": OkClient("semantic_scholar"),
        "arxiv": OkClient("arxiv"),
    }
    results = await dispatch("spikes", sources)
    assert len(results) == 2
    srcs = {r.source for r in results}
    assert srcs == {"semantic_scholar", "arxiv"}


@pytest.mark.asyncio
async def test_dispatch_single_source_targeted() -> None:
    """When only one source is configured only that source's results are returned."""
    sources = {"ss": OkClient("semantic_scholar")}
    results = await dispatch("spikes", sources)
    assert len(results) == 1
    assert results[0].source == "semantic_scholar"


# ---------------------------------------------------------------------------
# Tests — graceful degradation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_degrades_gracefully_on_one_failure() -> None:
    """One failing source does not raise to the caller; successful results are returned."""
    sources = {
        "ss": OkClient("semantic_scholar"),
        "fail": FailClient(),
    }
    # Must NOT raise; one failure must not abort the multi-source fan-out
    results = await dispatch("spikes", sources)
    assert len(results) == 1
    assert results[0].source == "semantic_scholar"


@pytest.mark.asyncio
async def test_dispatch_returns_error_records_when_requested() -> None:
    """return_errors=True → (results, [SourceError(...)]); SourceError captures source+reason."""
    sources = {
        "ss": OkClient("semantic_scholar"),
        "fail": FailClient(),
    }
    result_tuple = await dispatch("spikes", sources, return_errors=True)
    papers, errors = result_tuple
    assert len(papers) == 1
    assert papers[0].source == "semantic_scholar"
    assert len(errors) == 1
    assert isinstance(errors[0], SourceError)
    assert errors[0].source == "fail"
    assert "unavailable" in errors[0].reason.lower()


@pytest.mark.asyncio
async def test_dispatch_all_fail_returns_empty_not_raises() -> None:
    """When ALL sources fail, returns empty list (no exception) with errors recorded."""
    sources = {"a": FailClient(), "b": FailClient()}
    result_tuple = await dispatch("q", sources, return_errors=True)
    papers, errors = result_tuple
    assert papers == []
    assert len(errors) == 2


@pytest.mark.asyncio
async def test_dispatch_siblings_not_cancelled_on_failure() -> None:
    """A failure in one source does NOT cancel or interrupt sibling tasks."""
    # OkClient uses asyncio to simulate concurrent work; FailClient raises immediately.
    # We track that OkClient.search actually completed (result is present).
    completed: list[str] = []

    class TrackingOkClient:
        def __init__(self, source: str) -> None:
            self._source = source

        async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
            await asyncio.sleep(0)  # yield to event loop — simulate async work
            completed.append(self._source)
            return [_make_paper(self._source, 1)]

        async def fetch_by_id(self, eid: str) -> PaperResult | None:
            return None

    class ImmediateFailClient:
        async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
            raise RuntimeError("boom")

        async def fetch_by_id(self, eid: str) -> PaperResult | None:
            return None

    sources = {
        "good": TrackingOkClient("arxiv"),
        "bad": ImmediateFailClient(),
    }
    results = await dispatch("spikes", sources)
    # Sibling completed despite the failure
    assert "arxiv" in completed
    assert any(r.source == "arxiv" for r in results)


# ---------------------------------------------------------------------------
# Tests — rate-limit backoff
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_backoff_then_success() -> None:
    """A throttled source gets retried (with zero-delay injected) and eventually succeeds."""
    throttle = ThrottleClient("pubmed", fail_times=2)
    sources = {"pm": throttle}
    results = await dispatch(
        "spikes",
        sources,
        retry_on=(RateLimitError,),  # inject: which exceptions trigger retry
        max_retries=3,
        backoff_delay=0.0,  # inject: zero delay so test is instant
    )
    assert len(results) == 1
    assert results[0].source == "pubmed"
    assert throttle._calls == 3  # 2 failures + 1 success


@pytest.mark.asyncio
async def test_dispatch_exhausted_retries_degrades_gracefully() -> None:
    """Exhausting retries records a SourceError and does not raise to caller."""
    throttle = ThrottleClient("pubmed", fail_times=99)  # will never succeed within retry budget
    ok = OkClient("arxiv")
    sources = {"pm": throttle, "arxiv": ok}
    result_tuple = await dispatch(
        "spikes",
        sources,
        retry_on=(RateLimitError,),
        max_retries=2,
        backoff_delay=0.0,
        return_errors=True,
    )
    papers, errors = result_tuple
    # arxiv succeeded
    assert any(r.source == "arxiv" for r in papers)
    # pubmed recorded as error after exhausting retries
    assert any(e.source == "pm" for e in errors)
    pm_err = next(e for e in errors if e.source == "pm")
    assert "retry" in pm_err.reason.lower() or "429" in pm_err.reason.lower() or "requests" in pm_err.reason.lower()


@pytest.mark.asyncio
async def test_dispatch_max_results_forwarded() -> None:
    """max_results_per_source is forwarded to each adapter's search call."""
    received_max: list[int] = []

    class CapturingClient:
        async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
            received_max.append(max_results)
            return []

        async def fetch_by_id(self, eid: str) -> PaperResult | None:
            return None

    sources = {"c": CapturingClient()}
    await dispatch("q", sources, max_results_per_source=7)
    assert received_max == [7]
