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

## Vendored Arbor

`loop_sci/_vendor/arbor/` is a pinned snapshot of
[Arbor](https://github.com/RUC-NLPIR/Arbor) at commit
`0eae8ad6751615058c2f1cd0f80ff5729123d204` (Apache-2.0).
See `loop_sci/_vendor/arbor/LICENSE` for terms.
The coordinator and executor are reimplemented on top of these primitives; the
vendored files are not modified and not subject to this project's lint or coverage gates.
