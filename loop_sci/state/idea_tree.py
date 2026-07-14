"""State layer over the vendored IdeaTree/Node.

Re-exports IdeaTree and NodeStatus from the vendor.
Provides a Node subclass that adds a generic ``refs`` dict field that
round-trips through save/load_json (unlike a monkey-patched attribute,
which would be silently dropped by the vendor's to_dict/from_dict).

The IdeaTree exported here is patched to use this Node subclass so that
load_json returns Node instances with refs support.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loop_sci._vendor.arbor.idea_tree import (
    IdeaTree as _VendorIdeaTree,
    Node as _VendorNode,
    NodeStatus,
)

__all__ = ["Node", "IdeaTree", "NodeStatus"]


# ---------------------------------------------------------------------------
# Node subclass — adds generic refs dict that persists through save/reload
# ---------------------------------------------------------------------------

@dataclass
class Node(_VendorNode):
    """Vendored Node extended with a generic ``refs`` dict.

    ``refs`` round-trips through IdeaTree.save() / IdeaTree.load_json() so
    callers can attach arbitrary cross-system references (git branch, S3
    artifact path, run-id, …) alongside the existing ``code_ref`` field.
    """

    refs: dict[str, Any] | None = field(default=None)

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        if self.refs is not None:
            d["refs"] = dict(self.refs)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Node":  # type: ignore[override]
        # Build the base node via _VendorNode.from_dict, then wrap in our class.
        base = _VendorNode.from_dict(data)
        node = cls(
            id=base.id,
            parent_id=base.parent_id,
            children_ids=list(base.children_ids),
            depth=base.depth,
            hypothesis=base.hypothesis,
            status=base.status,
            insight=base.insight,
            result=base.result,
            score=base.score,
            score_split=base.score_split,
            test_score=base.test_score,
            code_ref=base.code_ref,
            related_work=base.related_work,
            grounding=base.grounding,
            eval_status=base.eval_status,
            stop_reason=base.stop_reason,
            attempt=base.attempt,
            refs=data.get("refs"),
        )
        return node


# ---------------------------------------------------------------------------
# IdeaTree subclass — uses our Node in load_json so refs is preserved
# ---------------------------------------------------------------------------

class IdeaTree(_VendorIdeaTree):
    """Re-export of the vendored IdeaTree, wired to use the extended Node."""

    @classmethod
    def load_json(cls, path: Path) -> "IdeaTree":  # type: ignore[override]
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        root_id = data["root_id"]
        root_node = Node.from_dict(data["nodes"][root_id])
        tree = cls(
            root=root_node,
            json_path=path,
            md_path=path.with_suffix(".md"),
            max_depth=data.get("max_depth"),
        )
        loaded_meta = data.get("meta", {})
        tree.meta = {**tree._default_meta(), **loaded_meta}
        for nid, ndata in data["nodes"].items():
            if nid != root_id:
                tree._nodes[nid] = Node.from_dict(ndata)
        return tree
