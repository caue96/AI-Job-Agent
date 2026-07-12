# Changelog

All notable changes to this project are documented here. The project uses semantic versioning.

## 1.0.0 - 2026-07-12

### Added

- Candidate profiles, normalized vacancy storage, tracked applications, status history, and audit
  events.
- Deterministic matching with explainable category scores and configurable hard blockers.
- Versioned, fact-cited application document generation in English, Spanish, and Portuguese.
- Approval-first React dashboard and explicit submission confirmation workflow.
- Alembic migrations, local PostgreSQL Compose topology, CI quality gates, and operational docs.

### Security and reliability

- Production remains fail-closed until authentication and tenant ownership are implemented.
- Local services bind to loopback by default; runtime containers are unprivileged and exclude
  development dependencies and local build context artifacts.
- Database uniqueness, foreign-key, timestamp-nullability, transaction rollback, and concurrent
  create paths are enforced and tested.
- AI prompt boundaries, strict structured output, fact citations, multilingual sponsorship checks,
  provider-error redaction, and explicit human approval are enforced.
- AI providers now return fact-selection plans rather than prose; documents are deterministically
  rendered from validated fact IDs, with cached-token, latency, and fallback metadata.

### Known scope

- Version 1.0 is a local-only, single-user release. It must not be exposed to untrusted networks.
- Manual external submission, synchronous document generation, and unpaginated collections are
  intentional 1.0 constraints.
