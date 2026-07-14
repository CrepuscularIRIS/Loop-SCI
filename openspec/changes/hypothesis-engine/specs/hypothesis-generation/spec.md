## ADDED Requirements

### Requirement: Gap mining from the verified fact base
The system SHALL mine candidate research gaps from the verified fact base (produced by literature-mining) and represent each as a problem card with the fields `{Q, WHY-NOW, PROBE/KILL, STAKES}`. Gap mining SHALL read facts through the fact base's stable query interface and SHALL NOT fetch new literature or read idea-tree internals directly.

#### Scenario: Gap cards derived from facts
- **WHEN** the engine is given a topic whose fact base contains verified facts (including at least one pair of tension/contradiction between facts)
- **THEN** it produces one or more problem cards, each carrying a question `Q`, a `WHY-NOW`, a `PROBE/KILL`, and `STAKES`, and each card references the fact ids it was derived from

#### Scenario: No fabricated gaps
- **WHEN** a proposed gap card cites supporting facts
- **THEN** every cited fact id resolves to a fact present in the fact base, and a card citing a non-existent fact is dropped before ranking

### Requirement: Logic-driven hypothesis generation
The system SHALL generate candidate hypotheses from a problem card using both inductive and deductive reasoning over the grounding facts, via the Qwen provider. Each hypothesis SHALL carry `{MECHANISM, KILL, BRACKET, DIFF-PREDICTION}` and SHALL be recorded as an idea-tree node descending from the relevant fact node(s), with rival framings recorded as sibling nodes.

#### Scenario: Hypotheses with mechanism and discriminating prediction
- **WHEN** the engine forges hypotheses from a problem card
- **THEN** each candidate node states a mechanism, an explicit kill condition, a plausibility bracket, and a diff-prediction that would distinguish it from the status quo, and at least one rival-frame sibling is produced

#### Scenario: Relabeling is discarded
- **WHEN** a candidate's diff-prediction does not survive the "strip-the-new-words" test (removing the novel terminology leaves no distinct prediction)
- **THEN** the candidate is classified as relabeling and discarded, not recorded as a live hypothesis

### Requirement: Bounded generation
The system SHALL bound generation by a per-run cap (cards × candidates) so that Qwen usage stays within the configured budget.

#### Scenario: Per-run bound respected
- **WHEN** generation runs with a configured cap
- **THEN** the number of problem cards and candidate hypotheses produced does not exceed the cap, and generation stops cleanly when the cap is reached
