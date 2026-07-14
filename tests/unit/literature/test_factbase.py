"""Tests for loop_sci.literature.factbase — JSON fact store + persist to idea-tree.

TDD RED phase: written before any implementation.
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path

from loop_sci.literature.extract.fact import Fact, SourceRef, VerificationStatus
from loop_sci.literature.factbase.store import FactStore
from loop_sci.literature.factbase.persist import persist_fact
from loop_sci.state.idea_tree import IdeaTree, Node


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_source_ref(n: int = 1) -> SourceRef:
    return SourceRef(source="arxiv", external_id=f"arxiv:2401.000{n}")


def _verified_fact(n: int = 1) -> Fact:
    return Fact(
        claim=f"Claim {n}",
        source_ref=_make_source_ref(n),
        evidence_span=f"Evidence text {n}",
        confidence=0.9,
        grounding_scope="abstract",
        verification=VerificationStatus(layer_reached=4, status="verified"),
    )


def _unverified_fact() -> Fact:
    return Fact(
        claim="Unverified claim",
        source_ref=SourceRef(source="arxiv", external_id="arxiv:2401.9999"),
        evidence_span="some text",
        confidence=0.4,
        grounding_scope="abstract",
        verification=VerificationStatus(layer_reached=2, status="rejected"),
    )


def _make_tree_with_paper(tmp_path: Path, paper_id: str = "paper_001") -> tuple[IdeaTree, str]:
    """Return (tree, paper_node_id) with a root and one paper node."""
    root = Node(id="ROOT", parent_id=None, hypothesis="test topic", depth=0, status="pending")
    tree = IdeaTree(root=root, json_path=tmp_path / "tree.json")
    paper_node = Node(
        id=paper_id,
        parent_id="ROOT",
        hypothesis="arXiv:2401.0001",
        depth=1,
        status="done",
    )
    tree.add_node(paper_node)
    return tree, paper_id


# ---------------------------------------------------------------------------
# FactStore tests
# ---------------------------------------------------------------------------

class TestFactStoreAddAndRetrieve:
    """Verified facts can be added and retrieved from the store."""

    def test_add_returns_fact_id(self, tmp_path):
        store = FactStore(tmp_path / "facts.json")
        f = _verified_fact(1)
        fid = store.add(f)
        assert fid is not None
        assert isinstance(fid, str)
        assert len(fid) > 0

    def test_all_returns_added_fact(self, tmp_path):
        store = FactStore(tmp_path / "facts.json")
        f = _verified_fact(1)
        store.add(f)
        all_facts = store.all()
        assert len(all_facts) == 1
        assert all_facts[0].claim == "Claim 1"

    def test_all_returns_multiple_facts(self, tmp_path):
        store = FactStore(tmp_path / "facts.json")
        store.add(_verified_fact(1))
        store.add(_verified_fact(2))
        store.add(_verified_fact(3))
        all_facts = store.all()
        assert len(all_facts) == 3
        claims = {f.claim for f in all_facts}
        assert claims == {"Claim 1", "Claim 2", "Claim 3"}

    def test_empty_store_returns_empty_list(self, tmp_path):
        store = FactStore(tmp_path / "facts.json")
        assert store.all() == []


class TestFactStoreFilter:
    """Filter interface retrieves facts by source and/or topic."""

    def test_filter_by_source_matches(self, tmp_path):
        store = FactStore(tmp_path / "facts.json")
        store.add(_verified_fact(1))
        store.add(_verified_fact(2))
        results = store.filter(source="arxiv")
        assert len(results) == 2

    def test_filter_by_source_no_match(self, tmp_path):
        store = FactStore(tmp_path / "facts.json")
        store.add(_verified_fact(1))
        results = store.filter(source="pubmed")
        assert results == []

    def test_filter_by_topic_matches(self, tmp_path):
        store = FactStore(tmp_path / "facts.json")
        store.add(_verified_fact(1))  # claim = "Claim 1"
        store.add(_verified_fact(2))  # claim = "Claim 2"
        results = store.filter(topic="Claim 1")
        assert len(results) == 1
        assert results[0].claim == "Claim 1"

    def test_filter_by_topic_no_match(self, tmp_path):
        store = FactStore(tmp_path / "facts.json")
        store.add(_verified_fact(1))
        results = store.filter(topic="nonexistent_topic_xyz")
        assert results == []

    def test_filter_by_source_and_topic_combined(self, tmp_path):
        store = FactStore(tmp_path / "facts.json")
        # fact1: arxiv source, "Claim 1"
        store.add(_verified_fact(1))
        # Add one with a different source
        different_source = Fact(
            claim="Claim 1 duplicate",
            source_ref=SourceRef(source="pubmed", external_id="pmid:111"),
            evidence_span="Evidence for pubmed fact",
            confidence=0.8,
            grounding_scope="abstract",
            verification=VerificationStatus(layer_reached=4, status="verified"),
        )
        store.add(different_source)
        results = store.filter(source="arxiv", topic="Claim 1")
        assert len(results) == 1
        assert results[0].source_ref.source == "arxiv"

    def test_filter_no_args_returns_all(self, tmp_path):
        store = FactStore(tmp_path / "facts.json")
        store.add(_verified_fact(1))
        store.add(_verified_fact(2))
        results = store.filter()
        assert len(results) == 2


class TestFactStoreJsonRoundTrip:
    """Store persists to and reloads from JSON losslessly."""

    def test_reload_reconstructs_facts(self, tmp_path):
        path = tmp_path / "facts.json"
        store = FactStore(path)
        f = _verified_fact(1)
        store.add(f)

        # Reload from disk
        reloaded_store = FactStore(path)
        all_facts = reloaded_store.all()
        assert len(all_facts) == 1
        r = all_facts[0]
        assert r.claim == "Claim 1"
        assert r.source_ref.source == "arxiv"
        assert r.source_ref.external_id == "arxiv:2401.0001"
        assert r.evidence_span == "Evidence text 1"
        assert r.confidence == 0.9
        assert r.verification is not None
        assert r.verification.status == "verified"
        assert r.verification.layer_reached == 4

    def test_reload_preserves_fact_id(self, tmp_path):
        path = tmp_path / "facts.json"
        store = FactStore(path)
        fid = store.add(_verified_fact(1))

        reloaded = FactStore(path)
        assert reloaded.all()[0].fact_id == fid

    def test_json_file_is_valid_json(self, tmp_path):
        path = tmp_path / "facts.json"
        store = FactStore(path)
        store.add(_verified_fact(1))
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(raw, list)
        assert len(raw) == 1
        assert "claim" in raw[0]

    def test_multiple_add_and_reload(self, tmp_path):
        path = tmp_path / "facts.json"
        store = FactStore(path)
        store.add(_verified_fact(1))
        store.add(_verified_fact(2))

        reloaded = FactStore(path)
        assert len(reloaded.all()) == 2


# ---------------------------------------------------------------------------
# persist_fact tests
# ---------------------------------------------------------------------------

class TestPersistFactToTreeAndStore:
    """persist_fact writes a verified fact to the idea-tree and JSON store."""

    def test_persist_adds_to_store(self, tmp_path):
        tree, paper_id = _make_tree_with_paper(tmp_path)
        store = FactStore(tmp_path / "facts.json")
        fact = _verified_fact(1)
        persist_fact(fact, tree=tree, paper_node_id=paper_id, store=store)
        assert len(store.all()) == 1

    def test_persist_returns_fact_id(self, tmp_path):
        tree, paper_id = _make_tree_with_paper(tmp_path)
        store = FactStore(tmp_path / "facts.json")
        fact_id = persist_fact(_verified_fact(1), tree=tree, paper_node_id=paper_id, store=store)
        assert fact_id is not None
        assert isinstance(fact_id, str)

    def test_persist_creates_fact_node_in_tree(self, tmp_path):
        tree, paper_id = _make_tree_with_paper(tmp_path)
        store = FactStore(tmp_path / "facts.json")
        persist_fact(_verified_fact(1), tree=tree, paper_node_id=paper_id, store=store)

        # Reload tree from disk and verify node structure
        reloaded = IdeaTree.load_json(tmp_path / "tree.json")
        paper = reloaded._nodes[paper_id]
        assert len(paper.children_ids) == 1
        fact_node = reloaded._nodes[paper.children_ids[0]]
        # Fact payload should be in refs
        assert fact_node.refs is not None
        assert fact_node.refs["claim"] == "Claim 1"

    def test_persist_fact_payload_in_refs(self, tmp_path):
        tree, paper_id = _make_tree_with_paper(tmp_path)
        store = FactStore(tmp_path / "facts.json")
        persist_fact(_verified_fact(1), tree=tree, paper_node_id=paper_id, store=store)

        reloaded = IdeaTree.load_json(tmp_path / "tree.json")
        paper = reloaded._nodes[paper_id]
        fact_node = reloaded._nodes[paper.children_ids[0]]
        refs = fact_node.refs
        assert refs["evidence_span"] == "Evidence text 1"
        assert refs["confidence"] == 0.9
        assert refs["grounding_scope"] == "abstract"

    def test_persist_fact_node_hypothesis_is_claim(self, tmp_path):
        tree, paper_id = _make_tree_with_paper(tmp_path)
        store = FactStore(tmp_path / "facts.json")
        persist_fact(_verified_fact(1), tree=tree, paper_node_id=paper_id, store=store)

        reloaded = IdeaTree.load_json(tmp_path / "tree.json")
        paper = reloaded._nodes[paper_id]
        fact_node = reloaded._nodes[paper.children_ids[0]]
        assert fact_node.hypothesis == "Claim 1"


class TestPersistRejectedFactBlocked:
    """Rejected/unverified facts MUST NOT be persisted to tree or store."""

    def test_persist_rejected_fact_raises(self, tmp_path):
        root = Node(id="ROOT", parent_id=None, hypothesis="test", depth=0, status="pending")
        tree = IdeaTree(root=root, json_path=tmp_path / "tree.json")
        store = FactStore(tmp_path / "facts.json")
        with pytest.raises(ValueError, match="only verified"):
            persist_fact(_unverified_fact(), tree=tree, paper_node_id="ROOT", store=store)

    def test_rejected_fact_not_in_store(self, tmp_path):
        root = Node(id="ROOT", parent_id=None, hypothesis="test", depth=0, status="pending")
        tree = IdeaTree(root=root, json_path=tmp_path / "tree.json")
        store = FactStore(tmp_path / "facts.json")
        try:
            persist_fact(_unverified_fact(), tree=tree, paper_node_id="ROOT", store=store)
        except ValueError:
            pass
        assert len(store.all()) == 0

    def test_rejected_fact_not_in_tree(self, tmp_path):
        root = Node(id="ROOT", parent_id=None, hypothesis="test", depth=0, status="pending")
        tree = IdeaTree(root=root, json_path=tmp_path / "tree.json")
        store = FactStore(tmp_path / "facts.json")
        try:
            persist_fact(_unverified_fact(), tree=tree, paper_node_id="ROOT", store=store)
        except ValueError:
            pass
        # ROOT should still have no children
        assert len(root.children_ids) == 0

    def test_pending_fact_raises(self, tmp_path):
        pending = Fact(
            claim="Pending claim",
            source_ref=SourceRef(source="arxiv", external_id="arxiv:0000.0001"),
            evidence_span="Some evidence here",
            confidence=0.7,
            grounding_scope="abstract",
            verification=VerificationStatus(layer_reached=1, status="pending"),
        )
        root = Node(id="ROOT", parent_id=None, hypothesis="test", depth=0, status="pending")
        tree = IdeaTree(root=root, json_path=tmp_path / "tree.json")
        store = FactStore(tmp_path / "facts.json")
        with pytest.raises(ValueError, match="only verified"):
            persist_fact(pending, tree=tree, paper_node_id="ROOT", store=store)

    def test_no_verification_fact_raises(self, tmp_path):
        no_verify = Fact(
            claim="No verification claim",
            source_ref=SourceRef(source="arxiv", external_id="arxiv:0000.0002"),
            evidence_span="Some evidence here",
            confidence=0.7,
            grounding_scope="abstract",
            verification=None,
        )
        root = Node(id="ROOT", parent_id=None, hypothesis="test", depth=0, status="pending")
        tree = IdeaTree(root=root, json_path=tmp_path / "tree.json")
        store = FactStore(tmp_path / "facts.json")
        with pytest.raises(ValueError, match="only verified"):
            persist_fact(no_verify, tree=tree, paper_node_id="ROOT", store=store)


class TestPersistDedup:
    """Two facts from the same paper are placed under the same paper node."""

    def test_two_facts_same_paper_node_two_fact_nodes(self, tmp_path):
        tree, paper_id = _make_tree_with_paper(tmp_path)
        store = FactStore(tmp_path / "facts.json")

        # Both facts go under the same paper_id — caller responsibility
        persist_fact(_verified_fact(1), tree=tree, paper_node_id=paper_id, store=store)
        persist_fact(_verified_fact(2), tree=tree, paper_node_id=paper_id, store=store)

        reloaded = IdeaTree.load_json(tmp_path / "tree.json")
        paper = reloaded._nodes[paper_id]
        # One paper node, two fact children
        assert len(paper.children_ids) == 2
        claims = {reloaded._nodes[cid].hypothesis for cid in paper.children_ids}
        assert claims == {"Claim 1", "Claim 2"}

    def test_two_facts_same_paper_two_store_entries(self, tmp_path):
        tree, paper_id = _make_tree_with_paper(tmp_path)
        store = FactStore(tmp_path / "facts.json")
        persist_fact(_verified_fact(1), tree=tree, paper_node_id=paper_id, store=store)
        persist_fact(_verified_fact(2), tree=tree, paper_node_id=paper_id, store=store)
        assert len(store.all()) == 2
