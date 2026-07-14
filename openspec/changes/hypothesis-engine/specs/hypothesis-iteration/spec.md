## ADDED Requirements

### Requirement: Kill metabolism
The system SHALL convert each killed (DOWN-verdicted or falsified) hypothesis into at least one of a CONSTRAINT, a CANDIDATE, or a REGION-CLOSE, and SHALL feed that outcome back into ranking so that the open hypothesis queue is reweighted. A pruned hypothesis node SHALL retain its kill reason.

#### Scenario: A kill produces a constraint that reweights the queue
- **WHEN** a candidate is killed during critique
- **THEN** the engine records a CONSTRAINT / CANDIDATE / REGION-CLOSE derived from the kill, the killed node is pruned with its reason retained, and the outcome updates the ranking of remaining open hypotheses

#### Scenario: Region-close halts dead-space re-exploration
- **WHEN** two or more mechanisms are killed by the same root cause
- **THEN** the engine marks that region closed and does not generate further candidates in the closed region within the run

### Requirement: Bounded multi-round iteration with stall detection
The system SHALL iterate generation → critique → metabolism over multiple rounds, tracking new findings per round. It SHALL trigger a structural pivot when the stall count reaches 2 and escalate (stop nudging, surface for human attention) when the stall count reaches 4. Iteration SHALL terminate rather than loop indefinitely.

#### Scenario: Pivot on stall
- **WHEN** two consecutive rounds add no new accepted findings
- **THEN** the engine performs a structural pivot (changes frame / objective / grounding) rather than repeating the same generation

#### Scenario: Escalate on persistent stall
- **WHEN** four consecutive rounds add no new accepted findings
- **THEN** the engine stops iterating and surfaces the run for human attention instead of continuing to spend budget

### Requirement: Resumable iteration
The system SHALL distinguish a `done` (self-reported) phase from an `accepted` (jury-verdicted, with a durable verdict id) phase, and SHALL persist a recovery anchor so a resumed run continues without re-critiquing already-accepted nodes or re-spending on completed work.

#### Scenario: Resume skips accepted nodes
- **WHEN** a run is resumed after interruption
- **THEN** hypotheses already marked accepted (with a verdict id) are not re-critiqued, and iteration continues from the recovery anchor without duplicating work
