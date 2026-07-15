"""Canonical ResearchPlan schema for Loop-SCI.

This module defines the dataclasses that make up a ResearchPlan, plus the
12-key ``PLAN_JSON_KEYS`` constant that is the stable serialisation contract
for all downstream tasks (assembly, rendering, gate, executor).

Grade literals for derivation items: ``[paper]``, ``[inferred]``, ``[guess]``.
"""
from __future__ import annotations

import dataclasses
from typing import Any

# ---------------------------------------------------------------------------
# Stable JSON key order (PDF order) — 12 keys, never reorder.
# ---------------------------------------------------------------------------

PLAN_JSON_KEYS: tuple[str, ...] = (
    "problem_statement",
    "rationale",
    "technical_details",
    "datasets",
    "source",
    "target",
    "paper_title",
    "abstract",
    "methods",
    "experiments",
    "results",
    "references",
)


# ---------------------------------------------------------------------------
# Leaf dataclasses
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Candidate:
    """A single candidate entry (dataset, source domain, or target domain).

    Args:
        value: Human-readable label for the candidate.
        candidate: Whether this is an active candidate.
        source_ref: Optional provenance mapping with keys ``source``,
            ``external_id``, and ``doi``.
    """

    value: str
    candidate: bool
    source_ref: dict[str, Any] | None = None


@dataclasses.dataclass
class Reference:
    """A bibliographic reference with optional verification status.

    Args:
        source: Source database name (e.g. ``"arxiv"``).
        external_id: Identifier in the source database.
        doi: DOI string, or ``None``.
        verified: Whether the reference has been verified.
        fact_id: Optional internal fact identifier.
    """

    source: str
    external_id: str
    doi: str | None
    verified: bool
    fact_id: str | None = None


@dataclasses.dataclass
class ResultsBlock:
    """Anticipated or observed results, expressed as a derivation chain.

    Args:
        derivation: Ordered list of ``{"step": str, "grade": str}`` dicts.
            Grade must be one of ``[paper]``, ``[inferred]``, or ``[guess]``.
        conclusion: Final conclusion sentence.
        confidence: Overall confidence label (e.g. ``"final"``).
    """

    derivation: list[dict[str, str]]
    conclusion: str
    confidence: str


@dataclasses.dataclass
class ExperimentsBlock:
    """Experimental design specification.

    Args:
        baselines: List of baseline method names.
        metrics: List of evaluation metric names.
        design: Free-text description of the experimental design.
    """

    baselines: list[str]
    metrics: list[str]
    design: str


@dataclasses.dataclass
class GateResult:
    """Outcome of the quality gate check.

    Args:
        passed: ``True`` if all gate checks passed.
        failures: List of failure reason strings (empty when passed).
    """

    passed: bool
    failures: list[str]


# ---------------------------------------------------------------------------
# ResearchPlan
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ResearchPlan:
    """Canonical 12-field research plan produced from a RankedHypothesis.

    The 12 content fields follow ``PLAN_JSON_KEYS`` order exactly.
    The two provenance fields ``node_id`` and ``gate`` are serialised after the
    content fields by ``to_dict`` and reconstructed by ``from_dict``.
    """

    # --- 12 content fields (PLAN_JSON_KEYS order) ---
    problem_statement: str
    rationale: str
    technical_details: str
    datasets: list[Candidate]
    source: list[Candidate]
    target: list[Candidate]
    paper_title: str
    abstract: str
    methods: str
    experiments: ExperimentsBlock
    results: ResultsBlock
    references: list[Reference]

    # --- provenance ---
    node_id: str
    gate: GateResult

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dict.

        Walks ``PLAN_JSON_KEYS`` in order, then appends ``node_id`` and
        ``gate``.  Nested dataclasses are serialised via
        ``dataclasses.asdict``; ``ResultsBlock.derivation`` items are
        plain dicts and pass through unchanged.
        """
        out: dict[str, Any] = {}

        for key in PLAN_JSON_KEYS:
            value = getattr(self, key)
            if isinstance(value, list):
                serialised: list[Any] = []
                for item in value:
                    if dataclasses.is_dataclass(item) and not isinstance(item, type):
                        serialised.append(dataclasses.asdict(item))
                    else:
                        # plain dict (derivation items) or scalar
                        serialised.append(item)
                out[key] = serialised
            elif dataclasses.is_dataclass(value) and not isinstance(value, type):
                out[key] = dataclasses.asdict(value)
            else:
                out[key] = value

        # provenance appended after content keys
        out["node_id"] = self.node_id
        out["gate"] = dataclasses.asdict(self.gate)

        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ResearchPlan:
        """Reconstruct a ``ResearchPlan`` from a serialised dict.

        Performs a lossless round-trip:
        ``ResearchPlan.from_dict(p.to_dict()).to_dict() == p.to_dict()``.
        """
        return cls(
            problem_statement=d["problem_statement"],
            rationale=d["rationale"],
            technical_details=d["technical_details"],
            datasets=[
                Candidate(
                    value=c["value"],
                    candidate=c["candidate"],
                    source_ref=c.get("source_ref"),
                )
                for c in d["datasets"]
            ],
            source=[
                Candidate(
                    value=c["value"],
                    candidate=c["candidate"],
                    source_ref=c.get("source_ref"),
                )
                for c in d["source"]
            ],
            target=[
                Candidate(
                    value=c["value"],
                    candidate=c["candidate"],
                    source_ref=c.get("source_ref"),
                )
                for c in d["target"]
            ],
            paper_title=d["paper_title"],
            abstract=d["abstract"],
            methods=d["methods"],
            experiments=ExperimentsBlock(
                baselines=d["experiments"]["baselines"],
                metrics=d["experiments"]["metrics"],
                design=d["experiments"]["design"],
            ),
            results=ResultsBlock(
                derivation=d["results"]["derivation"],
                conclusion=d["results"]["conclusion"],
                confidence=d["results"]["confidence"],
            ),
            references=[
                Reference(
                    source=r["source"],
                    external_id=r["external_id"],
                    doi=r.get("doi"),
                    verified=r["verified"],
                    fact_id=r.get("fact_id"),
                )
                for r in d["references"]
            ],
            node_id=d["node_id"],
            gate=GateResult(
                passed=d["gate"]["passed"],
                failures=d["gate"]["failures"],
            ),
        )
