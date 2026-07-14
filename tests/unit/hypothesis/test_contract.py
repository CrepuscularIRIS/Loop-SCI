"""Unit tests for loop_sci.hypothesis.stages.contract — derivation contract freeze.

OpenSpec 2.1: contract must be frozen on the node's refs BEFORE any verdict
is produced.  Tests cover the happy path, idempotent re-freeze, plain-text
tripwire requirement (no eval_cmd / shell fields), and malformed-JSON fallback.
"""
from __future__ import annotations

import json

import pytest

from loop_sci.hypothesis.schemas import Contract
from loop_sci.hypothesis.stages.contract import freeze_contract
from tests.conftest import MockProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hyp_refs(mechanism: str = "Glia encode fear via gap junctions") -> dict:
    return {
        "hyp": {
            "MECHANISM": mechanism,
            "KILL": "no glial",
            "BRACKET": "moderate",
            "DIFF_PREDICTION": "EEG",
        },
        "topic": "neuro",
    }


def _valid_response(
    hypothesis: str = "Glia encode fear",
    latent_root: str = "glial plasticity",
    accept_if: str = "BOLD signal differs by >0.5σ",
    kill_if: str = "No glial calcium transient in fear CS",
) -> str:
    return json.dumps(
        {
            "HYPOTHESIS": hypothesis,
            "LATENT_ROOT": latent_root,
            "ACCEPT_IF": accept_if,
            "KILL_IF": kill_if,
        }
    )


# ---------------------------------------------------------------------------
# Task-6 brief canonical test (verbatim per brief)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contract_frozen_with_required_fields() -> None:
    """Contract has all four required fields and is a Contract dataclass instance."""
    response = json.dumps(
        {
            "HYPOTHESIS": "Glia encode fear",
            "LATENT_ROOT": "glial plasticity",
            "ACCEPT_IF": "BOLD signal differs by >0.5σ",
            "KILL_IF": "No glial calcium transient in fear CS",
        }
    )
    provider = MockProvider(responses=[response])
    hyp_refs = {
        "hyp": {
            "MECHANISM": "Glia encode fear via gap junctions",
            "KILL": "no glial",
            "BRACKET": "moderate",
            "DIFF_PREDICTION": "EEG",
        },
        "topic": "neuro",
    }
    contract = await freeze_contract(hyp_refs, provider)
    assert isinstance(contract, Contract)
    assert contract.HYPOTHESIS == "Glia encode fear"
    assert contract.ACCEPT_IF != ""
    assert contract.KILL_IF != ""


# ---------------------------------------------------------------------------
# LATENT_ROOT is populated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contract_latent_root_populated() -> None:
    """LATENT_ROOT field is populated from the provider response."""
    provider = MockProvider(responses=[_valid_response(latent_root="glial plasticity")])
    contract = await freeze_contract(_make_hyp_refs(), provider)
    assert contract.LATENT_ROOT == "glial plasticity"


# ---------------------------------------------------------------------------
# Plain-text tripwires — no eval_cmd / shell keyword
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_if_and_kill_if_are_plain_text() -> None:
    """ACCEPT_IF / KILL_IF are plain derivation tripwires, not shell commands."""
    accept_if = "BOLD signal differs by >0.5σ in fear-conditioned vs control"
    kill_if = "No glial calcium transient observed in fear CS within 500 ms"
    provider = MockProvider(
        responses=[_valid_response(accept_if=accept_if, kill_if=kill_if)]
    )
    contract = await freeze_contract(_make_hyp_refs(), provider)

    # No eval_cmd / shell indicators
    assert "eval_cmd" not in str(contract.ACCEPT_IF).lower()
    assert "eval_cmd" not in str(contract.KILL_IF).lower()
    # Fields are non-empty human-readable text
    assert len(contract.ACCEPT_IF) > 5
    assert len(contract.KILL_IF) > 5


# ---------------------------------------------------------------------------
# No verdict dependency — contract can be frozen with empty refs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contract_frozen_before_verdict_exists() -> None:
    """freeze_contract succeeds when hyp_refs contain no verdict field."""
    # hyp_refs has no 'verdict' key at all — mimics pre-verdict state
    hyp_refs = {
        "hyp": {"MECHANISM": "X", "KILL": "y", "BRACKET": "low", "DIFF_PREDICTION": "Z"},
        "topic": "neurosci",
    }
    assert "verdict" not in hyp_refs  # explicit assertion: no verdict present
    provider = MockProvider(responses=[_valid_response(hypothesis="X")])
    contract = await freeze_contract(hyp_refs, provider)
    assert isinstance(contract, Contract)
    # The returned contract must not carry any verdict information
    assert not hasattr(contract, "verdict")


# ---------------------------------------------------------------------------
# Idempotent re-freeze
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_freeze_is_idempotent() -> None:
    """Calling freeze_contract twice with same hyp_refs returns a valid Contract both times."""
    provider = MockProvider(
        responses=[_valid_response(), _valid_response(hypothesis="Glia encode fear v2")]
    )
    hyp_refs = _make_hyp_refs()

    contract1 = await freeze_contract(hyp_refs, provider)
    contract2 = await freeze_contract(hyp_refs, provider)

    assert isinstance(contract1, Contract)
    assert isinstance(contract2, Contract)
    # Neither call crashes or corrupts the other
    assert contract1.HYPOTHESIS != "" and contract2.HYPOTHESIS != ""


# ---------------------------------------------------------------------------
# Malformed JSON → deterministic fallback (no crash)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_json_falls_back_to_fallback_contract() -> None:
    """When both provider attempts return malformed JSON, a fallback Contract is returned."""
    provider = MockProvider(responses=["this is not json"])
    hyp_refs = _make_hyp_refs(mechanism="Fallback mech")
    contract = await freeze_contract(hyp_refs, provider)

    assert isinstance(contract, Contract)
    # Fallback uses mechanism as HYPOTHESIS
    assert contract.HYPOTHESIS == "Fallback mech"
    # Remaining fields are non-empty placeholder strings
    assert contract.LATENT_ROOT != ""
    assert contract.ACCEPT_IF != ""
    assert contract.KILL_IF != ""


# ---------------------------------------------------------------------------
# Missing hyp key → fallback (robustness)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_hyp_key_does_not_crash() -> None:
    """freeze_contract handles hyp_refs without a 'hyp' key gracefully."""
    provider = MockProvider(responses=["bad json"])
    hyp_refs = {"topic": "neuro"}
    contract = await freeze_contract(hyp_refs, provider)
    assert isinstance(contract, Contract)
