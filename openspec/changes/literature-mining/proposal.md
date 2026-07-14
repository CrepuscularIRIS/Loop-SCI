## Why

Loop-SCI's foundation (`arbor-qwen-skeleton`) gives us a working multi-agent harness — coordinator/executor over an idea-tree, Qwen-via-Bailian provider, ToolProtocol, event bus — but it produces no scientific content yet. The competition's first scored capability (能力项一 文献挖掘与事实提取) is turning **literature + data into structured, trustworthy scientific facts**, because the whole downstream pipeline (hypothesis generation → the 13-field 《科学假设与研究计划》) is only as credible as the facts and citations under it. The rubric is explicit: citations must be **real (严禁虚构)** and verifiable (可验证性).

This change (#2 of the Loop-SCI programme) adds that capability on top of the foundation: given a neuroscience / brain-decoding topic, autonomously search **real** literature (Semantic Scholar + arXiv + PubMed), extract **structured scientific facts**, and **verify every citation through a 4-layer check** — producing a verified fact base (idea-tree nodes + a queryable JSON fact store) that the later hypothesis-engine consumes. Fabricated or misattributed citations are rejected, not stored.

## What Changes

- **NEW** `literature-search`: source adapters for **Semantic Scholar, arXiv, and PubMed** behind a unified paper-result schema; rate-limit handling; a mockable client boundary so the default test suite runs offline (opt-in live tests hit real APIs).
- **NEW** `fact-extraction`: a Qwen-driven step that extracts **structured scientific facts** (claim + entities + source paper + evidence span/quote + confidence) from a paper's abstract/available text, avoiding out-of-context claims (每个 fact carries its supporting span).
- **NEW** `citation-verification`: a **4-layer** verifier — (1) format, (2) API existence (DOI/title resolves to a real paper), (3) metadata match (authors/year/venue), (4) content-grounding (the cited claim actually appears in the source text) — that **rejects hallucinated or misattributed citations** (anti-fabrication).
- **NEW** `fact-base`: verified facts persist as **idea-tree nodes** (via the foundation's state layer) AND a **queryable JSON fact store**; a **lit-miner specialist executor** (dispatched by the coordinator) plus **search/fetch/extract/verify tools** registered in the ToolRegistry wire the capability into the foundation loop. Mining is **resumable** — re-running does not re-verify already-verified facts.
- **Out of scope (later changes):** hypothesis generation + the research-os gates (`hypothesis-engine`), the 13-field plan assembly (`research-plan-assembler`), experiment execution, the dashboard (`visualization`), and domain measured-data / dataset integration + SFT (`neuro-domain-pack`). This change ingests **literature**; multimodal measured neural *data* handling is the domain pack.

## Capabilities

### New Capabilities
- `literature-search`: Search/fetch adapters for Semantic Scholar, arXiv, PubMed under a unified result schema, with rate-limit handling and a mockable client boundary (offline-by-default tests + opt-in live).
- `fact-extraction`: Qwen-driven extraction of structured scientific facts (claim + entities + source + evidence span + confidence) from retrieved papers, each fact tied to its supporting text.
- `citation-verification`: A 4-layer citation verifier (format → API existence → metadata match → content-grounding) that rejects fabricated or misattributed citations.
- `fact-base`: Verified-fact persistence as idea-tree nodes + a queryable JSON fact store, plus the lit-miner specialist executor and the search/fetch/extract/verify tools that integrate the capability into the coordinator/executor loop; resumable.

### Modified Capabilities
<!-- None. Builds on the foundation's llm-provider / agent-engine / research-state without changing their spec-level behavior. -->

## Impact

- **Builds on the foundation** (`loop_sci/`): reuses the Qwen/Bailian provider, ToolRegistry, coordinator/executor, idea-tree/RunSession, and event bus. Adds a new `loop_sci/literature/` (or similarly named) package plus a specialist executor and tools.
- **New dependencies:** HTTP client for the scholarly APIs (Semantic Scholar, arXiv Atom feed, PubMed E-utilities); possibly a lightweight PDF/text parser for local-corpus/full-text; test fixtures with recorded API responses.
- **External systems:** Semantic Scholar API (optional key + rate limits), PubMed E-utilities (email/tool params + rate limits), arXiv (public). All behind a mockable client so CI stays network-free; opt-in `@pytest.mark.live` tests exercise the real APIs. Qwen (via Bailian) drives fact extraction — respects the 300¥ compute budget (cheap tier, bounded paper counts).
- **Enables:** the `hypothesis-engine` change, which consumes the verified fact base to generate hypotheses grounded in real, checked citations.
