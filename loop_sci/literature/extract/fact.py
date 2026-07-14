"""Structured scientific fact schema.

A ``Fact`` is the canonical record produced by the extraction layer.  It
carries the claim, the source paper reference, and a verbatim evidence span
so that every fact is grounded and traceable.

Design decisions
----------------
* ``source_ref`` and ``evidence_span`` are **required non-defaulted fields**;
  constructing a ``Fact`` without them is impossible at the Python level
  (``TypeError`` from dataclass positional args) and additionally rejected by
  ``__post_init__`` for empty-string / structurally invalid values.
* ``grounding_scope`` is constrained to ``"abstract"`` or ``"full_text"``
  and validated in ``__post_init__``.
* ``SourceRef`` and ``VerificationStatus`` are small, typed sub-structures
  rather than plain dicts so that downstream code (fact-base, idea-tree node
  payload) gets attribute access without dict-key guessing.
* ``to_dict`` / ``from_dict`` provide a lossless JSON-serializable round-trip.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

_VALID_SCOPES: frozenset[str] = frozenset({"abstract", "full_text"})

# Valid status values for VerificationStatus (T4 deferral: narrow to explicit set).
# "flagged" is retained for backwards-compatibility with existing tests/fact-base.
_VALID_STATUSES: frozenset[str] = frozenset({
    "pending",
    "pending_l4",
    "verified",
    "rejected",
    "failed",
    "flagged",
})


# ---------------------------------------------------------------------------
# Sub-structures
# ---------------------------------------------------------------------------


@dataclass
class SourceRef:
    """Reference to the source paper from which a fact was extracted.

    Attributes:
        source: Adapter name — ``"semantic_scholar"`` | ``"arxiv"`` | ``"pubmed"``.
        external_id: Source-scoped identifier, e.g. ``"s2:abc"`` or
            ``"arxiv:2401.0001"``.  Must not be empty.
        doi: Optional DOI string, e.g. ``"10.1038/nature12345"``.
    """

    source: str
    external_id: str
    doi: str | None = None

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError("SourceRef.source must not be empty")
        if not self.external_id:
            raise ValueError("SourceRef.external_id must not be empty")

    # -- serialization -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceRef:
        """Reconstruct a ``SourceRef`` from its dict representation."""
        return cls(
            source=data["source"],
            external_id=data["external_id"],
            doi=data.get("doi"),
        )


@dataclass
class VerificationStatus:
    """Structured record of the verification outcome for a fact.

    Attributes:
        layer_reached: The highest verification layer executed (1–4).
            Must be an integer in [1, 4].
        status: Outcome label.  Valid values: ``"pending"`` | ``"pending_l4"`` |
            ``"verified"`` | ``"rejected"`` | ``"failed"`` | ``"flagged"``.
        detail: Free-text annotation (e.g. reason for rejection).  Defaults to
            an empty string so callers don't need to supply it.
    """

    layer_reached: int
    status: str
    detail: str = ""

    def __post_init__(self) -> None:
        if not (1 <= self.layer_reached <= 4):
            raise ValueError(
                f"layer_reached must be in [1, 4]; got {self.layer_reached!r}"
            )
        if self.status not in _VALID_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(_VALID_STATUSES)!r}; "
                f"got {self.status!r}"
            )

    # -- serialization -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VerificationStatus:
        """Reconstruct a ``VerificationStatus`` from its dict representation."""
        return cls(
            layer_reached=data["layer_reached"],
            status=data["status"],
            detail=data.get("detail", ""),
        )


# ---------------------------------------------------------------------------
# Core schema
# ---------------------------------------------------------------------------


@dataclass
class Fact:
    """Canonical structured record for a single extracted scientific fact.

    ``source_ref`` and ``evidence_span`` are **mandatory** — a ``Fact``
    without them cannot be constructed.

    Attributes:
        claim: The extracted scientific claim in declarative form.
        source_ref: Reference to the source paper (adapter + id + optional DOI).
        evidence_span: Verbatim quote from the source that grounds the claim.
            Must be non-empty.
        confidence: Extraction confidence in ``[0.0, 1.0]``.
        grounding_scope: Which part of the paper was used —
            ``"abstract"`` or ``"full_text"``.
        entities: Optional list of named entities mentioned in the claim.
        verification: Optional verification outcome (populated by the verify
            layer — Task 6).
        fact_id: Opaque identifier assigned when the fact is persisted to the
            fact-base.  ``None`` until then.
    """

    claim: str
    source_ref: SourceRef
    evidence_span: str
    confidence: float
    grounding_scope: str
    entities: list[str] | None = field(default=None)
    verification: VerificationStatus | None = field(default=None)
    fact_id: str | None = field(default=None)

    def __post_init__(self) -> None:
        # evidence_span guard — the spec says this must never be absent/empty
        if not self.evidence_span:
            raise ValueError(
                "Fact.evidence_span must not be empty; every fact must be grounded "
                "by a verbatim quote from the source text."
            )
        # source_ref structural guard (SourceRef.__post_init__ handles field-level
        # checks; here we defend against a None being passed despite the type hint)
        if self.source_ref is None:
            raise ValueError("Fact.source_ref must not be None")
        # grounding_scope constraint
        if self.grounding_scope not in _VALID_SCOPES:
            raise ValueError(
                f"grounding_scope must be one of {sorted(_VALID_SCOPES)!r}; "
                f"got {self.grounding_scope!r}"
            )

    # -- serialization -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation of this fact.

        The dict is suitable for storage in the JSON fact-base and for embedding
        in idea-tree node payloads (``Node.refs``).
        """
        return {
            "claim": self.claim,
            "source_ref": self.source_ref.to_dict(),
            "evidence_span": self.evidence_span,
            "confidence": self.confidence,
            "grounding_scope": self.grounding_scope,
            "entities": self.entities,
            "verification": self.verification.to_dict() if self.verification else None,
            "fact_id": self.fact_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Fact:
        """Reconstruct a ``Fact`` from its dict representation.

        The round-trip ``Fact.from_dict(fact.to_dict()) == fact`` is guaranteed
        for all valid ``Fact`` instances.
        """
        verification_data = data.get("verification")
        return cls(
            claim=data["claim"],
            source_ref=SourceRef.from_dict(data["source_ref"]),
            evidence_span=data["evidence_span"],
            confidence=data["confidence"],
            grounding_scope=data["grounding_scope"],
            entities=data.get("entities"),
            verification=(
                VerificationStatus.from_dict(verification_data)
                if verification_data is not None
                else None
            ),
            fact_id=data.get("fact_id"),
        )
