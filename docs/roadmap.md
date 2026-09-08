# Known limitations and roadmap

## Current limitations

- Authentication is a fixed single-user development identity; `APP_ENV=production` blocks startup.
- The current deployment is a local Compose topology, not a reviewed production platform.
- AI document generation remains synchronous. Mock mode is deterministic; OpenAI mode requires a
  server-side key and keeps the request worker occupied during provider latency.
- Job and application lists are unpaginated. Discovery ranking is bounded, but long-lived catalogs
  need cursor pagination and archival/retention policy.
- Binary CV/document storage is a private local volume. It has database-backed metadata and
  retention state, but no object-storage adapter, replication, or independent recovery automation.
- The frontend has deterministic Playwright journeys but no component line-coverage threshold.
- SQLite-to-PostgreSQL import copies structured rows only; operators must migrate and verify the
  private file volumes separately.

## Versioned roadmap

### Version 1.1

- Add authenticated identity and enforce tenant ownership on every profile, search, application,
  document, notification, audit, and file operation before lifting the production startup guard.
- Add cursor pagination and lightweight list contracts for jobs and applications.
- Add managed backup schedules, restore drills, retention jobs, and operator-facing migration
  telemetry for PostgreSQL and document storage.
- Split frontend API/types/workflow code and add deterministic component interaction coverage.

### Version 1.2

- Add structured redacted logs, request correlation, metrics, traces, service-level objectives, and
  alerts for database pools, workers, providers, and AI latency/cost.
- Add identity-aware distributed quotas and AI budgets.
- Move binary artifacts behind a private object-storage abstraction with checksum verification and
  lifecycle rules if operational scale requires it.
- Add asynchronous document generation only after measured concurrency justifies a durable queue,
  idempotency contract, worker ownership, and polling API.

### Version 2.0

- Deliver a reviewed multi-tenant deployment topology with managed PostgreSQL, secrets management,
  TLS, disaster recovery, release migrations, image provenance, and security monitoring.
- Evolve multilingual matching and grounding with a versioned evaluation corpus while retaining
  deterministic score components, immutable profile/job inputs, and explicit human decisions.
- Expand compliant provider integrations only where an official or user-authorized access method,
  data-retention policy, and operational owner exist.

Automatic job submission, CAPTCHA bypass, private-endpoint access, and unsupported candidate claims
remain out of scope. The human-approval and evidence-grounding invariants are not roadmap items to
relax.
