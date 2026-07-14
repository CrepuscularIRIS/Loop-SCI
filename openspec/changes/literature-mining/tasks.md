## 1. Literature search (unified, mockable)

- [x] 1.1 Define the unified paper-result schema (source, external id/DOI, title, authors, year, venue, abstract, url) and a `SearchClient` interface with an injectable HTTP boundary
- [x] 1.2 Implement the Semantic Scholar adapter (search + lookup-by-id/DOI) against the mockable boundary
- [x] 1.3 Implement the arXiv adapter (Atom API search + id lookup)
- [x] 1.4 Implement the PubMed adapter (E-utilities esearch/efetch; email/tool params)
- [x] 1.5 Multi-source dispatch (one/several/all), per-source rate-limit backoff, and graceful degradation when one source fails (return others + a recorded note)
- [x] 1.6 Offline tests with recorded/mocked responses (no network) + opt-in `@pytest.mark.live` tests gated on credentials

## 2. Fact extraction (Qwen-driven, evidence-grounded)

- [x] 2.1 Define the structured fact schema (claim, source ref, evidence span, entities?, confidence) — no fact without source + evidence span
- [x] 2.2 Implement Qwen-driven extraction from a paper's available text (abstract/full text) via the foundation provider, bounded by a per-run cap
- [x] 2.3 Drop ungrounded/out-of-context output (claim with no traceable span) before it enters the fact base
- [x] 2.4 Unit tests: extraction returns grounded facts (mocked provider, no network); ungrounded claim dropped; per-run bound respected

## 3. Citation verification (4-layer anti-fabrication)

- [x] 3.1 Layer 1 (format) + Layer 2 (existence: DOI/title resolves via API) against the mockable boundary
- [x] 3.2 Layer 3 (metadata match: authors/year/venue within tolerance)
- [x] 3.3 Layer 4 (content-grounding: cited claim supported by the resolved paper's text) — method + threshold from the design phase (abstract-level default; full-text for PMC-OA)
- [x] 3.4 Record each citation's pass/fail layer; reject fabricated (fail L2) and misattributed (fail L4); never store unverified as verified
- [x] 3.5 Tests: fully-valid passes all 4; hallucinated DOI rejected at L2; real-paper-but-misattributed rejected at L4; re-run does not re-verify already-verified

## 4. Fact base (persistence + query) + foundation integration

- [x] 4.1 Persist verified facts as idea-tree nodes (via the state layer) AND a queryable JSON fact store; reject/unverified facts are not persisted
- [x] 4.2 Implement the LitMinerExecutor (search→extract→verify→record) over the foundation Executor seam; record-before-decide + atomic persist
- [x] 4.3 Register `search`/`fetch`/`extract`/`verify` tools in the ToolRegistry for agent-driven use
- [x] 4.4 Stable fact-base query interface (retrieve-all, filter by source/topic) not coupled to idea-tree internals
- [x] 4.5 Resumability: re-run skips already-processed papers + already-verified citations (keyed by external id); no API re-spend or duplicates

## 5. End-to-end, tests & docs

- [x] 5.1 Offline integration test: coordinator dispatches the LitMinerExecutor against a mocked SearchClient + mocked Qwen provider → ≥1 verified fact persisted to idea-tree + fact store; a hallucinated citation rejected
- [x] 5.2 Opt-in `@pytest.mark.live` e2e: real search + real Qwen extraction + real verification over a small neuro topic (skip-verified without credentials)
- [x] 5.3 Coverage gate (≥80% on new code, excl. vendored) + ruff clean + README section (sources, credentials/env, fact-base output, live-tests-need-keys note)
