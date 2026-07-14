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
