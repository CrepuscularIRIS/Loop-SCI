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

## Vendored Arbor

`loop_sci/_vendor/arbor/` is a pinned snapshot of
[Arbor](https://github.com/RUC-NLPIR/Arbor) at commit
`0eae8ad6751615058c2f1cd0f80ff5729123d204` (Apache-2.0).
See `loop_sci/_vendor/arbor/LICENSE` for terms.
The coordinator and executor are reimplemented on top of these primitives; the
vendored files are not modified and not subject to this project's lint or coverage gates.
