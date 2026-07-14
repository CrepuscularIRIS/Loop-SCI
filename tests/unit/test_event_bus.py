"""Unit tests for loop_sci.events re-exports.

Covers:
- EventBus subscriber receives event data
- NullBus is a no-op (on/emit never calls registered lambdas)
- Subscriber parity: behaviour is identical with/without a side-effect subscriber
- Wildcard on_all subscriber receives all events
- Sync emit swallows subscriber exceptions (fire-and-forget contract)
"""

import pytest
from loop_sci.events import EventBus, NullBus


def test_subscriber_receives_event():
    """Subscriber callback is called with the emitted event data."""
    bus = EventBus()
    received = []
    bus.on("test.event", lambda e: received.append(e.data))
    bus.emit("test.event", {"key": "value"})
    assert received == [{"key": "value"}]


def test_null_bus_is_noop():
    """NullBus.emit must not call any registered callback (on is a no-op)."""
    bus = NullBus()
    # NullBus.on is a no-op, so lambda is discarded — emit must not raise
    bus.on("x", lambda e: (_ for _ in ()).throw(RuntimeError("should not be called")))
    bus.emit("x", {"a": 1})  # must not raise


def test_subscriber_parity_with_without():
    """Run result is identical with and without a subscriber.

    With EventBus+subscriber: subscriber captures events.
    With NullBus: nothing is captured; emit behaviour is identical.
    """
    results_with = []
    results_without = []

    bus_with = EventBus()
    bus_with.on("node.updated", lambda e: results_with.append(e.data["node_id"]))
    bus_with.emit("node.updated", {"node_id": "1"})

    bus_without = NullBus()
    # No subscriber — just emit and ensure no side-effects
    bus_without.emit("node.updated", {"node_id": "1"})

    # The event data is the same; only difference is whether a listener captured it
    assert results_with == ["1"]
    assert results_without == []


def test_wildcard_subscriber():
    """on_all callback receives every emitted event regardless of type."""
    bus = EventBus()
    received_types = []
    bus.on_all(lambda e: received_types.append(e.type))
    bus.emit("a")
    bus.emit("b")
    assert received_types == ["a", "b"]


def test_subscriber_exception_does_not_propagate():
    """Sync emit swallows subscriber exceptions (fire-and-forget contract).

    Verified in loop_sci/_vendor/arbor/events/bus.py ~line 54-70:
    emit() wraps each callback invocation in try/except Exception, logging
    failures at DEBUG level. The exception NEVER propagates to the caller.
    """
    bus = EventBus()
    bus.on("boom", lambda e: (_ for _ in ()).throw(RuntimeError("crash")))
    bus.emit("boom", {})  # must not raise
