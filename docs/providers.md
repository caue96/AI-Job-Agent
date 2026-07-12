# Provider integration guide

## Current provider support

There is no enabled external job-board adapter and no CSV parser. Jobs are imported by posting a
normalized manual payload to `POST /v1/jobs`. The import service normalizes URLs, computes a
stable content hash, and rejects duplicate source/external IDs, normalized URLs, or content.
Scraping, CAPTCHA handling, account automation, and direct application submission are out of
scope.

AI document generation has two provider modes:

- `mock` (default): deterministic, offline, and used by tests;
- `openai`: OpenAI Responses API with a strict Pydantic fact-selection plan, enabled only when an
  API key is configured in development mode.

The OpenAI provider reuses one SDK client and connection pool per API process. Configure
`AI_REQUEST_TIMEOUT_SECONDS` and `AI_MAX_RETRIES` to the deployment latency budget. The service
releases its read transaction before the provider request and reacquires the application lock
only for revalidation, version allocation, and persistence.

Provider output is untrusted. The provider can select only existing fact IDs; application code
validates the plan and renders the final package from fixed templates. It cannot bypass plan
validation, grounding checks, workflow state checks, or explicit submission approval.

Mock selection and rendering support deterministic English, Spanish, or Portuguese output.
Candidate claims have structural provenance because no model-authored prose reaches the final
package. Human review remains mandatory because users can enter inaccurate profile facts and
model-selected relevance can be imperfect. The complete prompt registry and failure policy are in
[`ai-architecture.md`](ai-architecture.md).

## Requirements for a future job adapter

A future adapter should remain outside route handlers and must:

1. fetch only through an authorized API or source;
2. document authorization, terms, rate limits, retention, and deletion obligations;
3. map external records into `JobCreate` without copying provider instructions into prompts;
4. provide stable source and external identifiers for idempotency;
5. retain raw payloads only when a reviewed data-retention requirement exists;
6. use bounded timeouts, retries with backoff, and observable failure handling;
7. add deterministic mapping, validation, duplicate, and error tests.

Do not introduce a queue or Redis solely in anticipation of adapters. Add background
infrastructure only with a concrete durable workload and operational ownership.
