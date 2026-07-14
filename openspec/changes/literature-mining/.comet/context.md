# Comet Design Handoff

- Change: literature-mining
- Phase: design
- Mode: compact
- Context hash: a3a91665a162c83a7a215af26acea299d16825bb05e2806533fe7668eb9be317

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/literature-mining/proposal.md

- Source: openspec/changes/literature-mining/proposal.md
- Lines: 1-31
- SHA256: 7cc06dc358a0ff26a065fe9173b3f284ed09d8031078bc24136dfc168cf12407

```md
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

```

## openspec/changes/literature-mining/design.md

- Source: openspec/changes/literature-mining/design.md
- Lines: 1-44
- SHA256: dd1aad9fa8915d9d46621130648d917f341001f5ef33e3b8b448ddd676c9d51d

```md
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

```

## openspec/changes/literature-mining/tasks.md

- Source: openspec/changes/literature-mining/tasks.md
- Lines: 1-37
- SHA256: 641a34152dd45a44aeb5aba46201155dcc8d00e449d85e1cb8c89b73322deb35

```md
## 1. Literature search (unified, mockable)

- [ ] 1.1 Define the unified paper-result schema (source, external id/DOI, title, authors, year, venue, abstract, url) and a `SearchClient` interface with an injectable HTTP boundary
- [ ] 1.2 Implement the Semantic Scholar adapter (search + lookup-by-id/DOI) against the mockable boundary
- [ ] 1.3 Implement the arXiv adapter (Atom API search + id lookup)
- [ ] 1.4 Implement the PubMed adapter (E-utilities esearch/efetch; email/tool params)
- [ ] 1.5 Multi-source dispatch (one/several/all), per-source rate-limit backoff, and graceful degradation when one source fails (return others + a recorded note)
- [ ] 1.6 Offline tests with recorded/mocked responses (no network) + opt-in `@pytest.mark.live` tests gated on credentials

## 2. Fact extraction (Qwen-driven, evidence-grounded)

- [ ] 2.1 Define the structured fact schema (claim, source ref, evidence span, entities?, confidence) — no fact without source + evidence span
- [ ] 2.2 Implement Qwen-driven extraction from a paper's available text (abstract/full text) via the foundation provider, bounded by a per-run cap
- [ ] 2.3 Drop ungrounded/out-of-context output (claim with no traceable span) before it enters the fact base
- [ ] 2.4 Unit tests: extraction returns grounded facts (mocked provider, no network); ungrounded claim dropped; per-run bound respected

## 3. Citation verification (4-layer anti-fabrication)

- [ ] 3.1 Layer 1 (format) + Layer 2 (existence: DOI/title resolves via API) against the mockable boundary
- [ ] 3.2 Layer 3 (metadata match: authors/year/venue within tolerance)
- [ ] 3.3 Layer 4 (content-grounding: cited claim supported by the resolved paper's text) — method + threshold from the design phase (abstract-level default; full-text for PMC-OA)
- [ ] 3.4 Record each citation's pass/fail layer; reject fabricated (fail L2) and misattributed (fail L4); never store unverified as verified
- [ ] 3.5 Tests: fully-valid passes all 4; hallucinated DOI rejected at L2; real-paper-but-misattributed rejected at L4; re-run does not re-verify already-verified

## 4. Fact base (persistence + query) + foundation integration

- [ ] 4.1 Persist verified facts as idea-tree nodes (via the state layer) AND a queryable JSON fact store; reject/unverified facts are not persisted
- [ ] 4.2 Implement the LitMinerExecutor (search→extract→verify→record) over the foundation Executor seam; record-before-decide + atomic persist
- [ ] 4.3 Register `search`/`fetch`/`extract`/`verify` tools in the ToolRegistry for agent-driven use
- [ ] 4.4 Stable fact-base query interface (retrieve-all, filter by source/topic) not coupled to idea-tree internals
- [ ] 4.5 Resumability: re-run skips already-processed papers + already-verified citations (keyed by external id); no API re-spend or duplicates

## 5. End-to-end, tests & docs

- [ ] 5.1 Offline integration test: coordinator dispatches the LitMinerExecutor against a mocked SearchClient + mocked Qwen provider → ≥1 verified fact persisted to idea-tree + fact store; a hallucinated citation rejected
- [ ] 5.2 Opt-in `@pytest.mark.live` e2e: real search + real Qwen extraction + real verification over a small neuro topic (skip-verified without credentials)
- [ ] 5.3 Coverage gate (≥80% on new code, excl. vendored) + ruff clean + README section (sources, credentials/env, fact-base output, live-tests-need-keys note)

```

## openspec/changes/literature-mining/specs/citation-verification/spec.md

- Source: openspec/changes/literature-mining/specs/citation-verification/spec.md
- Lines: 1-29
- SHA256: 5cf93a26bf220724a45e714e7b1b4faef10c7788e5af3c1e0c6af129f9c3654a

```md
## ADDED Requirements

### Requirement: Four-layer citation verification
The system SHALL verify each citation through four ordered layers: (1) **format** — the citation is well-formed and has a resolvable identifier (DOI or title+author); (2) **existence** — the identifier resolves to a real paper via an authoritative API; (3) **metadata match** — the citation's authors/year/venue match the resolved paper within tolerance; (4) **content-grounding** — the cited claim is supported by the resolved paper's available text (abstract/full text). A citation SHALL carry the layer at which it passed or failed.

#### Scenario: A fully valid citation passes all four layers
- **WHEN** a citation with a correct DOI, matching metadata, and a claim grounded in the source is verified
- **THEN** it passes all four layers and is marked verified

### Requirement: Reject fabricated citations (anti-fabrication)
The system SHALL reject any citation that fails an early layer. A hallucinated citation (nonexistent DOI/paper) SHALL be rejected at the existence layer and SHALL NOT be stored in the fact base.

#### Scenario: Hallucinated citation is rejected at existence
- **WHEN** a citation references a DOI/paper that does not resolve via the API
- **THEN** it fails at layer 2 (existence), is rejected, and does not enter the fact base

### Requirement: Catch misattributed claims (content-grounding)
The system SHALL flag/reject a citation whose paper is real and metadata-correct but whose cited claim is NOT supported by the source text.

#### Scenario: Misattributed claim caught at content-grounding
- **WHEN** a citation resolves to a real, metadata-matching paper but the claim it is used to support does not appear in that paper's text
- **THEN** it fails at layer 4 (content-grounding) and is rejected or flagged unverified, never stored as a verified fact

### Requirement: Verification is offline-testable and resumable
The verifier SHALL run against a mockable API boundary (offline default suite) and SHALL record each citation's verification status so a re-run does not re-verify already-verified citations.

#### Scenario: Already-verified citation is not re-checked on re-run
- **WHEN** verification is re-run over a fact base containing already-verified citations
- **THEN** those citations are not re-verified against the API, and only new/unverified ones are checked

```

## openspec/changes/literature-mining/specs/fact-base/spec.md

- Source: openspec/changes/literature-mining/specs/fact-base/spec.md
- Lines: 1-33
- SHA256: 2cd2a1bf9615784c6eb10ca89e3095b2bc2fc375d3445b5bb79f45ebbdb00281

```md
## ADDED Requirements

### Requirement: Verified-fact persistence (idea-tree + fact store)
The system SHALL persist only verified facts, as both idea-tree nodes (via the foundation's state layer) and a queryable JSON fact store. Each stored fact SHALL retain its claim, source reference, evidence span, and verification status. An unverified/rejected fact SHALL NOT be persisted to the fact base.

#### Scenario: Verified fact is persisted to both stores
- **WHEN** a fact whose citation passed verification is recorded
- **THEN** it appears as an idea-tree node AND in the JSON fact store, retaining its claim/source/evidence/verification-status

#### Scenario: Rejected fact is not persisted
- **WHEN** a fact whose citation failed verification is processed
- **THEN** it is not written to the idea-tree or the fact store

### Requirement: Lit-miner specialist executor + tools integration
The system SHALL expose the capability through the foundation loop: a lit-miner specialist executor the coordinator can dispatch (search → extract → verify → record), AND search/fetch/extract/verify tools registered in the ToolRegistry so an agent can invoke them. Recording a verified fact SHALL persist it before the coordinator's next decision (consistent with the foundation's record-before-decide invariant).

#### Scenario: Coordinator dispatches the lit-miner and a verified fact is recorded
- **WHEN** the coordinator dispatches the lit-miner executor for a topic
- **THEN** it searches, extracts, verifies, and records at least one verified fact into the fact base before the coordinator's next decision

### Requirement: Resumable mining
The system SHALL make mining resumable: re-running over an existing run continues from persisted state without re-doing completed search/extract/verify work for already-processed papers/facts.

#### Scenario: Resume continues without re-processing done work
- **WHEN** a mining run is interrupted after persisting some verified facts and is then resumed
- **THEN** it continues with new papers/facts and does not re-verify or duplicate the already-persisted verified facts

### Requirement: Queryable fact base
The system SHALL let the (future) hypothesis-engine query the fact base — at minimum, retrieve all verified facts and filter by source or topic — through a stable interface, without depending on idea-tree internals.

#### Scenario: Facts are retrievable for downstream use
- **WHEN** a consumer requests the verified facts for a topic
- **THEN** it receives the structured verified facts (claim + source + evidence + status) from the fact store via the stable query interface

```

## openspec/changes/literature-mining/specs/fact-extraction/spec.md

- Source: openspec/changes/literature-mining/specs/fact-extraction/spec.md
- Lines: 1-26
- SHA256: f4b3e33d0edd353e56d69b9e3989fed4dd7ad2300b4bd2a097bb390aaaba5172

```md
## ADDED Requirements

### Requirement: Structured scientific fact schema
The system SHALL represent an extracted fact as a structured record containing at least: a claim statement, the source paper reference (external id/DOI), an evidence span (the supporting quote/text from the source), optional entities, and a confidence value. A fact without a source reference and an evidence span SHALL NOT be produced.

#### Scenario: Extracted fact carries its evidence
- **WHEN** a fact is extracted from a paper
- **THEN** the fact record includes the claim, the source paper id, and the exact supporting evidence span, so the claim is never left un-sourced or out of context

### Requirement: Qwen-driven extraction from retrieved papers
The system SHALL use the foundation's Qwen provider to extract facts from a retrieved paper's available text (abstract or fuller text when available), producing zero or more structured facts per paper. Extraction SHALL be bounded (a cap on papers/facts per run) to respect the compute budget.

#### Scenario: Facts extracted from a paper's text
- **WHEN** extraction runs over a retrieved paper with an abstract
- **THEN** it returns structured facts whose evidence spans are substrings/quotes traceable to that paper's text, and a paper with no extractable claim yields zero facts (not a fabricated one)

#### Scenario: Extraction respects the per-run bound
- **WHEN** a run configures a maximum number of papers/facts
- **THEN** extraction stops at that bound rather than processing the entire corpus, keeping cost bounded

### Requirement: No out-of-context or unsupported facts
The system SHALL NOT emit a fact whose evidence span does not come from the cited source. Extraction output that lacks a grounding span for its claim SHALL be dropped before it enters the fact base.

#### Scenario: Ungrounded extraction is dropped
- **WHEN** the extractor proposes a claim it cannot tie to a span in the source text
- **THEN** that claim is discarded and does not become a stored fact

```

## openspec/changes/literature-mining/specs/literature-search/spec.md

- Source: openspec/changes/literature-mining/specs/literature-search/spec.md
- Lines: 1-30
- SHA256: cddb72ec27bd0f46278fc82f754621b77a45d0bba55035ba7664ec77e11a2be0

```md
## ADDED Requirements

### Requirement: Unified multi-source search
The system SHALL search scholarly literature across Semantic Scholar, arXiv, and PubMed behind a single interface, returning results in a unified schema (at least: source, external id/DOI, title, authors, year, venue, abstract, url). A query SHALL be dispatchable to one, several, or all configured sources.

#### Scenario: Query returns unified results from multiple sources
- **WHEN** a topic query is issued to the configured sources
- **THEN** results come back in the unified schema regardless of which source produced them, each tagged with its originating source and external id

#### Scenario: A single source can be targeted
- **WHEN** the caller restricts a query to one source (e.g. PubMed only)
- **THEN** only that source is queried and results are returned in the unified schema

### Requirement: Mockable client boundary (offline-by-default)
The system SHALL isolate all network access behind a client boundary that can be mocked, so the default test suite runs with NO network. Live API access SHALL be exercised only by opt-in tests gated on the presence of the relevant credentials/config.

#### Scenario: Default suite runs offline
- **WHEN** the default test suite runs without network or API keys
- **THEN** search behavior is verified against mocked/recorded responses and no live HTTP call is made

#### Scenario: Live tests are opt-in
- **WHEN** live tests run with the required credentials present
- **THEN** they hit the real APIs; without credentials they are skipped cleanly, not failed

### Requirement: Rate-limit and error resilience
The system SHALL respect each source's rate limits (backoff on 429/throttle) and SHALL surface a typed, non-crashing error when a source is unavailable, so one failing source does not abort a multi-source query.

#### Scenario: One source failing does not abort the query
- **WHEN** one configured source errors or rate-limits while others succeed
- **THEN** the query returns the available results plus a recorded note about the failed source, without raising to the caller

```
