---
change: research-plan-assembler
design-doc: docs/superpowers/specs/2026-07-14-research-plan-assembler-design.md
base-ref: f0efc9562f6e702d442502ed36123d5653ab40fb
---

# Research Plan Assembler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn one change #4 `RankedHypothesis` into a gated, 12-field 《科学假设与研究计划》 emitted as canonical JSON (source of truth) plus a Markdown rendering derived from it.

**Architecture:** A new standalone `loop_sci/plan/` package mirroring `loop_sci/hypothesis/`: `schemas.py` (canonical `ResearchPlan` + leaf dataclasses), deterministic assembly helpers (`fields.py`, `results.py`, `references.py`, `render.py`, `gate.py`), a `PlanAssemblerExecutor` (`executor.py`) with `async run(unit) -> ExecutorResult`, an `assemble` tool (`tools.py`), and a Hydra config group (`config.py` + `conf/plan/default.yaml`). Three Qwen calls per plan (reasoning fields; Results derivation; Title+Abstract); Datasets/Source/Target/References/gate/render are all deterministic (no provider call). References are real-by-construction (grounding-fact `SourceRef`s) with optional provider-proposed extras routed through change #2 `VerificationPipeline.verify`.

**Tech Stack:** Python 3, dataclasses, `asyncio`, Hydra 1.3.4 (config group), pytest + `pytest-asyncio`, ruff 0.15.21. Reuses `loop_sci.hypothesis.ranked.RankedHypothesis`, `loop_sci.literature.factbase.store.FactStore`, `loop_sci.literature.extract.fact.{Fact,SourceRef,VerificationStatus}`, `loop_sci.literature.verify.citation.VerificationPipeline`, `loop_sci.state.session.RunSession`, `loop_sci.engine.types.{DispatchUnit,ExecutorResult}`, `loop_sci.engine.tools.ToolRegistry`.

## Global Constraints

Every task's requirements implicitly include this section. Copy values verbatim.

- **Interpreter/linter (MANDATORY):** the project interpreter is `.venv/bin/python` (hydra 1.3.4, ruff 0.15.21). Bare `python`/`pytest` is a conda env WITHOUT deps. ALL test/lint commands use `.venv/bin/python -m pytest ...` and `.venv/bin/ruff ...`. Never invoke bare `pytest`, `python`, or `ruff`.
- **The 12 exact fields (PDF §4, pinned order):** Problem Statement, Rationale, Technical Details, Datasets, Source, Target, Paper Title, Abstract, Methods, Experiments, Results, References. Experiments carries **baselines + metrics in one field**.
- **The 12 exact canonical JSON keys (stable, snake_case):** `problem_statement`, `rationale`, `technical_details`, `datasets`, `source`, `target`, `paper_title`, `abstract`, `methods`, `experiments`, `results`, `references`. Plus provenance keys `node_id` and `gate`.
- **Evidence grades (exactly these three literals):** `[paper]`, `[inferred]`, `[guess]` (brackets included), consistent with change #4 `DerivationStep.grade`.
- **Results shape:** `{"derivation": [{"step": str, "grade": "[paper]|[inferred]|[guess]"}], "conclusion": str, "confidence": "final"|"low"}`. NO execution, NO shell, NO `eval`, NO subprocess anywhere in the Results path.
- **Load-bearing-guess downgrade (deterministic, provider-free):** a load-bearing Results step graded `[guess]` (no `[paper]`/`[inferred]` support) forces `confidence != "final"` → `"low"`.
- **Datasets/Source/Target:** DETERMINISTIC from grounding facts as candidates, each carrying `candidate: bool` (and `source_ref` where applicable). NEVER fabricate a dataset when grounding is absent — populate with an explicit empty/grounding-absent candidate marker (a recorded state, not a silent blank).
- **References — grounding-only by DEFAULT:** seed from grounding facts' `SourceRef`s (already verified in the #2 fact base → real by construction, count ≥ distinct grounding sources). Provider-proposed extras are behind a config flag `allow_provider_refs` that is **OFF by default**; when on, each extra is wrapped as a `Fact` and routed through `VerificationPipeline.verify(fact) -> VerificationStatus`; admit only `status == "verified"`, else drop or flag `verified: false` — never present as real. With the flag OFF the default path performs **zero** verification round-trips.
- **References entry shape:** `{"source": str, "external_id": str, "doi": str|None, "verified": bool, "fact_id": str|None}`.
- **JSON↔Markdown parity:** canonical JSON is the source of truth; Markdown is DERIVED from it. Every one of the 12 fields present in JSON appears in the Markdown and vice-versa — no field in one form but missing in the other. A completeness assertion enforces this.
- **Deterministic gate (provider-free):** plan is `final` iff (a) all 12 fields present + non-empty (Datasets/Source/Target satisfied by ≥1 candidate OR an explicit grounding-absent marker); (b) every References entry `verified: true`; (c) no ungrounded load-bearing claim (a `[guess]` load-bearing Results step forcing `confidence != final` fails the gate). Failure → plan flagged incomplete with the specific failed checks, NOT emitted as final.
- **Executor discipline:** `PlanAssemblerExecutor.run(unit)` is standalone (does NOT subclass Coordinator), exception-safe (any raise → `ExecutorResult(status="error", ...)`, never a partial persisted plan), no coordinator-interface change, `auto_git` stays off.
- **Resume keying:** keyed by the hypothesis **node_id** (stable SHA-1 from #4). If `session_dir/plans/<node_id>.json` exists → load and return it with NO provider call and NO verification, leaving the persisted plan unchanged.
- **Retry/robustness per Qwen call:** retry-once then drop, `isinstance` guard on parsed JSON shape (mirror `loop_sci/hypothesis/stages/contract.py`). A malformed response degrades to a gate failure, never a crash or a fabricated field.
- **Provider seam:** `await provider.create(system=..., messages=[{"role","content"}], max_tokens=...)` returning a response with `.get_text()` and a `.model` attr. Offline tests use `MockProvider` from `tests/conftest.py`. Verification offline uses `MockSearchClient` (see `tests/unit/literature/test_citation_verify.py`).
- **Coverage ≥80% on new code** (vendored `loop_sci/_vendor/**` excluded). Default suite: NO network, NO git. Live tests are opt-in `@pytest.mark.live`, skipped without `DASHSCOPE_API_KEY`.
- **File size:** keep each new module 200–400 lines; split if it grows past 400.

---

## File Structure

- `loop_sci/plan/__init__.py` — package exports (mirrors `hypothesis/__init__.py`).
- `loop_sci/plan/schemas.py` — `ResearchPlan` + leaf dataclasses (`Candidate`, `DerivationStep` reuse, `ResultsBlock`, `ExperimentsBlock`, `Reference`, `GateResult`) + `to_dict`/`from_dict`.
- `loop_sci/plan/fields.py` — Call 1 (reasoning fields) + Call 3 (Title/Abstract) + deterministic Datasets/Source/Target.
- `loop_sci/plan/results.py` — Call 2 (Results formula-derivation) + load-bearing-guess downgrade.
- `loop_sci/plan/references.py` — grounding-seed + optional verify()-gated extras.
- `loop_sci/plan/render.py` — canonical JSON build + Markdown rendering + parity assertion.
- `loop_sci/plan/gate.py` — deterministic completeness/anti-fabrication gate.
- `loop_sci/plan/config.py` — `PlanConfig` dataclass.
- `loop_sci/plan/executor.py` — `PlanAssemblerExecutor` (`async run`, resume, persist).
- `loop_sci/plan/tools.py` — `register_plan_tools` (`assemble` tool).
- `conf/plan/default.yaml` — Hydra config group.
- `loop_sci/config/schemas.py` — add `PlanConf` + `LoopSCIConfig.plan` (Modify).
- `conf/config.yaml` — add `plan: default` to `defaults` (Modify).
- `loop_sci/config/loader.py` — wire `PlanConf` (Modify).
- `tests/unit/plan/` — unit tests per group.
- `tests/integration/test_plan_assembler_e2e.py` — offline e2e + resume.
- `tests/live/test_plan_assembler_live.py` — opt-in live.
- `README.md` — add plan-assembler section (Modify).

---

## Task 1: Canonical schema (`loop_sci/plan/schemas.py`)

**Files:**
- Create: `loop_sci/plan/__init__.py`
- Create: `loop_sci/plan/schemas.py`
- Test: `tests/unit/plan/__init__.py`, `tests/unit/plan/test_schemas.py`

**Interfaces:**
- Produces: `Candidate(value: str, candidate: bool, source_ref: dict | None = None)`;
  `Reference(source: str, external_id: str, doi: str | None, verified: bool, fact_id: str | None = None)`;
  `ResultsBlock(derivation: list[dict], conclusion: str, confidence: str)` where each derivation item is `{"step": str, "grade": str}`;
  `ExperimentsBlock(baselines: list[str], metrics: list[str], design: str)`;
  `GateResult(passed: bool, failures: list[str])`;
  `ResearchPlan` with fields `problem_statement: str`, `rationale: str`, `technical_details: str`, `datasets: list[Candidate]`, `source: list[Candidate]`, `target: list[Candidate]`, `paper_title: str`, `abstract: str`, `methods: str`, `experiments: ExperimentsBlock`, `results: ResultsBlock`, `references: list[Reference]`, `node_id: str`, `gate: GateResult`; plus `ResearchPlan.to_dict() -> dict` and `ResearchPlan.from_dict(d) -> ResearchPlan` (lossless round-trip).
- Module constant `PLAN_JSON_KEYS: tuple[str, ...]` = the 12 snake_case keys in PDF order.

- [x] **Step 1: Write the failing test**

```python
# tests/unit/plan/test_schemas.py
from loop_sci.plan.schemas import (
    Candidate, ExperimentsBlock, GateResult, ResearchPlan, Reference,
    ResultsBlock, PLAN_JSON_KEYS,
)


def _plan() -> ResearchPlan:
    return ResearchPlan(
        problem_statement="P", rationale="R", technical_details="T",
        datasets=[Candidate(value="D1", candidate=True, source_ref={"source": "arxiv", "external_id": "arxiv:1", "doi": None})],
        source=[Candidate(value="S1", candidate=True)],
        target=[Candidate(value="Tg1", candidate=True)],
        paper_title="Title", abstract="Abs", methods="M",
        experiments=ExperimentsBlock(baselines=["b"], metrics=["m"], design="d"),
        results=ResultsBlock(derivation=[{"step": "x", "grade": "[paper]"}], conclusion="c", confidence="final"),
        references=[Reference(source="arxiv", external_id="arxiv:1", doi=None, verified=True, fact_id="f1")],
        node_id="hyp_abc", gate=GateResult(passed=True, failures=[]),
    )


def test_plan_json_keys_are_the_12_pinned_keys_in_order():
    assert PLAN_JSON_KEYS == (
        "problem_statement", "rationale", "technical_details", "datasets",
        "source", "target", "paper_title", "abstract", "methods",
        "experiments", "results", "references",
    )


def test_to_dict_carries_all_12_keys_plus_provenance():
    d = _plan().to_dict()
    for k in PLAN_JSON_KEYS:
        assert k in d
    assert d["node_id"] == "hyp_abc"
    assert d["gate"] == {"passed": True, "failures": []}


def test_from_dict_roundtrips():
    p = _plan()
    assert ResearchPlan.from_dict(p.to_dict()).to_dict() == p.to_dict()
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/plan/test_schemas.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'loop_sci.plan'`.

- [x] **Step 3: Write minimal implementation**

Create `loop_sci/plan/__init__.py` (empty for now, exports added in later tasks). Create `loop_sci/plan/schemas.py` with all leaf dataclasses above, `PLAN_JSON_KEYS`, and `ResearchPlan`. `to_dict` walks `PLAN_JSON_KEYS` in order, serialising `Candidate`/`Reference`/`ResultsBlock`/`ExperimentsBlock`/`GateResult` via `dataclasses.asdict`, then appends `node_id` and `gate`. `from_dict` reconstructs each nested dataclass. Use `from __future__ import annotations` and full type hints. Keep derivation items as plain dicts `{"step","grade"}` (grade is one of the three bracketed literals).

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/plan/test_schemas.py -v`
Expected: PASS (3 passed).

- [x] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check loop_sci/plan/schemas.py loop_sci/plan/__init__.py tests/unit/plan/test_schemas.py
git add loop_sci/plan/__init__.py loop_sci/plan/schemas.py tests/unit/plan/
git commit -m "feat(plan): canonical ResearchPlan schema with 12 pinned keys"
```

**Acceptance (traces to plan-assembly-integration "Canonical JSON + rendered Markdown" + plan-field-assembly task 1.1):** 12 keys stable + provenance; lossless round-trip.

---

## Task 2: Reasoning fields + Datasets/Source/Target (`loop_sci/plan/fields.py`)

Covers OpenSpec task group 1 (1.2, 1.3) and the domain-parameterization requirement.

**Files:**
- Create: `loop_sci/plan/fields.py`
- Test: `tests/unit/plan/test_fields.py`

**Interfaces:**
- Consumes: `RankedHypothesis` (from `loop_sci.hypothesis.ranked`), `FactStore`, a provider (Call 1 / Call 3), `Candidate` / `ExperimentsBlock` (Task 1).
- Produces:
  `async def assemble_reasoning_fields(hyp: RankedHypothesis, facts: list[Fact], provider, *, domain: str) -> dict` returning
  `{"problem_statement": str, "rationale": str, "technical_details": str, "methods": str, "experiments": ExperimentsBlock}` (Call 1; retry-once→drop; on failure fields are empty strings / empty ExperimentsBlock so the gate later fails).
  `async def assemble_title_abstract(plan_context: dict, provider, *, domain: str) -> dict` returning `{"paper_title": str, "abstract": str}` (Call 3).
  `def build_dst_candidates(hyp: RankedHypothesis, facts: list[Fact]) -> dict` returning `{"datasets": list[Candidate], "source": list[Candidate], "target": list[Candidate]}` — DETERMINISTIC, no provider.

- [x] **Step 1: Write the failing test**

```python
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
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/plan/test_fields.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'loop_sci.plan.fields'`.

- [x] **Step 3: Write minimal implementation**

Create `loop_sci/plan/fields.py`:
- `assemble_reasoning_fields`: build a system prompt anchored to `hyp.problem`, `hyp.mechanism`, `hyp.derivation_chain`, `hyp.diff_prediction`, and `domain`; require a JSON object with keys `problem_statement, rationale, technical_details, methods, experiments{baselines,metrics,design}`. Retry-once→drop pattern from `contract.py`: `for attempt in range(2): try: resp = await provider.create(...); d = json.loads(resp.get_text()); isinstance guard; return {...}`. On both-attempts failure, return empties (`""` and `ExperimentsBlock([], [], "")`) so the gate fails downstream. Parse `experiments` into an `ExperimentsBlock` (coerce `baselines`/`metrics` to `list[str]`).
- `assemble_title_abstract`: same discipline, JSON with `paper_title, abstract`; system prompt passes `plan_context` + `domain`.
- `build_dst_candidates` (deterministic): resolve grounding facts by `hyp.grounding_fact_ids` against the `facts` list (match `fact.fact_id`); for each grounding fact whose claim/entities mention dataset-like tokens, emit a dataset `Candidate(value=<entity or claim snippet>, candidate=True, source_ref=fact.source_ref.to_dict())`. `source` = candidates from grounding facts' claims (historical data derivation rests on). `target` = candidates derived deterministically from `hyp.diff_prediction` tokens (to-be-collected features), `Candidate(value=..., candidate=True)` (no source_ref). When no grounding fact exists, return a single grounding-absent marker per field: `[Candidate(value="", candidate=True, source_ref=None)]` — NEVER invent a concrete dataset.

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/plan/test_fields.py -v`
Expected: PASS (5 passed).

- [x] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check loop_sci/plan/fields.py tests/unit/plan/test_fields.py
git add loop_sci/plan/fields.py tests/unit/plan/test_fields.py
git commit -m "feat(plan): domain-parameterized reasoning fields + deterministic DST candidates"
```

**Acceptance (traces to plan-field-assembly scenarios):** reasoning fields non-empty, Experiments carries baselines+metrics; domain parameterized (two domains, no code change); DST candidates trace to grounding facts; no fabricated dataset when grounding absent.

---

## Task 3: Results by formula-derivation (`loop_sci/plan/results.py`)

Covers OpenSpec task group 2 (2.1, 2.2).

**Files:**
- Create: `loop_sci/plan/results.py`
- Test: `tests/unit/plan/test_results.py`

**Interfaces:**
- Consumes: `RankedHypothesis`, provider (Call 2), `ResultsBlock` (Task 1).
- Produces:
  `async def derive_results(hyp: RankedHypothesis, provider, *, domain: str) -> ResultsBlock` — Call 2 producing `{derivation: [{step, grade}], conclusion}`; then applies the deterministic downgrade and sets `confidence`.
  `def apply_load_bearing_downgrade(derivation: list[dict], conclusion: str) -> str` — returns `"final"` unless a load-bearing step is `[guess]` with no `[paper]`/`[inferred]` support, in which case `"low"`. Load-bearing = the LAST derivation step (the decisive step the conclusion rests on).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/plan/test_results.py
import json
import pytest
from loop_sci.hypothesis.ranked import RankedHypothesis
from loop_sci.plan.results import apply_load_bearing_downgrade, derive_results
from tests.conftest import MockProvider


def _hyp():
    return RankedHypothesis(
        node_id="h", problem="p", mechanism="m",
        derivation_chain=[{"step": "s", "grade": "[paper]", "fact_ids": ["f1"]}],
        diff_prediction="d", novelty=0.4, self_consistency=0.5, overall_score=0.4,
        grounding_fact_ids=["f1"],
    )


def test_downgrade_when_load_bearing_step_is_guess():
    deriv = [{"step": "a", "grade": "[paper]"}, {"step": "b", "grade": "[guess]"}]
    assert apply_load_bearing_downgrade(deriv, "feasible") == "low"


def test_final_when_load_bearing_grounded():
    deriv = [{"step": "a", "grade": "[guess]"}, {"step": "b", "grade": "[paper]"}]
    assert apply_load_bearing_downgrade(deriv, "feasible") == "final"


@pytest.mark.asyncio
async def test_derive_results_is_graded_derivation_no_execution():
    resp = json.dumps({
        "derivation": [{"step": "bound from mechanism", "grade": "[inferred]"}],
        "conclusion": "effect size within [0.1, 0.3]",
    })
    rb = await derive_results(_hyp(), MockProvider(responses=[resp]), domain="neuroscience")
    assert rb.derivation and all(s["grade"] in ("[paper]", "[inferred]", "[guess]") for s in rb.derivation)
    assert rb.confidence == "final"
    assert rb.conclusion


@pytest.mark.asyncio
async def test_load_bearing_guess_downgrades_to_low():
    resp = json.dumps({
        "derivation": [{"step": "guessed decisive step", "grade": "[guess]"}],
        "conclusion": "feasible",
    })
    rb = await derive_results(_hyp(), MockProvider(responses=[resp]), domain="neuroscience")
    assert rb.confidence == "low"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/plan/test_results.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'loop_sci.plan.results'`.

- [ ] **Step 3: Write minimal implementation**

Create `loop_sci/plan/results.py`. `derive_results`: system prompt instructs an analytical feasibility argument (expected bound/effect size) from `hyp.mechanism` + `hyp.diff_prediction`, each step graded `[paper]`/`[inferred]`/`[guess]`, and EXPLICITLY forbids reporting any executed measurement or shell/eval command. Retry-once→drop; `isinstance` guard; coerce each step to `{"step": str, "grade": <one of the three; default "[guess]">}`. On both-attempts failure return `ResultsBlock(derivation=[], conclusion="", confidence="low")`. Then `confidence = apply_load_bearing_downgrade(derivation, conclusion)`. `apply_load_bearing_downgrade`: if `not derivation` → `"low"`; let `last = derivation[-1]`; if `last["grade"] == "[guess]"` and no other step is `[paper]`/`[inferred]` → `"low"`, else `"final"`. NO subprocess/eval imports anywhere in this module.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/plan/test_results.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check loop_sci/plan/results.py tests/unit/plan/test_results.py
git add loop_sci/plan/results.py tests/unit/plan/test_results.py
git commit -m "feat(plan): Results by evidence-graded formula-derivation with load-bearing-guess downgrade"
```

**Acceptance (traces to results-derivation scenarios):** graded derivation, no execution path; load-bearing `[guess]` downgrades to low/non-final; grounded derivation reaches a feasibility conclusion.

---

## Task 4: Real-only reference verification (`loop_sci/plan/references.py`)

Covers OpenSpec task group 3 (3.1, 3.2).

**Files:**
- Create: `loop_sci/plan/references.py`
- Test: `tests/unit/plan/test_references.py`

**Interfaces:**
- Consumes: `RankedHypothesis`, `list[Fact]`, `VerificationPipeline`, `Reference` (Task 1).
- Produces:
  `async def collect_references(hyp: RankedHypothesis, facts: list[Fact], *, provider_refs: list[dict] | None = None, allow_provider_refs: bool = False, pipeline: VerificationPipeline | None = None) -> list[Reference]`.
  Seeds `Reference(verified=True)` from each distinct grounding fact `SourceRef`. When `allow_provider_refs` and `pipeline` are set, wraps each `provider_refs` dict as a `Fact` and calls `await pipeline.verify(fact)`; admits only `status == "verified"` (dropped otherwise). With flag OFF: zero verify calls.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/plan/test_references.py
import pytest
from loop_sci.hypothesis.ranked import RankedHypothesis
from loop_sci.literature.extract.fact import Fact, SourceRef
from loop_sci.literature.factbase.store import FactStore
from loop_sci.literature.search.schema import PaperResult
from loop_sci.literature.verify.citation import VerificationPipeline
from loop_sci.plan.references import collect_references


class MockSearchClient:
    def __init__(self, result): self._result = result; self.fetch_calls = []
    async def search(self, query, *, max_results=10): return []
    async def fetch_by_id(self, external_id):
        self.fetch_calls.append(external_id); return self._result


def _hyp(fids):
    return RankedHypothesis(node_id="h", problem="p", mechanism="m",
        derivation_chain=[], diff_prediction="d", novelty=None,
        self_consistency=None, overall_score=None, grounding_fact_ids=fids)


def _facts(tmp_path):
    store = FactStore(tmp_path / "f.json")
    f1 = store.add(Fact(claim="c1", source_ref=SourceRef("arxiv", "arxiv:1", None),
        evidence_span="e", confidence=0.9, grounding_scope="abstract"))
    f2 = store.add(Fact(claim="c2", source_ref=SourceRef("pubmed", "pm:2", None),
        evidence_span="e", confidence=0.9, grounding_scope="abstract"))
    return store, [f1, f2]


@pytest.mark.asyncio
async def test_grounded_hypothesis_yields_real_refs_count_ge_distinct_sources(tmp_path):
    store, fids = _facts(tmp_path)
    refs = await collect_references(_hyp(fids), store.all())
    assert len(refs) >= 2
    assert all(r.verified for r in refs)


@pytest.mark.asyncio
async def test_default_path_makes_no_verify_calls(tmp_path):
    store, fids = _facts(tmp_path)
    client = MockSearchClient(result=None)
    pipeline = VerificationPipeline({"arxiv": client})
    await collect_references(_hyp(fids), store.all(),
        provider_refs=[{"source": "arxiv", "external_id": "arxiv:99", "doi": None, "claim": "x"}],
        allow_provider_refs=False, pipeline=pipeline)
    assert client.fetch_calls == []  # extras skipped when flag OFF


@pytest.mark.asyncio
async def test_fabricated_citation_dropped(tmp_path):
    store, fids = _facts(tmp_path)
    client = MockSearchClient(result=None)  # nothing resolves -> not verified
    pipeline = VerificationPipeline({"arxiv": client})
    refs = await collect_references(_hyp(fids), store.all(),
        provider_refs=[{"source": "arxiv", "external_id": "arxiv:99", "doi": None, "claim": "hallucinated"}],
        allow_provider_refs=True, pipeline=pipeline)
    assert all(r.external_id != "arxiv:99" for r in refs)


@pytest.mark.asyncio
async def test_verified_provider_ref_admitted(tmp_path):
    store, fids = _facts(tmp_path)
    paper = PaperResult(source="arxiv", external_id="arxiv:99", title="T",
        authors=["A"], year=2020, abstract="a", doi=None)
    client = MockSearchClient(result=paper)
    pipeline = VerificationPipeline({"arxiv": client})
    refs = await collect_references(_hyp(fids), store.all(),
        provider_refs=[{"source": "arxiv", "external_id": "arxiv:99", "doi": None,
                        "claim": "real", "evidence_span": "grounded quote"}],
        allow_provider_refs=True, pipeline=pipeline)
    assert any(r.external_id == "arxiv:99" and r.verified for r in refs)
```

> Note: confirm `PaperResult`'s field names against `loop_sci/literature/search/schema.py` before writing the test; adjust the constructor kwargs to match.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/plan/test_references.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'loop_sci.plan.references'`.

- [ ] **Step 3: Write minimal implementation**

Create `loop_sci/plan/references.py`. `collect_references`:
1. Resolve grounding facts from `hyp.grounding_fact_ids` against `facts` (match `fact.fact_id`); for each distinct `source_ref`, append `Reference(source=ref.source, external_id=ref.external_id, doi=ref.doi, verified=True, fact_id=fact.fact_id)`. Dedupe by `(source, external_id)`.
2. If `allow_provider_refs` and `pipeline` and `provider_refs`: for each dict, build a `Fact(claim=..., source_ref=SourceRef(...), evidence_span=... or claim, confidence=0.5, grounding_scope="abstract")`; `status = await pipeline.verify(fact)`; if `status.status == "verified"` append `Reference(..., verified=True, fact_id=None)`; else drop (or append `verified=False` if a "flag" mode is desired — default: drop). Guard each wrap in try/except so a malformed extra is skipped, not fatal.
3. With flag OFF, never touch `pipeline` → zero verify calls.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/plan/test_references.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check loop_sci/plan/references.py tests/unit/plan/test_references.py
git add loop_sci/plan/references.py tests/unit/plan/test_references.py
git commit -m "feat(plan): grounding-only references by default, verify()-gated extras"
```

**Acceptance (traces to reference-verification-assembly scenarios):** only verified references appear; fabricated citation dropped; grounded hypothesis yields real refs (count ≥ distinct grounding sources); offline via mocked seam; default path zero round-trips.

---

## Task 5: Render (JSON build + Markdown parity) + gate (`render.py`, `gate.py`)

Covers OpenSpec task group 4 (4.1, 4.2, 4.3).

**Files:**
- Create: `loop_sci/plan/render.py`
- Create: `loop_sci/plan/gate.py`
- Test: `tests/unit/plan/test_render.py`, `tests/unit/plan/test_gate.py`

**Interfaces:**
- Consumes: `ResearchPlan`, `PLAN_JSON_KEYS`, `Candidate`, `Reference`, `ResultsBlock`, `ExperimentsBlock`, `GateResult` (Task 1).
- Produces:
  `def render_markdown(plan: ResearchPlan) -> str` — Markdown with a `## ` heading per field in PDF order (headings from a `PLAN_FIELD_TITLES` map: `problem_statement→"Problem Statement"`, … `references→"References"`).
  `def assert_json_markdown_parity(plan: ResearchPlan) -> None` — raises `AssertionError` if any of the 12 field titles is missing from the rendered Markdown.
  `def run_gate(plan: ResearchPlan) -> GateResult` — deterministic, provider-free.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/plan/test_render.py
from loop_sci.plan.render import PLAN_FIELD_TITLES, assert_json_markdown_parity, render_markdown
from tests.unit.plan.test_schemas import _plan  # reuse the builder


def test_markdown_contains_all_12_field_titles():
    md = render_markdown(_plan())
    for title in PLAN_FIELD_TITLES.values():
        assert f"## {title}" in md


def test_parity_holds_for_complete_plan():
    assert_json_markdown_parity(_plan())  # must not raise
```

```python
# tests/unit/plan/test_gate.py
from dataclasses import replace
from loop_sci.plan.gate import run_gate
from loop_sci.plan.schemas import Reference, ResultsBlock
from tests.unit.plan.test_schemas import _plan


def test_gate_passes_on_complete_verified_plan():
    g = run_gate(_plan())
    assert g.passed and g.failures == []


def test_gate_fails_on_empty_field():
    p = replace(_plan(), problem_statement="")
    g = run_gate(p)
    assert not g.passed and any("problem_statement" in f for f in g.failures)


def test_gate_fails_on_unverified_reference():
    p = replace(_plan(), references=[Reference("arxiv", "arxiv:1", None, verified=False, fact_id=None)])
    g = run_gate(p)
    assert not g.passed and any("reference" in f.lower() for f in g.failures)


def test_gate_fails_on_ungrounded_load_bearing_claim():
    p = replace(_plan(), results=ResultsBlock(
        derivation=[{"step": "decisive", "grade": "[guess]"}], conclusion="feasible", confidence="low"))
    g = run_gate(p)
    assert not g.passed and any("load-bearing" in f.lower() or "confidence" in f.lower() for f in g.failures)
```

> `_plan` must be importable — mark `tests/unit/plan/test_schemas.py::_plan` as a plain module-level helper (it already is). If cross-test import is undesirable, copy the builder into a shared `tests/unit/plan/_helpers.py` and import from there in Tasks 5–7.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/plan/test_render.py tests/unit/plan/test_gate.py -v`
Expected: FAIL with `ModuleNotFoundError` for `loop_sci.plan.render` / `loop_sci.plan.gate`.

- [ ] **Step 3: Write minimal implementation**

`loop_sci/plan/render.py`: define `PLAN_FIELD_TITLES: dict[str, str]` (12 keys → PDF titles in order). `render_markdown` walks `PLAN_JSON_KEYS`, emits `## <Title>` then a rendered body per field type (Candidates as bullet list with `(candidate)` flag; ExperimentsBlock as "Baselines: …\nMetrics: …\nDesign: …"; ResultsBlock as graded derivation bullets + conclusion + confidence; References as bullet list `source:external_id (verified)`). `assert_json_markdown_parity` renders once and asserts each `## <Title>` present.
`loop_sci/plan/gate.py`: `run_gate` collects failures: for each of the 12 keys, non-empty check (str fields truthy; list fields have ≥1 entry; DST fields satisfied by ≥1 candidate incl. grounding-absent marker); every `Reference.verified` true else failure `"unverified reference: <id>"`; Results check — if `plan.results.confidence != "final"` add `"load-bearing ungrounded claim / confidence != final"`. `passed = not failures`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/plan/test_render.py tests/unit/plan/test_gate.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check loop_sci/plan/render.py loop_sci/plan/gate.py tests/unit/plan/test_render.py tests/unit/plan/test_gate.py
git add loop_sci/plan/render.py loop_sci/plan/gate.py tests/unit/plan/test_render.py tests/unit/plan/test_gate.py
git commit -m "feat(plan): JSON->Markdown rendering with parity + deterministic gate"
```

**Acceptance (traces to plan-assembly-integration "Canonical JSON + rendered Markdown" + "Deterministic gate" scenarios):** all 12 fields in both forms (no divergence); gate fails on missing/empty field, unverified reference, ungrounded load-bearing claim; passes on complete verified plan; no provider call.

---

## Task 6: Config group + executor + tool (`config.py`, `executor.py`, `tools.py`, wiring)

Covers OpenSpec task group 4 (4.4, 4.5) and group 1 (1.4 call budget).

**Files:**
- Create: `loop_sci/plan/config.py`
- Create: `loop_sci/plan/executor.py`
- Create: `loop_sci/plan/tools.py`
- Create: `conf/plan/default.yaml`
- Modify: `loop_sci/plan/__init__.py` (add exports)
- Modify: `loop_sci/config/schemas.py` (add `PlanConf`, `LoopSCIConfig.plan`)
- Modify: `conf/config.yaml` (add `plan: default` to `defaults`)
- Modify: `loop_sci/config/loader.py` (wire `PlanConf`)
- Test: `tests/unit/plan/test_executor.py`, `tests/unit/plan/test_tools.py`, `tests/unit/plan/test_plan_config.py`

**Interfaces:**
- Consumes: everything from Tasks 1–5; `RankedHypothesisStore`, `FactStore`, `RunSession`, `DispatchUnit`, `ExecutorResult`, `ToolRegistry`, `VerificationPipeline`.
- Produces:
  `PlanConfig(domain: str = "natural-science", call_budget: int = 3, allow_provider_refs: bool = False, ...)`.
  `PlanAssemblerExecutor(session, *, provider, ranked_store, fact_store, verification_pipeline=None, config=None)` with `async def run(unit: DispatchUnit) -> ExecutorResult` and helper `async def assemble_for_node(node_id: str) -> ResearchPlan`.
  `register_plan_tools(registry: ToolRegistry, executor)` registering the `assemble` tool.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/plan/test_executor.py
import json
import pytest
from loop_sci.hypothesis.ranked import RankedHypothesis, RankedHypothesisStore
from loop_sci.hypothesis.schemas import build_hyp_refs, HypothesisHyp, DerivationStep
from loop_sci.literature.extract.fact import Fact, SourceRef
from loop_sci.literature.factbase.store import FactStore
from loop_sci.engine.types import DispatchUnit
from loop_sci.plan.config import PlanConfig
from loop_sci.plan.executor import PlanAssemblerExecutor
from loop_sci.state.idea_tree import IdeaTree, Node
from loop_sci.state.session import RunSession
from tests.conftest import MockProvider


def _c1(): return json.dumps({"problem_statement": "P", "rationale": "R",
    "technical_details": "T", "methods": "M",
    "experiments": {"baselines": ["b"], "metrics": ["m"], "design": "d"}})
def _c2(): return json.dumps({"derivation": [{"step": "s", "grade": "[paper]"}], "conclusion": "feasible"})
def _c3(): return json.dumps({"paper_title": "Ti", "abstract": "Ab"})


def _session_with_hyp(tmp_path):
    session = RunSession.create(runs_root=tmp_path, task="t")
    store = FactStore(session.session_dir / "facts.json")
    fid = store.add(Fact(claim="ImageNet helps", source_ref=SourceRef("arxiv", "arxiv:1", None),
        evidence_span="e", confidence=0.9, grounding_scope="abstract", entities=["ImageNet"]))
    refs = build_hyp_refs(kind="hypothesis", frame="primary", topic="scaling",
        hyp=HypothesisHyp(MECHANISM="m", KILL="k", BRACKET="br", DIFF_PREDICTION="d"),
        derivation=[DerivationStep(step="s", grade="[paper]", fact_ids=[fid])],
        contract=None, verdict=None, scores=None, autopsy=None,
        iteration=__import__("loop_sci.hypothesis.schemas", fromlist=["Iteration"]).Iteration())
    node = Node(id="hyp_node1", parent_id="ROOT", hypothesis="m", depth=2, status="accepted", refs=refs)
    node.score = 0.5
    session.tree.add_node(node); session.tree.save()
    return session, store, fid


@pytest.mark.asyncio
async def test_executor_assembles_gated_12_field_plan(tmp_path):
    session, store, fid = _session_with_hyp(tmp_path)
    ex = PlanAssemblerExecutor(session, provider=MockProvider(responses=[_c1(), _c2(), _c3()]),
        ranked_store=RankedHypothesisStore(session.tree), fact_store=store,
        config=PlanConfig(domain="neuroscience"))
    res = await ex.run(DispatchUnit(node_id="hyp_node1", goal="scaling"))
    assert res.status == "done"
    assert (session.session_dir / "plans" / "hyp_node1.json").exists()
    assert (session.session_dir / "plans" / "hyp_node1.md").exists()


@pytest.mark.asyncio
async def test_resume_does_not_reassemble(tmp_path):
    session, store, fid = _session_with_hyp(tmp_path)
    prov = MockProvider(responses=[_c1(), _c2(), _c3()])
    ex = PlanAssemblerExecutor(session, provider=prov,
        ranked_store=RankedHypothesisStore(session.tree), fact_store=store)
    await ex.run(DispatchUnit(node_id="hyp_node1", goal="scaling"))
    calls_after_first = prov._index
    await ex.run(DispatchUnit(node_id="hyp_node1", goal="scaling"))
    assert prov._index == calls_after_first  # no new provider calls on resume


@pytest.mark.asyncio
async def test_run_is_exception_safe(tmp_path):
    session, store, _ = _session_with_hyp(tmp_path)
    ex = PlanAssemblerExecutor(session, provider=MockProvider(responses=[_c1(), _c2(), _c3()]),
        ranked_store=RankedHypothesisStore(session.tree), fact_store=store)
    res = await ex.run(DispatchUnit(node_id="does_not_exist", goal="scaling"))
    assert res.status in ("error", "done")  # unknown node -> structured, never raises
```

```python
# tests/unit/plan/test_tools.py
import json, pytest
from loop_sci.engine.tools import ToolRegistry
from loop_sci.plan.tools import register_plan_tools


@pytest.mark.asyncio
async def test_assemble_tool_offline_no_executor_structured_error():
    reg = ToolRegistry()
    register_plan_tools(reg, executor=None)
    out = await reg.call("assemble", {"node_id": "hyp_node1"})
    assert "error" in json.loads(out)
```

```python
# tests/unit/plan/test_plan_config.py
from loop_sci.config import load_config


def test_plan_config_group_loads_with_defaults():
    cfg = load_config(config_dir="conf")
    assert cfg.plan.domain
    assert cfg.plan.call_budget == 3
    assert cfg.plan.allow_provider_refs is False
```

> Confirm `ToolRegistry.call` / `register` signatures against `loop_sci/engine/tools.py` and `Node`/`IdeaTree`/`RunSession.create` signatures against their modules before writing; adjust kwargs to match. Mirror `register_hypothesis_tools` for the tool structure.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/plan/test_executor.py tests/unit/plan/test_tools.py tests/unit/plan/test_plan_config.py -v`
Expected: FAIL with `ModuleNotFoundError` / `AttributeError: 'LoopSCIConfig' object has no attribute 'plan'`.

- [ ] **Step 3: Write minimal implementation**

- `loop_sci/plan/config.py`: `@dataclass PlanConfig` with `domain: str = "natural-science"`, `call_budget: int = 3`, `allow_provider_refs: bool = False`, plus any thresholds (e.g. `min_reference_count: int = 1`). Full docstring like `HypothesisConfig`.
- `loop_sci/plan/executor.py`: `PlanAssemblerExecutor`. `run` wraps `_assemble(unit)` in try/except → `ExecutorResult(status="error", ...)`. `_assemble`: (1) resolve `RankedHypothesis` by `unit.node_id` via `ranked_store.get_ranked(...)` (match `r.node_id`); if none → `ExecutorResult(status="error", summary="unknown node ...")`. (2) Resume: if `session_dir/plans/<node_id>.json` exists → load JSON, return `ExecutorResult(status="done", ...)` with NO provider/verify calls. (3) Call 1 + `build_dst_candidates`; (4) Call 2 `derive_results`; (5) Call 3 `assemble_title_abstract`; (6) `collect_references(...)` (extras only if `config.allow_provider_refs`); (7) build `ResearchPlan`, run `run_gate`, set `plan.gate`; (8) `render_markdown` + `assert_json_markdown_parity`; (9) mkdir `plans/`, write `<node_id>.json` (from `plan.to_dict()`) and `<node_id>.md`; `session.advance_step()`. Respect `call_budget` (default 3): if budget < 3, skip the lowest-priority call(s) cleanly (Title/Abstract first) so the run stops without crashing. Return `ExecutorResult(status="done", summary=..., refs={"node_id":..., "gate_passed": plan.gate.passed})`.
- `loop_sci/plan/tools.py`: `register_plan_tools(registry, executor)` registering `assemble` (schema: `{node_id: string}`). Mirror `register_hypothesis_tools`: if `executor is None` → `{"error": "no_executor", ...}`; else `await executor.run(DispatchUnit(node_id=node_id, goal=""))` and return structured JSON; catch exceptions → structured error.
- Wiring: add `PlanConf` to `loop_sci/config/schemas.py` mirroring `PlanConfig` fields; add `plan: PlanConf = field(default_factory=PlanConf)` to `LoopSCIConfig`. Add `plan: default` under `defaults:` in `conf/config.yaml`. Create `conf/plan/default.yaml` (`# @package _global_.plan` + `domain: "natural-science"`, `call_budget: 3`, `allow_provider_refs: false`, `min_reference_count: 1`). In `loader.py` add `plan_fields = {f for f in vars(PlanConf())}` and `plan=PlanConf(**{k: v for k, v in d.get("plan", {}).items() if k in plan_fields})`.
- `loop_sci/plan/__init__.py`: export `PlanAssemblerExecutor`, `PlanConfig`, `ResearchPlan`, `register_plan_tools`, and the schema dataclasses, with `__all__`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/plan/test_executor.py tests/unit/plan/test_tools.py tests/unit/plan/test_plan_config.py -v`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check loop_sci/plan/ conf/plan/default.yaml loop_sci/config/schemas.py loop_sci/config/loader.py tests/unit/plan/
git add loop_sci/plan/ conf/plan/default.yaml conf/config.yaml loop_sci/config/schemas.py loop_sci/config/loader.py tests/unit/plan/
git commit -m "feat(plan): PlanAssemblerExecutor + assemble tool + Hydra config group wired into LoopSCIConfig"
```

**Acceptance (traces to plan-assembly-integration "Specialist executor and tool integration" scenarios):** executor assembles a gated 12-field plan (JSON+Markdown) offline, no network/git; resume returns existing plan without re-invoking provider/verification; tool wraps the same pipeline offline; config group loads. `auto_git` untouched (stays off).

---

## Task 7: Offline e2e + resume, live opt-in, coverage + README

Covers OpenSpec task group 5 (5.1, 5.2, 5.3) and the group-4 unit tie-together (4.6).

**Files:**
- Create: `tests/integration/test_plan_assembler_e2e.py`
- Create: `tests/live/test_plan_assembler_live.py`
- Modify: `README.md` (add plan-assembler section)
- Test: the two files above

**Interfaces:**
- Consumes: `PlanAssemblerExecutor`, `VerificationPipeline`, `MockSearchClient`, `MockProvider`, a seeded `RunSession` + `FactStore` + `RankedHypothesis` (reuse the `_session_with_hyp` builder from Task 6; factor it into `tests/integration/` or import).

- [ ] **Step 1: Write the failing integration test**

```python
# tests/integration/test_plan_assembler_e2e.py
import json, pytest
from loop_sci.engine.types import DispatchUnit
from loop_sci.hypothesis.ranked import RankedHypothesisStore
from loop_sci.plan.config import PlanConfig
from loop_sci.plan.executor import PlanAssemblerExecutor
from loop_sci.plan.schemas import PLAN_JSON_KEYS
from tests.conftest import MockProvider
# reuse the seeded-session helper (import or replicate from tests/unit/plan/test_executor.py)


@pytest.mark.asyncio
async def test_e2e_offline_gated_complete_plan_and_resume(tmp_path):
    session, store, fid = _session_with_hyp(tmp_path)   # provides accepted hyp + grounding fact
    prov = MockProvider(responses=[_c1(), _c2(), _c3()])
    ex = PlanAssemblerExecutor(session, provider=prov,
        ranked_store=RankedHypothesisStore(session.tree), fact_store=store,
        config=PlanConfig(domain="neuroscience"))
    res = await ex.run(DispatchUnit(node_id="hyp_node1", goal="scaling"))
    assert res.status == "done"

    data = json.loads((session.session_dir / "plans" / "hyp_node1.json").read_text())
    for k in PLAN_JSON_KEYS:
        assert k in data
    assert data["gate"]["passed"] is True
    assert data["references"] and all(r["verified"] for r in data["references"])
    md = (session.session_dir / "plans" / "hyp_node1.md").read_text()
    assert "## Problem Statement" in md and "## References" in md

    idx = prov._index
    res2 = await ex.run(DispatchUnit(node_id="hyp_node1", goal="scaling"))
    assert res2.status == "done"
    assert prov._index == idx  # resume: no re-spend
```

- [ ] **Step 2: Run to verify it fails, then passes**

Run: `.venv/bin/python -m pytest tests/integration/test_plan_assembler_e2e.py -v`
Expected first: FAIL (helper not defined) → define `_session_with_hyp`/`_c1`/`_c2`/`_c3` in the file (copy from Task 6) → PASS.

- [ ] **Step 3: Write the live opt-in test**

```python
# tests/live/test_plan_assembler_live.py
import os, pytest

pytestmark = pytest.mark.live


@pytest.mark.skipif(not os.environ.get("DASHSCOPE_API_KEY"), reason="needs DASHSCOPE_API_KEY")
@pytest.mark.asyncio
async def test_live_assembly_small_domain_topic(tmp_path):
    # Build a real Bailian provider, a seeded fact base, one RankedHypothesis,
    # run PlanAssemblerExecutor for a small domain-parameterized topic, assert a
    # gated JSON+Markdown plan was written. Mirror tests/live/test_hypothesis_live.py setup.
    ...
```

Run (must be skipped without key): `.venv/bin/python -m pytest tests/live/test_plan_assembler_live.py -v`
Expected: SKIPPED (no `DASHSCOPE_API_KEY`).

- [ ] **Step 4: Full suite + coverage + lint**

```bash
.venv/bin/python -m pytest tests/unit/plan tests/integration/test_plan_assembler_e2e.py \
  --cov=loop_sci/plan --cov-report=term-missing
```
Expected: all pass, coverage on `loop_sci/plan` ≥ 80%. Add tests for any uncovered branch (e.g. call_budget < 3, malformed Call-1 JSON → gate fail, grounding-absent DST path).

```bash
.venv/bin/ruff check loop_sci/plan tests/unit/plan tests/integration/test_plan_assembler_e2e.py tests/live/test_plan_assembler_live.py
```
Expected: no errors.

- [ ] **Step 5: README section + commit**

Add a "Research Plan Assembler (change #5)" section to `README.md` covering: the 12-field 《科学假设与研究计划》 overview; Results by formula-derivation (evidence-graded, no execution); real-reference verification (grounding-only default, verify()-gated extras); the runtime domain parameter; JSON (source of truth) + derived Markdown output; and "live tests need `DASHSCOPE_API_KEY`". Then:

```bash
git add tests/integration/test_plan_assembler_e2e.py tests/live/test_plan_assembler_live.py README.md
git commit -m "test(plan): offline e2e + resume, live opt-in; docs: plan-assembler README section"
```

**Acceptance (traces to plan-assembly-integration resume scenario + task group 5):** offline e2e produces a gated complete 12-field plan (JSON+Markdown) with real references, no network/git; resume does not re-assemble; live test skipped without key; coverage ≥80% on `loop_sci/plan`; ruff clean; README section present.

---

## Self-Review Notes

- **Spec coverage:** plan-field-assembly → Tasks 1–2; results-derivation → Task 3; reference-verification-assembly → Task 4; plan-assembly-integration (JSON/MD, gate, executor+tool, resume) → Tasks 5–7. Task groups 1–5 each map to Tasks 2, 3, 4, 5+6, 7.
- **Type consistency:** `ResearchPlan`, `Candidate`, `Reference`, `ResultsBlock`, `ExperimentsBlock`, `GateResult`, `PLAN_JSON_KEYS`, `PlanConfig`, `PlanAssemblerExecutor.run/assemble_for_node`, `collect_references`, `derive_results`, `apply_load_bearing_downgrade`, `build_dst_candidates`, `assemble_reasoning_fields`, `assemble_title_abstract`, `render_markdown`, `assert_json_markdown_parity`, `run_gate`, `register_plan_tools` are defined once and reused verbatim across tasks.
- **Before writing, confirm upstream signatures** (`PaperResult` fields, `ToolRegistry.register/call`, `Node`/`IdeaTree`/`RunSession.create`, `FactStore.add` returning `fact_id`) against their source modules — the plan flags each such spot inline.
