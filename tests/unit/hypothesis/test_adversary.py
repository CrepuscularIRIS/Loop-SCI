"""Unit tests for loop_sci.hypothesis.stages.adversary.

Tests run fully offline via MockProvider (no network / no API key).

TDD contract (from task-7-brief.md / osp 2.2-2.5):
- Deterministic gate fires BEFORE any jury/reviewer call.
- load-bearing [guess] step  → DOWN via deterministic-gate; reviewer call-count 0.
- mechanism contradicts grounding fact → DOWN via deterministic-gate; reviewer call-count 0.
- no-self-acquit: reviewer.model == generator_model → UP rejected.
- distinct reviewer model honored (qwen-plus vs qwen-max).
- incoherent hypothesis: jury issues DOWN verdict.
- ungrounded citation: downgraded to [guess] / not accepted.
- grounded step carries [paper]/[inferred] + fact_id.
"""
from __future__ import annotations

import json

import pytest

from loop_sci.hypothesis.schemas import DerivationStep
from loop_sci.hypothesis.stages.adversary import run_adversary
from loop_sci.literature.extract.fact import Fact, SourceRef
from loop_sci.literature.factbase.store import FactStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _store(tmp_path, claims: list[str]) -> FactStore:
    """Build a FactStore with one Fact per claim string."""
    store = FactStore(tmp_path / "f.json")
    for i, c in enumerate(claims):
        f = Fact(
            claim=c,
            source_ref=SourceRef(source="s2", external_id=f"x{i}"),
            evidence_span=c[:20],
            confidence=1.0,
            grounding_scope="abstract",
        )
        f.fact_id = f"fact_{i}"
        store.add(f)
    return store


def _hyp_refs(mech: str) -> dict:
    return {
        "hyp": {
            "MECHANISM": mech,
            "KILL": "k",
            "BRACKET": "b",
            "DIFF_PREDICTION": "d",
        },
        "topic": "neuro",
        "kind": "hypothesis",
        "frame": "primary",
        "grounding_fact_ids": ["fact_0"],
    }


# ---------------------------------------------------------------------------
# Test 1: Deterministic gate downs a candidate WITHOUT calling the reviewer
# (load-bearing [guess] step triggers the gate)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deterministic_gate_downs_load_bearing_guess_without_jury_call(
    tmp_path,
) -> None:
    """A [guess]-graded derivation step must be caught by the deterministic gate.

    The reviewer must NOT be invoked (_index stays at 0).
    """
    from tests.conftest import MockProvider

    store = _store(tmp_path, ["Neurons do NOT fire glial oscillations."])
    derivation = [DerivationStep(step="s", grade="[guess]", fact_ids=[])]
    reviewer = MockProvider(responses=["should not be called"], model="qwen-plus")

    verdict = await run_adversary(
        _hyp_refs("Glial oscillations encode fear"),
        derivation,
        store,
        "qwen-max",
        reviewer,
    )

    assert verdict.result == "DOWN"
    assert verdict.decided_by == "deterministic-gate"
    assert reviewer._index == 0, "reviewer was called despite gate failure — violation"


# ---------------------------------------------------------------------------
# Test 2: Deterministic gate downs a mechanism that contradicts a grounding fact
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deterministic_gate_downs_contradicting_mechanism_without_jury_call(
    tmp_path,
) -> None:
    """A mechanism that contradicts a stored fact triggers the gate (no jury call)."""
    from tests.conftest import MockProvider

    # Fact explicitly negates glial oscillations
    store = _store(tmp_path, ["Neurons do NOT exhibit glial oscillations."])
    # Derivation has only grounded steps — gate must fire on the contradiction
    derivation = [DerivationStep(step="lit review", grade="[paper]", fact_ids=["fact_0"])]
    reviewer = MockProvider(responses=["should not be called"], model="qwen-plus")

    verdict = await run_adversary(
        _hyp_refs("Glial oscillations encode fear memory"),
        derivation,
        store,
        "qwen-max",
        reviewer,
    )

    assert verdict.result == "DOWN"
    assert verdict.decided_by == "deterministic-gate"
    assert reviewer._index == 0


# ---------------------------------------------------------------------------
# Test 3: No-self-acquit — reviewer model == generator model → UP rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_self_acquit_rejects_up_when_reviewer_equals_generator(
    tmp_path,
) -> None:
    """If reviewer.model == generator_model, an UP verdict MUST be rejected.

    Structural enforcement: we verify the UP from the reviewer is converted to DOWN.
    """
    from tests.conftest import MockProvider

    store = _store(tmp_path, ["Neurons fire action potentials."])
    derivation = [DerivationStep(step="established", grade="[paper]", fact_ids=["fact_0"])]
    # reviewer claims UP but has SAME model as generator
    reviewer = MockProvider(
        responses=[json.dumps({"result": "UP", "reasons": []})],
        model="qwen-max",  # same as generator_model below
    )

    verdict = await run_adversary(
        _hyp_refs("A novel mechanism"),
        derivation,
        store,
        "qwen-max",  # generator_model
        reviewer,
    )

    assert verdict.result == "DOWN", "No-self-acquit must reject UP from same model"


# ---------------------------------------------------------------------------
# Test 4: Distinct reviewer honored — UP from qwen-plus (not equal to qwen-max) accepted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_distinct_reviewer_up_is_honored(tmp_path) -> None:
    """UP from a reviewer with a DIFFERENT model identity must be accepted."""
    from tests.conftest import MockProvider

    store = _store(tmp_path, ["Neurons fire action potentials."])
    derivation = [DerivationStep(step="established", grade="[paper]", fact_ids=["fact_0"])]
    reviewer = MockProvider(
        responses=[json.dumps({"result": "UP", "reasons": ["novel and grounded"]})],
        model="qwen-plus",  # DISTINCT from generator
    )

    verdict = await run_adversary(
        _hyp_refs("A novel mechanism"),
        derivation,
        store,
        "qwen-max",  # generator_model
        reviewer,
    )

    assert verdict.result == "UP"
    assert verdict.decided_by == "jury"
    assert verdict.reviewer_model == "qwen-plus"


# ---------------------------------------------------------------------------
# Test 5: Incoherent hypothesis downed by jury
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_incoherent_hypothesis_downed_by_jury(tmp_path) -> None:
    """An incoherent hypothesis should receive a DOWN verdict from the jury."""
    from tests.conftest import MockProvider

    store = _store(tmp_path, ["Neurons fire action potentials."])
    derivation = [DerivationStep(step="established", grade="[paper]", fact_ids=["fact_0"])]
    response = json.dumps({"result": "DOWN", "reasons": ["mechanism contradicts fact_0"]})
    reviewer = MockProvider(responses=[response], model="qwen-plus")

    verdict = await run_adversary(
        _hyp_refs("Novel glial mechanism"),
        derivation,
        store,
        "qwen-max",
        reviewer,
    )

    assert verdict.result == "DOWN"
    assert verdict.decided_by == "jury"
    assert "fact_0" in " ".join(verdict.reasons)


# ---------------------------------------------------------------------------
# Test 9: Ungrounded [paper] step with absent fact_id → DOWN via gate (no jury)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paper_step_with_absent_fact_id_downed_without_jury(tmp_path) -> None:
    """A [paper] step citing a fact_id not in the store triggers the deterministic gate.

    The reviewer MUST NOT be called (_index stays 0).
    """
    from tests.conftest import MockProvider

    store = _store(tmp_path, ["Neurons fire action potentials."])
    # fact_ABSENT does not exist in the store (only fact_0 does)
    derivation = [DerivationStep(step="cited step", grade="[paper]", fact_ids=["fact_ABSENT"])]
    reviewer = MockProvider(responses=["should not be called"], model="qwen-plus")

    verdict = await run_adversary(
        _hyp_refs("Some mechanism"),
        derivation,
        store,
        "qwen-max",
        reviewer,
    )

    assert verdict.result == "DOWN"
    assert verdict.decided_by == "deterministic-gate"
    assert reviewer._index == 0, "reviewer must NOT be called when gate fires on absent fact_id"


# ---------------------------------------------------------------------------
# Test 10: [paper] step with fact_ids=[] (claims grounding, cites nothing) → DOWN via gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paper_step_with_empty_fact_ids_downed_without_jury(tmp_path) -> None:
    """A [paper] step with fact_ids=[] triggers the deterministic gate (no jury call).

    [paper]/[inferred] MUST cite at least one resolvable fact_id.
    """
    from tests.conftest import MockProvider

    store = _store(tmp_path, ["Neurons fire action potentials."])
    derivation = [DerivationStep(step="empty citation", grade="[paper]", fact_ids=[])]
    reviewer = MockProvider(responses=["should not be called"], model="qwen-plus")

    verdict = await run_adversary(
        _hyp_refs("Some mechanism"),
        derivation,
        store,
        "qwen-max",
        reviewer,
    )

    assert verdict.result == "DOWN"
    assert verdict.decided_by == "deterministic-gate"
    assert reviewer._index == 0, "reviewer must NOT be called when gate fires on empty fact_ids"


# ---------------------------------------------------------------------------
# Test 11: Grounded [paper] step (fact_id resolves) passes gate and reaches jury
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grounded_paper_step_passes_new_gate_and_reaches_jury(tmp_path) -> None:
    """A [paper] step whose fact_ids all resolve in the store MUST pass the gate.

    The jury should be called (_index advances to 1).
    [guess] steps are NOT subject to the citation-resolution rule.
    """
    from tests.conftest import MockProvider

    store = _store(tmp_path, ["Neurons fire action potentials."])
    # All fact_ids resolve (fact_0 is in the store)
    derivation = [DerivationStep(step="grounded cite", grade="[paper]", fact_ids=["fact_0"])]
    response = json.dumps({"result": "UP", "reasons": ["well grounded"]})
    reviewer = MockProvider(responses=[response], model="qwen-plus")

    verdict = await run_adversary(
        _hyp_refs("A novel mechanism"),
        derivation,
        store,
        "qwen-max",
        reviewer,
    )

    assert reviewer._index == 1, "jury should have been called for a grounded [paper] step"
    assert verdict.decided_by == "jury"


# ---------------------------------------------------------------------------
# Test 6: Ungrounded citation — derivation step with no fact_ids is [guess]
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_bearing_guess_step_is_downed_without_jury(tmp_path) -> None:
    """A derivation step with grade=[guess] (ungrounded) triggers the gate."""
    from tests.conftest import MockProvider

    store = _store(tmp_path, ["Neurons fire action potentials."])
    # Mixed derivation: one grounded, one guess
    derivation = [
        DerivationStep(step="grounded step", grade="[paper]", fact_ids=["fact_0"]),
        DerivationStep(step="ungrounded step", grade="[guess]", fact_ids=[]),
    ]
    reviewer = MockProvider(responses=["should not be called"], model="qwen-plus")

    verdict = await run_adversary(
        _hyp_refs("A mechanism"),
        derivation,
        store,
        "qwen-max",
        reviewer,
    )

    assert verdict.result == "DOWN"
    assert verdict.decided_by == "deterministic-gate"
    assert reviewer._index == 0


# ---------------------------------------------------------------------------
# Test 7: Grounded step carries [paper]/[inferred] + fact_id (passes gate, reaches jury)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grounded_paper_step_passes_gate_reaches_jury(tmp_path) -> None:
    """A fully grounded derivation (all [paper] with fact_ids) passes the gate.

    The jury is reached and the verdict carries reviewer_model and decided_by=jury.
    """
    from tests.conftest import MockProvider

    store = _store(tmp_path, ["Neurons fire action potentials."])
    derivation = [
        DerivationStep(step="cited from paper X", grade="[paper]", fact_ids=["fact_0"]),
        DerivationStep(step="inferred from X", grade="[inferred]", fact_ids=["fact_0"]),
    ]
    response = json.dumps({"result": "UP", "reasons": ["well supported"]})
    reviewer = MockProvider(responses=[response], model="qwen-plus")

    verdict = await run_adversary(
        _hyp_refs("Neuronal firing encodes memory"),
        derivation,
        store,
        "qwen-max",
        reviewer,
    )

    # Gate did not fire → jury was called → reviewer_index advanced
    assert reviewer._index == 1, "reviewer should have been called once"
    assert verdict.decided_by == "jury"
    assert verdict.reviewer_model == "qwen-plus"


# ---------------------------------------------------------------------------
# Test 8: Invalid JSON from reviewer falls back to DOWN
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_json_from_reviewer_falls_back_to_down(tmp_path) -> None:
    """If the reviewer returns invalid JSON on both attempts, verdict is DOWN."""
    from tests.conftest import MockProvider

    store = _store(tmp_path, ["Neurons fire action potentials."])
    derivation = [DerivationStep(step="s", grade="[paper]", fact_ids=["fact_0"])]
    reviewer = MockProvider(responses=["not valid json at all"], model="qwen-plus")

    verdict = await run_adversary(
        _hyp_refs("A mechanism"),
        derivation,
        store,
        "qwen-max",
        reviewer,
    )

    assert verdict.result == "DOWN"
    assert verdict.decided_by == "jury"
