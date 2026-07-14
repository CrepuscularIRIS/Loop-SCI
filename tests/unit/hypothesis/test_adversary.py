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


# ---------------------------------------------------------------------------
# BLOCKER 3 bite-test: falsy fact_id in store must NOT satisfy citation gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blocker3_falsy_fact_id_in_store_does_not_satisfy_gate(tmp_path) -> None:
    """A fact with fact_id='' (falsy) genuinely stored must NOT let an
    empty-string citation pass the anti-fabrication gate.

    Injection strategy: seed store._records directly with a raw dict whose
    fact_id is '' so the falsy id survives into store.all() without being
    regenerated by FactStore.add() (which regenerates any falsy id it sees).

    Failure mode matrix:
      UNFILTERED (old code):  valid_ids = {''} (falsy id included)
                              → '' ∈ valid_ids → gate does NOT fire
                              → candidate reaches jury → decided_by == 'jury'
                              → assertions below FAIL (test bites the old code)
      FILTERED (new code):    valid_ids = {} (falsy id excluded by `if f.fact_id`)
                              → '' ∉ valid_ids → gate fires → DOWN
                              → decided_by == 'deterministic-gate', reviewer not called
                              → assertions below PASS
    """
    from tests.conftest import MockProvider

    # ------------------------------------------------------------------
    # Inject a raw record with fact_id="" directly into store._records so
    # store.all() yields Fact(fact_id="") without going through add(),
    # which would regenerate the id to 'fact_<uuid>'.
    # ------------------------------------------------------------------
    store = FactStore(tmp_path / "f.json")
    raw_record: dict = {
        "claim": "Some baseline fact.",
        "source_ref": {"source": "s2", "external_id": "x0", "doi": None},
        "evidence_span": "Some baseline fact.",
        "confidence": 1.0,
        "grounding_scope": "abstract",
        "entities": None,
        "verification": None,
        "fact_id": "",  # falsy id — MUST survive into store.all()
    }
    store._records.append(raw_record)

    # Verify the injection: store.all() must return exactly one fact with a falsy id.
    all_facts = store.all()
    assert len(all_facts) == 1, "Injection failed: store.all() returned wrong count"
    assert all_facts[0].fact_id == "", (
        "Injection failed: fact_id was regenerated despite bypassing add()"
    )

    # Derivation cites the empty-string fact_id — must NOT resolve after the fix.
    derivation = [DerivationStep(step="cite empty id", grade="[paper]", fact_ids=[""])]
    reviewer = MockProvider(
        responses=[
            # Supply a valid UP response so that IF the gate incorrectly passes
            # (old code), the jury would return UP — making decided_by=="jury",
            # which would cause the assertions below to FAIL and expose the bug.
            __import__("json").dumps({"result": "UP", "reasons": ["novel"]}),
        ],
        model="qwen-plus",
    )

    verdict = await run_adversary(
        _hyp_refs("Mechanism citing empty fact_id"),
        derivation,
        store,
        "qwen-max",
        reviewer,
    )

    # With the fix: falsy ids filtered out → '' ∉ valid_ids → gate fires → DOWN.
    # Without the fix: '' ∈ valid_ids → gate passes → jury called → decided_by=='jury'
    # → first assert fails (DOWN vs UP) — biting the unfixed code.
    assert verdict.result == "DOWN", (
        "A derivation citing an empty-string fact_id must be DOWN'd by the gate "
        f"(falsy ids must be excluded from valid_ids). Got result={verdict.result!r}"
    )
    assert verdict.decided_by == "deterministic-gate", (
        "Expected decided_by='deterministic-gate' (gate must fire before jury). "
        f"Got decided_by={verdict.decided_by!r}"
    )
    # Reviewer must NOT have been called: gate short-circuits before the jury.
    assert reviewer._index == 0, (
        "Reviewer must NOT be called when gate fires on empty-string fact_id. "
        f"Got reviewer._index={reviewer._index}"
    )


# ---------------------------------------------------------------------------
# BLOCKER 2 bite-test (adversary-level): no-self-acquit uses REAL gen identity
# ---------------------------------------------------------------------------
#
# NOTE: This adversary-level test confirms that run_adversary itself enforces
# no-self-acquit correctly.  The EXECUTOR-LEVEL wiring test — which proves that
# HypothesisExecutor passes getattr(self._gen, "model", cfg.generator_model)
# rather than cfg.generator_model — lives in test_executor.py as
# test_blocker2_executor_uses_real_gen_model_not_config_string.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blocker2_no_self_acquit_uses_real_gen_identity_not_config_string(
    tmp_path,
) -> None:
    """No-self-acquit fires when the REAL generator model == reviewer model.

    Scenario: both generator and reviewer use "qwen-plus" (same real identity),
    while the *caller* supplies generator_model="qwen-plus" (i.e. the real value,
    as the fixed executor now does via getattr).

    The adversary must reject the UP verdict and return DOWN via deterministic-gate.

    Failure mode matrix (at the run_adversary level):
      OLD adversary (hypothetical — before any fix): if the no-self-acquit check
        were absent entirely, the jury UP would be honored → decided_by=="jury"
        → first assert below FAILS → bites the unfixed code.
      NEW adversary (current): comparison "qwen-plus"=="qwen-plus" fires →
        DOWN, decided_by=="deterministic-gate", reviewer._index==0 → all pass.

    The complementary executor-level test in test_executor.py bites the WIRING
    bug where the executor passed cfg.generator_model ("qwen-max") instead of
    the real gen.model ("qwen-plus") — a distinction invisible at this level.
    """
    from tests.conftest import MockProvider

    store = _store(tmp_path, ["Neurons fire action potentials."])
    derivation = [DerivationStep(step="established", grade="[paper]", fact_ids=["fact_0"])]

    # Both generator and reviewer have the SAME real model identity.
    # Supply UP so that IF no-self-acquit were absent, the jury would UP the
    # candidate — making decided_by=="jury" and causing the asserts to FAIL.
    reviewer = MockProvider(
        responses=[json.dumps({"result": "UP", "reasons": ["novel"]})],
        model="qwen-plus",
    )

    # Pass the REAL gen model (as the fixed executor now does).
    verdict = await run_adversary(
        _hyp_refs("A novel mechanism"),
        derivation,
        store,
        "qwen-plus",   # real generator identity == reviewer identity → gate fires
        reviewer,
    )

    assert verdict.result == "DOWN", (
        "No-self-acquit must fire when real gen.model == rev.model. "
        f"Got result={verdict.result!r}"
    )
    assert verdict.decided_by == "deterministic-gate", (
        f"Expected decided_by='deterministic-gate', got {verdict.decided_by!r}"
    )
    assert reviewer._index == 0, (
        "Reviewer must not be called when no-self-acquit fires. "
        f"Got reviewer._index={reviewer._index}"
    )
