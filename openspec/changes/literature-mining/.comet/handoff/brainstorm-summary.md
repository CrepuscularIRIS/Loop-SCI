# Brainstorm Summary

- Change: literature-mining
- Date: 2026-07-14

## Confirmed Technical Approach

Package `loop_sci/literature/` on the shipped foundation: search/ (SearchClient + injectable HTTP boundary; Semantic Scholar / arXiv / PubMed adapters → unified PaperResult; dispatch with backoff + graceful degrade) · extract/ (Fact schema; Qwen-driven, evidence-span-required, bounded) · verify/ (4-layer citation pipeline; grounding.py hybrid) · factbase/ (JSON store + query iface; persist verified fact → idea-tree node) · executor.py (LitMinerExecutor) · tools.py (search/fetch/extract/verify for ToolRegistry).

Confirmed design decisions:
- **Content-grounding (L4): HYBRID** — cheap lexical/keyword-overlap pre-filter decides obvious pass/fail; Qwen judge (cheap tier) adjudicates only borderline; record grounding confidence + which path decided.
- **Grounding scope:** abstract by default; full-text when freely available (PMC-OA / arXiv); record scope (abstract|full_text) per fact.
- **Fact→idea-tree:** per-fact node under a per-paper parent under the topic root; payload in the foundation's persisted `Node.refs` dict (NO vendored edits).
- **Fact schema:** claim · source_ref (source+id/DOI) · evidence_span · entities? · confidence · grounding_scope · verification (layer reached + status). No fact without source_ref + evidence_span.
- **Verification 4-layer, short-circuit:** format → existence (API resolve) → metadata match (authors/year/venue tolerance) → content-grounding (hybrid). Hallucinated→reject L2; misattributed→reject L4; record pass/fail layer.
- **Fact base:** verified facts only → idea-tree nodes + JSON fact store with stable query iface (retrieve-all / filter by source/topic); hypothesis-engine doesn't touch idea-tree internals.
- **Integration:** LitMinerExecutor (foundation Executor seam) runs search→extract→verify→record with record-before-decide + atomic persist; tools registered in ToolRegistry.
- **Resumability:** key by paper external-id + fact-id; skip already-processed papers + already-verified citations; within-run response cache.

## Key Trade-offs and Risks

- API keys/rate limits (Semantic Scholar optional key; PubMed E-utilities email/tool; arXiv public) → mockable client + backoff + opt-in live tests.
- Qwen-judge cost (L4) → lexical pre-filter + per-run bounds + cheap tier keep it within 300¥.
- Abstract-only grounding can miss full-text nuance → record grounding_scope per fact so downstream weighs it.
- Fact payload lives in the foundation's persisted `Node.refs` (subclass field from change #1) — no vendored edits.

## Testing Strategy

Offline-by-default: mock SearchClient (recorded responses) + mock Qwen provider for all unit + integration tests, incl. anti-fabrication (hallucinated→L2 reject; misattributed→L4 reject; only-verified-persisted; resume-no-reverify). Opt-in `@pytest.mark.live` e2e over a small neuro topic (skip without credentials). ≥80% coverage on new code (excl vendored), ruff clean.

## Spec Patches

None — the 4 delta specs are complete; the Design Doc refines the Fact schema (incl. grounding_scope) without changing any acceptance scenario.
