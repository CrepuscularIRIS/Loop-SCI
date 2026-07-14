# Task 12 Report: Coordinator — Keystone Loop

## Status: DONE

---

## ROOT Bootstrap Choice

**Choice (a):** When `get_pending_leaves()` returns `[]` but ROOT is still `pending`, dispatch ROOT itself.

**Rationale:** This is the simplest correct design. A fresh session always has a pending ROOT at depth 0. `get_pending_leaves()` explicitly excludes `depth == 0` nodes, so a naive loop would do nothing. By returning `root` as the fallback in `_observe()`, we guarantee ≥1 cycle runs on any fresh stub session without seeding extra nodes. After ROOT is recorded done, the loop re-checks `get_pending_leaves()` — if new children were added (by a future ideation layer), they'd be dispatched next. No extra `add_node` calls needed in the foundation.

---

## Record / Persist Approach

- **Mutable fields (status, score, insight):** called via `session.tree.update_node(node_id, **updates)` which applies the vendor `MUTABLE_FIELDS` whitelist and auto-calls `save()` internally.
- **refs field:** NOT in the vendor `MUTABLE_FIELDS` — `update_node(refs=...)` would raise `ValueError`. Solution: set `node.refs = result.refs` directly, then call `session.tree.save()` explicitly. This persists the full node including refs before the next decision (invariant maintained). No vendored file was modified.
- **Persist before decide invariant:** `_record()` is called before `session.advance_step()` and the next `_observe()` call. The loop only reads the tree after a full persist cycle.

---

## Executor Injection for Tests

The `Coordinator.__init__` accepts an optional `executor=` keyword argument. When provided, it is used directly (test seam). When None, a real `Executor` is constructed from `cfg`. Tests inject a `StubExecutor` whose `async run()` returns scripted `ExecutorResult` objects — no network, no LLM, no patching needed.

```python
coordinator = Coordinator(cfg=None, executor=StubExecutor([...]), step_budget=5)
```

---

## Step Budget + Finalize Logic

- Loop condition: `while steps < self.step_budget`
- `steps` incremented after each `_record()` + `advance_step()` call
- On budget exhaustion or when `_observe()` returns `None` (no pending work): exits the while loop
- `session.mark_complete()` is called unconditionally after the loop — budget exhaustion still marks the session complete
- `error` and `bounded_exit` results are recorded as `needs_retry` and the loop continues to the next pending node (no early exit on executor failure)

---

## Event Emission

Per-cycle events emitted (fire-and-forget, never block):
- `SESSION_START` at start of `run()`
- `EXECUTOR_START` before each `executor.run()` call
- `EXECUTOR_END` after each `_record()` call
- `SESSION_END` at end of `run()` with total steps count

`NullBus` (default) silently drops all events — zero behavior change when no subscriber is wired.

---

## TDD: RED → GREEN

**RED:** Wrote 10 tests in `tests/unit/test_coordinator.py` before any production code. Verified all 10 failed with `ModuleNotFoundError: No module named 'loop_sci.engine.coordinator'` — correct failure for the right reason.

**GREEN:** Implemented `loop_sci/engine/coordinator.py`. All 10 tests pass immediately. No test was modified during implementation.

---

## Test Results

```
tests/unit/test_coordinator.py — 10 passed in 0.34s
tests/unit/ (full suite) — 119 passed in 0.76s (zero failures, zero warnings)
```

Tests cover:
1. One full observe→dispatch→record cycle on a fresh stub session
2. Dispatched node recorded as `done` in tree
3. Tree persisted to disk before session marked complete (verified via reload)
4. Step budget stops loop after N steps
5. `EXECUTOR_START` + `EXECUTOR_END` events received by subscriber
6. `SESSION_START` + `SESSION_END` lifecycle events emitted
7. NullBus vs real EventBus behavior parity (same node statuses, same call counts)
8. `error` result recorded and loop continues to next pending node
9. Already-complete session is a no-op (executor never called)
10. `refs` dict persisted to disk and reloaded correctly

---

## Files Changed

| File | Action |
|------|--------|
| `loop_sci/engine/coordinator.py` | Created |
| `loop_sci/engine/__init__.py` | Updated: added `Coordinator` export |
| `tests/unit/test_coordinator.py` | Created |

No vendored files were modified. `loop_sci/state/idea_tree.py` was not modified — refs are handled by direct attribute set + explicit `save()`.

---

## Self-Review

- Control flow is deterministic and simple
- Bootstrap (dispatch ROOT) is explicit and documented in module docstring
- `refs` handling is explicit: direct set + `save()` call (no silent drop)
- Executor injection is clean: test stub vs real executor via same `executor=` kwarg
- Step budget defaults to 10; can be overridden via `cfg.engine.step_budget` or kwarg
- `mark_complete()` always called (budget exhaustion still finalizes the session)
- Events are fire-and-forget; NullBus swallows them without side effects

## Concerns

None. The design is minimal and correct. Tasks 13 (integration) and 16 (e2e) can exercise it without modification to this file.
