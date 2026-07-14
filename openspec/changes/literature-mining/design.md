## Context

Change #2 of Loop-SCI, built on the shipped `arbor-qwen-skeleton` foundation (coordinator/executor over an idea-tree, Qwen-via-Bailian provider, ToolRegistry, RunSession, event bus). It adds the first scored pipeline capability (能力项一 文献挖掘与事实提取): topic → real literature → structured facts → 4-layer-verified citations → a verified fact base the hypothesis-engine will consume. The competition mandates real citations (严禁虚构) and rewards verifiability. Deep per-module design is refined in the Comet design phase; this is the high-level framework.

## Goals / Non-Goals

**Goals:**
- Search real literature across Semantic Scholar + arXiv + PubMed behind one mockable interface (offline-by-default tests).
- Extract structured, evidence-grounded facts via Qwen; never emit an un-sourced/out-of-context claim.
- Verify every citation through 4 layers (format → existence → metadata → content-grounding); reject fabricated/misattributed.
- Persist only verified facts to idea-tree nodes + a queryable JSON fact store; make mining resumable.
- Wire it into the foundation as a lit-miner specialist executor + ToolRegistry tools.

**Non-Goals:** hypothesis generation/gates; 13-field plan assembly; experiment execution; dashboard; domain measured-data/datasets + SFT (neuro-domain-pack). No new provider/LLM infra — reuse the foundation.

## Decisions

**D1 — Source adapters behind a unified, mockable `SearchClient`.** One interface, three adapters (Semantic Scholar REST; arXiv Atom API; PubMed E-utilities esearch/efetch). All HTTP behind an injectable client so the default suite uses recorded/mocked responses and `@pytest.mark.live` tests hit real APIs. Per-source rate-limit/backoff; one failing source degrades gracefully (returns others + a note). *Alternative:* a single aggregator API (e.g. OpenAlex only) — rejected to keep domain coverage (PubMed for neuro) and citation cross-checking.

**D2 — Fact extraction reuses the foundation Qwen provider.** A bounded extraction step prompts Qwen to return structured facts with a required evidence span; output lacking a grounding span is dropped. Bound papers/facts per run for the 300¥ budget. No new model infra.

**D3 — 4-layer citation verification pipeline.** Ordered, short-circuiting: format → existence (DOI/title resolves via API) → metadata match (authors/year/venue within tolerance) → content-grounding (claim supported by the resolved paper's text). Content-grounding method is the main open question (substring/fuzzy match vs embedding similarity vs a Qwen judge over the abstract) — settled in the design phase; likely abstract-level for most papers, full-text for the PMC open-access subset. Each citation records its pass/fail layer.

**D4 — Fact base = idea-tree nodes + JSON fact store.** Verified facts persist via the foundation's state layer (one idea-tree node per fact or per paper — decided in design) carrying the fact payload, AND to a separate queryable JSON fact store exposing a stable query interface (retrieve-all, filter by source/topic) so the hypothesis-engine does not depend on idea-tree internals. Only verified facts are written.

**D5 — Integration via a lit-miner specialist executor + tools.** A `LitMinerExecutor` (specialization over the foundation Executor seam) runs search→extract→verify→record for a dispatched topic; plus `search`/`fetch`/`extract`/`verify` tools registered in the ToolRegistry for agent-driven use. Recording honors the foundation's record-before-decide + atomic-persist invariants.

**D6 — Resumability via persisted state.** The fact store + idea-tree are the durable record; a resumed run skips already-processed papers and already-verified citations (keyed by external id) rather than re-hitting the APIs or re-spending Qwen.

## Risks / Trade-offs

- **[API keys + rate limits]** (Semantic Scholar optional key; PubMed E-utilities email/tool params; arXiv public) → mockable client for CI; opt-in live tests; backoff; cache responses within a run to avoid re-spend.
- **[Content-grounding accuracy vs cost]** (layer 4) → for most papers only the abstract is available, so grounding is abstract-level; a Qwen judge is accurate but costs tokens, a substring/embedding check is cheap but weaker. Decide the method + a confidence threshold in design; make it configurable.
- **[Abstract-only limits misattribution detection]** → layer 4 may pass a claim that's in the abstract but nuanced in full text; record grounding confidence + source scope (abstract vs full-text) so downstream can weigh it.
- **[Qwen extraction cost vs 300¥ budget]** → bounded papers/facts per run, cheap tier default, response caching.
- **[Fact→idea-tree mapping]** → the foundation's `Node` uses a whitelist for mutable fields + a persisted `refs` dict; store the fact payload in `refs`/`insight` or extend the mapping — settle in design without editing vendored code.

## Open Questions

- Content-grounding method (substring/fuzzy vs embedding vs Qwen judge) + threshold — resolved in the design phase via a cheap probe.
- Exact fact schema fields (entities? claim type? grounding confidence + source scope) — finalized in design.
- Fact→idea-tree node granularity (per fact vs per paper) and where the payload lives on the node.
- Whether Semantic Scholar / a PubMed email are available for live tests (offline path works regardless).
- Local-corpus ingestion (user PDFs) — deferred unless needed; APIs cover the core path.
