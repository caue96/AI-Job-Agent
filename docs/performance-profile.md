# Performance profile and optimizations

Date: 2026-07-11

## Scope and method

The profile traced SQL statements in integration tests, reviewed transaction boundaries and
external calls, inspected React request/render paths, and verified production bundle size.
The test environment uses SQLite and the deterministic AI provider, so structural counts
(queries, requests, payload cardinality, and lock duration) are more reliable here than
machine-specific millisecond benchmarks. PostgreSQL indexes are supplied through Alembic.

## Optimizations implemented

### 1. AI calls no longer hold a row lock or database transaction

Previously document generation locked the application row before calling the external AI
provider. Network latency and retries therefore extended the lock and occupied a database
transaction. The service now validates and prepares immutable inputs, ends the read
transaction, performs the provider request, then reacquires the application row lock,
revalidates its state, allocates the next version, and persists atomically.

An integration test observes the provider boundary and verifies that the request session has
no active transaction during generation. This is the largest latency/concurrency
optimization because external AI latency is expected to dominate request time.

### 2. The OpenAI client and connection pool are reused

The provider previously constructed a new SDK client for every generation. The dependency is
now cached once per API process and the provider owns one reusable client, allowing HTTP
connection pooling and avoiding repeated client setup. `AI_REQUEST_TIMEOUT_SECONDS` adds a
bounded, configurable provider latency (60 seconds by default, maximum 300) while existing
retry behavior remains configurable.

The model now returns one compact fact-ID plan instead of full CV, cover-letter, recruiter, and
answer prose. Final prose is rendered locally. Output tokens are capped, vacancy descriptions are
truncated to a configured maximum, and cached input tokens are accounted separately. This reduces
output latency and cost while removing the provider prose channel.

### 3. Job duplicate detection uses one narrow query

Job import previously issued as many as three sequential lookups for source ID, normalized
URL, and content hash, each loading a complete job row. One indexed `OR` query now retrieves
only the four fields needed to preserve the same duplicate-priority messages.

Measured query budget: **three job lookup round trips reduced to one**, with large description
and raw-payload columns excluded from duplicate checks. A SQL statement-count regression test
enforces the single lookup.

### 4. Post-commit entity reloads were removed

Request-scoped sessions now use `expire_on_commit=False`. Insert/update endpoints return the
already flushed state instead of issuing an unconditional `SELECT` after every commit. This
removes one database round trip from profile creation/update, job import, application
creation/transition, and document generation. Request sessions are discarded immediately,
so retained ORM state cannot become stale across requests.

### 5. Ordered-query indexes match API access patterns

The new migration adds:

- `jobs(discovered_at)` for the job feed order;
- `applications(user_id, updated_at)` for the user-scoped tracker order;
- `application_status_history(application_id, created_at)` for chronological history.

Existing unique `(application_id, version)` storage already supports document version lookup
and ordering. The model declarations and migration remain synchronized.

### 6. Document payload cardinality is bounded for the dashboard

The existing document-history endpoint still returns every version by default. An opt-in
`latest_valid=true` projection filters and limits in SQL. The dashboard uses it because it
renders only the newest valid package. Selection now transfers and validates **one full JSON
document instead of N versions**, without changing the default API behavior or generation
history.

### 7. Large API responses use balanced gzip compression

FastAPI compresses responses of at least 1,000 bytes at compression level 5. This reduces
network transfer for job descriptions, match analyses, and generated packages while avoiding
maximum-compression CPU cost. A regression test verifies the response encoding.

### 8. Mutations no longer trigger duplicate collection requests

The dashboard previously performed the mutation and then refetched both `/v1/jobs` and
`/v1/applications`. Transition responses now replace the affected application directly;
analysis and generation update the exact local fields returned by their responses.

Measured request count per transition/analyze/generate action: **three API requests reduced
to one**. The explicit Refresh button still reloads both collections.

### 9. Dashboard lookup and metric work is linear per state change

Repeated `jobs.find(...)` calls made filtering and rendering proportional to applications
times jobs. Memoized job/application maps provide constant-time joins. Five status scans plus
a score scan were replaced by one memoized aggregation pass. Search still performs one
necessary pass over applications.

### 10. Stale document requests are cancelled

Changing selection quickly previously allowed multiple full document responses to continue
and race. Each selection now uses an `AbortController`; cleanup cancels the obsolete request,
reducing network, JSON parsing, memory allocation, and incorrect transient renders.

## Review by requested area

| Area | Result |
| --- | --- |
| Database queries | Duplicate checks collapsed; post-commit reads removed; ordered indexes added |
| API latency | Mutation round trips reduced; gzip added; AI transaction released before network wait |
| AI requests | Client pooled, timeout bounded, database lock acquired only for persistence |
| Caching | Safe process-local provider/client cache added; mutable user data is deliberately not cached |
| Background workers | None exist; synchronous response semantics retained |
| Memory usage | Duplicate checks use projections; dashboard loads one document package; stale fetches abort |
| Duplicate API calls | Mutation-triggered collection refreshes removed |
| N+1 queries | No collection endpoint dereferences ORM relationships; no N+1 path found |
| Unnecessary rendering | Memoized maps and one-pass metrics replace repeated scans/lookups |
| Large payloads | Latest-valid SQL limit and gzip reduce document/job transfer cost |

## Remaining constraints and opportunities

- `/v1/jobs` and `/v1/applications` intentionally retain their existing unpaginated response
  contract. Their total ORM and JSON memory therefore grows linearly with record count.
  Cursor pagination and lightweight list schemas are the next scaling step, but would require
  an explicit API/UI contract decision rather than a behavior-preserving internal change.
- AI generation remains synchronous because callers currently expect the generated package in
  the response. A durable background queue would improve long-request capacity but requires a
  job-status/polling contract, idempotency policy, and operational worker infrastructure.
- A shared response cache is not justified for the current single-user, frequently mutated
  tracker. Introducing one now would add invalidation complexity and a risk of cross-user data
  leakage. Immutable job-detail caching can be reconsidered after authentication and tenant
  ownership are implemented.
- The deterministic matcher is CPU-light relative to database and AI I/O. Its alias searches
  operate on bounded schema inputs and Python's regex cache already reuses compiled patterns;
  no material CPU bottleneck was found there.

## Verification snapshot

- SQL query-count regression: job duplicate detection performs one job lookup.
- AI transaction regression: provider executes with no active request transaction.
- API payload regression: large responses are gzip encoded.
- Document regression: full history remains available; `latest_valid=true` returns one newest
  valid version.
- Frontend production bundle: approximately 203 kB JavaScript, 64 kB gzip in the verification
  build; no code-splitting opportunity is material at the current single-screen size.
