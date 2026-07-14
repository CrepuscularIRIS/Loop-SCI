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
