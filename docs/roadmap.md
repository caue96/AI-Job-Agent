# Known limitations and roadmap

## Current limitations

- Authentication is a fixed single-user development identity; production startup is blocked.
- Jobs can be imported only through the API using already normalized manual data. No CSV parser
  or external job-board adapter exists.
- The dashboard reviews and advances existing applications but does not provide profile editing
  or job-import forms.
- AI generation is synchronous. Mock mode is the default; OpenAI mode requires a key and trusted
  local development configuration.
- DOCX/PDF export, account-level data export/deletion, retention automation, and background
  workers are not implemented.
- Job and application lists are unpaginated, and the frontend has no separate unit-test coverage
  threshold.

## Versioned roadmap

### Version 1.1

- Split frontend API/types/workflow code and add deterministic interaction tests.
- Add cursor pagination and lightweight job/application list schemas.
- Add PostgreSQL integration, migration, and concurrency coverage.
- Add privacy deletion/export and documented retention controls for the local data store.

### Version 1.2

- Add structured redacted logs, request correlation, metrics, and operational health checks.
- Improve multilingual matching aliases and grounding evidence without weakening human review.
- Add authorized CSV/provider ingestion only after terms and retention policies are reviewed.

### Version 2.0

- Introduce authenticated identity, tenant ownership, rate limits, AI budgets, recovery, and a
  reviewed production deployment topology as one deliberate contract change.
- Add durable background generation only if measured concurrent workload justifies its queue,
  idempotency, polling, and operational complexity.

Direct submission and browser automation remain out of scope unless product requirements and
the explicit human-approval invariant are deliberately revised.
