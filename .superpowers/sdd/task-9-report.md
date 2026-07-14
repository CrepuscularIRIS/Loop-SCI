# Task 9 Report: Event bus re-export + subscriber-parity test

## What was re-exported

`loop_sci/events/__init__.py` re-exports the following from the vendored sources
(no reimplementation — pure re-export):

From `loop_sci._vendor.arbor.events.bus`:
- `Event` — dataclass with `.type: str`, `.data: dict`, `.timestamp: float`
- `EventBus` — full pub/sub bus with `on`, `on_all`, `off`, `emit`, `aemit`
- `NullBus` — no-op drop-in with matching interface

From `loop_sci._vendor.arbor.events.types`:
- `IDEA_PROPOSED`, `IDEA_COMPLETED`, `IDEA_PRUNED`, `IDEA_MERGED`
- `EXECUTOR_START`, `EXECUTOR_END`
- `SESSION_START`, `SESSION_END`

## ACTUAL sync-emit exception behavior

Read `bus.py` lines 54–70 directly. The SYNC `emit` method wraps **each** callback
invocation in `try/except Exception`, logging failures at DEBUG level:

```python
for cb in self._collect(event_type):
    try:
        if asyncio.iscoroutinefunction(cb):
            self._schedule_async(cb, event)
        else:
            cb(event)
    except Exception:
        log.debug("event subscriber failed for %s", event_type, exc_info=True)
```

The docstring also states explicitly: "Subscriber exceptions are swallowed —
core must never crash because a logger blew up."

**Conclusion:** The brief's `test_subscriber_exception_does_not_propagate` is
**correct** as written. Sync emit DOES swallow exceptions. No test adjustment
was needed; we kept the test and added a comment in the test file citing the
exact lines verified.

## TDD RED → GREEN

1. **RED**: Wrote `tests/unit/test_event_bus.py` (5 tests) before creating
   `loop_sci/events/__init__.py`. Ran pytest — got:
   `ModuleNotFoundError: No module named 'loop_sci.events'`
   All 5 tests collected 0 items / 1 error. RED confirmed.

2. **GREEN**: Created `loop_sci/events/__init__.py` with pure re-exports.
   Ran pytest — all 5 passed in 0.01s.

3. **Full suite**: 84/84 passed (0 regressions).

## Test results

```
tests/unit/test_event_bus.py::test_subscriber_receives_event         PASSED
tests/unit/test_event_bus.py::test_null_bus_is_noop                  PASSED
tests/unit/test_event_bus.py::test_subscriber_parity_with_without    PASSED
tests/unit/test_event_bus.py::test_wildcard_subscriber               PASSED
tests/unit/test_event_bus.py::test_subscriber_exception_does_not_propagate PASSED

5 passed in 0.01s
84 passed in 0.74s (full suite)
```

## Files changed

| File | Action |
|------|--------|
| `loop_sci/events/__init__.py` | Created (re-export module) |
| `tests/unit/test_event_bus.py` | Created (5 unit tests) |

No vendored files were modified.

## Self-review

- Re-export is a thin facade — no logic introduced.
- `__all__` is explicit; downstream `from loop_sci.events import *` stays clean.
- NullBus test uses the fact that `NullBus.on` is itself a no-op (discards
  the callback), so the lambda never runs even if emit were called with data.
- Subscriber-parity test uses EventBus for the "with" side and NullBus for the
  "without" side, honestly demonstrating that the emitter's behaviour is
  identical regardless of observers.
- Exception-swallow test confirmed against actual vendored implementation before
  writing; comment in test cites the exact file and line range.

## Concerns

None. The vendored bus.py's contract (exception-swallowing, fire-and-forget)
is clearly documented in its own docstring and matches the test expectations.
The re-export is minimal and stable.
