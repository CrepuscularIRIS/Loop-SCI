## ADDED Requirements

### Requirement: Real-only References via the verification pipeline
The system SHALL produce the References field as a list of **real** citations only, by routing every candidate reference through the literature-mining verification pipeline (change #2 `VerificationPipeline`). A candidate reference that does not verify SHALL be excluded from the References field (or explicitly flagged as unverified), enforcing the 严禁虚构 constraint. Verification SHALL be reproducible offline with mocked seams (no network in the default test suite).

#### Scenario: Only verified references appear
- **WHEN** the assembler collects candidate references (from the hypothesis grounding facts and any provider-proposed citations) and routes them through the verification pipeline
- **THEN** the References field contains only citations that passed verification, each carrying its source reference (source/id/DOI), and no unverifiable citation is presented as real

#### Scenario: Fabricated citation dropped
- **WHEN** a provider-proposed reference cannot be verified (fails existence/metadata/grounding)
- **THEN** it is excluded from the References field (or flagged as unverified), and it never appears as a real reference in the assembled plan

### Requirement: Grounding facts seed the reference list
The system SHALL seed the References field from the hypothesis's grounding facts' source references — which are already verified facts from the fact base — so that a hypothesis grounded in real literature yields real references without introducing new unverified citations.

#### Scenario: Grounded hypothesis yields real references
- **WHEN** a hypothesis grounded in verified facts is assembled
- **THEN** the References field includes the source references of those grounding facts, and the reference count is at least the number of distinct grounding sources
