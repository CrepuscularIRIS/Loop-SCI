## ADDED Requirements

### Requirement: Unified LLM provider interface
The system SHALL expose a single `LLMProvider` interface that all agents call, decoupling agent logic from any concrete backend. The interface SHALL accept a message list plus tool definitions and SHALL return a normalized response containing text, tool-call, and (when available) reasoning blocks.

#### Scenario: Agent calls provider without knowing the backend
- **WHEN** an agent issues a completion request through the `LLMProvider` interface
- **THEN** the request succeeds against the configured backend and returns a normalized response object whose shape does not depend on which backend served it

#### Scenario: Tool-call round trip
- **WHEN** the provider returns a tool-call block and the agent supplies the tool result on the next turn
- **THEN** the provider accepts the tool result in the message list and continues the conversation without loss of prior turns

### Requirement: Qwen-via-Bailian backend
The system SHALL provide a Qwen backend that reaches Alibaba Cloud 百炼 (Bailian) through an OpenAI-compatible endpoint, and SHALL allow selecting the model tier (Qwen-Max / Qwen-Plus / Qwen-Turbo) via configuration. Because the endpoint is OpenAI-compatible, any other OpenAI-compatible Qwen host (DashScope, local vLLM) SHALL be usable by changing only base-URL/model configuration.

#### Scenario: Configured Qwen tier is used
- **WHEN** the config selects `qwen-plus` against the Bailian base URL
- **THEN** a live completion is served by that model and the response records the model id actually used

#### Scenario: Swap endpoint without code change
- **WHEN** the base URL and model name are changed in config to another OpenAI-compatible Qwen host
- **THEN** the provider works against the new host with no source-code modification

### Requirement: Credential management
The system SHALL load the Bailian API key from environment variable or config (never hard-coded), SHALL fail fast with a clear message when the key is missing, and SHALL redact the key from all logs and config dumps. A helper SHALL emit a non-secret invocation record (timestamp, model, endpoint host) suitable for the competition's credential/screenshot evidence requirement.

#### Scenario: Missing key fails fast
- **WHEN** no Bailian API key is present in environment or config
- **THEN** startup aborts with an explicit error naming the missing variable, and no request is attempted

#### Scenario: Secrets never leak
- **WHEN** the resolved configuration is dumped or a request is logged
- **THEN** the API key is shown redacted and never appears in plaintext

### Requirement: Resilient request handling
The system SHALL apply configurable timeout and bounded retry-with-backoff to provider calls, and SHALL surface a typed error (rate-limit, timeout, auth, server) to the caller when retries are exhausted.

#### Scenario: Transient failure is retried
- **WHEN** a provider call returns a retryable error within the retry budget
- **THEN** the call is retried with backoff and, on eventual success, returns a normal response

#### Scenario: Exhausted retries raise a typed error
- **WHEN** retries are exhausted for a rate-limit condition
- **THEN** the caller receives a typed rate-limit error rather than a raw or generic exception
