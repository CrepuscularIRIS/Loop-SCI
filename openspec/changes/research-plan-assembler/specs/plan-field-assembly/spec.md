## ADDED Requirements

### Requirement: Domain-parameterized field assembly from a ranked hypothesis
The system SHALL assemble the reasoning/context fields of the 《科学假设与研究计划》 — Problem Statement, Rationale, Technical Details, Paper Title, Abstract, Methods, Experiments — from a single ranked hypothesis (change #4 `RankedHypothesis`) plus the verified fact base, via the Qwen provider. The scientific **domain SHALL be a runtime parameter** (e.g. natural-science or humanities/social-science topic), not hard-coded; the same assembler SHALL produce a plan for any domain without code change. Assembly SHALL be reproducible offline with a mock provider.

#### Scenario: Twelve-field reasoning fields produced from a hypothesis
- **WHEN** the assembler is given a ranked hypothesis (problem, mechanism, evidence-graded derivation chain, diff-prediction, grounding fact-ids) and a target domain
- **THEN** it produces non-empty Problem Statement, Rationale, Technical Details, Paper Title, Abstract, Methods, and Experiments fields, where Rationale reflects the hypothesis's derivation chain and Experiments contains both baseline comparison and evaluation metrics

#### Scenario: Domain is parameterized, not hard-coded
- **WHEN** the assembler is invoked twice with the same hypothesis-shaped input but two different domain parameters (e.g. a neuroscience topic and a non-neuroscience topic)
- **THEN** both runs succeed and produce a full field set with no code change, and the domain parameter is reflected in the assembled content

### Requirement: Datasets, Source, and Target grounded as fact-base candidates
The system SHALL populate the Datasets, Source (the historical data the hypothesis derivation rests on), and Target (the to-be-collected data features the validation experiment needs) fields from the hypothesis's grounding facts, presented as **candidates** carrying their source references. The assembler SHALL NOT fabricate a dataset with no basis in the fact base; real dataset resolution is out of scope (deferred to the domain pack).

#### Scenario: Dataset/Source/Target candidates trace to grounding facts
- **WHEN** a hypothesis grounded in verified facts is assembled
- **THEN** the Datasets, Source, and Target fields reference dataset/data candidates drawn from those grounding facts (with their source references), and each candidate is marked as a candidate rather than a resolved dataset

#### Scenario: No fabricated dataset when grounding is absent
- **WHEN** a hypothesis has no grounding fact that mentions a dataset
- **THEN** the Datasets/Source/Target fields are populated conservatively (candidate/pending) without inventing a concrete dataset that does not appear in the fact base
