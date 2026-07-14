"""Tests for the Fact schema — TDD RED phase written before any implementation."""
from __future__ import annotations

import pytest

from loop_sci.literature.extract.fact import Fact, SourceRef, VerificationStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_source_ref() -> SourceRef:
    return SourceRef(source="semantic_scholar", external_id="s2:abc123")


def _valid_fact(**overrides) -> Fact:
    kwargs = dict(
        claim="SNN outperforms ANN on sparse data",
        source_ref=_valid_source_ref(),
        evidence_span="SNNs outperform ANNs on sparse data by 12%",
        confidence=0.85,
        grounding_scope="abstract",
    )
    kwargs.update(overrides)
    return Fact(**kwargs)


# ---------------------------------------------------------------------------
# 1. Evidence-required guarantee
# ---------------------------------------------------------------------------

def test_fact_requires_both_source_ref_and_evidence_span():
    """Constructing a Fact without source_ref + evidence_span must raise."""
    with pytest.raises((TypeError, ValueError)):
        Fact(claim="X causes Y")  # missing source_ref + evidence_span


def test_fact_missing_source_ref_raises():
    """Omitting source_ref must raise, even when evidence_span is present."""
    with pytest.raises((TypeError, ValueError)):
        Fact(
            claim="X causes Y",
            evidence_span="X causes Y in our study",
            confidence=0.7,
            grounding_scope="abstract",
        )


def test_fact_missing_evidence_span_raises():
    """Omitting evidence_span must raise, even when source_ref is present."""
    with pytest.raises((TypeError, ValueError)):
        Fact(
            claim="X causes Y",
            source_ref=_valid_source_ref(),
            confidence=0.7,
            grounding_scope="abstract",
        )


def test_fact_empty_evidence_span_raises():
    """An empty string evidence_span must be rejected."""
    with pytest.raises(ValueError):
        _valid_fact(evidence_span="")


def test_fact_empty_source_ref_external_id_raises():
    """A SourceRef with empty external_id must be rejected."""
    with pytest.raises(ValueError):
        _valid_fact(source_ref=SourceRef(source="arxiv", external_id=""))


# ---------------------------------------------------------------------------
# 2. Valid construction
# ---------------------------------------------------------------------------

def test_valid_fact_construction_defaults():
    """A minimal valid Fact has None for optional fields."""
    f = _valid_fact()
    assert f.claim == "SNN outperforms ANN on sparse data"
    assert f.source_ref.source == "semantic_scholar"
    assert f.source_ref.external_id == "s2:abc123"
    assert f.evidence_span == "SNNs outperform ANNs on sparse data by 12%"
    assert f.confidence == 0.85
    assert f.grounding_scope == "abstract"
    assert f.entities is None
    assert f.verification is None
    assert f.fact_id is None


def test_valid_fact_with_all_fields():
    """All optional fields can be populated."""
    vs = VerificationStatus(layer_reached=2, status="verified", detail="cross-checked")
    f = _valid_fact(
        entities=["SNN", "ANN"],
        verification=vs,
        fact_id="fact-001",
    )
    assert f.entities == ["SNN", "ANN"]
    assert f.verification.layer_reached == 2
    assert f.verification.status == "verified"
    assert f.verification.detail == "cross-checked"
    assert f.fact_id == "fact-001"


def test_valid_fact_full_text_scope():
    """grounding_scope='full_text' is accepted."""
    f = _valid_fact(grounding_scope="full_text")
    assert f.grounding_scope == "full_text"


def test_source_ref_with_doi():
    """SourceRef accepts an optional doi field."""
    ref = SourceRef(
        source="pubmed",
        external_id="pmid:12345",
        doi="10.1038/nature12345",
    )
    assert ref.doi == "10.1038/nature12345"


# ---------------------------------------------------------------------------
# 3. grounding_scope constraint
# ---------------------------------------------------------------------------

def test_invalid_grounding_scope_raises():
    """An invalid grounding_scope value must be rejected."""
    with pytest.raises(ValueError, match="grounding_scope"):
        _valid_fact(grounding_scope="chapter")


def test_grounding_scope_abstract_accepted():
    """'abstract' is a valid grounding_scope."""
    f = _valid_fact(grounding_scope="abstract")
    assert f.grounding_scope == "abstract"


# ---------------------------------------------------------------------------
# 4. VerificationStatus standalone
# ---------------------------------------------------------------------------

def test_verification_status_defaults():
    """VerificationStatus.detail defaults to empty string."""
    vs = VerificationStatus(layer_reached=1, status="flagged")
    assert vs.detail == ""
    assert vs.layer_reached == 1
    assert vs.status == "flagged"


def test_fact_with_verification_status():
    """A Fact can carry a VerificationStatus."""
    vs = VerificationStatus(layer_reached=4, status="verified")
    f = _valid_fact(verification=vs)
    assert f.verification.status == "verified"
    assert f.verification.layer_reached == 4


# ---------------------------------------------------------------------------
# 5. Serialization round-trip
# ---------------------------------------------------------------------------

def test_fact_to_dict_round_trip_minimal():
    """to_dict / from_dict round-trip is lossless for a minimal Fact."""
    f = _valid_fact()
    d = f.to_dict()
    restored = Fact.from_dict(d)
    assert restored == f


def test_fact_to_dict_round_trip_full():
    """to_dict / from_dict round-trip is lossless for a fully-populated Fact."""
    vs = VerificationStatus(layer_reached=3, status="rejected", detail="contradicted")
    f = _valid_fact(
        entities=["protein-X", "inhibitor-Y"],
        verification=vs,
        fact_id="fact-007",
        grounding_scope="full_text",
        source_ref=SourceRef(
            source="arxiv",
            external_id="arxiv:2501.00001",
            doi="10.1000/xyz123",
        ),
    )
    d = f.to_dict()
    restored = Fact.from_dict(d)
    assert restored == f
    assert restored.verification.status == "rejected"
    assert restored.source_ref.doi == "10.1000/xyz123"


def test_to_dict_is_json_serializable():
    """to_dict output must be serializable with standard json module."""
    import json
    f = _valid_fact(entities=["X"], fact_id="abc")
    d = f.to_dict()
    serialized = json.dumps(d)
    assert isinstance(serialized, str)
    loaded = json.loads(serialized)
    assert loaded["claim"] == f.claim


def test_to_dict_contains_expected_keys():
    """to_dict output must include all required keys."""
    f = _valid_fact()
    d = f.to_dict()
    for key in ("claim", "source_ref", "evidence_span", "confidence", "grounding_scope"):
        assert key in d, f"Missing key: {key}"
