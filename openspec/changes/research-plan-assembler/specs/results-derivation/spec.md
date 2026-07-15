## ADDED Requirements

### Requirement: Results by formula-derivation with evidence-graded steps
The system SHALL produce the Results field by **formula-derivation** — an analytical feasibility argument (an expected bound, effect size, or derivation showing the experiment is feasible within a stated range) derived from the hypothesis mechanism and diff-prediction. Each derivation step SHALL carry an evidence grade drawn from `[paper] | [inferred] | [guess]`, consistent with change #4. The system SHALL NOT execute any experiment, run any command, or fabricate a measured result.

#### Scenario: Formula-derivation Results with graded steps
- **WHEN** the assembler derives the Results field for a hypothesis with a mechanism and a diff-prediction
- **THEN** it produces an analytical feasibility argument whose steps are each annotated `[paper]`, `[inferred]`, or `[guess]`, and it does not report any executed-experiment measurement

#### Scenario: No execution path
- **WHEN** the Results field is produced
- **THEN** no experiment is run and no shell/eval command is invoked; the feasibility claim is derivational only

### Requirement: No ungrounded load-bearing result claim
The system SHALL NOT allow a load-bearing step of the Results derivation to rest solely on a `[guess]`. A feasibility conclusion whose supporting chain is load-bearing on an ungrounded step SHALL be downgraded (marked non-final / low-confidence), never presented as an established result.

#### Scenario: Load-bearing guess downgrades the result
- **WHEN** the Results derivation's decisive step is graded `[guess]` with no `[paper]`/`[inferred]` support
- **THEN** the Results field is marked as low-confidence / non-final rather than asserting feasibility as established
