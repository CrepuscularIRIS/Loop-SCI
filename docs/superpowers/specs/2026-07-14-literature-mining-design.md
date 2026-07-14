---
comet_change: literature-mining
role: technical-design
canonical_spec: openspec
---

# literature-mining — Technical Design

Deep refinement of the open-phase `design.md` for change #2 of Loop-SCI, built on the shipped `arbor-qwen-skeleton` foundation. Adds the first scored pipeline capability (能力项一): topic → real literature → structured facts → 4-layer-verified citations → a verified fact base the hypothesis-engine consumes. Upstream source of truth is the OpenSpec change (proposal / design / 4 specs / tasks). No Spec Patches.

## 1. Package layout

```
loop_sci/literature/
  search/
    schema.py            # PaperResult (source, external_id/doi, title, authors, year, venue, abstract, url)
    client.py            # SearchClient protocol + injectable HTTP boundary (mockable)
    semantic_scholar.py  # adapter → PaperResult
    arxiv.py             # adapter (Atom API) → PaperResult
    pubmed.py            # adapter (E-utilities esearch/efetch) → PaperResult
    dispatch.py          # multi-source fan-out, per-source backoff, graceful degrade
  extract/
    fact.py              # Fact dataclass (schema below)
    extractor.py         # Qwen-driven extraction (evidence-required, bounded)
  verify/
    citation.py          # 4-layer pipeline (format → existence → metadata → grounding)
    grounding.py         # hybrid: lexical pre-filter → Qwen judge (borderline only)
  factbase/
    store.py             # JSON fact store + stable query interface
    persist.py           # verified Fact → idea-tree node (per-fact under per-paper) + store
  executor.py            # LitMinerExecutor (search→extract→verify→record)
  tools.py               # search/fetch/extract/verify tools for the ToolRegistry
tests/ (unit + integration offline; tests/live/ opt-in)
```

## 2. Literature search (`literature-search`)

**`SearchClient`** wraps an **injectable HTTP transport** so all network access is mockable: the default suite runs on recorded/fixture responses, and `@pytest.mark.live` tests inject a real transport. Each adapter (`semantic_scholar` REST, `arxiv` Atom, `pubmed` E-utilities esearch→efetch) maps its raw response to a unified **`PaperResult`**. `dispatch(query, sources)` fans out to the configured sources concurrently, applies per-source **rate-limit backoff** (429/throttle), and **degrades gracefully** — one source erroring returns the others plus a recorded note, never raising to the caller. PubMed adapter carries the required `tool`/`email` params; Semantic Scholar uses an optional key from config; arXiv is keyless.

## 3. Fact extraction (`fact-extraction`)

**`Fact`** = `claim · source_ref (source + external_id/doi) · evidence_span (verbatim quote from the source) · entities? · confidence · grounding_scope (abstract|full_text) · verification (layer reached + status)`. Constructing a `Fact` without `source_ref` **and** `evidence_span` is impossible (enforced in the dataclass). `extractor.py` reuses the foundation Qwen provider: it prompts for structured facts with a **mandatory evidence span**, is **bounded** by a per-run cap (papers × facts) to respect the 300¥ budget, and **drops** any proposed claim whose evidence span is not traceable to the source text before it reaches the fact base.

## 4. Citation verification (`citation-verification`)

An ordered, **short-circuiting** pipeline; each citation records the layer it reached and the verdict:
- **L1 format** — well-formed, has a resolvable identifier (DOI or title+author).
- **L2 existence** — the identifier resolves to a real paper via the API (Semantic Scholar / PubMed / arXiv). A hallucinated DOI/paper fails here → **rejected**.
- **L3 metadata match** — authors/year/venue match the resolved paper within tolerance (year exact; author surname overlap; venue fuzzy).
- **L4 content-grounding** — the cited claim is supported by the resolved paper's text. **Hybrid** (`grounding.py`): a cheap **lexical/keyword-overlap** score decides clear pass/fail; only **borderline** claims go to a **Qwen entailment judge** (cheap tier) over the source text. Scope = **abstract by default**, **full-text** for the PMC-OA subset / arXiv when freely available; the `grounding_scope` is recorded on the fact. A real, metadata-matching paper whose claim is absent from the text fails here → **rejected/flagged**, never stored as verified.

Verification runs against the same mockable API boundary and records status so a re-run does not re-verify already-verified citations.

## 5. Fact base (`fact-base`)

Only **verified** facts persist, to **two** places:
- **Idea-tree** (foundation state layer): topic **root** → **paper** nodes → **fact** nodes; the `Fact` payload lives in the foundation's persisted **`Node.refs`** dict (the subclass field added in change #1 — **no vendored edits**). Recording honors the foundation's **record-before-decide + atomic persist** invariants.
- **JSON fact store** (`store.py`): a queryable store exposing a **stable interface** (retrieve-all, filter by source/topic) so the hypothesis-engine consumes facts without touching idea-tree internals.

A rejected/unverified fact is written to neither.

## 6. Integration & resumability (`fact-base`)

**`LitMinerExecutor`** (a specialization over the foundation Executor seam) runs **search → extract → verify → record** for a coordinator-dispatched topic and returns a structured `ExecutorResult`. Additionally, **`search`/`fetch`/`extract`/`verify` tools** register in the ToolRegistry for agent-driven use. **Resumability**: keyed by paper **external-id** and **fact-id** — a resumed run skips already-processed papers and already-verified citations (no API re-spend, no duplicates), with a **within-run response cache** to avoid re-hitting an API for the same id.

## 7. Testing strategy

- **Unit (offline):** search adapters map fixtures → PaperResult; dispatch degrades on one-source failure; extractor returns grounded facts + drops ungrounded (mock provider); the 4 verification layers incl. hybrid grounding (lexical + mock-Qwen judge); fact store persist/query + reject-not-persisted; resume-no-reverify.
- **Integration (offline):** coordinator dispatches `LitMinerExecutor` against a **mock SearchClient + mock Qwen provider** → ≥1 verified fact in idea-tree + store; a **hallucinated citation rejected at L2**; a **misattributed claim rejected at L4**.
- **Live (opt-in `@pytest.mark.live`):** real multi-source search + real Qwen extraction + real verification over a small neuro topic; skip cleanly without credentials.
- Coverage ≥80% on new `loop_sci/literature/` code (vendored excluded); ruff clean; README section (sources, credentials/env, fact-base output, live-needs-keys).

## 8. Risks / trade-offs

- **[API keys + rate limits]** → mockable client (offline CI), backoff, opt-in live; PubMed email/tool + optional Semantic Scholar key from config.
- **[Qwen-judge cost at L4]** → lexical pre-filter routes only borderline claims to Qwen; per-run bounds; cheap tier; within-run cache.
- **[Abstract-only grounding misses full-text nuance]** → `grounding_scope` recorded per fact so downstream weighs abstract-grounded vs full-text-grounded facts.
- **[Fact→node payload]** → lives in the foundation's persisted `Node.refs` dict; no vendored edits; per-fact granularity keeps hypothesis-engine traversal simple.
- **[Multi-source citation identity]** → the same paper may appear across sources; dedup by DOI/normalized-title when persisting to avoid duplicate fact nodes.

## 9. Open questions (resolved during build)

- Exact lexical-vs-Qwen threshold for the hybrid grounding router — tuned with a cheap probe in the first verify task.
- PubMed full-text availability handling (PMC-OA fetch path) vs abstract fallback — settled when the PubMed adapter lands.
- Whether a Semantic Scholar key / PubMed email are available for live tests (offline path works regardless).
- Local-corpus (user PDFs) ingestion — deferred; the three APIs cover the core path.
