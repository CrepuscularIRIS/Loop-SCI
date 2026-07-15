# tests/unit/plan/test_fields.py
import json
import pytest
from loop_sci.hypothesis.ranked import RankedHypothesis
from loop_sci.literature.extract.fact import Fact, SourceRef
from loop_sci.literature.factbase.store import FactStore
from loop_sci.plan.fields import (
    assemble_reasoning_fields, assemble_title_abstract, build_dst_candidates,
)
from loop_sci.plan.schemas import ExperimentsBlock
from tests.conftest import MockProvider


def _hyp(fact_ids):
    return RankedHypothesis(
        node_id="hyp_x", problem="how does X scale",
        mechanism="X grows with Y", derivation_chain=[{"step": "s", "grade": "[paper]", "fact_ids": fact_ids}],
        diff_prediction="Y up -> Z up", novelty=0.4, self_consistency=0.5,
        overall_score=0.45, grounding_fact_ids=fact_ids,
    )


def _seed_facts(tmp_path):
    store = FactStore(tmp_path / "facts.json")
    fid = store.add(Fact(
        claim="ImageNet dataset improves accuracy",
        source_ref=SourceRef(source="arxiv", external_id="arxiv:1", doi=None),
        evidence_span="we trained on ImageNet", confidence=0.9,
        grounding_scope="abstract", entities=["ImageNet"],
    ))
    return store, fid


def _c1_response(domain):
    return json.dumps({
        "problem_statement": f"[{domain}] problem", "rationale": "because derivation chain",
        "technical_details": "details", "methods": "methods",
        "experiments": {"baselines": ["baseline-A"], "metrics": ["accuracy"], "design": "A/B"},
    })


@pytest.mark.asyncio
async def test_reasoning_fields_nonempty_and_experiments_has_baselines_and_metrics(tmp_path):
    store, fid = _seed_facts(tmp_path)
    prov = MockProvider(responses=[_c1_response("neuroscience")])
    out = await assemble_reasoning_fields(_hyp([fid]), store.all(), prov, domain="neuroscience")
    assert out["problem_statement"] and out["rationale"] and out["technical_details"] and out["methods"]
    exp = out["experiments"]
    assert isinstance(exp, ExperimentsBlock)
    assert exp.baselines and exp.metrics


@pytest.mark.asyncio
async def test_domain_is_parameterized_no_code_change(tmp_path):
    store, fid = _seed_facts(tmp_path)
    for domain in ("neuroscience", "economics"):
        prov = MockProvider(responses=[_c1_response(domain)])
        out = await assemble_reasoning_fields(_hyp([fid]), store.all(), prov, domain=domain)
        assert domain in out["problem_statement"]


def test_dst_candidates_trace_to_grounding_facts(tmp_path):
    store, fid = _seed_facts(tmp_path)
    dst = build_dst_candidates(_hyp([fid]), store.all())
    assert any(c.candidate for c in dst["datasets"])
    # a dataset candidate carries the grounding fact's source ref
    assert any(c.source_ref and c.source_ref["external_id"] == "arxiv:1" for c in dst["datasets"])
    assert dst["source"] and dst["target"]


def test_no_fabricated_dataset_when_grounding_absent(tmp_path):
    store = FactStore(tmp_path / "facts.json")  # empty
    dst = build_dst_candidates(_hyp([]), store.all())
    # grounding-absent marker: a candidate flagged candidate=True with an empty/pending value, never invented
    assert all(c.candidate for c in dst["datasets"])
    assert all(c.source_ref is None for c in dst["datasets"])


@pytest.mark.asyncio
async def test_title_abstract_produced_last(tmp_path):
    prov = MockProvider(responses=[json.dumps({"paper_title": "T", "abstract": "A"})])
    out = await assemble_title_abstract({"problem_statement": "P"}, prov, domain="neuroscience")
    assert out["paper_title"] == "T" and out["abstract"] == "A"
