# Changelog

## 1.0.0 grounded cover-letter completion

- Added multilingual cover letters with structured evidence planning, deterministic rendering,
  claim validation, immutable edits, explicit approval, and private TXT/DOCX/PDF exports.
- Added the review interface, integration/E2E coverage, documentation, and migration
  `20260721_0011`.

## 1.0.0 job discovery completion

- Added the documented provider compliance registry, official ITJobs.pt and InfoJobs adapters,
  configured Tecnoempleo RSS support, and compliant manual/CSV/imported-email fallbacks.
- Added editable multilingual search profiles, database-backed scheduling, isolated provider runs,
  raw and normalized storage, cross-source duplicate groups, deterministic ranking, visible hard
  filters, and deduplicated in-app notifications.
- Added the responsive discovery dashboard, scoped APIs, migration, deterministic backend coverage,
  browser end-to-end coverage, security controls, provider documentation, and Compose worker.

## 1.0.0 CV import completion

- Added private PDF CV upload, validation, extraction, scanned-document detection, retention, and
  user-controlled deletion.
- Added strict evidence-bearing AI extraction with prompt-injection boundaries, deterministic
  fallback, exact page-quote verification, and user-edit provenance.
- Added accessible upload/review/compare/merge/replace UI, immutable profile versions, audit events,
  migration, backend regression coverage, and a Playwright end-to-end workflow test.
- Repaired the pre-release foundation and generated-document PostgreSQL enum migrations so a fresh
  Compose database can apply the complete migration chain without duplicate type creation.

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
