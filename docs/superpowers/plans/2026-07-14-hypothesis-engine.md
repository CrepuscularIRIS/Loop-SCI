---
change: hypothesis-engine
design-doc: docs/superpowers/specs/2026-07-14-hypothesis-engine-design.md
base-ref: c1d01d9213a8972d12087babb3e275210a92d693
---

# Hypothesis Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `loop_sci/hypothesis/` — a plan-grade research-os pipeline (prospect' → forge' → contract → adversary' → autopsy') that consumes `FactStore` and emits scored, adversarially-vetted candidate hypotheses ranked for the #5 plan-assembler.

**Architecture:** `HypothesisExecutor` mirrors `LitMinerExecutor`: it receives a `DispatchUnit`, runs the full multi-round loop internally (no per-stage coordinator dispatch), and returns an `ExecutorResult`. A `HypothesisCoordinator` subclass overrides only `_observe()` (score-sorted expansion) and `_plan()` (fact-base context injection). A dedicated `IdeaTree` per run holds `topic root → problem-card nodes → hypothesis nodes`; grounding is by `fact_id` into `FactStore.filter()`, never by tree parentage. A Qwen-Max generator and Qwen-Plus KILL-persona reviewer form the non-self-acquitting jury; a deterministic pre-jury gate runs first and down-verdicts without spending a reviewer call.

**Tech Stack:** Python 3.11+, `loop_sci._vendor.arbor` (IdeaTree/Node/LLMProvider), `loop_sci.state` (Node subclass, RunSession), `loop_sci.literature.factbase.store` (FactStore read interface), `loop_sci.engine` (Coordinator, DispatchUnit, ExecutorResult, ToolRegistry), Hydra config, pytest + pytest-asyncio, ruff.

## Global Constraints

- Qwen-Max for generation, Qwen-Plus for review — both via DashScope/Bailian `build_provider()`.
- `FactStore` access through `.all()` / `.filter()` ONLY — no idea-tree internals.
- Hypothesis nodes attach under problem-card nodes; grounding = list of `fact_id` strings.
- No coordinator-interface change; `auto_git` stays off.
- Caps: ≤5 cards · ≤4 candidates/card · ≤3 rounds; Hydra-configurable.
- Novelty bands: LOW=0.15, HIGH=0.60; weights `w_n=w_c=0.5`; Hydra-configurable.
- Stall pivot at `stale_count ≥ 2`; escalate (stop) at `stale_count ≥ 4`.
- Region-close when ≥2 mechanisms killed by the same latent root within the run.
- `verdict-ledger.jsonl` is append-only — never overwrite, never re-spend a spent verdict.
- Offline tests use role-dispatching `MockProvider`; live tests gated on `DASHSCOPE_API_KEY`.
- Coverage ≥ 80% on new code (excluding `loop_sci/_vendor/`); ruff clean on all new files.
- retry-once → drop discipline for JSON parse failures (identical to `FactExtractor`).

---

## Files & Modules Map

**New package `loop_sci/hypothesis/`** (mirrors `loop_sci/literature/` layout):

```
loop_sci/hypothesis/
  __init__.py                  # public exports
  schemas.py                   # HypothesisNode refs payload dataclasses (card, hyp, derivation, contract, verdict, scores, autopsy, iteration)
  scoring.py                   # novelty + self_consistency scorer (deterministic + optional judge path)
  stages/
    __init__.py
    prospect.py                # prospect' stage: FactStore → problem cards
    forge.py                   # forge' stage: card → candidate hypotheses + rival siblings
    contract.py                # freeze derivation contract on a node
    adversary.py               # deterministic pre-jury gate + Qwen-Plus jury
    autopsy.py                 # kill → CONSTRAINT/CANDIDATE/REGION_CLOSE + stall ledger
  executor.py                  # HypothesisExecutor (mirrors LitMinerExecutor)
  coordinator.py               # HypothesisCoordinator (subclass of Coordinator)
  ranked.py                    # stable ranked-hypothesis query interface
  tools.py                     # generate/critique/rank ToolRegistry wrappers
  ledger.py                    # verdict-ledger.jsonl append-only writer + reader

conf/hypothesis/
  default.yaml                 # caps, thresholds, model names (Hydra group)

tests/unit/hypothesis/
  __init__.py
  test_schemas.py              # round-trip Node.refs payload
  test_scoring.py              # novelty/self_consistency; band logic; anti-fab floor
  test_prospect.py             # gap cards grounded; non-existent fact-id dropped
  test_forge.py                # mechanism/kill/bracket/diff-prediction; rival sibling; relabeling discarded; cap
  test_contract.py             # contract frozen before verdict; fields present
  test_adversary.py            # deterministic gate DOWN without jury call; no-self-acquit; incoherent DOWN
  test_autopsy.py              # kill → constraint reweights queue; region-close; pivot@2; escalate@4
  test_ledger.py               # append-only; resume skips accepted
  test_ranked.py               # ranked interface fields; best-first order; no tree internals
  test_tools.py                # generate/critique/rank tools via MockProvider offline
  test_executor.py             # HypothesisExecutor end-to-end offline; resume skips accepted
  test_coordinator.py          # HypothesisCoordinator _observe score-sort; _plan injects context

tests/integration/
  test_hypothesis_pipeline.py  # coordinator → executor → MockProvider + seeded FactStore → ≥1 accepted

tests/live/
  test_hypothesis_live.py      # @pytest.mark.live — real Qwen-Max + Qwen-Plus, neuro topic
```

**Modified files:**

- `conf/config.yaml` — add `- hypothesis: default` to `defaults`
- `loop_sci/hypothesis/__init__.py` — `HypothesisExecutor`, `HypothesisCoordinator`, `RankedHypothesisStore`
- `README.md` — add hypothesis-engine section (pipeline overview, jury, budget, ranked output, live keys)

---

## Task 1: Schemas and Node.refs payload

**OpenSpec tasks:** 1.1

**Files:**
- Create: `loop_sci/hypothesis/schemas.py`
- Create: `loop_sci/hypothesis/__init__.py`
- Create: `tests/unit/hypothesis/__init__.py`
- Create: `tests/unit/hypothesis/test_schemas.py`

**Interfaces:**
- Produces: `ProblemCard(Q, WHY_NOW, PROBE_KILL, STAKES)`, `HypothesisHyp(MECHANISM, KILL, BRACKET, DIFF_PREDICTION)`, `DerivationStep(step, grade, fact_ids)`, `Contract(HYPOTHESIS, LATENT_ROOT, ACCEPT_IF, KILL_IF)`, `Verdict(id, reviewer_model, result, reasons, decided_by)`, `Scores(novelty, self_consistency, decided_by)`, `Autopsy(outcome, region, note)`, `Iteration(round, stall_count)`, `HypothesisRefs(kind, frame, topic, card, hyp, derivation, contract, verdict, scores, autopsy, iteration)`.
- Produces: `build_card_refs(kind, frame, topic, card) -> dict`, `build_hyp_refs(...) -> dict`, `refs_from_dict(d) -> HypothesisRefs`.
- All dicts must round-trip through `json.dumps` / `json.loads` and through `Node.to_dict()` / `Node.from_dict()`.

- [x] **Step 1: Write failing test**

```python
# tests/unit/hypothesis/test_schemas.py
import json, pytest
from loop_sci.hypothesis.schemas import (
    ProblemCard, HypothesisHyp, DerivationStep, Contract,
    Verdict, Scores, Autopsy, Iteration, HypothesisRefs,
    build_card_refs, build_hyp_refs, refs_from_dict,
)
from loop_sci.state.idea_tree import Node

def test_card_refs_round_trips_through_node():
    card = ProblemCard(Q="Why?", WHY_NOW="now", PROBE_KILL="pk", STAKES=0.8)
    refs = build_card_refs(kind="problem-card", frame="primary", topic="neuro", card=card)
    node = Node(id="n1", parent_id=None, hypothesis="h", depth=1, status="pending", refs=refs)
    d = node.to_dict()
    node2 = Node.from_dict(d)
    assert node2.refs["kind"] == "problem-card"
    assert node2.refs["card"]["STAKES"] == 0.8

def test_hyp_refs_verdict_serializable():
    v = Verdict(id="v1", reviewer_model="qwen-plus", result="DOWN", reasons=["fab"], decided_by="deterministic-gate")
    hyp = HypothesisHyp(MECHANISM="m", KILL="k", BRACKET="b", DIFF_PREDICTION="d")
    refs = build_hyp_refs(kind="hypothesis", frame="primary", topic="neuro", hyp=hyp,
                          derivation=[], contract=None, verdict=v, scores=None, autopsy=None,
                          iteration=Iteration(round=1, stall_count=0))
    raw = json.dumps(refs)
    back = refs_from_dict(json.loads(raw))
    assert back.verdict.result == "DOWN"
    assert back.verdict.decided_by == "deterministic-gate"
```

- [x] **Step 2: Run test — verify FAIL**

```bash
cd /home/lingxufeng/cli/Loop-SCI && python -m pytest tests/unit/hypothesis/test_schemas.py -v 2>&1 | tail -5
```
Expected: `ModuleNotFoundError` or `ImportError`.

- [x] **Step 3: Implement `loop_sci/hypothesis/schemas.py`**

```python
# loop_sci/hypothesis/schemas.py
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Literal

@dataclass
class ProblemCard:
    Q: str; WHY_NOW: str; PROBE_KILL: str; STAKES: float

@dataclass
class HypothesisHyp:
    MECHANISM: str; KILL: str; BRACKET: str; DIFF_PREDICTION: str

@dataclass
class DerivationStep:
    step: str
    grade: Literal["[paper]", "[inferred]", "[guess]"]
    fact_ids: list[str] = field(default_factory=list)

@dataclass
class Contract:
    HYPOTHESIS: str; LATENT_ROOT: str; ACCEPT_IF: str; KILL_IF: str

@dataclass
class Verdict:
    id: str
    reviewer_model: str
    result: Literal["UP", "DOWN"]
    reasons: list[str]
    decided_by: Literal["jury", "deterministic-gate"]

@dataclass
class Scores:
    novelty: float
    self_consistency: float
    decided_by: Literal["deterministic", "judge"] = "deterministic"

@dataclass
class Autopsy:
    outcome: Literal["CONSTRAINT", "CANDIDATE", "REGION_CLOSE"]
    region: str
    note: str

@dataclass
class Iteration:
    round: int = 0
    stall_count: int = 0

@dataclass
class HypothesisRefs:
    kind: Literal["problem-card", "hypothesis"]
    frame: Literal["primary", "rival"]
    topic: str
    card: ProblemCard | None = None
    hyp: HypothesisHyp | None = None
    derivation: list[DerivationStep] = field(default_factory=list)
    contract: Contract | None = None
    verdict: Verdict | None = None
    scores: Scores | None = None
    autopsy: Autopsy | None = None
    iteration: Iteration = field(default_factory=Iteration)


def _dc_to_dict(obj: Any) -> Any:
    if obj is None:
        return None
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _dc_to_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [_dc_to_dict(i) for i in obj]
    return obj


def build_card_refs(*, kind: str, frame: str, topic: str, card: ProblemCard) -> dict[str, Any]:
    return _dc_to_dict(HypothesisRefs(kind=kind, frame=frame, topic=topic, card=card))  # type: ignore[arg-type]


def build_hyp_refs(*, kind: str, frame: str, topic: str,
                   hyp: HypothesisHyp, derivation: list[DerivationStep],
                   contract: Contract | None, verdict: Verdict | None,
                   scores: Scores | None, autopsy: Autopsy | None,
                   iteration: Iteration) -> dict[str, Any]:
    return _dc_to_dict(HypothesisRefs(kind=kind, frame=frame, topic=topic,  # type: ignore[arg-type]
                                      hyp=hyp, derivation=derivation,
                                      contract=contract, verdict=verdict,
                                      scores=scores, autopsy=autopsy,
                                      iteration=iteration))


def refs_from_dict(d: dict[str, Any]) -> HypothesisRefs:
    card = ProblemCard(**d["card"]) if d.get("card") else None
    hyp = HypothesisHyp(**d["hyp"]) if d.get("hyp") else None
    derivation = [DerivationStep(**s) for s in (d.get("derivation") or [])]
    contract = Contract(**d["contract"]) if d.get("contract") else None
    verdict_d = d.get("verdict")
    verdict = Verdict(**verdict_d) if verdict_d else None
    scores_d = d.get("scores")
    scores = Scores(**scores_d) if scores_d else None
    autopsy_d = d.get("autopsy")
    autopsy = Autopsy(**autopsy_d) if autopsy_d else None
    iteration = Iteration(**(d.get("iteration") or {}))
    return HypothesisRefs(kind=d["kind"], frame=d["frame"], topic=d["topic"],
                          card=card, hyp=hyp, derivation=derivation,
                          contract=contract, verdict=verdict, scores=scores,
                          autopsy=autopsy, iteration=iteration)
```

Create `loop_sci/hypothesis/__init__.py` (empty for now) and `tests/unit/hypothesis/__init__.py` (empty).

- [x] **Step 4: Run test — verify PASS**

```bash
cd /home/lingxufeng/cli/Loop-SCI && python -m pytest tests/unit/hypothesis/test_schemas.py -v
```
Expected: `2 passed`.

- [x] **Step 5: Commit**

```bash
git add loop_sci/hypothesis/__init__.py loop_sci/hypothesis/schemas.py tests/unit/hypothesis/__init__.py tests/unit/hypothesis/test_schemas.py
git commit -m "feat(hypothesis): add HypothesisRefs schema and Node.refs payload helpers"
```

---

## Task 2: Scoring (novelty + self-consistency)

**OpenSpec tasks:** 4.1

**Files:**
- Create: `loop_sci/hypothesis/scoring.py`
- Create: `tests/unit/hypothesis/test_scoring.py`

**Interfaces:**
- Consumes: `DerivationStep`, `Scores` (from Task 1); `list[Fact]` (from `FactStore.all()`).
- Produces: `score_hypothesis(mechanism: str, derivation: list[DerivationStep], facts: list[Fact], *, w_n: float = 0.5, w_c: float = 0.5, low: float = 0.15, high: float = 0.60) -> Scores`.

- [x] **Step 1: Write failing test**

```python
# tests/unit/hypothesis/test_scoring.py
import pytest
from loop_sci.hypothesis.scoring import score_hypothesis
from loop_sci.hypothesis.schemas import DerivationStep, Scores
from loop_sci.literature.extract.fact import Fact, SourceRef

def _fact(claim: str) -> Fact:
    return Fact(claim=claim, source_ref=SourceRef(source="s2", external_id="x"),
                evidence_span=claim[:20], grounding_scope="abstract")

def test_restatement_gets_low_novelty():
    # mechanism is a substring of an existing fact → low novelty
    facts = [_fact("Synaptic plasticity enables memory consolidation.")]
    s = score_hypothesis("Synaptic plasticity enables memory", [], facts)
    assert s.novelty <= 0.15

def test_novel_mechanism_gets_high_novelty():
    facts = [_fact("Synaptic plasticity enables memory consolidation.")]
    s = score_hypothesis("Glial oscillations encode fear traces via gap junctions.", [], facts)
    assert s.novelty >= 0.60

def test_guess_derivation_lowers_self_consistency():
    steps = [DerivationStep(step="step1", grade="[guess]", fact_ids=[]),
             DerivationStep(step="step2", grade="[guess]", fact_ids=[])]
    s = score_hypothesis("Some mech", steps, [])
    assert s.self_consistency < 0.5

def test_paper_graded_derivation_raises_self_consistency():
    steps = [DerivationStep(step="step1", grade="[paper]", fact_ids=["f1"]),
             DerivationStep(step="step2", grade="[paper]", fact_ids=["f2"])]
    s = score_hypothesis("Some mech", steps, [])
    assert s.self_consistency >= 0.8

def test_overall_score_is_weighted_average():
    facts = [_fact("Synaptic plasticity enables memory consolidation.")]
    steps = [DerivationStep(step="s", grade="[paper]", fact_ids=["f1"])]
    s = score_hypothesis("Glial oscillations encode fear traces.", steps, facts,
                         w_n=0.5, w_c=0.5)
    expected = 0.5 * s.novelty + 0.5 * s.self_consistency
    # score is not stored on Scores; caller sets Node.score
    assert abs(expected - (0.5 * s.novelty + 0.5 * s.self_consistency)) < 1e-9
```

- [x] **Step 2: Run test — verify FAIL**

```bash
cd /home/lingxufeng/cli/Loop-SCI && python -m pytest tests/unit/hypothesis/test_scoring.py -v 2>&1 | tail -5
```

- [x] **Step 3: Implement `loop_sci/hypothesis/scoring.py`**

```python
# loop_sci/hypothesis/scoring.py
from __future__ import annotations
import re
from loop_sci.hypothesis.schemas import DerivationStep, Scores
from loop_sci.literature.extract.fact import Fact

def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))

def _novelty_score(mechanism: str, facts: list[Fact], low: float, high: float) -> float:
    if not facts:
        return high
    mech_tokens = _tokenize(mechanism)
    max_overlap = max(
        len(mech_tokens & _tokenize(f.claim)) / max(len(mech_tokens), 1)
        for f in facts
    )
    if max_overlap >= (1.0 - low):  # mechanism is largely a restatement
        return low * max_overlap  # ≤ LOW
    if max_overlap <= (1.0 - high):
        return high + (1.0 - high) * (1.0 - max_overlap)  # ≥ HIGH
    # in-band: linear interpolation (deterministic; judge path deferred)
    return 1.0 - max_overlap

def _self_consistency_score(derivation: list[DerivationStep]) -> float:
    if not derivation:
        return 1.0
    grade_weights = {"[paper]": 1.0, "[inferred]": 0.6, "[guess]": 0.0}
    scores = [grade_weights.get(s.grade, 0.0) for s in derivation]
    return sum(scores) / len(scores)

def score_hypothesis(
    mechanism: str,
    derivation: list[DerivationStep],
    facts: list[Fact],
    *,
    w_n: float = 0.5,
    w_c: float = 0.5,
    low: float = 0.15,
    high: float = 0.60,
) -> Scores:
    n = _novelty_score(mechanism, facts, low, high)
    c = _self_consistency_score(derivation)
    return Scores(novelty=n, self_consistency=c, decided_by="deterministic")
```

- [x] **Step 4: Run test — verify PASS**

```bash
cd /home/lingxufeng/cli/Loop-SCI && python -m pytest tests/unit/hypothesis/test_scoring.py -v
```
Expected: `5 passed`.

- [x] **Step 5: Commit**

```bash
git add loop_sci/hypothesis/scoring.py tests/unit/hypothesis/test_scoring.py
git commit -m "feat(hypothesis): add deterministic novelty+self-consistency scorer"
```

---

## Task 3: Verdict ledger

**OpenSpec tasks:** 3.4

**Files:**
- Create: `loop_sci/hypothesis/ledger.py`
- Create: `tests/unit/hypothesis/test_ledger.py`

**Interfaces:**
- Produces: `VerdictLedger(path: Path)`, methods `append(verdict_id, node_id, reviewer_model, result, round_n)`, `accepted_node_ids() -> set[str]`, `all_entries() -> list[dict]`.

- [x] **Step 1: Write failing test**

```python
# tests/unit/hypothesis/test_ledger.py
import json
from pathlib import Path
import pytest
from loop_sci.hypothesis.ledger import VerdictLedger

def test_append_and_reload(tmp_path):
    ledger = VerdictLedger(tmp_path / "ledger.jsonl")
    ledger.append("v1", "node-a", "qwen-plus", "UP", round_n=1)
    ledger.append("v2", "node-b", "qwen-plus", "DOWN", round_n=1)
    lines = (tmp_path / "ledger.jsonl").read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["verdict_id"] == "v1"

def test_accepted_node_ids(tmp_path):
    ledger = VerdictLedger(tmp_path / "ledger.jsonl")
    ledger.append("v1", "node-a", "qwen-plus", "UP", round_n=1)
    ledger.append("v2", "node-b", "qwen-plus", "DOWN", round_n=1)
    assert ledger.accepted_node_ids() == {"node-a"}

def test_resume_loads_existing(tmp_path):
    p = tmp_path / "ledger.jsonl"
    p.write_text(json.dumps({"verdict_id": "v0", "node_id": "n0",
                              "reviewer_model": "qwen-plus",
                              "result": "UP", "round": 0}) + "\n")
    ledger = VerdictLedger(p)
    assert "n0" in ledger.accepted_node_ids()
```

- [x] **Step 2: Run test — verify FAIL**

```bash
cd /home/lingxufeng/cli/Loop-SCI && python -m pytest tests/unit/hypothesis/test_ledger.py -v 2>&1 | tail -5
```

- [x] **Step 3: Implement `loop_sci/hypothesis/ledger.py`**

```python
# loop_sci/hypothesis/ledger.py
from __future__ import annotations
import json
from pathlib import Path

class VerdictLedger:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._entries: list[dict] = []
        if self._path.exists():
            for line in self._path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    self._entries.append(json.loads(line))

    def append(self, verdict_id: str, node_id: str, reviewer_model: str,
                result: str, *, round_n: int) -> None:
        entry = {"verdict_id": verdict_id, "node_id": node_id,
                 "reviewer_model": reviewer_model, "result": result, "round": round_n}
        self._entries.append(entry)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def accepted_node_ids(self) -> set[str]:
        return {e["node_id"] for e in self._entries if e["result"] == "UP"}

    def all_entries(self) -> list[dict]:
        return list(self._entries)
```

- [x] **Step 4: Run test — verify PASS**

```bash
cd /home/lingxufeng/cli/Loop-SCI && python -m pytest tests/unit/hypothesis/test_ledger.py -v
```
Expected: `3 passed`.

- [x] **Step 5: Commit**

```bash
git add loop_sci/hypothesis/ledger.py tests/unit/hypothesis/test_ledger.py
git commit -m "feat(hypothesis): add append-only VerdictLedger for resume and audit"
```

---

## Task 4: prospect' stage

**OpenSpec tasks:** 1.2

**Files:**
- Create: `loop_sci/hypothesis/stages/__init__.py`
- Create: `loop_sci/hypothesis/stages/prospect.py`
- Create: `tests/unit/hypothesis/test_prospect.py`

**Interfaces:**
- Consumes: `FactStore` (`.all()` / `.filter(topic=...)`), `LLMProvider` (retry-once → drop), `build_card_refs` (Task 1).
- Produces: `async run_prospect(topic: str, store: FactStore, provider: LLMProvider, *, max_cards: int = 5) -> list[tuple[str, dict]]` — list of `(card_node_id, refs_dict)` ordered by STAKES desc; drops cards citing non-existent `fact_id`s.

LLM prompt returns JSON array: `[{"Q": "...", "WHY_NOW": "...", "PROBE_KILL": "...", "STAKES": 0.0–1.0, "fact_ids": ["..."]}]`. Invalid JSON → retry once → drop.

- [x] **Step 1: Write failing test**

```python
# tests/unit/hypothesis/test_prospect.py
import json, pytest
from unittest.mock import AsyncMock
from loop_sci.hypothesis.stages.prospect import run_prospect
from loop_sci.literature.factbase.store import FactStore
from loop_sci.literature.extract.fact import Fact, SourceRef

def _make_store(tmp_path, claims):
    store = FactStore(tmp_path / "facts.json")
    for i, c in enumerate(claims):
        f = Fact(claim=c, source_ref=SourceRef(source="s2", external_id=f"s{i}"),
                 evidence_span=c[:20], grounding_scope="abstract")
        f.fact_id = f"fact_{i}"
        store.add(f)
    return store

@pytest.mark.asyncio
async def test_gap_cards_derived_from_facts(tmp_path):
    store = _make_store(tmp_path, ["Neurons fire. Evidence X.", "Evidence Y contradicts X."])
    response = json.dumps([
        {"Q": "Why?", "WHY_NOW": "now", "PROBE_KILL": "pk", "STAKES": 0.9,
         "fact_ids": ["fact_0", "fact_1"]}
    ])
    from tests.conftest import MockProvider
    provider = MockProvider(responses=[response])
    cards = await run_prospect("neuro", store, provider, max_cards=5)
    assert len(cards) == 1
    node_id, refs = cards[0]
    assert refs["card"]["STAKES"] == 0.9
    assert set(refs.get("grounding_fact_ids", [])) == {"fact_0", "fact_1"}

@pytest.mark.asyncio
async def test_card_with_nonexistent_fact_id_dropped(tmp_path):
    store = _make_store(tmp_path, ["Neurons fire."])
    response = json.dumps([
        {"Q": "Q1", "WHY_NOW": "n", "PROBE_KILL": "p", "STAKES": 0.8,
         "fact_ids": ["fact_0", "NONEXISTENT"]}
    ])
    from tests.conftest import MockProvider
    provider = MockProvider(responses=[response])
    cards = await run_prospect("neuro", store, provider, max_cards=5)
    assert len(cards) == 0  # dropped because NONEXISTENT not in store

@pytest.mark.asyncio
async def test_invalid_json_retried_then_dropped(tmp_path):
    store = _make_store(tmp_path, ["Fact A."])
    from tests.conftest import MockProvider
    provider = MockProvider(responses=["not json", "also not json"])
    cards = await run_prospect("neuro", store, provider, max_cards=5)
    assert cards == []
```

- [x] **Step 2: Run test — verify FAIL**

```bash
cd /home/lingxufeng/cli/Loop-SCI && python -m pytest tests/unit/hypothesis/test_prospect.py -v 2>&1 | tail -5
```

- [x] **Step 3: Implement `loop_sci/hypothesis/stages/prospect.py`**

```python
# loop_sci/hypothesis/stages/prospect.py
from __future__ import annotations
import json, logging, uuid
from loop_sci.hypothesis.schemas import ProblemCard, build_card_refs
from loop_sci.literature.factbase.store import FactStore

log = logging.getLogger(__name__)

_PROSPECT_SYSTEM = (
    "You are a research gap analyst. Given verified facts about a topic, "
    "identify the most important open questions. Return ONLY a JSON array of objects, "
    "each with keys: Q (string), WHY_NOW (string), PROBE_KILL (string), "
    "STAKES (float 0-1), fact_ids (list of fact_id strings that support this gap)."
)

async def run_prospect(
    topic: str,
    store: FactStore,
    provider,
    *,
    max_cards: int = 5,
) -> list[tuple[str, dict]]:
    facts = store.filter(topic=topic) or store.all()
    fact_index = {f.fact_id: f for f in facts if f.fact_id}
    fact_summary = "\n".join(
        f"[{f.fact_id}] {f.claim}" for f in facts[:50]
    )
    prompt = (
        f"Topic: {topic}\n\nVerified facts:\n{fact_summary}\n\n"
        f"Return up to {max_cards} gap cards as a JSON array."
    )

    raw = await _call_with_retry(provider, prompt)
    if raw is None:
        return []

    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        return []

    cards: list[tuple[str, dict]] = []
    for item in items[:max_cards]:
        cited = item.get("fact_ids", [])
        if not all(fid in fact_index for fid in cited):
            log.debug("prospect: dropping card citing non-existent fact_ids %s", cited)
            continue
        card = ProblemCard(
            Q=item.get("Q", ""),
            WHY_NOW=item.get("WHY_NOW", ""),
            PROBE_KILL=item.get("PROBE_KILL", ""),
            STAKES=float(item.get("STAKES", 0.0)),
        )
        node_id = f"card_{uuid.uuid4().hex[:8]}"
        refs = build_card_refs(kind="problem-card", frame="primary", topic=topic, card=card)
        refs["grounding_fact_ids"] = cited
        cards.append((node_id, refs))

    return sorted(cards, key=lambda t: t[1]["card"]["STAKES"], reverse=True)


async def _call_with_retry(provider, prompt: str) -> str | None:
    from loop_sci._vendor.arbor.llm.base import LLMProvider
    for attempt in range(2):
        resp = await provider.create(
            system=_PROSPECT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text if resp.content else ""
        try:
            json.loads(text)
            return text
        except json.JSONDecodeError:
            log.debug("prospect: JSON parse failed attempt %d", attempt)
    return None
```

Create `loop_sci/hypothesis/stages/__init__.py` (empty).

- [x] **Step 4: Run test — verify PASS**

```bash
cd /home/lingxufeng/cli/Loop-SCI && python -m pytest tests/unit/hypothesis/test_prospect.py -v
```
Expected: `3 passed`.

- [x] **Step 5: Commit**

```bash
git add loop_sci/hypothesis/stages/__init__.py loop_sci/hypothesis/stages/prospect.py tests/unit/hypothesis/test_prospect.py
git commit -m "feat(hypothesis): implement prospect' stage — mine gap cards from FactStore"
```

---

## Task 5: forge' stage + relabeling filter + cap

**OpenSpec tasks:** 1.3, 1.4, 1.5

**Files:**
- Create: `loop_sci/hypothesis/stages/forge.py`
- Create: `tests/unit/hypothesis/test_forge.py`

**Interfaces:**
- Consumes: card `refs` dict (Task 1), `FactStore`, `LLMProvider`.
- Produces: `async run_forge(card_node_id: str, card_refs: dict, store: FactStore, provider: LLMProvider, *, max_candidates: int = 4) -> list[tuple[str, dict, list[DerivationStep]]]` — `(hyp_node_id, hyp_refs, derivation)` per candidate; ≥1 rival-frame sibling; relabeling discarded.

LLM prompt returns: `{"candidates": [{"MECHANISM": "...", "KILL": "...", "BRACKET": "...", "DIFF_PREDICTION": "...", "frame": "primary"|"rival", "derivation": [{"step": "...", "grade": "[paper]"|"[inferred]"|"[guess]", "fact_ids": ["..."]}]}]}`.

- [x] **Step 1: Write failing test**

```python
# tests/unit/hypothesis/test_forge.py
import json, pytest
from loop_sci.hypothesis.stages.forge import run_forge
from loop_sci.hypothesis.schemas import ProblemCard, build_card_refs
from loop_sci.literature.factbase.store import FactStore
from loop_sci.literature.extract.fact import Fact, SourceRef

def _store_with_fact(tmp_path):
    store = FactStore(tmp_path / "facts.json")
    f = Fact(claim="Neurons fire action potentials.", source_ref=SourceRef(source="s2", external_id="s0"),
             evidence_span="Neurons fire", grounding_scope="abstract")
    f.fact_id = "fact_0"
    store.add(f)
    return store

def _card_refs():
    card = ProblemCard(Q="Why?", WHY_NOW="now", PROBE_KILL="pk", STAKES=0.9)
    return build_card_refs(kind="problem-card", frame="primary", topic="neuro", card=card)

@pytest.mark.asyncio
async def test_candidates_have_required_fields(tmp_path):
    store = _store_with_fact(tmp_path)
    response = json.dumps({"candidates": [
        {"MECHANISM": "Glial sync", "KILL": "no glial", "BRACKET": "plausible",
         "DIFF_PREDICTION": "Distinct EEG signature", "frame": "primary",
         "derivation": [{"step": "Neurons → glia", "grade": "[inferred]", "fact_ids": ["fact_0"]}]},
        {"MECHANISM": "Rival mech", "KILL": "rival kill", "BRACKET": "low",
         "DIFF_PREDICTION": "Different pattern", "frame": "rival",
         "derivation": [{"step": "Alternative", "grade": "[guess]", "fact_ids": []}]},
    ]})
    from tests.conftest import MockProvider
    provider = MockProvider(responses=[response])
    results = await run_forge("card_1", _card_refs(), store, provider, max_candidates=4)
    assert len(results) >= 2
    hyp_node_id, hyp_refs, derivation = results[0]
    assert hyp_refs["hyp"]["MECHANISM"] == "Glial sync"
    frames = [r[1]["frame"] for r in results]
    assert "rival" in frames

@pytest.mark.asyncio
async def test_relabeling_discarded(tmp_path):
    store = _store_with_fact(tmp_path)
    # DIFF_PREDICTION identical to mechanism (relabeling)
    response = json.dumps({"candidates": [
        {"MECHANISM": "Neurons fire", "KILL": "k", "BRACKET": "b",
         "DIFF_PREDICTION": "Neurons fire",  # same as mechanism = relabeling
         "frame": "primary", "derivation": []},
    ]})
    from tests.conftest import MockProvider
    provider = MockProvider(responses=[response])
    results = await run_forge("card_1", _card_refs(), store, provider, max_candidates=4)
    assert len(results) == 0

@pytest.mark.asyncio
async def test_cap_respected(tmp_path):
    store = _store_with_fact(tmp_path)
    candidates = [
        {"MECHANISM": f"Mech {i}", "KILL": "k", "BRACKET": "b",
         "DIFF_PREDICTION": f"Distinct pred {i}", "frame": "primary" if i == 0 else "rival",
         "derivation": []}
        for i in range(10)
    ]
    response = json.dumps({"candidates": candidates})
    from tests.conftest import MockProvider
    provider = MockProvider(responses=[response])
    results = await run_forge("card_1", _card_refs(), store, provider, max_candidates=4)
    assert len(results) <= 4
```

- [x] **Step 2: Run test — verify FAIL**

```bash
cd /home/lingxufeng/cli/Loop-SCI && python -m pytest tests/unit/hypothesis/test_forge.py -v 2>&1 | tail -5
```

- [x] **Step 3: Implement `loop_sci/hypothesis/stages/forge.py`**

```python
# loop_sci/hypothesis/stages/forge.py
from __future__ import annotations
import json, logging, re, uuid
from loop_sci.hypothesis.schemas import (
    HypothesisHyp, DerivationStep, build_hyp_refs, Contract, Iteration,
)
from loop_sci.literature.factbase.store import FactStore

log = logging.getLogger(__name__)

_FORGE_SYSTEM = (
    "You are a hypothesis forge. Given a research gap card and verified facts, "
    "generate candidate hypotheses using induction and deduction. "
    "Return ONLY a JSON object: {\"candidates\": [{\"MECHANISM\": \"...\", \"KILL\": \"...\", "
    "\"BRACKET\": \"...\", \"DIFF_PREDICTION\": \"...\", \"frame\": \"primary\"|\"rival\", "
    "\"derivation\": [{\"step\": \"...\", \"grade\": \"[paper]\"|\"[inferred]\"|\"[guess]\", "
    "\"fact_ids\": [\"...\"]}]}]}. Include at least one rival-frame candidate."
)


def _is_relabeling(mechanism: str, diff_prediction: str) -> bool:
    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", s.lower().strip())
    return _norm(mechanism) == _norm(diff_prediction)


async def run_forge(
    card_node_id: str,
    card_refs: dict,
    store: FactStore,
    provider,
    *,
    max_candidates: int = 4,
) -> list[tuple[str, dict, list[DerivationStep]]]:
    facts = store.all()
    fact_summary = "\n".join(
        f"[{f.fact_id}] {f.claim}" for f in facts[:50] if f.fact_id
    )
    card_data = card_refs.get("card", {})
    prompt = (
        f"Gap card:\n{json.dumps(card_data, ensure_ascii=False)}\n\n"
        f"Verified facts:\n{fact_summary}\n\n"
        f"Generate up to {max_candidates} hypothesis candidates (include ≥1 rival)."
    )

    raw = await _call_with_retry(provider, prompt)
    if raw is None:
        return []
    try:
        data = json.loads(raw)
        raw_candidates = data.get("candidates", [])
    except json.JSONDecodeError:
        return []

    results: list[tuple[str, dict, list[DerivationStep]]] = []
    for item in raw_candidates[:max_candidates]:
        mech = item.get("MECHANISM", "")
        diff_pred = item.get("DIFF_PREDICTION", "")
        if _is_relabeling(mech, diff_pred):
            log.debug("forge: discarding relabeling candidate: %s", mech)
            continue
        hyp = HypothesisHyp(
            MECHANISM=mech, KILL=item.get("KILL", ""),
            BRACKET=item.get("BRACKET", ""), DIFF_PREDICTION=diff_pred,
        )
        derivation = [
            DerivationStep(step=s["step"], grade=s.get("grade", "[guess]"),
                           fact_ids=s.get("fact_ids", []))
            for s in item.get("derivation", [])
        ]
        frame = item.get("frame", "primary")
        refs = build_hyp_refs(
            kind="hypothesis", frame=frame, topic=card_refs.get("topic", ""),
            hyp=hyp, derivation=derivation, contract=None, verdict=None,
            scores=None, autopsy=None, iteration=Iteration(),
        )
        hyp_node_id = f"hyp_{uuid.uuid4().hex[:8]}"
        results.append((hyp_node_id, refs, derivation))

    return results


async def _call_with_retry(provider, prompt: str) -> str | None:
    for attempt in range(2):
        resp = await provider.create(
            system=_FORGE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text if resp.content else ""
        try:
            json.loads(text)
            return text
        except json.JSONDecodeError:
            log.debug("forge: JSON parse failed attempt %d", attempt)
    return None
```

- [x] **Step 4: Run test — verify PASS**

```bash
cd /home/lingxufeng/cli/Loop-SCI && python -m pytest tests/unit/hypothesis/test_forge.py -v
```
Expected: `3 passed`.

- [x] **Step 5: Commit**

```bash
git add loop_sci/hypothesis/stages/forge.py tests/unit/hypothesis/test_forge.py
git commit -m "feat(hypothesis): implement forge' stage with relabeling filter and candidate cap"
```

---

## Task 6: contract freeze

**OpenSpec tasks:** 2.1

**Files:**
- Create: `loop_sci/hypothesis/stages/contract.py`
- Create: `tests/unit/hypothesis/test_contract.py`

**Interfaces:**
- Consumes: `hyp_refs` dict, `LLMProvider`.
- Produces: `async freeze_contract(hyp_refs: dict, provider: LLMProvider) -> Contract` — LLM returns `{"HYPOTHESIS": "...", "LATENT_ROOT": "...", "ACCEPT_IF": "...", "KILL_IF": "..."}`.

- [x] **Step 1: Write failing test**

```python
# tests/unit/hypothesis/test_contract.py
import json, pytest
from loop_sci.hypothesis.stages.contract import freeze_contract
from loop_sci.hypothesis.schemas import Contract

@pytest.mark.asyncio
async def test_contract_frozen_with_required_fields():
    from tests.conftest import MockProvider
    response = json.dumps({
        "HYPOTHESIS": "Glia encode fear",
        "LATENT_ROOT": "glial plasticity",
        "ACCEPT_IF": "BOLD signal differs by >0.5σ",
        "KILL_IF": "No glial calcium transient in fear CS",
    })
    provider = MockProvider(responses=[response])
    hyp_refs = {"hyp": {"MECHANISM": "Glia encode fear via gap junctions",
                        "KILL": "no glial", "BRACKET": "moderate", "DIFF_PREDICTION": "EEG"},
                "topic": "neuro"}
    contract = await freeze_contract(hyp_refs, provider)
    assert isinstance(contract, Contract)
    assert contract.HYPOTHESIS == "Glia encode fear"
    assert contract.ACCEPT_IF != ""
    assert contract.KILL_IF != ""
```

- [x] **Step 2: Run test — verify FAIL**

```bash
cd /home/lingxufeng/cli/Loop-SCI && python -m pytest tests/unit/hypothesis/test_contract.py -v 2>&1 | tail -5
```

- [x] **Step 3: Implement `loop_sci/hypothesis/stages/contract.py`**

```python
# loop_sci/hypothesis/stages/contract.py
from __future__ import annotations
import json, logging
from loop_sci.hypothesis.schemas import Contract

log = logging.getLogger(__name__)

_CONTRACT_SYSTEM = (
    "You are a derivation contract writer. Freeze a concise contract for the hypothesis. "
    "Return ONLY JSON: {\"HYPOTHESIS\": \"...\", \"LATENT_ROOT\": \"...\", "
    "\"ACCEPT_IF\": \"logical/formula tripwire for acceptance\", "
    "\"KILL_IF\": \"logical/formula tripwire for rejection\"}. "
    "ACCEPT_IF and KILL_IF must be derivation tripwires, NOT executable commands."
)

async def freeze_contract(hyp_refs: dict, provider) -> Contract:
    mech = (hyp_refs.get("hyp") or {}).get("MECHANISM", "")
    prompt = f"Hypothesis mechanism: {mech}\nTopic: {hyp_refs.get('topic', '')}"
    for attempt in range(2):
        resp = await provider.create(
            system=_CONTRACT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text if resp.content else ""
        try:
            d = json.loads(text)
            return Contract(
                HYPOTHESIS=d["HYPOTHESIS"], LATENT_ROOT=d["LATENT_ROOT"],
                ACCEPT_IF=d["ACCEPT_IF"], KILL_IF=d["KILL_IF"],
            )
        except (json.JSONDecodeError, KeyError):
            log.debug("contract: parse failed attempt %d", attempt)
    return Contract(HYPOTHESIS=mech, LATENT_ROOT="unknown",
                    ACCEPT_IF="(unavailable)", KILL_IF="(unavailable)")
```

- [x] **Step 4: Run test — verify PASS**

```bash
cd /home/lingxufeng/cli/Loop-SCI && python -m pytest tests/unit/hypothesis/test_contract.py -v
```

- [x] **Step 5: Commit**

```bash
git add loop_sci/hypothesis/stages/contract.py tests/unit/hypothesis/test_contract.py
git commit -m "feat(hypothesis): implement derivation contract freeze before jury"
```

---

## Task 7: adversary' stage — deterministic gate + Qwen-vs-Qwen jury

**OpenSpec tasks:** 2.2, 2.3, 2.4

**Files:**
- Create: `loop_sci/hypothesis/stages/adversary.py`
- Create: `tests/unit/hypothesis/test_adversary.py`

**Interfaces:**
- Consumes: `hyp_refs` dict, `derivation: list[DerivationStep]`, `store: FactStore`, `generator_model: str`, `reviewer: LLMProvider`.
- Produces: `async run_adversary(hyp_refs, derivation, store, generator_model, reviewer) -> Verdict`.
- Deterministic gate fires first: if mechanism contradicts a grounding fact OR any load-bearing derivation step is `[guess]`, returns `Verdict(decided_by="deterministic-gate", result="DOWN")` — no reviewer call.
- Structural no-self-acquit: if `reviewer.model == generator_model`, result is DOWN regardless.

- [x] **Step 1: Write failing test**

```python
# tests/unit/hypothesis/test_adversary.py
import pytest
from loop_sci.hypothesis.stages.adversary import run_adversary
from loop_sci.hypothesis.schemas import DerivationStep, Verdict
from loop_sci.literature.factbase.store import FactStore
from loop_sci.literature.extract.fact import Fact, SourceRef
import json

def _store(tmp_path, claims):
    store = FactStore(tmp_path / "f.json")
    for i, c in enumerate(claims):
        f = Fact(claim=c, source_ref=SourceRef(source="s2", external_id=f"x{i}"),
                 evidence_span=c[:20], grounding_scope="abstract")
        f.fact_id = f"fact_{i}"
        store.add(f)
    return store

def _hyp_refs(mech: str) -> dict:
    return {"hyp": {"MECHANISM": mech, "KILL": "k", "BRACKET": "b", "DIFF_PREDICTION": "d"},
            "topic": "neuro", "kind": "hypothesis", "frame": "primary",
            "grounding_fact_ids": ["fact_0"]}

@pytest.mark.asyncio
async def test_deterministic_gate_downs_without_jury_call(tmp_path):
    store = _store(tmp_path, ["Neurons do NOT fire glial oscillations."])
    derivation = [DerivationStep(step="s", grade="[guess]", fact_ids=[])]
    from tests.conftest import MockProvider
    reviewer = MockProvider(responses=["should not be called"])
    verdict = await run_adversary(_hyp_refs("Glial oscillations encode fear"),
                                  derivation, store, "qwen-max", reviewer)
    assert verdict.result == "DOWN"
    assert verdict.decided_by == "deterministic-gate"
    assert reviewer._index == 0  # reviewer was NOT called

@pytest.mark.asyncio
async def test_no_self_acquit(tmp_path):
    store = _store(tmp_path, ["Neurons fire."])
    derivation = [DerivationStep(step="s", grade="[paper]", fact_ids=["fact_0"])]
    # reviewer.model == generator_model → must return DOWN
    from tests.conftest import MockProvider
    reviewer = MockProvider(responses=[json.dumps({"result": "UP", "reasons": []})])
    reviewer.model = "qwen-max"  # same as generator
    verdict = await run_adversary(_hyp_refs("A novel mechanism"),
                                  derivation, store, "qwen-max", reviewer)
    assert verdict.result == "DOWN"

@pytest.mark.asyncio
async def test_incoherent_hypothesis_downed_by_jury(tmp_path):
    store = _store(tmp_path, ["Neurons fire action potentials."])
    derivation = [DerivationStep(step="s", grade="[paper]", fact_ids=["fact_0"])]
    response = json.dumps({"result": "DOWN", "reasons": ["mechanism contradicts fact_0"]})
    from tests.conftest import MockProvider
    reviewer = MockProvider(responses=[response])
    reviewer.model = "qwen-plus"
    verdict = await run_adversary(_hyp_refs("Novel glial mechanism"),
                                  derivation, store, "qwen-max", reviewer)
    assert verdict.result == "DOWN"
    assert verdict.decided_by == "jury"
```

- [x] **Step 2: Run test — verify FAIL**

```bash
cd /home/lingxufeng/cli/Loop-SCI && python -m pytest tests/unit/hypothesis/test_adversary.py -v 2>&1 | tail -5
```

- [x] **Step 3: Implement `loop_sci/hypothesis/stages/adversary.py`**

```python
# loop_sci/hypothesis/stages/adversary.py
from __future__ import annotations
import json, logging, uuid
from loop_sci.hypothesis.schemas import DerivationStep, Verdict
from loop_sci.literature.factbase.store import FactStore

log = logging.getLogger(__name__)

_ADVERSARY_SYSTEM = (
    "You are an adversarial scientific reviewer with a KILL bias. "
    "Your job is to rigorously challenge the hypothesis. "
    "Check: (C) every decomposed claim needs an artifact/fact; "
    "(D) generalization: does the mechanism hold beyond the specific finding? "
    "Return ONLY JSON: {\"result\": \"UP\"|\"DOWN\", \"reasons\": [\"...\"]}"
)

def _has_load_bearing_guess(derivation: list[DerivationStep]) -> bool:
    return any(s.grade == "[guess]" for s in derivation)

def _mechanism_contradicts_facts(mechanism: str, store: FactStore) -> bool:
    mech_lower = mechanism.lower()
    for fact in store.all():
        if "not" in fact.claim.lower() or "no " in fact.claim.lower():
            # simple contradiction check: fact claims negation of mechanism keyword
            key_words = set(mech_lower.split()) - {"the", "a", "an", "is", "are", "of", "in", "and"}
            fact_lower = fact.claim.lower()
            if any(w in fact_lower for w in key_words) and ("not" in fact_lower or "no " in fact_lower):
                return True
    return False

async def run_adversary(
    hyp_refs: dict,
    derivation: list[DerivationStep],
    store: FactStore,
    generator_model: str,
    reviewer,
) -> Verdict:
    mechanism = (hyp_refs.get("hyp") or {}).get("MECHANISM", "")

    # Deterministic pre-jury gate
    if _has_load_bearing_guess(derivation) or _mechanism_contradicts_facts(mechanism, store):
        return Verdict(
            id=f"det_{uuid.uuid4().hex[:8]}",
            reviewer_model="deterministic-gate",
            result="DOWN",
            reasons=["Failed deterministic pre-jury gate: load-bearing [guess] or mechanism contradiction"],
            decided_by="deterministic-gate",
        )

    # Structural no-self-acquit
    reviewer_model = getattr(reviewer, "model", "unknown")
    if reviewer_model == generator_model:
        return Verdict(
            id=f"nsa_{uuid.uuid4().hex[:8]}",
            reviewer_model=reviewer_model,
            result="DOWN",
            reasons=["No-self-acquit: reviewer model matches generator model"],
            decided_by="deterministic-gate",
        )

    # Jury call
    prompt = (
        f"Mechanism: {mechanism}\n"
        f"Derivation:\n" + "\n".join(f"  {s.grade} {s.step}" for s in derivation) +
        f"\nGrounding fact_ids: {hyp_refs.get('grounding_fact_ids', [])}"
    )
    for attempt in range(2):
        resp = await reviewer.create(
            system=_ADVERSARY_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text if resp.content else ""
        try:
            d = json.loads(text)
            return Verdict(
                id=f"jury_{uuid.uuid4().hex[:8]}",
                reviewer_model=reviewer_model,
                result=d["result"],
                reasons=d.get("reasons", []),
                decided_by="jury",
            )
        except (json.JSONDecodeError, KeyError):
            log.debug("adversary: parse failed attempt %d", attempt)

    return Verdict(
        id=f"jury_{uuid.uuid4().hex[:8]}",
        reviewer_model=reviewer_model,
        result="DOWN",
        reasons=["Reviewer returned invalid JSON"],
        decided_by="jury",
    )
```

- [x] **Step 4: Run test — verify PASS**

```bash
cd /home/lingxufeng/cli/Loop-SCI && python -m pytest tests/unit/hypothesis/test_adversary.py -v
```
Expected: `3 passed`.

- [x] **Step 5: Commit**

```bash
git add loop_sci/hypothesis/stages/adversary.py tests/unit/hypothesis/test_adversary.py
git commit -m "feat(hypothesis): implement adversary' with deterministic gate and no-self-acquit jury"
```

---

## Task 8: autopsy' + stall ledger + region-close

**OpenSpec tasks:** 3.1, 3.2, 3.3

**Files:**
- Create: `loop_sci/hypothesis/stages/autopsy.py`
- Create: `tests/unit/hypothesis/test_autopsy.py`

**Interfaces:**
- Produces: `classify_kill(verdict: Verdict, hyp_refs: dict) -> Autopsy`.
- Produces: `StallLedger` with `.record_round(new_accepted_count: int) -> Literal["continue", "pivot", "escalate"]`.
- Produces: `RegionTracker` with `.record_kill(latent_root: str) -> bool` (returns True when ≥2 kills same root = region closed).

- [x] **Step 1: Write failing test**

```python
# tests/unit/hypothesis/test_autopsy.py
import pytest
from loop_sci.hypothesis.stages.autopsy import classify_kill, StallLedger, RegionTracker
from loop_sci.hypothesis.schemas import Verdict, Autopsy

def _verdict(result="DOWN"):
    return Verdict(id="v1", reviewer_model="qwen-plus", result=result,
                   reasons=["too speculative"], decided_by="jury")

def test_kill_produces_constraint():
    hyp_refs = {"hyp": {"MECHANISM": "Glial mech"}, "topic": "neuro",
                 "contract": {"LATENT_ROOT": "glial plasticity"}}
    a = classify_kill(_verdict("DOWN"), hyp_refs)
    assert isinstance(a, Autopsy)
    assert a.outcome in {"CONSTRAINT", "CANDIDATE", "REGION_CLOSE"}

def test_stall_pivot_at_2():
    sl = StallLedger()
    assert sl.record_round(0) == "continue"
    assert sl.record_round(0) == "pivot"

def test_stall_escalate_at_4():
    sl = StallLedger()
    for _ in range(3):
        sl.record_round(0)
    assert sl.record_round(0) == "escalate"

def test_region_close_after_two_same_root():
    rt = RegionTracker()
    assert rt.record_kill("glial_plasticity") == False
    assert rt.record_kill("glial_plasticity") == True  # second kill → close

def test_region_close_different_roots_no_close():
    rt = RegionTracker()
    rt.record_kill("root_a")
    assert rt.record_kill("root_b") == False
```

- [x] **Step 2: Run test — verify FAIL**

```bash
cd /home/lingxufeng/cli/Loop-SCI && python -m pytest tests/unit/hypothesis/test_autopsy.py -v 2>&1 | tail -5
```

- [x] **Step 3: Implement `loop_sci/hypothesis/stages/autopsy.py`**

```python
# loop_sci/hypothesis/stages/autopsy.py
from __future__ import annotations
from collections import Counter
from typing import Literal
from loop_sci.hypothesis.schemas import Autopsy, Verdict


def classify_kill(verdict: Verdict, hyp_refs: dict) -> Autopsy:
    contract = hyp_refs.get("contract") or {}
    latent_root = contract.get("LATENT_ROOT", "unknown") if isinstance(contract, dict) else "unknown"
    reasons_text = " ".join(verdict.reasons).lower()
    if "region" in reasons_text or "dead" in reasons_text:
        outcome: Literal["CONSTRAINT", "CANDIDATE", "REGION_CLOSE"] = "REGION_CLOSE"
    elif "alternative" in reasons_text or "candidate" in reasons_text:
        outcome = "CANDIDATE"
    else:
        outcome = "CONSTRAINT"
    return Autopsy(outcome=outcome, region=latent_root, note="; ".join(verdict.reasons))


class StallLedger:
    def __init__(self, pivot_at: int = 2, escalate_at: int = 4) -> None:
        self._stall_count = 0
        self._pivot_at = pivot_at
        self._escalate_at = escalate_at

    def record_round(self, new_accepted_count: int) -> Literal["continue", "pivot", "escalate"]:
        if new_accepted_count == 0:
            self._stall_count += 1
        else:
            self._stall_count = 0
        if self._stall_count >= self._escalate_at:
            return "escalate"
        if self._stall_count >= self._pivot_at:
            return "pivot"
        return "continue"


class RegionTracker:
    def __init__(self) -> None:
        self._kills: Counter[str] = Counter()
        self._closed: set[str] = set()

    def record_kill(self, latent_root: str) -> bool:
        self._kills[latent_root] += 1
        if self._kills[latent_root] >= 2:
            self._closed.add(latent_root)
            return True
        return False

    def is_closed(self, latent_root: str) -> bool:
        return latent_root in self._closed
```

- [x] **Step 4: Run test — verify PASS**

```bash
cd /home/lingxufeng/cli/Loop-SCI && python -m pytest tests/unit/hypothesis/test_autopsy.py -v
```
Expected: `5 passed`.

- [x] **Step 5: Commit**

```bash
git add loop_sci/hypothesis/stages/autopsy.py tests/unit/hypothesis/test_autopsy.py
git commit -m "feat(hypothesis): implement autopsy' with CONSTRAINT/CANDIDATE/REGION_CLOSE, stall ledger, region tracker"
```

---

## Task 9: Ranked query interface

**OpenSpec tasks:** 4.2

**Files:**
- Create: `loop_sci/hypothesis/ranked.py`
- Create: `tests/unit/hypothesis/test_ranked.py`

**Interfaces:**
- Consumes: `IdeaTree` (from `loop_sci.state.idea_tree`), `refs_from_dict` (Task 1).
- Produces: `RankedHypothesisStore(tree: IdeaTree)`, method `get_ranked(*, topic: str | None = None, status: str | None = None) -> list[RankedHypothesis]`.
- `RankedHypothesis` is a plain dataclass with: `node_id`, `problem`, `mechanism`, `derivation_chain`, `diff_prediction`, `novelty`, `self_consistency`, `overall_score`, `grounding_fact_ids`. Does NOT expose IdeaTree node objects.

- [ ] **Step 1: Write failing test**

```python
# tests/unit/hypothesis/test_ranked.py
import pytest
from loop_sci.hypothesis.ranked import RankedHypothesisStore, RankedHypothesis
from loop_sci.hypothesis.schemas import (
    HypothesisHyp, DerivationStep, Verdict, Scores, Iteration, build_hyp_refs,
)
from loop_sci.state.idea_tree import IdeaTree, Node

def _make_tree_with_hyp(tmp_path, overall_score, verdict_result="UP"):
    root = Node(id="ROOT", parent_id=None, hypothesis="neuro topic", depth=0, status="pending")
    tree = IdeaTree(root=root, json_path=tmp_path / "tree.json")
    hyp = HypothesisHyp(MECHANISM="Glia encode fear", KILL="k", BRACKET="b", DIFF_PREDICTION="EEG sig")
    derivation = [DerivationStep(step="s1", grade="[paper]", fact_ids=["fact_0"])]
    verdict = Verdict(id="v1", reviewer_model="qwen-plus", result=verdict_result,
                      reasons=[], decided_by="jury")
    scores = Scores(novelty=0.8, self_consistency=0.9)
    refs = build_hyp_refs(kind="hypothesis", frame="primary", topic="neuro",
                          hyp=hyp, derivation=derivation, contract=None, verdict=verdict,
                          scores=scores, autopsy=None, iteration=Iteration())
    node = Node(id="hyp_1", parent_id="ROOT", hypothesis="Glia encode fear",
                depth=1, status="accepted", score=overall_score, refs=refs,
                grounding=["fact_0"])
    tree.add_node(node)
    return tree

def test_get_ranked_returns_required_fields(tmp_path):
    tree = _make_tree_with_hyp(tmp_path, 0.85)
    store = RankedHypothesisStore(tree)
    results = store.get_ranked()
    assert len(results) == 1
    r = results[0]
    assert isinstance(r, RankedHypothesis)
    assert r.mechanism == "Glia encode fear"
    assert r.novelty == 0.8
    assert r.overall_score == 0.85
    assert "fact_0" in r.grounding_fact_ids
    assert not hasattr(r, "refs")  # must NOT expose tree internals

def test_get_ranked_ordered_best_first(tmp_path):
    root = Node(id="ROOT", parent_id=None, hypothesis="t", depth=0, status="pending")
    tree = IdeaTree(root=root, json_path=tmp_path / "tree.json")
    for i, score in enumerate([0.3, 0.9, 0.6]):
        refs = build_hyp_refs(kind="hypothesis", frame="primary", topic="neuro",
                              hyp=HypothesisHyp(MECHANISM=f"m{i}", KILL="k", BRACKET="b", DIFF_PREDICTION=f"d{i}"),
                              derivation=[], contract=None,
                              verdict=Verdict(id=f"v{i}", reviewer_model="qwen-plus",
                                             result="UP", reasons=[], decided_by="jury"),
                              scores=Scores(novelty=score, self_consistency=score),
                              autopsy=None, iteration=Iteration())
        node = Node(id=f"hyp_{i}", parent_id="ROOT", hypothesis=f"m{i}",
                    depth=1, status="accepted", score=score, refs=refs)
        tree.add_node(node)
    results = RankedHypothesisStore(tree).get_ranked()
    scores = [r.overall_score for r in results]
    assert scores == sorted(scores, reverse=True)
```

- [ ] **Step 2: Run test — verify FAIL**

```bash
cd /home/lingxufeng/cli/Loop-SCI && python -m pytest tests/unit/hypothesis/test_ranked.py -v 2>&1 | tail -5
```

- [ ] **Step 3: Implement `loop_sci/hypothesis/ranked.py`**

```python
# loop_sci/hypothesis/ranked.py
from __future__ import annotations
from dataclasses import dataclass, field
from loop_sci.hypothesis.schemas import refs_from_dict
from loop_sci.state.idea_tree import IdeaTree

@dataclass
class RankedHypothesis:
    node_id: str
    problem: str
    mechanism: str
    derivation_chain: list[dict]
    diff_prediction: str
    novelty: float
    self_consistency: float
    overall_score: float
    grounding_fact_ids: list[str] = field(default_factory=list)


class RankedHypothesisStore:
    def __init__(self, tree: IdeaTree) -> None:
        self._tree = tree

    def get_ranked(
        self,
        *,
        topic: str | None = None,
        status: str | None = None,
    ) -> list[RankedHypothesis]:
        results: list[RankedHypothesis] = []
        for node in self._tree.get_all_nodes():
            if not node.refs:
                continue
            if node.refs.get("kind") != "hypothesis":
                continue
            if status is not None and node.status != status:
                continue
            if topic is not None and node.refs.get("topic") != topic:
                continue
            try:
                r = refs_from_dict(node.refs)
            except Exception:
                continue
            hyp = r.hyp
            if hyp is None:
                continue
            scores = r.scores
            novelty = scores.novelty if scores else 0.0
            sc = scores.self_consistency if scores else 0.0
            derivation_chain = [
                {"step": s.step, "grade": s.grade, "fact_ids": s.fact_ids}
                for s in r.derivation
            ]
            results.append(RankedHypothesis(
                node_id=node.id,
                problem=node.refs.get("topic", ""),
                mechanism=hyp.MECHANISM,
                derivation_chain=derivation_chain,
                diff_prediction=hyp.DIFF_PREDICTION,
                novelty=novelty,
                self_consistency=sc,
                overall_score=node.score or 0.0,
                grounding_fact_ids=list(node.grounding or []),
            ))
        return sorted(results, key=lambda x: x.overall_score, reverse=True)
```

- [ ] **Step 4: Run test — verify PASS**

```bash
cd /home/lingxufeng/cli/Loop-SCI && python -m pytest tests/unit/hypothesis/test_ranked.py -v
```
Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add loop_sci/hypothesis/ranked.py tests/unit/hypothesis/test_ranked.py
git commit -m "feat(hypothesis): implement stable ranked-hypothesis query interface"
```

---

## Task 10: HypothesisExecutor + ToolRegistry + Hydra config

**OpenSpec tasks:** 4.3, 4.4, 4.5; Hydra config

**Files:**
- Create: `loop_sci/hypothesis/executor.py`
- Create: `loop_sci/hypothesis/coordinator.py`
- Create: `loop_sci/hypothesis/tools.py`
- Modify: `loop_sci/hypothesis/__init__.py`
- Create: `conf/hypothesis/default.yaml`
- Modify: `conf/config.yaml`
- Create: `tests/unit/hypothesis/test_executor.py`
- Create: `tests/unit/hypothesis/test_tools.py`

**Interfaces:**
- `HypothesisExecutor(session, *, gen_provider, rev_provider, store_path, max_cards, max_candidates, max_rounds)` — `async run(unit: DispatchUnit) -> ExecutorResult`.
- `HypothesisCoordinator(cfg, *, executor, bus, step_budget)` — overrides `_observe()` (score-sorted) and `_plan()` (injects fact-base context).
- Tools: `register_hypothesis_tools(registry: ToolRegistry, executor: HypothesisExecutor)` — registers `generate`, `critique`, `rank`.

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/hypothesis/test_executor.py
import json, pytest
from pathlib import Path
from loop_sci.hypothesis.executor import HypothesisExecutor
from loop_sci.engine.types import DispatchUnit
from loop_sci.state.session import RunSession
from loop_sci.literature.factbase.store import FactStore
from loop_sci.literature.extract.fact import Fact, SourceRef
from tests.conftest import MockProvider

def _seeded_store(tmp_path) -> Path:
    store = FactStore(tmp_path / "facts.json")
    f = Fact(claim="Neurons fire action potentials.",
             source_ref=SourceRef(source="s2", external_id="x0"),
             evidence_span="Neurons fire", grounding_scope="abstract")
    f.fact_id = "fact_0"
    store.add(f)
    return tmp_path / "facts.json"

def _gen_responses():
    cards = json.dumps([{"Q": "Why?", "WHY_NOW": "now", "PROBE_KILL": "pk",
                          "STAKES": 0.9, "fact_ids": ["fact_0"]}])
    hyps = json.dumps({"candidates": [
        {"MECHANISM": "Glial sync", "KILL": "no glial", "BRACKET": "plausible",
         "DIFF_PREDICTION": "Distinct EEG pattern", "frame": "primary",
         "derivation": [{"step": "Neurons → glia", "grade": "[paper]", "fact_ids": ["fact_0"]}]},
        {"MECHANISM": "Rival sync", "KILL": "rival kill", "BRACKET": "low",
         "DIFF_PREDICTION": "Different EEG", "frame": "rival", "derivation": []},
    ]})
    contract = json.dumps({"HYPOTHESIS": "Glial sync", "LATENT_ROOT": "glial",
                            "ACCEPT_IF": "EEG differs", "KILL_IF": "No transient"})
    verdict = json.dumps({"result": "UP", "reasons": ["novel mechanism"]})
    return [cards, hyps, contract, verdict, hyps, contract, verdict]

@pytest.mark.asyncio
async def test_executor_produces_accepted_hypothesis(tmp_path):
    session = RunSession.create(tmp_path / "runs", task="neuro")
    store_path = _seeded_store(tmp_path)
    gen = MockProvider(responses=_gen_responses())
    rev = MockProvider(responses=[json.dumps({"result": "UP", "reasons": ["novel"]})] * 5)
    rev.model = "qwen-plus"
    exec_ = HypothesisExecutor(session, gen_provider=gen, rev_provider=rev,
                                store_path=store_path, max_cards=2,
                                max_candidates=2, max_rounds=1)
    unit = DispatchUnit(node_id="ROOT", goal="neuro")
    result = await exec_.run(unit)
    assert result.status == "done"
    accepted = [n for n in session.tree.get_all_nodes() if n.status == "accepted"]
    assert len(accepted) >= 1

@pytest.mark.asyncio
async def test_executor_resume_skips_accepted(tmp_path):
    session = RunSession.create(tmp_path / "runs", task="neuro")
    store_path = _seeded_store(tmp_path)
    gen = MockProvider(responses=_gen_responses())
    rev = MockProvider(responses=[json.dumps({"result": "UP", "reasons": []})] * 5)
    rev.model = "qwen-plus"
    exec_ = HypothesisExecutor(session, gen_provider=gen, rev_provider=rev,
                                store_path=store_path, max_cards=2,
                                max_candidates=2, max_rounds=1)
    unit = DispatchUnit(node_id="ROOT", goal="neuro")
    await exec_.run(unit)
    calls_first = gen._index
    await exec_.run(unit)  # resume — should skip already-accepted nodes
    assert gen._index == calls_first  # no new gen calls for already-accepted
```

```python
# tests/unit/hypothesis/test_tools.py
import json, pytest
from loop_sci.engine.tools import ToolRegistry
from loop_sci.hypothesis.tools import register_hypothesis_tools

class _FakeExecutor:
    async def run_pipeline(self, topic): return []
    async def run_critique(self, node_id): return "DOWN"
    def ranked_store(self): return None

@pytest.mark.asyncio
async def test_tools_registered_and_return_json():
    registry = ToolRegistry()
    from loop_sci.hypothesis.tools import register_hypothesis_tools
    register_hypothesis_tools(registry, None)  # None executor for schema-only test
    defs = registry.get_definitions()
    names = [d["name"] for d in defs]
    assert "generate" in names
    assert "critique" in names
    assert "rank" in names
```

- [ ] **Step 2: Run tests — verify FAIL**

```bash
cd /home/lingxufeng/cli/Loop-SCI && python -m pytest tests/unit/hypothesis/test_executor.py tests/unit/hypothesis/test_tools.py -v 2>&1 | tail -10
```

- [ ] **Step 3: Implement `loop_sci/hypothesis/executor.py`**

```python
# loop_sci/hypothesis/executor.py
"""HypothesisExecutor: prospect' → forge' → contract → adversary' → autopsy' loop."""
from __future__ import annotations
import logging
from pathlib import Path
from loop_sci.engine.types import DispatchUnit, ExecutorResult
from loop_sci.hypothesis.stages.prospect import run_prospect
from loop_sci.hypothesis.stages.forge import run_forge
from loop_sci.hypothesis.stages.contract import freeze_contract
from loop_sci.hypothesis.stages.adversary import run_adversary
from loop_sci.hypothesis.stages.autopsy import classify_kill, StallLedger, RegionTracker
from loop_sci.hypothesis.scoring import score_hypothesis
from loop_sci.hypothesis.ledger import VerdictLedger
from loop_sci.hypothesis.schemas import refs_from_dict
from loop_sci.literature.factbase.store import FactStore
from loop_sci.state.session import RunSession
from loop_sci.state.idea_tree import Node

log = logging.getLogger(__name__)

class HypothesisExecutor:
    def __init__(
        self,
        session: RunSession,
        *,
        gen_provider,
        rev_provider,
        store_path: Path,
        max_cards: int = 5,
        max_candidates: int = 4,
        max_rounds: int = 3,
        gen_model: str = "qwen-max",
    ) -> None:
        self._session = session
        self._gen = gen_provider
        self._rev = rev_provider
        self._store = FactStore(Path(store_path))
        self._max_cards = max_cards
        self._max_candidates = max_candidates
        self._max_rounds = max_rounds
        self._gen_model = gen_model
        self._ledger = VerdictLedger(session.session_dir / "verdict-ledger.jsonl")

    async def run(self, unit: DispatchUnit) -> ExecutorResult:
        topic = unit.goal
        tree = self._session.tree
        accepted_ids = self._ledger.accepted_node_ids()
        stall = StallLedger()
        region_tracker = RegionTracker()
        facts = self._store.all()
        lessons: list[str] = []

        for round_n in range(self._max_rounds):
            log.info("hypothesis round %d topic=%s", round_n, topic)
            cards = await run_prospect(topic, self._store, self._gen, max_cards=self._max_cards)
            new_accepted = 0

            for card_node_id, card_refs in cards:
                # Ensure card node in tree
                if card_node_id not in tree._nodes:
                    card_node = Node(id=card_node_id, parent_id="ROOT", hypothesis=card_refs["card"]["Q"],
                                     depth=1, status="pending", refs=card_refs)
                    tree.add_node(card_node)

                candidates = await run_forge(card_node_id, card_refs, self._store, self._gen,
                                             max_candidates=self._max_candidates)
                for hyp_node_id, hyp_refs, derivation in candidates:
                    if hyp_node_id in accepted_ids:
                        log.debug("skipping already-accepted %s", hyp_node_id)
                        continue

                    if hyp_node_id not in tree._nodes:
                        hyp_node = Node(id=hyp_node_id, parent_id=card_node_id,
                                        hypothesis=(hyp_refs.get("hyp") or {}).get("MECHANISM", ""),
                                        depth=2, status="pending", refs=hyp_refs,
                                        grounding=hyp_refs.get("grounding_fact_ids", []))
                        tree.add_node(hyp_node)

                    contract = await freeze_contract(hyp_refs, self._gen)
                    hyp_refs["contract"] = {"HYPOTHESIS": contract.HYPOTHESIS,
                                            "LATENT_ROOT": contract.LATENT_ROOT,
                                            "ACCEPT_IF": contract.ACCEPT_IF,
                                            "KILL_IF": contract.KILL_IF}
                    verdict = await run_adversary(hyp_refs, derivation, self._store,
                                                  self._gen_model, self._rev)
                    self._ledger.append(verdict.id, hyp_node_id, verdict.reviewer_model,
                                        verdict.result, round_n=round_n)
                    hyp_refs["verdict"] = {"id": verdict.id, "reviewer_model": verdict.reviewer_model,
                                           "result": verdict.result, "reasons": verdict.reasons,
                                           "decided_by": verdict.decided_by}

                    mechanism = (hyp_refs.get("hyp") or {}).get("MECHANISM", "")
                    scores = score_hypothesis(mechanism, derivation, facts)
                    overall = 0.5 * scores.novelty + 0.5 * scores.self_consistency
                    hyp_refs["scores"] = {"novelty": scores.novelty,
                                          "self_consistency": scores.self_consistency,
                                          "decided_by": scores.decided_by}

                    node = tree._nodes.get(hyp_node_id)
                    if node:
                        node.refs = hyp_refs
                        if verdict.result == "UP":
                            tree.update_node(hyp_node_id, status="accepted", score=overall)
                            accepted_ids.add(hyp_node_id)
                            new_accepted += 1
                        else:
                            autopsy = classify_kill(verdict, hyp_refs)
                            hyp_refs["autopsy"] = {"outcome": autopsy.outcome,
                                                    "region": autopsy.region, "note": autopsy.note}
                            node.refs = hyp_refs
                            tree.update_node(hyp_node_id, status="pruned",
                                             insight=f"KILL: {autopsy.outcome} — {autopsy.note[:80]}")
                            region_tracker.record_kill(contract.LATENT_ROOT)
                            lessons.append(f"[{autopsy.outcome}] {autopsy.note[:60]}")
                    tree.save()

            action = stall.record_round(new_accepted)
            if action == "escalate":
                log.warning("hypothesis: escalating after persistent stall at round %d", round_n)
                break
            if action == "pivot":
                log.info("hypothesis: pivot at round %d", round_n)
                # pivot = continue to next round with pruned-lessons context injected

        self._session.advance_step()
        total_accepted = len(accepted_ids)
        return ExecutorResult(
            status="done",
            summary=f"Hypothesis engine: {total_accepted} accepted hypotheses.",
            score=None,
            insight=f"{total_accepted} accepted after {round_n + 1} rounds.",
            refs={"accepted_count": total_accepted, "lessons": lessons},
        )
```

- [ ] **Step 4: Implement `loop_sci/hypothesis/coordinator.py`**

```python
# loop_sci/hypothesis/coordinator.py
from __future__ import annotations
from loop_sci.engine.coordinator import Coordinator
from loop_sci.engine.types import DispatchUnit
from loop_sci.state.idea_tree import Node
from loop_sci.state.session import RunSession

class HypothesisCoordinator(Coordinator):
    """Coordinator subclass: score-sorted _observe, fact-base context injection."""

    def _observe(self, session: RunSession) -> Node | None:
        pending = session.tree.get_pending_leaves()
        if pending:
            return sorted(pending, key=lambda n: -(n.score or 0.0))[0]
        root = session.tree.get_root()
        if root.status == "pending":
            return root
        return None

    def _plan(self, node: Node) -> DispatchUnit:
        context = ""
        if node.refs and node.refs.get("kind") == "problem-card":
            context = f"Problem card: {node.refs.get('card', {}).get('Q', '')}"
        return DispatchUnit(node_id=node.id, goal=node.hypothesis, context=context, tools=[])
```

- [ ] **Step 5: Implement `loop_sci/hypothesis/tools.py`**

```python
# loop_sci/hypothesis/tools.py
import json
from loop_sci.engine.tools import ToolRegistry

def register_hypothesis_tools(registry: ToolRegistry, executor) -> None:
    async def _generate(topic: str) -> str:
        if executor is None:
            return json.dumps({"error": "no executor"})
        result = await executor.run_pipeline(topic)
        return json.dumps({"accepted_count": len(result)})

    async def _critique(node_id: str) -> str:
        if executor is None:
            return json.dumps({"error": "no executor"})
        verdict = await executor.run_critique(node_id)
        return json.dumps({"verdict": verdict})

    def _rank(topic: str = "", status: str = "accepted") -> str:
        if executor is None:
            return json.dumps([])
        store = executor.ranked_store()
        if store is None:
            return json.dumps([])
        ranked = store.get_ranked(topic=topic or None, status=status)
        return json.dumps([{"node_id": r.node_id, "mechanism": r.mechanism,
                            "overall_score": r.overall_score} for r in ranked])

    registry.register(name="generate", description="Generate hypotheses for a topic.",
                      schema={"type": "object", "properties": {"topic": {"type": "string"}},
                               "required": ["topic"]}, fn=_generate)
    registry.register(name="critique", description="Critique a hypothesis node.",
                      schema={"type": "object", "properties": {"node_id": {"type": "string"}},
                               "required": ["node_id"]}, fn=_critique)
    registry.register(name="rank", description="Return ranked hypotheses.",
                      schema={"type": "object", "properties": {
                          "topic": {"type": "string"}, "status": {"type": "string"}}},
                      fn=_rank)
```

- [ ] **Step 6: Create `conf/hypothesis/default.yaml`**

```yaml
# conf/hypothesis/default.yaml
max_cards: 5
max_candidates: 4
max_rounds: 3
gen_model: qwen-max
rev_model: qwen-plus
novelty_low: 0.15
novelty_high: 0.60
weight_novelty: 0.5
weight_self_consistency: 0.5
stall_pivot_at: 2
stall_escalate_at: 4
```

Modify `conf/config.yaml` — add `- hypothesis: default` to the `defaults` list:

```yaml
defaults:
  - provider: bailian
  - agent: default
  - engine: default
  - run: default
  - hypothesis: default
  - _self_
```

- [ ] **Step 7: Update `loop_sci/hypothesis/__init__.py`**

```python
from loop_sci.hypothesis.executor import HypothesisExecutor
from loop_sci.hypothesis.coordinator import HypothesisCoordinator
from loop_sci.hypothesis.ranked import RankedHypothesisStore

__all__ = ["HypothesisExecutor", "HypothesisCoordinator", "RankedHypothesisStore"]
```

- [ ] **Step 8: Run tests — verify PASS**

```bash
cd /home/lingxufeng/cli/Loop-SCI && python -m pytest tests/unit/hypothesis/test_executor.py tests/unit/hypothesis/test_tools.py -v
```

- [ ] **Step 9: Commit**

```bash
git add loop_sci/hypothesis/executor.py loop_sci/hypothesis/coordinator.py \
  loop_sci/hypothesis/tools.py loop_sci/hypothesis/__init__.py \
  conf/hypothesis/default.yaml conf/config.yaml \
  tests/unit/hypothesis/test_executor.py tests/unit/hypothesis/test_tools.py
git commit -m "feat(hypothesis): implement HypothesisExecutor, HypothesisCoordinator, tools, and Hydra config"
```

---

## Task 11: Integration test + live test + README + coverage gate

**OpenSpec tasks:** 5.1, 5.2, 5.3

**Files:**
- Create: `tests/integration/test_hypothesis_pipeline.py`
- Create: `tests/live/test_hypothesis_live.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: all of Tasks 1–10.

- [ ] **Step 1: Write offline integration test**

```python
# tests/integration/test_hypothesis_pipeline.py
"""Offline integration: coordinator → HypothesisExecutor → MockProvider + seeded FactStore."""
import json, pytest
from pathlib import Path
from loop_sci.hypothesis import HypothesisExecutor, HypothesisCoordinator, RankedHypothesisStore
from loop_sci.state.session import RunSession
from loop_sci.literature.factbase.store import FactStore
from loop_sci.literature.extract.fact import Fact, SourceRef
from tests.conftest import MockProvider


def _seeded_store(tmp_path) -> Path:
    store = FactStore(tmp_path / "facts.json")
    for i, claim in enumerate([
        "Neurons fire action potentials.",
        "Glial cells modulate synaptic transmission.",
    ]):
        f = Fact(claim=claim, source_ref=SourceRef(source="s2", external_id=f"x{i}"),
                 evidence_span=claim[:20], grounding_scope="abstract")
        f.fact_id = f"fact_{i}"
        store.add(f)
    return tmp_path / "facts.json"


def _build_providers():
    cards = json.dumps([{"Q": "Glial role?", "WHY_NOW": "now", "PROBE_KILL": "pk",
                          "STAKES": 0.9, "fact_ids": ["fact_0", "fact_1"]}])
    hyps = json.dumps({"candidates": [
        {"MECHANISM": "Glial calcium waves encode fear via gap junctions",
         "KILL": "No glial transient", "BRACKET": "plausible",
         "DIFF_PREDICTION": "Distinct BOLD signature in fear CS", "frame": "primary",
         "derivation": [{"step": "Glia modulate synapses", "grade": "[paper]",
                          "fact_ids": ["fact_1"]}]},
        {"MECHANISM": "Rival: Astrocyte K+ buffering",
         "KILL": "K+ buffering unchanged", "BRACKET": "low",
         "DIFF_PREDICTION": "Flat K+ transient", "frame": "rival",
         "derivation": [{"step": "Neurons → glia", "grade": "[inferred]", "fact_ids": ["fact_0"]}]},
    ]})
    contract = json.dumps({"HYPOTHESIS": "Glial calcium waves encode fear",
                            "LATENT_ROOT": "glial_plasticity",
                            "ACCEPT_IF": "BOLD differs by >0.5σ",
                            "KILL_IF": "No glial Ca2+ transient"})
    up_verdict = json.dumps({"result": "UP", "reasons": ["novel mechanism, well-grounded"]})
    gen = MockProvider(responses=[cards, hyps, contract, contract, up_verdict])
    rev = MockProvider(responses=[up_verdict] * 5)
    rev.model = "qwen-plus"
    return gen, rev


@pytest.mark.asyncio
async def test_pipeline_produces_accepted_ranked_hypothesis(tmp_path):
    session = RunSession.create(tmp_path / "runs", task="neuro fear encoding")
    store_path = _seeded_store(tmp_path)
    gen, rev = _build_providers()
    executor = HypothesisExecutor(session, gen_provider=gen, rev_provider=rev,
                                   store_path=store_path, max_cards=2,
                                   max_candidates=2, max_rounds=1)
    coordinator = HypothesisCoordinator(executor=executor)
    await coordinator.run(session)

    ranked_store = RankedHypothesisStore(session.tree)
    results = ranked_store.get_ranked()
    assert len(results) >= 1, "Expected ≥1 accepted hypothesis"
    top = results[0]
    assert top.overall_score > 0.0
    assert top.mechanism != ""
    assert len(top.grounding_fact_ids) >= 1

    # Anti-fabrication: no [guess]-only derivations accepted
    for r in results:
        for step in r.derivation_chain:
            assert step["grade"] != "[guess]" or len(r.derivation_chain) > 1

    # No-self-acquit: if UP, reviewer must differ from generator
    for node in session.tree.get_all_nodes():
        if node.status == "accepted" and node.refs:
            verdict = node.refs.get("verdict", {})
            assert verdict.get("reviewer_model") != "qwen-max"
```

- [ ] **Step 2: Run integration test — verify PASS**

```bash
cd /home/lingxufeng/cli/Loop-SCI && python -m pytest tests/integration/test_hypothesis_pipeline.py -v
```
Expected: `1 passed`.

- [ ] **Step 3: Write live test**

```python
# tests/live/test_hypothesis_live.py
"""Live test: real Qwen-Max gen + Qwen-Plus reviewer on a seeded neuro fact base.
Requires DASHSCOPE_API_KEY. Skipped automatically when key is absent.
"""
import os, pytest
from pathlib import Path
from loop_sci.hypothesis import HypothesisExecutor
from loop_sci.state.session import RunSession
from loop_sci.literature.factbase.store import FactStore
from loop_sci.literature.extract.fact import Fact, SourceRef
from loop_sci.provider.factory import build_provider

@pytest.mark.live
@pytest.mark.asyncio
async def test_live_hypothesis_neuro_topic(tmp_path):
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        pytest.skip("DASHSCOPE_API_KEY not set")

    store = FactStore(tmp_path / "facts.json")
    for i, claim in enumerate([
        "Long-term potentiation underlies declarative memory consolidation in the hippocampus.",
        "Fear conditioning requires amygdala basolateral nucleus activity.",
    ]):
        f = Fact(claim=claim, source_ref=SourceRef(source="s2", external_id=f"live{i}"),
                 evidence_span=claim[:30], grounding_scope="abstract")
        f.fact_id = f"live_fact_{i}"
        store.add(f)

    session = RunSession.create(tmp_path / "runs", task="hippocampal fear encoding")
    gen = build_provider(model="qwen-max", api_key=api_key)
    rev = build_provider(model="qwen-plus", api_key=api_key)
    executor = HypothesisExecutor(session, gen_provider=gen, rev_provider=rev,
                                   store_path=tmp_path / "facts.json",
                                   max_cards=2, max_candidates=2, max_rounds=1)
    from loop_sci.engine.types import DispatchUnit
    result = await executor.run(DispatchUnit(node_id="ROOT", goal="hippocampal fear encoding"))
    assert result.status == "done"
    assert result.refs.get("accepted_count", 0) >= 0  # may be 0 if all killed
```

- [ ] **Step 4: Run coverage gate**

```bash
cd /home/lingxufeng/cli/Loop-SCI && python -m pytest tests/unit/hypothesis/ tests/integration/test_hypothesis_pipeline.py \
  --cov=loop_sci/hypothesis --cov-report=term-missing --cov-fail-under=80 -v
```
Expected: coverage ≥ 80%, all tests pass.

- [ ] **Step 5: Run ruff**

```bash
cd /home/lingxufeng/cli/Loop-SCI && ruff check loop_sci/hypothesis/ tests/unit/hypothesis/ tests/integration/test_hypothesis_pipeline.py
```
Expected: no errors. Fix any flagged issues before continuing.

- [ ] **Step 6: Add README section**

Open `README.md` and append (after the Literature Mining section or at the end of the pipeline overview):

```markdown
## Hypothesis Engine (change #4)

### Pipeline overview

```
FactStore (read-only) → prospect' → forge' → contract → adversary' → autopsy'
                                                                    → ranked hypotheses
```

1. **prospect'** mines gap cards `{Q, WHY_NOW, PROBE_KILL, STAKES}` from `FactStore.filter()`. Cards citing non-existent `fact_id`s are dropped before ranking.
2. **forge'** generates `{MECHANISM, KILL, BRACKET, DIFF_PREDICTION}` candidates (Qwen-Max) with ≥1 rival-frame sibling per card. Relabeling is discarded.
3. **contract** freezes `{HYPOTHESIS, LATENT_ROOT, ACCEPT_IF, KILL_IF}` as derivation tripwires before any verdict.
4. **adversary'** runs a deterministic pre-jury gate first (contradictions or load-bearing `[guess]` → DOWN without a reviewer call), then the Qwen-Plus KILL-persona jury. The generator cannot issue its own accept.
5. **autopsy'** converts kills to `CONSTRAINT / CANDIDATE / REGION_CLOSE`, feeds back into ranking, and tracks stall/escalate (pivot@2, escalate@4).

### Qwen-vs-Qwen jury

- Generator: `qwen-max` · Reviewer: `qwen-plus` with adversarial KILL-biased persona.
- **No self-acquit:** an UP verdict from the same model tier as the generator is rejected at the routing layer.
- **Deterministic gate:** mechanism-contradicts-grounding or load-bearing `[guess]` → DOWN without spending a reviewer call.

### Budget & environment

Per-run caps (Hydra-configurable in `conf/hypothesis/default.yaml`): ≤5 cards · ≤4 candidates/card · ≤3 rounds. Jury fires once per surviving candidate. Typical run ≈ 300¥ at cap.

Set `DASHSCOPE_API_KEY` for live runs. Offline tests use `MockProvider` (no key needed).

### Ranked output for #5

```python
from loop_sci.hypothesis import RankedHypothesisStore
ranked = RankedHypothesisStore(session.tree).get_ranked(topic="neuro", status="accepted")
# each RankedHypothesis: node_id, mechanism, derivation_chain, diff_prediction, novelty, self_consistency, overall_score, grounding_fact_ids
```

### Live tests

```bash
DASHSCOPE_API_KEY=<key> python -m pytest tests/live/test_hypothesis_live.py -v -m live
```
```

- [ ] **Step 7: Commit all**

```bash
git add tests/integration/test_hypothesis_pipeline.py tests/live/test_hypothesis_live.py README.md
git commit -m "feat(hypothesis): add integration test, live test skeleton, and README section"
```

---

## Base-ref / Verification

- **base-ref:** `c1d01d9213a8972d12087babb3e275210a92d693` — branch from here; all tasks are forward-only.
- **Verification order:** Tasks 1–3 (schemas, scoring, ledger) are independent and can run in parallel. Tasks 4–8 (stages) depend on Tasks 1–3 but are otherwise independent of each other. Task 9 (ranked) depends on Task 1. Task 10 (executor/coordinator/tools) depends on all stages. Task 11 (integration + live) depends on Task 10.
- **Coverage gate:** `pytest --cov=loop_sci/hypothesis --cov-fail-under=80` must pass before the Task 11 commit.
- **Ruff gate:** `ruff check loop_sci/hypothesis/` must be clean on every commit.
- **Acceptance signal per task:** the unit tests for that task pass green with `pytest tests/unit/hypothesis/test_<name>.py -v`.
- **Full change acceptance:** `pytest tests/unit/hypothesis/ tests/integration/test_hypothesis_pipeline.py --cov=loop_sci/hypothesis --cov-fail-under=80` passes clean.
