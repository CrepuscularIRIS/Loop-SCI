## ADDED Requirements

### Requirement: Derivation contract before critique
The system SHALL freeze a derivation contract for each candidate hypothesis before adversarial critique, containing at least HYPOTHESIS, LATENT-ROOT, ACCEPT-IF, and KILL-IF fields. The contract SHALL be plan-grade: ACCEPT-IF / KILL-IF are stated as derivation tripwires (logical or formula-derived conditions), not executable run commands.

#### Scenario: Contract frozen before verdict
- **WHEN** a candidate hypothesis enters critique
- **THEN** a derivation contract with HYPOTHESIS, LATENT-ROOT, ACCEPT-IF, and KILL-IF is recorded on the node before any verdict is produced

### Requirement: Cross-model adversarial jury (never self-acquit)
The system SHALL adjudicate each candidate through an adversarial jury in which the reviewer is a distinct model configuration from the generator — a different Qwen tier with a KILL-biased adversarial persona and varied sampling. A candidate SHALL NOT be able to grant its own passing verdict; the generator's configuration MUST NOT produce the accept verdict.

#### Scenario: Incoherent hypothesis is DOWN-verdicted
- **WHEN** a candidate whose mechanism contradicts its grounding facts is critiqued
- **THEN** the jury returns a DOWN verdict, the node is not marked accepted, and the reviewer configuration differs from the generator configuration

#### Scenario: No self-acquittal
- **WHEN** the generator configuration is asked to adjudicate its own candidate
- **THEN** the system routes the verdict to the distinct reviewer configuration instead, and an accept verdict issued by the generator configuration is rejected

#### Scenario: Deterministic pre-jury gate rejects without spending a jury call
- **WHEN** a candidate fails a deterministic pre-jury check (its mechanism contradicts a grounding fact, or a load-bearing derivation step is graded `[guess]`) before the reviewer is invoked
- **THEN** the candidate receives a DOWN verdict from the deterministic gate, no jury (Qwen reviewer) call is made for it, and the recorded reason identifies the failed deterministic check

### Requirement: Evidence-grade anti-fabrication
The system SHALL annotate each derivation step with an evidence grade drawn from `[paper] | [inferred] | [guess]`. Any claim or citation not grounded in a fact present in the fact base SHALL be downgraded to an ungrounded hypothesis (never promoted to accepted), enforcing the no-fabrication constraint.

#### Scenario: Ungrounded citation downgraded
- **WHEN** a candidate cites a source or asserts an artifact that does not resolve to a fact in the fact base
- **THEN** that step is graded `[guess]` (or the claim is downgraded to hypothesis) and the candidate cannot reach accepted status on the strength of that step

#### Scenario: Grounded steps carry paper-grade evidence
- **WHEN** a derivation step is supported by a verified fact
- **THEN** the step is annotated `[paper]` (or `[inferred]` when logically derived from paper-grade facts) with a reference to the supporting fact id
