"""TDD tests for collect_references — strict no-fabrication reference assembly.

RED phase: written before any implementation exists in loop_sci/plan/references.py.

Design:
- Seeded refs come from grounding facts' SourceRefs (already verified in fact-base).
- Provider-proposed extras are only admitted when allow_provider_refs=True AND pipeline
  is set, and only when pipeline.verify() returns status="verified".
- Default path (allow_provider_refs=False) makes ZERO verify round-trips.
"""
from __future__ import annotations

import pytest

from loop_sci.hypothesis.ranked import RankedHypothesis
from loop_sci.literature.extract.fact import Fact, SourceRef
from loop_sci.literature.factbase.store import FactStore
from loop_sci.literature.search.schema import PaperResult
from loop_sci.literature.verify.citation import VerificationPipeline
from loop_sci.plan.references import collect_references


class MockSearchClient:
    """Offline mock — no network calls."""

    def __init__(self, result: PaperResult | None) -> None:
        self._result = result
        self.fetch_calls: list[str] = []

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        return []

    async def fetch_by_id(self, external_id: str) -> PaperResult | None:
        self.fetch_calls.append(external_id)
        return self._result


def _hyp(fids: list[str]) -> RankedHypothesis:
    return RankedHypothesis(
        node_id="h",
        problem="p",
        mechanism="m",
        derivation_chain=[],
        diff_prediction="d",
        novelty=None,
        self_consistency=None,
        overall_score=None,
        grounding_fact_ids=fids,
    )


def _facts(tmp_path):  # type: ignore[no-untyped-def]
    store = FactStore(tmp_path / "f.json")
    f1 = store.add(
        Fact(
            claim="c1",
            source_ref=SourceRef("arxiv", "arxiv:1", None),
            evidence_span="e",
            confidence=0.9,
            grounding_scope="abstract",
        )
    )
    f2 = store.add(
        Fact(
            claim="c2",
            source_ref=SourceRef("pubmed", "pm:2", None),
            evidence_span="e",
            confidence=0.9,
            grounding_scope="abstract",
        )
    )
    return store, [f1, f2]


@pytest.mark.asyncio
async def test_grounded_hypothesis_yields_real_refs_count_ge_distinct_sources(
    tmp_path,
) -> None:
    """Seeded refs from grounding facts must all be verified=True and count >= 2."""
    store, fids = _facts(tmp_path)
    refs = await collect_references(_hyp(fids), store.all())
    assert len(refs) >= 2
    assert all(r.verified for r in refs)


@pytest.mark.asyncio
async def test_default_path_makes_no_verify_calls(tmp_path) -> None:
    """With allow_provider_refs=False (default), pipeline.verify() must never be called."""
    store, fids = _facts(tmp_path)
    client = MockSearchClient(result=None)
    pipeline = VerificationPipeline({"arxiv": client})
    await collect_references(
        _hyp(fids),
        store.all(),
        provider_refs=[
            {"source": "arxiv", "external_id": "arxiv:99", "doi": None, "claim": "x"}
        ],
        allow_provider_refs=False,
        pipeline=pipeline,
    )
    assert client.fetch_calls == []  # extras skipped when flag OFF


@pytest.mark.asyncio
async def test_fabricated_citation_dropped(tmp_path) -> None:
    """A provider-proposed citation whose fetch_by_id returns None must be dropped."""
    store, fids = _facts(tmp_path)
    client = MockSearchClient(result=None)  # nothing resolves → not verified
    pipeline = VerificationPipeline({"arxiv": client})
    refs = await collect_references(
        _hyp(fids),
        store.all(),
        provider_refs=[
            {
                "source": "arxiv",
                "external_id": "arxiv:99",
                "doi": None,
                "claim": "hallucinated",
            }
        ],
        allow_provider_refs=True,
        pipeline=pipeline,
    )
    assert all(r.external_id != "arxiv:99" for r in refs)


@pytest.mark.asyncio
async def test_verified_provider_ref_admitted(tmp_path) -> None:
    """A provider ref that passes pipeline.verify() (status='verified') must be admitted."""
    store, fids = _facts(tmp_path)
    # Abstract contains the evidence_span so L4 lexical score is 1.0 → "verified"
    paper = PaperResult(
        source="arxiv",
        external_id="arxiv:99",
        title="T",
        authors=["A"],
        year=2020,
        venue=None,
        abstract="grounded quote",
        url=None,
        doi=None,
    )
    client = MockSearchClient(result=paper)
    pipeline = VerificationPipeline({"arxiv": client})
    refs = await collect_references(
        _hyp(fids),
        store.all(),
        provider_refs=[
            {
                "source": "arxiv",
                "external_id": "arxiv:99",
                "doi": None,
                "claim": "real",
                "evidence_span": "grounded quote",
            }
        ],
        allow_provider_refs=True,
        pipeline=pipeline,
    )
    assert any(r.external_id == "arxiv:99" and r.verified for r in refs)
