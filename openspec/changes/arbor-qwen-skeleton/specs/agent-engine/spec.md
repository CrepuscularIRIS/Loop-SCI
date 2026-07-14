## ADDED Requirements

### Requirement: ReAct agent runtime
The system SHALL provide an agent runtime that runs a reason-act loop: call the `LLMProvider`, dispatch any requested tools, feed results back, and repeat until the agent emits a final answer or a step budget is reached. The runtime SHALL be provider-agnostic (works on any `LLMProvider`, including Qwen-via-Bailian).

#### Scenario: Loop runs to a final answer
- **WHEN** an agent is given a task solvable with its available tools
- **THEN** the runtime alternates LLM calls and tool dispatches until the agent produces a final answer, and returns that answer with the full step trace

#### Scenario: Step budget stops runaway loops
- **WHEN** an agent exceeds its configured maximum step budget without finishing
- **THEN** the runtime halts, returns a bounded-exit result marked incomplete, and does not loop indefinitely

### Requirement: Tool registry and dispatch
The system SHALL let tools be registered by name with a schema, SHALL pass registered tool definitions to the provider, and SHALL execute the tool named in a tool-call and return its result to the agent. Unknown or malformed tool calls SHALL return a structured tool error to the agent rather than crashing the run.

#### Scenario: Registered tool executes
- **WHEN** the agent issues a tool-call for a registered tool with valid arguments
- **THEN** the tool runs and its output is returned to the agent on the next turn

#### Scenario: Unknown tool is handled gracefully
- **WHEN** the agent issues a tool-call for a tool that is not registered
- **THEN** the runtime returns a structured "unknown tool" error to the agent and the run continues

### Requirement: Coordinator/executor orchestration
The system SHALL provide a coordinator agent that plans and dispatches work to one or more executor agents, and executor agents that carry out a single dispatched unit and report a structured result back to the coordinator. The coordinator SHALL record each executor outcome into research-state (the idea-tree) before deciding the next step.

#### Scenario: Coordinator dispatches an executor and records the result
- **WHEN** the coordinator dispatches a unit of work to an executor
- **THEN** the executor runs, returns a structured result, and the coordinator writes that result into the idea-tree before its next decision

#### Scenario: One research cycle turns end-to-end
- **WHEN** a run is started against a stub research task on the Qwen backend
- **THEN** the coordinator completes at least one observe→dispatch→record cycle and the run terminates cleanly with persisted state

### Requirement: Context management
The system SHALL manage each agent's context so a long run does not exceed model limits, compacting or summarizing prior turns while preserving the durable state needed to continue (the idea-tree remains the source of truth across compaction).

#### Scenario: Long run stays within context limits
- **WHEN** an agent's accumulated context approaches the configured threshold
- **THEN** the runtime compacts earlier turns and continues without a context-overflow error, and the idea-tree still reflects all recorded outcomes
