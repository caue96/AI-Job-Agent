# Production readiness review

Reviewed: backend API, persistence and migrations, AI generation, frontend, Compose/Dockerfiles, CI, tests, and documentation. Findings were refreshed against the repository on 2026-07-12.

## Critical issues

### C1. The API has no production authentication boundary

Every route resolves the fixed `local@example.invalid` user. The `password_hash` column is unused, and neither API nor UI establishes an authenticated identity. Exposing the current service would expose all candidate and application data to any caller.

**Fix implemented:** production configuration now fails closed. The service only permits development/test modes until a reviewed authentication and tenant-ownership design is implemented. This prevents accidental public deployment of the development identity model.

### C2. Docker Compose embeds a database password

`docker-compose.yml` hard-coded `jobagent` in both the database and API connection string. It would be copied into deployments and logs.

**Fix implemented:** Compose now requires database credentials through environment variables and `.env.example` contains placeholders only.

## High-priority issues

### H1. Generated-document versioning can race

Document versions were calculated as `max(version) + 1` without a row lock. Concurrent generation could cause a unique-constraint failure or version collision.

**Fix implemented:** generation ends its read transaction before the provider call, then locks and revalidates the owning application before calculating and inserting the next version.

### H2. The frontend production container ran the Vite development server

The web image used `pnpm dev`, which is not an immutable production artifact and has unnecessary development-server exposure.

**Fix implemented:** the Dockerfile now performs a locked Vite build in a builder stage and serves static files from an unprivileged Nginx image with a restrictive configuration.

### H3. Redis was declared but entirely unused

There was no queue, cache, or application dependency using Redis, yet it added an exposed service, configuration, operations burden, and misleading architecture documentation.

**Fix implemented:** Redis configuration and the Compose service were removed. It can be reintroduced with a concrete background-work implementation.

### H4. CI did not validate the Compose interpolation contract

The workflow could pass while a changed Compose file had missing variables or invalid interpolation.

**Fix implemented:** CI now validates Compose with explicit, non-secret CI-only values.

### H5. Duplicate checks were not safe under concurrency

Job URL/content checks and application existence checks used read-then-insert logic. Two
concurrent requests could both pass the read, leaving correctness to an unhandled database
exception; URL and content fingerprints were not database-unique at all.

**Fix implemented:** normalized job URLs and content hashes now have unique indexes, application
and job insert races are translated to stable 409 responses, and the local identity bootstrap
recovers from a concurrent first request. Deterministic tests cover the conflict paths.

### H6. SQLite did not enforce foreign keys

SQLite connections used in development and tests accepted orphaned rows that PostgreSQL rejects.

**Fix implemented:** the shared engine factory enables `PRAGMA foreign_keys=ON` on every SQLite
connection, and test fixtures use that factory. A regression test proves orphan inserts fail.

### H7. Provider errors and frontend selection races leaked through abstraction boundaries

OpenAI SDK failures became generic server errors, and an AI response completing after the user
selected another application could render the returned document under the wrong application.

**Fix implemented:** provider errors are wrapped and returned as a redacted 502 response. The
dashboard associates delayed document responses with the application that initiated them before
updating visible document state.

### H8. Local defaults exposed an unauthenticated API beyond localhost

Compose and Vite development ports listened on every interface despite the local-only contract.

**Fix implemented:** host port bindings and the development server now default to loopback. The
backend image installs runtime dependencies only and runs under an unprivileged account.

## Medium-priority issues

- Candidate claims now have structural provenance because providers return fact IDs only and
  application code renders the prose. Model-selected relevance can still be imperfect and needs a
  versioned live-model evaluation corpus before changing model snapshots.
- `/v1/jobs` and `/v1/applications` are unpaginated; large datasets will increase latency and frontend memory use.
- `main.py` repeats application/profile/job context loading across handlers; a dependency or service helper would reduce route-level duplication.
- The frontend is concentrated in one component, which makes independent UI testing and changes harder.
- The project has only SQLite migration coverage locally. PostgreSQL migration/integration coverage should run in CI when a container runner is available.

## Low-priority improvements

- Replace broad JSON columns with typed child entities where querying/reporting becomes important.
- Add audit-retention and privacy-deletion policies before storing production data.
- Separate frontend API types/client code from view components.

## Scope note

This review intentionally does not add product features such as provider ingestion, user registration, document export, or multi-tenancy. The production fail-closed control is a security correction, not a replacement for the required future authentication design.
