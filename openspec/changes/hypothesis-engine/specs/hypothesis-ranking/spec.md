## ADDED Requirements

### Requirement: Novelty and self-consistency scoring
The system SHALL score each surviving hypothesis on at least novelty and self-consistency, recording the scores on the idea-tree node (`Node.score` and a subscore map in `Node.refs`). Scoring SHALL be reproducible offline with a mock provider.

#### Scenario: Scores recorded on the node
- **WHEN** a hypothesis passes critique
- **THEN** its node carries a numeric overall score plus a subscore map including `novelty` and `self_consistency`, persisted with the tree

#### Scenario: Novelty measured against the fact base
- **WHEN** two candidates are scored, one restating an existing verified fact and one proposing a mechanism absent from the fact base
- **THEN** the mechanism-proposing candidate receives the higher novelty subscore

### Requirement: Stable ranked-hypothesis query interface
The system SHALL expose a stable interface returning hypotheses ranked by score (retrieve-all ranked, filter by topic/status) that the downstream plan-assembler consumes without touching idea-tree internals. Each returned item SHALL carry problem, derivation chain with evidence grades, diff-prediction, novelty and self-consistency scores, and grounding fact/reference ids.

#### Scenario: Downstream consumes ranked output
- **WHEN** a consumer requests the ranked hypotheses for a topic
- **THEN** it receives them ordered best-first with all required fields, and does not need to import or traverse idea-tree node structures

### Requirement: Specialist executor and tools integration
The system SHALL provide a `HypothesisExecutor` over the foundation Executor seam (search-free: it consumes the fact base, generates, critiques, iterates, and records) and SHALL register `generate` / `critique` / `rank` tools in the ToolRegistry for agent-driven use. Integration SHALL require no change to the coordinator interface and SHALL keep `auto_git` disabled.

#### Scenario: Executor runs the loop end-to-end offline
- **WHEN** the coordinator dispatches the `HypothesisExecutor` for a topic against a mock provider and a populated fact base
- **THEN** it produces at least one accepted, scored hypothesis recorded in the idea-tree and retrievable through the ranked query interface, with no network calls and no git operations

#### Scenario: Tools wrap the same pipeline
- **WHEN** the `generate` / `critique` / `rank` tools are invoked through the registry
- **THEN** they exercise the same underlying pipeline with injected dependencies and return structured results (or structured errors), offline
