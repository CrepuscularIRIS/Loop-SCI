# Task 7 Report: Idea-tree state layer

## Decision: `refs` — Real Persisted Subclass

**Chose: PREFERRED option — real persisted field via thin Node subclass.**

Rationale: The brief's monkey-patch approach (`_VendorNode.__init__` patching + annotation injection) sets `refs` as a runtime attribute at object construction, but `to_dict()` in the vendored Node only serializes the known fields listed in its body, and `from_dict()` uses a fixed constructor call. A monkey-patched attribute is never written to JSON and is never restored on load — it silently drops. A test that only does `node.refs = {...}; assert node.refs[...]` passes trivially without exercising persistence at all, creating false confidence.

Instead, `loop_sci/state/idea_tree.py` defines:

```python
@dataclass
class Node(_VendorNode):
    refs: dict[str, Any] | None = field(default=None)

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        if self.refs is not None:
            d["refs"] = dict(self.refs)
        return d

    @classmethod
    def from_dict(cls, data) -> "Node":
        base = _VendorNode.from_dict(data)
        return cls(...all base fields..., refs=data.get("refs"))
```

This means `refs` survives a `save() → load_json()` round trip. The test `test_refs_field_round_trips` verifies this explicitly.

## Atomic-Write Test Alignment

`_atomic_write` in the vendored code uses:
```python
tmp = path.with_suffix(path.suffix + ".tmp")
```
For `idea_tree.json`, `path.suffix` is `.json`, so `.json` + `.tmp` = `.json.tmp`.
`path.with_suffix(".json.tmp")` produces `idea_tree.json.tmp`.

The test uses the same expression:
```python
tmp_file = path.with_suffix(path.suffix + ".tmp")  # idea_tree.json.tmp
```
This mirrors the real implementation rather than guessing a filename.

## Accessors Re-Exported vs Added

All accessor and mutation methods (`get_node`, `get_root`, `get_children`, `get_all_nodes`, `get_nodes_by_status`, `get_pending_leaves`, `add_node`, `update_node`, `next_child_id`, `save`, `load_json`) already exist on the vendored `IdeaTree`. The state layer re-exports them without reimplementation, except:

- `IdeaTree.load_json` is overridden to use `Node.from_dict` (our subclass) so that loaded nodes carry `refs`.
- The vendored `Node` is subclassed to add `refs` with real serialization.

No vendored files were modified.

## `state/__init__.py` — RunSession Deferred

`state/__init__.py` exports only `Node`, `IdeaTree`, `NodeStatus`. `RunSession` import is deferred to Task 8 to avoid an `ImportError` since `session.py` does not yet exist.

## Brief's `test_child_id_is_derivable` Correction

The brief's version called `next_child_id("ROOT")` twice before any add and asserted `id1 != id2`. That is impossible: `next_child_id` is purely deterministic on tree state; without an intervening mutation both calls return `"1"`. The test was corrected to:
1. Assert `next_child_id` is idempotent before mutation (both calls → same `id1`).
2. Add the child with `id1`, then assert the next call returns a different (incremented) `id2`.
3. Assert a second call without further mutation returns the same `id2`.

This correctly tests the "derivable" property.

## Test Results

10/10 passed. Full suite: 73/73 passed (no regressions).

## TDD RED/GREEN Evidence

- RED: `ModuleNotFoundError: No module named 'loop_sci.state'` — confirmed before implementation.
- GREEN: All 10 tests pass after implementing the subclass + `__init__.py`.
- One test needed correction (see above) before final green.

## Files Changed

- Created: `loop_sci/state/__init__.py`
- Created: `loop_sci/state/idea_tree.py`
- Created: `tests/unit/test_idea_tree.py`

## Self-Review

- No vendored files modified.
- `session.py` not created (Task 8's responsibility).
- `refs` round-trips verified by a test that saves then reloads the tree.
- Atomic-write test aligned to real `_atomic_write` temp-file naming.
- `get_pending_leaves` correctly requires `depth > 0` (mirrors vendored behavior).

## Concerns

- The `Node` subclass adds `refs` as a dataclass field after parent fields. Python dataclasses require fields with defaults to come after fields without defaults. The parent `Node` has fields without defaults (`id`, `parent_id`), then fields with defaults. Since our `refs` has a default (`None`), it must appear after all required fields — which it does.
- `IdeaTree.load_json` is duplicated from the vendor (minor maintenance burden), but is necessary to swap in `Node.from_dict` without modifying vendor code.
- `MUTABLE_FIELDS` on the vendored Node does not include `refs`, so `update_node(node_id, refs=...)` will raise `ValueError`. Users must set `refs` directly on the node object. This is acceptable for now; Task 8 can add `refs` to `MUTABLE_FIELDS` if needed via the subclass.
