# Loop-SCI

Multi-agent research harness powered by Qwen via Alibaba Cloud Bailian. Foundation skeleton for the XH-202619 AI Scientist project — this change establishes the core provider, engine, state, and CLI layers.

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --group dev
cp .env.example .env
# Edit .env and set: DASHSCOPE_API_KEY=sk-...
```

## Bailian Credentials

Set `DASHSCOPE_API_KEY` in your environment or `.env` file. The provider connects via the OpenAI-compatible Bailian endpoint:

```
https://dashscope.aliyuncs.com/compatible-mode/v1
```

The active model tier and tool-call protocol are configured in `conf/provider/bailian.yaml`:

```yaml
model: qwen-plus          # tier — qwen-turbo / qwen-plus / qwen-max
tool_protocol: native     # native (function-calling) or prompt (text-encoded)
```

## Running

Start a research run:

```bash
loop-sci run --task "What are three key principles of the scientific method?"
```

Each run creates a directory under `runs/<run_id>/` containing:
- `idea_tree.json` — hypothesis tree with per-node status and insights
- `run.json` — run metadata (task, timestamps, final status)

Resume a paused or interrupted run:

```bash
loop-sci resume <run_id>
```

Inspect a completed run:

```bash
loop-sci inspect <run_id>
```

## Testing

Offline suite (no API key required, suitable for CI):

```bash
uv run pytest
```

Live smoke tests (require `DASHSCOPE_API_KEY`; validate real Qwen completions and native tool-call support):

```bash
DASHSCOPE_API_KEY=sk-... uv run pytest -m live -v -s
```

With coverage:

```bash
uv run pytest --cov=loop_sci --cov-report=term-missing
```

Coverage is measured over `loop_sci/` excluding the vendored Arbor tree (`loop_sci/_vendor/`). Current: **96%**.

## Architecture

```
CLI (typer)
  └── Coordinator          # orchestrates the research loop
        └── Executor       # invokes AgentRuntime for a single node
              └── AgentRuntime  # bridges LoopSCIConfig → Arbor AgentConfig
                    └── Provider (Bailian/OpenAI-compat)
                          └── ToolRegistry  # named tools with JSON schemas

State
  ├── IdeaTree (idea_tree.json)   # hypothesis tree, atomic persist
  └── RunSession (run.json)       # run envelope and checkpoint

Config: Hydra + OmegaConf (`conf/`)
Events: EventBus seam — NullBus by default; subscribe for future dashboard
```

## Literature Mining

Loop-SCI change #2 adds end-to-end evidence-grounded literature mining: starting from a research topic, the system retrieves real papers, extracts structured facts, and runs a four-layer citation verification pipeline before any fact is persisted.

### What it does

```
Topic
  └── multi-source search (Semantic Scholar / arXiv / PubMed)
        └── Qwen extraction → candidate Fact objects (evidence_span required)
              └── 4-layer citation verification
                    L1 format   — DOI / arXiv-ID / PMID well-formed
                    L2 existence — DOI resolves; arXiv abstract reachable; PMID in efetch
                    L3 metadata  — title / author similarity ≥ threshold
                    L4 content-grounding — lexical overlap + Qwen judge for borderline claims
                          └── verified Fact base
                                ├── IdeaTree nodes  (runs/<run_id>/idea_tree.json)
                                └── JSON fact store (runs/<run_id>/facts.json)
```

**Anti-fabrication guarantees:** hallucinated citations are rejected at L2 (non-existent DOI); misattributed claims are rejected at L4 (claim not supported by the paper's abstract). Only fully verified facts are persisted — nothing is stored when any layer fails.

### Credentials / environment

| Variable | Required | Purpose |
|---|---|---|
| `DASHSCOPE_API_KEY` | Yes | Qwen via Alibaba Cloud Bailian (reused from foundation) |
| `SEMANTIC_SCHOLAR_API_KEY` | Optional | Higher Semantic Scholar rate-limits |
| `PUBMED_EMAIL` | Optional | Polite-pool access on NCBI efetch |

Add these to `.env` (gitignored). Offline tests need none of them.

### Running literature mining

Drive the `LitMinerExecutor` directly from Python:

```python
from loop_sci.state.session import RunSession
from loop_sci.literature.executor import LitMinerExecutor, LitMinerConfig

session = RunSession.create(run_id="my-run", task="graph neural networks")
cfg = LitMinerConfig(max_papers=5, facts_per_paper=3)
executor = LitMinerExecutor(session=session, config=cfg)
import asyncio
asyncio.run(executor.run())
# Results in: runs/my-run/idea_tree.json  +  runs/my-run/facts.json
```

Or use the individual tool-registry tools (`lit_search`, `lit_fetch`, `lit_extract`, `lit_verify`) inside a ToolRegistry-backed AgentRuntime — each tool is registered automatically when `loop_sci.literature` is imported.

**Fact-base output format** (`facts.json`):

```json
[
  {
    "claim": "GNNs achieve state-of-the-art on node classification",
    "source_ref": "10.1145/3394486.3403076",
    "evidence_span": "GNNs consistently outperform MLP baselines on ...",
    "verification": {"status": "verified", "layers": {"l1": true, "l2": true, "l3": true, "l4": true}}
  }
]
```

Each verified fact also appears as a node in `idea_tree.json` with `refs["verification"]["status"] == "verified"`.

### Testing

Offline (no API key — all network calls mocked; suitable for CI):

```bash
uv run pytest
```

Live (real Semantic Scholar / arXiv / PubMed APIs + real Qwen calls; requires `DASHSCOPE_API_KEY`):

```bash
DASHSCOPE_API_KEY=sk-... uv run pytest -m live -v -s
```

The live test at `tests/live/test_lit_miner_live.py` is skipped automatically unless the key is present.

---

## Hypothesis Engine (change #4)

### Pipeline overview

```
FactStore (read-only) → prospect' → forge' → contract → adversary' → autopsy'
                                                                    → ranked hypotheses
```

1. **prospect'** mines gap cards `{Q, WHY_NOW, PROBE_KILL, STAKES}` from `FactStore.filter()`. Cards citing non-existent `fact_id`s are dropped before ranking.
2. **forge'** generates `{MECHANISM, KILL, BRACKET, DIFF_PREDICTION}` candidates (Qwen-Max) with ≥1 rival-frame sibling per card. Relabeling candidates are discarded.
3. **contract** freezes `{HYPOTHESIS, LATENT_ROOT, ACCEPT_IF, KILL_IF}` as derivation tripwires before any verdict.
4. **adversary'** runs a deterministic pre-jury gate first (contradictions or load-bearing `[guess]` or ungrounded `[paper]`/`[inferred]` citations → DOWN without a reviewer call), then the Qwen-Plus KILL-persona jury. The generator cannot issue its own accept.
5. **autopsy'** converts kills to `CONSTRAINT / CANDIDATE / REGION_CLOSE`, feeds back into ranking, and tracks stall/escalate (pivot@2, escalate@4).

### Qwen-vs-Qwen jury

- Generator: `qwen-max` · Reviewer: `qwen-plus` with adversarial KILL-biased persona.
- **No self-acquit:** an UP verdict from the same model tier as the generator is rejected at the routing layer before any verdict is recorded.
- **Deterministic gate:** mechanism-contradicts-grounding, load-bearing `[guess]`, or ungrounded `[paper]`/`[inferred]` citation → DOWN without spending a reviewer call.

### Budget & environment

Per-run caps (Hydra-configurable in `conf/hypothesis/default.yaml`): ≤5 cards · ≤4 candidates/card · ≤3 rounds. Jury fires once per surviving candidate after the deterministic gate.

Set `DASHSCOPE_API_KEY` for live runs. Offline tests use `MockProvider` (no key needed).

### Ranked output for downstream plan-assembler (#5)

```python
from loop_sci.hypothesis import RankedHypothesisStore
ranked = RankedHypothesisStore(session.tree).get_ranked(topic="neuro", status="accepted")
# each RankedHypothesis: node_id, mechanism, derivation_chain, diff_prediction,
#                        novelty, self_consistency, overall_score, grounding_fact_ids
```

Results are sorted best-first by `overall_score` (= `w_n * novelty + w_c * self_consistency`).

### Live tests

```bash
DASHSCOPE_API_KEY=<key> python -m pytest tests/live/test_hypothesis_live.py -v -m live
```

Skipped automatically when `DASHSCOPE_API_KEY` is absent.

---

## Research Plan Assembler (change #5)

`PlanAssemblerExecutor` converts a `RankedHypothesis` into a full 《科学假设与研究计划》 (Scientific Hypothesis and Research Plan) — a 12-field structured document persisted as both JSON (source of truth) and derived Markdown.

### 12-field plan overview

| # | JSON key | Description |
|---|----------|-------------|
| 1 | `problem_statement` | Research problem anchored to the hypothesis |
| 2 | `rationale` | Why this hypothesis is worth pursuing |
| 3 | `technical_details` | Implementation-level specifics |
| 4 | `datasets` | Dataset candidates traced to grounding facts |
| 5 | `source` | Source-domain candidates from grounding facts |
| 6 | `target` | Target-domain tokens from `diff_prediction` |
| 7 | `paper_title` | Proposed paper title |
| 8 | `abstract` | Proposed abstract |
| 9 | `methods` | Methodological approach |
| 10 | `experiments` | Baselines, metrics, and experimental design |
| 11 | `results` | Evidence-graded feasibility derivation |
| 12 | `references` | Verified bibliographic references |

### Results by formula-derivation (no execution)

`results` is an evidence-graded analytical derivation chain — never an executed measurement.
Each step carries a grade literal: `[paper]` (cited literature), `[inferred]` (logical derivation), or `[guess]` (speculative).
`confidence` is set deterministically by `apply_load_bearing_downgrade`: when the decisive last step is `[guess]`, confidence downgrades to `"low"`, and the quality gate fails.

### Real-reference verification (anti-fabrication)

References are assembled from grounding facts only (default, zero verify calls):

- **Seed path** (always active): each `fact_id` in `hyp.grounding_fact_ids` is resolved against the `FactStore` and lifted to a `Reference(verified=True)` entry.  Real by construction.
- **Extras path** (opt-in, `allow_provider_refs=True`): provider-proposed citations are routed through `VerificationPipeline.verify()`; only `status="verified"` results are admitted.  All others are silently dropped.

### Runtime domain parameter

`PlanConfig(domain="neuroscience")` injects the domain string into all LLM prompts (Calls 1–3), so the same pipeline adapts to any research domain without code changes.

### Output format

The `plans/` subdirectory of the session contains:

- `<node_id>.json` — canonical 12-field JSON (source of truth); includes `gate` and `node_id` provenance.
- `<node_id>.md` — Markdown derived from JSON via `render_markdown`; structural parity is asserted by `assert_json_markdown_parity`.

Resume is zero-cost: if `<node_id>.json` already exists, the executor returns immediately without any provider call.

### Usage

```python
from loop_sci.plan.executor import PlanAssemblerExecutor
from loop_sci.plan.config import PlanConfig
from loop_sci.hypothesis.ranked import RankedHypothesisStore

executor = PlanAssemblerExecutor(
    session,
    provider=provider,
    ranked_store=RankedHypothesisStore(session.tree),
    fact_store=fact_store,
    config=PlanConfig(domain="neuroscience"),
)
result = await executor.run(DispatchUnit(node_id="hyp_node1", goal="scaling"))
# result.status == "done"; plans/hyp_node1.json + plans/hyp_node1.md written
```

### Live tests

```bash
DASHSCOPE_API_KEY=<key> python -m pytest tests/live/test_plan_assembler_live.py -v -m live
```

Skipped automatically when `DASHSCOPE_API_KEY` is absent.

---

## Vendored Arbor

`loop_sci/_vendor/arbor/` is a pinned snapshot of
[Arbor](https://github.com/RUC-NLPIR/Arbor) at commit
`0eae8ad6751615058c2f1cd0f80ff5729123d204` (Apache-2.0).
See `loop_sci/_vendor/arbor/LICENSE` for terms.
The coordinator and executor are reimplemented on top of these primitives; the
vendored files are not modified and not subject to this project's lint or coverage gates.
