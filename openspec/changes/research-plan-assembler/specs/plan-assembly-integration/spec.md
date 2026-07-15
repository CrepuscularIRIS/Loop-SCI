## ADDED Requirements

### Requirement: Canonical JSON + rendered Markdown output
The system SHALL emit the assembled plan in two forms: a **canonical JSON** object carrying all 12 standardized fields (Problem Statement, Rationale, Technical Details, Datasets, Source, Target, Paper Title, Abstract, Methods, Experiments, Results, References) under stable keys, and a **rendered Markdown** 《科学假设与研究计划》 derived from the same JSON. The JSON SHALL be the machine-consumable source of truth for downstream review/visualization; the Markdown SHALL be derived from it (no independent content).

#### Scenario: Both output forms produced with all 12 fields
- **WHEN** a plan is assembled
- **THEN** the canonical JSON contains all 12 fields under their stable keys, and the rendered Markdown presents the same 12 fields as a readable document with no field present in one form but missing in the other

### Requirement: Deterministic completeness and anti-fabrication gate
The system SHALL apply a **deterministic gate** before a plan is emitted as final: all 12 fields present and non-empty; every entry in References verified (real); and no load-bearing claim ungrounded (consistent with results-derivation). A plan failing the gate SHALL be rejected/flagged as incomplete rather than emitted as a final deliverable. The gate SHALL require no provider call.

#### Scenario: Incomplete or unverified plan fails the gate
- **WHEN** an assembled plan is missing a field, has an empty field, or contains an unverified reference
- **THEN** the deterministic gate marks the plan as failing (not final), identifying the failed check, without invoking the provider

#### Scenario: Complete verified plan passes the gate
- **WHEN** an assembled plan has all 12 fields non-empty, all references verified, and no ungrounded load-bearing claim
- **THEN** the deterministic gate passes and the plan is emitted as final

### Requirement: Specialist executor and tool integration
The system SHALL provide a `PlanAssemblerExecutor` over the foundation Executor seam (it consumes a ranked hypothesis, assembles the fields, derives Results, verifies References, gates, and records the plan) and SHALL register an `assemble` tool in the ToolRegistry wrapping the same pipeline with injected dependencies. Integration SHALL require no change to the coordinator interface, SHALL keep `auto_git` disabled, and SHALL be resumable via `RunSession` (a completed plan is not re-assembled on resume).

#### Scenario: Executor assembles a plan end-to-end offline
- **WHEN** the executor is dispatched for a ranked hypothesis against a mock provider, a seeded fact base, and a mocked verification seam
- **THEN** it produces a gated, complete 12-field plan (JSON + Markdown) with real references and no network calls or git operations, retrievable through the plan record

#### Scenario: Tool wraps the same pipeline
- **WHEN** the `assemble` tool is invoked through the registry with injected dependencies
- **THEN** it exercises the same underlying assembly pipeline and returns a structured result (or a structured error), offline
