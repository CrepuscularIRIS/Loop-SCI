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
