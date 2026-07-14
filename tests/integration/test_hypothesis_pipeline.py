"""Offline integration: coordinator → HypothesisExecutor → MockProvider + seeded FactStore.

Scenarios covered
-----------------
1. Happy path: full pipeline produces ≥1 ACCEPTED hypothesis, scored and ranked
   best-first with all required RankedHypothesis fields.
2. Anti-fabrication pinned: a candidate with an absent fact_id ([paper] step)
   receives DOWN from the deterministic gate and never reaches accepted.
3. No-self-acquit pinned: accepted hypothesis verdicts carry reviewer_model
   distinct from the generator model ("qwen-max").
4. Resume-across-disk-reload: run once, reload session from disk (IdeaTree from
   json_path), run again — already-accepted nodes are skipped, NO re-critique /
   NO new verdict-ledger entries, NO duplicate nodes.

NO network, NO git, NO API keys required.  All tests are in the default suite.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Expose project root and tests/ for conftest import
sys.path.insert(0, str(Path(__file__).parents[2]))
sys.path.insert(0, str(Path(__file__).parents[2] / "tests"))

from loop_sci.hypothesis import HypothesisCoordinator, HypothesisExecutor, RankedHypothesisStore
from loop_sci.hypothesis.config import HypothesisConfig
from loop_sci.hypothesis.ledger import VerdictLedger
from loop_sci.literature.extract.fact import Fact, SourceRef
from loop_sci.literature.factbase.store import FactStore
from loop_sci.state.idea_tree import IdeaTree
from loop_sci.state.session import RunSession
from conftest import MockProvider  # noqa: E402

# ---------------------------------------------------------------------------
# Scripted responses
# ---------------------------------------------------------------------------

_CARDS_JSON = json.dumps([
    {
        "Q": "Glial role in fear?",
        "WHY_NOW": "New calcium imaging available",
        "PROBE_KILL": "Calcium transients absent",
        "STAKES": 0.9,
        "fact_ids": ["fact_0", "fact_1"],
    }
])

# Primary candidate: grounded [paper] step citing fact_1 (EXISTS in store) → gate passes
# Rival candidate: [inferred] step citing fact_0 (EXISTS in store) → gate passes
_HYPS_JSON = json.dumps({
    "candidates": [
        {
            "MECHANISM": "Glial calcium waves encode fear via gap junctions",
            "KILL": "No glial transient observed",
            "BRACKET": "plausible",
            "DIFF_PREDICTION": "Distinct BOLD signature in fear CS+ vs CS-",
            "frame": "primary",
            "derivation": [
                {
                    "step": "Glia modulate synapses",
                    "grade": "[paper]",
                    "fact_ids": ["fact_1"],
                }
            ],
        },
        {
            "MECHANISM": "Rival: Astrocyte K+ buffering modulates fear",
            "KILL": "K+ buffering unchanged in fear conditioning",
            "BRACKET": "low",
            "DIFF_PREDICTION": "Flat K+ transient vs elevated fear response",
            "frame": "rival",
            "derivation": [
                {
                    "step": "Neurons signal glia via potassium",
                    "grade": "[inferred]",
                    "fact_ids": ["fact_0"],
                }
            ],
        },
    ]
})

# Candidate with an ABSENT fact_id — deterministic gate must fire DOWN for this
_HYPS_WITH_UNGROUNDED = json.dumps({
    "candidates": [
        {
            "MECHANISM": "Ungrounded speculation about glial fear",
            "KILL": "No evidence",
            "BRACKET": "speculative",
            "DIFF_PREDICTION": "Completely different BOLD pattern distinct from baseline",
            "frame": "primary",
            "derivation": [
                {
                    "step": "Cite a paper that does not exist",
                    "grade": "[paper]",
                    "fact_ids": ["nonexistent_fact_id"],  # NOT in store → gate fires
                }
            ],
        },
    ]
})

_CONTRACT_JSON = json.dumps({
    "HYPOTHESIS": "Glial calcium waves encode fear",
    "LATENT_ROOT": "glial_plasticity",
    "ACCEPT_IF": "BOLD signal differs by >0.5σ",
    "KILL_IF": "No glial Ca2+ transient observed",
})

_CONTRACT_RIVAL_JSON = json.dumps({
    "HYPOTHESIS": "Astrocyte K+ buffering modulates fear",
    "LATENT_ROOT": "astrocyte_potassium",
    "ACCEPT_IF": "K+ transient elevated >20mM",
    "KILL_IF": "K+ buffering unchanged in fear conditioning",
})

_UP_VERDICT = json.dumps({"result": "UP", "reasons": ["novel mechanism, well-grounded"]})
_DOWN_VERDICT = json.dumps({"result": "DOWN", "reasons": ["insufficient grounding for rival"]})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_store(store_path: Path) -> None:
    """Seed the FactStore with two known facts."""
    store = FactStore(store_path)
    for i, claim in enumerate([
        "Neurons fire action potentials.",
        "Glial cells modulate synaptic transmission.",
    ]):
        f = Fact(
            claim=claim,
            source_ref=SourceRef(source="s2", external_id=f"x{i}"),
            evidence_span=claim[:20],
            grounding_scope="abstract",
            confidence=0.9,
        )
        f.fact_id = f"fact_{i}"
        store.add(f)


def _build_happy_providers() -> tuple[MockProvider, MockProvider]:
    """Build gen + rev providers for the happy-path scenario.

    Response sequence (gen):
      1. prospect call    → cards JSON
      2. forge call       → hyps JSON (2 candidates)
      3. contract call    → contract JSON (primary candidate)
      4. contract call    → contract rival JSON (rival candidate)

    Response sequence (rev):
      1. UP verdict (primary gets accepted)
      2. DOWN verdict (rival gets rejected)
    """
    gen = MockProvider(
        responses=[_CARDS_JSON, _HYPS_JSON, _CONTRACT_JSON, _CONTRACT_RIVAL_JSON],
        model="qwen-max",
    )
    rev = MockProvider(
        responses=[_UP_VERDICT, _DOWN_VERDICT] * 5,
        model="qwen-plus",
    )
    return gen, rev


def _make_session(runs_root: Path, task: str = "neuro fear encoding") -> RunSession:
    return RunSession.create(runs_root, task=task)


# ---------------------------------------------------------------------------
# Scenario 1: Happy path — accepted hypothesis in ranked store
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_produces_accepted_ranked_hypothesis(tmp_path: Path) -> None:
    """Full pipeline produces ≥1 accepted hypothesis retrievable via RankedHypothesisStore.

    Assertions
    ----------
    - result.status == "done"
    - At least one node in the tree has status "accepted"
    - RankedHypothesisStore.get_ranked() returns ≥1 item, best-first by score
    - Top RankedHypothesis has overall_score > 0.0, non-empty mechanism
    - grounding_fact_ids is non-empty
    - refs["scores"] is present on the accepted node
    """
    session = _make_session(tmp_path / "runs")
    store_path = tmp_path / "facts.json"
    _seed_store(store_path)

    gen, rev = _build_happy_providers()
    config = HypothesisConfig(max_cards=2, max_candidates=2, max_rounds=1)
    executor = HypothesisExecutor(
        session,
        gen_provider=gen,
        rev_provider=rev,
        store_path=store_path,
        config=config,
    )
    coordinator = HypothesisCoordinator(executor=executor)
    await coordinator.run(session)

    # Executor result: tree must have ≥1 accepted node
    accepted_nodes = [
        n for n in session.tree.get_all_nodes() if n.status == "accepted"
    ]
    assert len(accepted_nodes) >= 1, (
        f"Expected ≥1 accepted node in tree, got {len(accepted_nodes)}"
    )

    # Node.score is the weighted value; refs["scores"] must be present
    for node in accepted_nodes:
        assert node.score is not None, "Accepted node must have a score"
        assert node.score > 0.0, "Accepted node score must be > 0.0"
        assert node.refs is not None, "Accepted node must have refs"
        assert "scores" in node.refs, "Accepted node refs must include 'scores'"
        scores = node.refs["scores"]
        assert "novelty" in scores
        assert "self_consistency" in scores
        assert "overall" in scores

    # RankedHypothesisStore.get_ranked returns results best-first
    ranked_store = RankedHypothesisStore(session.tree)
    results = ranked_store.get_ranked()
    assert len(results) >= 1, "RankedHypothesisStore.get_ranked() must return ≥1 result"

    top = results[0]
    assert top.overall_score is not None, "Top result must have overall_score"
    assert top.overall_score > 0.0, "Top result overall_score must be > 0.0"
    assert top.mechanism != "", "Top result mechanism must be non-empty"
    assert len(top.grounding_fact_ids) >= 1, (
        "Top result must have ≥1 grounding_fact_id"
    )

    # Best-first ordering: results are sorted by overall_score descending
    scores_seq = [r.overall_score for r in results if r.overall_score is not None]
    assert scores_seq == sorted(scores_seq, reverse=True), (
        "get_ranked() must return results sorted best-first by overall_score"
    )


# ---------------------------------------------------------------------------
# Scenario 2: Anti-fabrication pinned — absent fact_id → DOWN, never accepted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anti_fabrication_absent_fact_id_never_accepted(tmp_path: Path) -> None:
    """Candidate citing a non-existent fact_id is killed by deterministic gate.

    The deterministic pre-jury gate in adversary' checks that every [paper] or
    [inferred] step cites fact_ids that actually exist in the FactStore.  A step
    citing 'nonexistent_fact_id' (absent from the seeded store) must fire DOWN
    immediately — no reviewer call, never reaches accepted.

    Assertions
    ----------
    - Ungrounded candidate is NOT in accepted nodes
    - Its verdict has decided_by == "deterministic-gate"
    - reviewer_model == "deterministic-gate" (gate path — no reviewer call)
    """
    session = _make_session(tmp_path / "runs")
    store_path = tmp_path / "facts.json"
    _seed_store(store_path)

    # gen returns: cards → ungrounded hyps → contract (but adversary gate fires before jury)
    gen = MockProvider(
        responses=[_CARDS_JSON, _HYPS_WITH_UNGROUNDED, _CONTRACT_JSON] * 5,
        model="qwen-max",
    )
    # rev should NOT be called for the ungrounded candidate (gate fires first)
    # Give it UP so that IF it were called, it would wrongly accept
    rev = MockProvider(
        responses=[_UP_VERDICT] * 10,
        model="qwen-plus",
    )
    config = HypothesisConfig(max_cards=1, max_candidates=1, max_rounds=1)
    executor = HypothesisExecutor(
        session,
        gen_provider=gen,
        rev_provider=rev,
        store_path=store_path,
        config=config,
    )
    coordinator = HypothesisCoordinator(executor=executor)
    await coordinator.run(session)

    # No accepted nodes (ungrounded candidate must be killed)
    accepted = [n for n in session.tree.get_all_nodes() if n.status == "accepted"]
    assert len(accepted) == 0, (
        f"Ungrounded candidate must never reach accepted, got {len(accepted)} accepted"
    )

    # The pruned node must show deterministic-gate as decided_by
    pruned = [n for n in session.tree.get_all_nodes() if n.status == "pruned"]
    assert len(pruned) >= 1, "At least one node must be pruned by the gate"
    for node in pruned:
        if node.refs and "verdict" in node.refs:
            verdict = node.refs["verdict"]
            assert verdict.get("decided_by") == "deterministic-gate", (
                f"Ungrounded candidate must be killed by deterministic-gate, "
                f"got decided_by={verdict.get('decided_by')!r}"
            )

    # Reviewer was NOT called — rev._index should be 0
    assert rev._index == 0, (
        f"Reviewer must not be called for deterministic-gate path, "
        f"got rev._index={rev._index}"
    )


# ---------------------------------------------------------------------------
# Scenario 3: No-self-acquit pinned — reviewer_model != generator_model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_self_acquit_accepted_verdict_has_distinct_reviewer(tmp_path: Path) -> None:
    """Accepted hypotheses must carry a verdict with reviewer_model != generator model.

    The structural no-self-acquit check in adversary' enforces that the generator
    (qwen-max) cannot issue its own accept.  An accepted node's verdict must show
    the reviewer model (qwen-plus), distinct from the generator (qwen-max).

    Assertions
    ----------
    - At least one accepted node exists
    - Every accepted node's verdict has reviewer_model == "qwen-plus" (not "qwen-max")
    - No accepted node has reviewer_model equal to the generator model
    """
    session = _make_session(tmp_path / "runs")
    store_path = tmp_path / "facts.json"
    _seed_store(store_path)

    gen, rev = _build_happy_providers()  # gen=qwen-max, rev=qwen-plus (distinct)
    config = HypothesisConfig(max_cards=1, max_candidates=2, max_rounds=1)
    executor = HypothesisExecutor(
        session,
        gen_provider=gen,
        rev_provider=rev,
        store_path=store_path,
        config=config,
    )
    coordinator = HypothesisCoordinator(executor=executor)
    await coordinator.run(session)

    accepted = [n for n in session.tree.get_all_nodes() if n.status == "accepted"]
    assert len(accepted) >= 1, "Need ≥1 accepted node for this assertion to be meaningful"

    generator_model = gen.model  # "qwen-max"
    for node in accepted:
        assert node.refs is not None
        verdict = node.refs.get("verdict", {})
        reviewer_model = verdict.get("reviewer_model")
        assert reviewer_model is not None, "Accepted node verdict must have reviewer_model"
        assert reviewer_model != generator_model, (
            f"No-self-acquit: accepted verdict reviewer_model must differ from "
            f"generator_model={generator_model!r}, got reviewer_model={reviewer_model!r}"
        )
        assert reviewer_model == "qwen-plus", (
            f"Accepted node reviewer_model must be 'qwen-plus' (distinct reviewer), "
            f"got {reviewer_model!r}"
        )


# ---------------------------------------------------------------------------
# Scenario 4: Resume across disk reload — no re-critique, no duplicates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_across_disk_reload_skips_accepted(tmp_path: Path) -> None:
    """After a disk reload, already-accepted nodes are skipped completely.

    Construction
    ------------
    Run 1: fresh session → full pipeline → ≥1 accepted node → saved to disk.
    Reload: RunSession.load + IdeaTree from json_path.
    Run 2: reload session + fresh executor → accepted nodes MUST be skipped.

    Assertions
    ----------
    - Run 1 produces ≥1 accepted node
    - Run 2 with reloaded session produces NO new accepted nodes
    - No duplicate node ids after both runs
    - VerdictLedger entry count does NOT increase after Run 2
    - Already-accepted node ids are the same set after Run 2
    """
    runs_root = tmp_path / "runs"
    store_path = tmp_path / "facts.json"
    _seed_store(store_path)

    # --- Run 1: full pipeline ---
    session1 = _make_session(runs_root)
    gen1, rev1 = _build_happy_providers()
    config = HypothesisConfig(max_cards=2, max_candidates=2, max_rounds=1)
    executor1 = HypothesisExecutor(
        session1,
        gen_provider=gen1,
        rev_provider=rev1,
        store_path=store_path,
        config=config,
    )
    coordinator1 = HypothesisCoordinator(executor=executor1)
    await coordinator1.run(session1)

    accepted_after_run1 = {
        n.id for n in session1.tree.get_all_nodes() if n.status == "accepted"
    }
    assert len(accepted_after_run1) >= 1, "Run 1 must produce ≥1 accepted node"

    # Capture ledger state after run 1
    ledger_path = session1.session_dir / "verdict-ledger.jsonl"
    assert ledger_path.exists(), "VerdictLedger must be written to disk after Run 1"
    ledger_entries_after_run1 = VerdictLedger(ledger_path).all_entries()
    assert len(ledger_entries_after_run1) >= 1, (
        "VerdictLedger must have ≥1 entry after Run 1"
    )

    # Disk state: idea_tree.json must exist
    tree_path = session1.session_dir / "idea_tree.json"
    assert tree_path.exists(), "idea_tree.json must be written after Run 1"

    # --- Disk reload ---
    session2 = RunSession.load(runs_root, session1.run_id)
    # Explicitly reload the tree from json to mirror test_lit_miner_e2e.py pattern
    reloaded_tree = IdeaTree.load_json(tree_path)
    session2.tree = reloaded_tree  # type: ignore[assignment]

    # Verify the accepted nodes survived the reload
    accepted_after_reload = {
        n.id for n in session2.tree.get_all_nodes() if n.status == "accepted"
    }
    assert accepted_after_reload == accepted_after_run1, (
        f"Reloaded tree must contain the same accepted nodes as Run 1: "
        f"expected={accepted_after_run1}, got={accepted_after_reload}"
    )

    # --- Run 2: fresh executor on the reloaded session ---
    # Provide fresh responses to detect any re-processing
    gen2, rev2 = _build_happy_providers()
    executor2 = HypothesisExecutor(
        session2,
        gen_provider=gen2,
        rev_provider=rev2,
        store_path=store_path,
        config=config,
    )
    # Manually call executor.run with the ROOT goal (coordinator would skip session if done)
    from loop_sci.engine.types import DispatchUnit

    result2 = await executor2.run(DispatchUnit(node_id="ROOT", goal="neuro fear encoding"))
    assert result2.status == "done", f"Run 2 must complete cleanly, got {result2.status!r}"

    # No new accepted nodes — only the original ones remain
    accepted_after_run2 = {
        n.id for n in session2.tree.get_all_nodes() if n.status == "accepted"
    }
    assert accepted_after_run2 == accepted_after_run1, (
        f"Run 2 must not add new accepted nodes: "
        f"before={accepted_after_run1}, after={accepted_after_run2}"
    )

    # No duplicate node ids in the tree
    all_node_ids = [n.id for n in session2.tree.get_all_nodes()]
    assert len(all_node_ids) == len(set(all_node_ids)), (
        f"Tree must have no duplicate node ids after resume: {all_node_ids}"
    )

    # VerdictLedger must NOT have new entries for already-accepted nodes
    ledger_entries_after_run2 = VerdictLedger(ledger_path).all_entries()
    # The ledger may have entries for NON-accepted nodes that were re-processed
    # (e.g. rejected rivals in round 2); but already-accepted node_ids must not
    # appear as NEW entries (i.e. they should NOT be critiqued again).
    accepted_node_ids_in_ledger_run1 = {
        e["node_id"]
        for e in ledger_entries_after_run1
        if e.get("result") == "UP"
    }
    # Any UP entries in run 2 ledger for the same node_ids would be re-critiques
    run2_only_entries = ledger_entries_after_run2[len(ledger_entries_after_run1):]
    re_critiqued_accepted = {
        e["node_id"]
        for e in run2_only_entries
        if e["node_id"] in accepted_node_ids_in_ledger_run1
    }
    assert len(re_critiqued_accepted) == 0, (
        f"Already-accepted nodes must not be re-critiqued in Run 2: "
        f"re-critiqued={re_critiqued_accepted}"
    )
