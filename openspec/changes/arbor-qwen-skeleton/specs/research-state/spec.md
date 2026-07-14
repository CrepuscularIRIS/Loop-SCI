## ADDED Requirements

### Requirement: Idea-tree state model
The system SHALL model research state as a tree of nodes, where each node carries at least: a stable id, a hypothesis/description, a status (e.g. pending / running / done / merged / pruned), an optional score, an optional insight, and optional references (code/branch/artifact). The tree SHALL be the single durable source of truth for research progress.

#### Scenario: Node records an outcome
- **WHEN** an executor outcome is written to a node
- **THEN** the node's status, score, insight, and references reflect that outcome and are retrievable by node id

#### Scenario: Tree encodes parent/child structure
- **WHEN** a child hypothesis is added under a parent node
- **THEN** the tree exposes the parent/child relationship and the child inherits a derivable, unique id

### Requirement: Persistence with auto-save
The system SHALL persist the idea-tree to a canonical JSON file within the run's session directory and SHALL auto-save on every mutation, so an interrupted process never loses more than the in-flight mutation.

#### Scenario: Mutation is durable immediately
- **WHEN** a node is added or updated
- **THEN** the canonical JSON on disk reflects the change without requiring an explicit save call

#### Scenario: Reload reconstructs the tree
- **WHEN** the canonical JSON is loaded in a fresh process
- **THEN** the reconstructed tree is structurally equal to the tree that was saved

#### Scenario: Interrupted mid-write never corrupts the tree
- **WHEN** the process is killed while a mutation is being persisted
- **THEN** the on-disk canonical JSON is either the pre-mutation or the post-mutation state and is always valid JSON (writes are atomic — temp file plus replace)

### Requirement: Run lifecycle with checkpoint and resume
The system SHALL create a per-run session directory holding the idea-tree, run metadata, and logs, and SHALL support resuming an interrupted run from its last checkpoint so the coordinator continues from saved state rather than restarting.

#### Scenario: Resume continues from saved state
- **WHEN** a run is interrupted after recording some outcomes and is then resumed
- **THEN** the coordinator loads the existing idea-tree and continues from the last checkpoint without repeating completed work

#### Scenario: Resuming an already-complete run is a safe no-op
- **WHEN** resume is invoked on a run whose work is already complete
- **THEN** no completed work is re-executed and the run terminates cleanly reporting completion

### Requirement: Event-bus seam for observers
The system SHALL emit run/tree/agent events onto a decoupled event bus that observers can subscribe to, and the engine SHALL incur no behavioral change when no subscriber is attached. This seam exists so the later visualization change can attach live without modifying the engine.

#### Scenario: Observer receives events without affecting the engine
- **WHEN** a subscriber is attached to the event bus during a run
- **THEN** it receives node-mutation and lifecycle events, and the run's behavior and results are identical to a run with no subscriber
