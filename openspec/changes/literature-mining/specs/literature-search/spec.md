## ADDED Requirements

### Requirement: Unified multi-source search
The system SHALL search scholarly literature across Semantic Scholar, arXiv, and PubMed behind a single interface, returning results in a unified schema (at least: source, external id/DOI, title, authors, year, venue, abstract, url). A query SHALL be dispatchable to one, several, or all configured sources.

#### Scenario: Query returns unified results from multiple sources
- **WHEN** a topic query is issued to the configured sources
- **THEN** results come back in the unified schema regardless of which source produced them, each tagged with its originating source and external id

#### Scenario: A single source can be targeted
- **WHEN** the caller restricts a query to one source (e.g. PubMed only)
- **THEN** only that source is queried and results are returned in the unified schema

### Requirement: Mockable client boundary (offline-by-default)
The system SHALL isolate all network access behind a client boundary that can be mocked, so the default test suite runs with NO network. Live API access SHALL be exercised only by opt-in tests gated on the presence of the relevant credentials/config.

#### Scenario: Default suite runs offline
- **WHEN** the default test suite runs without network or API keys
- **THEN** search behavior is verified against mocked/recorded responses and no live HTTP call is made

#### Scenario: Live tests are opt-in
- **WHEN** live tests run with the required credentials present
- **THEN** they hit the real APIs; without credentials they are skipped cleanly, not failed

### Requirement: Rate-limit and error resilience
The system SHALL respect each source's rate limits (backoff on 429/throttle) and SHALL surface a typed, non-crashing error when a source is unavailable, so one failing source does not abort a multi-source query.

#### Scenario: One source failing does not abort the query
- **WHEN** one configured source errors or rate-limits while others succeed
- **THEN** the query returns the available results plus a recorded note about the failed source, without raising to the caller
