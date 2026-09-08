# PostgreSQL persistence and migration runbook

## Authority and boundaries

PostgreSQL 16 is the authoritative store for all structured runtime state. API controllers obtain a
unit of work, application services consume repository protocols, and only
`app/repositories/sqlalchemy.py` owns application queries. The pure matcher and AI adapters receive
validated objects and do not open sessions, commit transactions, read documents, or write JSON.

The database contains users, candidate/contact/work-authorization data, normalized skills and
languages, employment, education, certifications, projects and achievements, immutable profile
versions, CV import/extraction/evidence/correction metadata, providers and user configurations,
search/provider runs and errors, raw provider payloads, normalized/versioned jobs, requirements,
sources, cursors, duplicate groups, explainable/versioned matches, recommendations, generated
documents, validation records, export metadata, notification state, audit records, idempotency
records, and migration reports.

PDF, DOCX, TXT, and generated binary files remain in private persistent volumes. `stored_files`
records the owner, opaque storage key, original filename, MIME type, byte size, SHA-256 checksum,
creation time, retention state, and deletion time. A storage key is not a raw host path and is never
returned as a download location. The database and both document volumes form one backup unit.

No JSON file, browser local storage, process dictionary, or temporary object is an authoritative
store. SQLite is permitted only for isolated tests and as the read-only source of the legacy import.

## Relational model decisions

- Candidate and job skills share a normalized `skills` vocabulary. Candidate projects, job
  versions, and match versions reference it through join tables.
- Education, certifications, projects, achievements, requirements, evidence, score components,
  blockers, decisions, extraction fields, and validation issues are relational rows rather than
  embedded core data.
- JSONB is reserved for provider payloads/metadata, immutable snapshots, bounded analysis details,
  and extension data whose shape legitimately varies.
- Candidate profiles, jobs, and applications have optimistic version columns. Database uniqueness
  protects provider IDs, canonical URLs, content hashes, run/job matches, input/engine match
  versions, notifications, scheduled runs, and idempotency keys.
- Jobs retain lifecycle/deletion fields and history. Candidate deletion remains a deliberate hard
  delete because it is a privacy operation; immutable audit/snapshot retention follows the existing
  local-only product policy.

## Transaction boundaries and concurrency

One HTTP request or worker tick owns one unit of work. Creating profiles, importing/confirming CVs,
importing or merging jobs, scoring matches, creating CV variants, and creating cover-letter
versions write their related rows in one transaction. Services flush when they need IDs or must
surface a constraint failure. They commit internally only at documented external-provider boundaries
and when recording an upload attempt before untrusted PDF parsing, so failed uploads still count.

Before a slow AI request, a service commits its validated input state. After the request it reloads
and locks the owning record, verifies the job/profile/match identity, validates grounded output, and
persists a new immutable version. Scheduled discovery claims due configurations with
`FOR UPDATE SKIP LOCKED`. Normalized skill creation uses `INSERT ... ON CONFLICT`, and retryable
uniqueness/optimistic-lock failures map to a safe conflict response. CV upload throttling is stored in
PostgreSQL and serialized per user with an advisory transaction lock.

## Schema upgrades

Back up PostgreSQL and the two file volumes before every release. Validate the revision on a
disposable database first:

```bash
docker compose --profile test up -d test-db
cd backend
export DATABASE_URL='postgresql+psycopg://jobagent_test:jobagent_test@localhost:55432/jobagent_test'
alembic upgrade head
alembic current
alembic check
```

Revision `20260907_0012` is expand-first: it creates normalized tables and indexes, converts flexible
existing JSON columns to JSONB on PostgreSQL, adds nullable skill links, backfills skills/job
versions/requirements/file metadata, and only then makes skill links non-null. It does not drop
legacy business columns. Review the revision and rehearse it on a recent restored backup for a
managed environment; schedule JSON-to-JSONB rewrites for a maintenance window on a large database.

Alembic downgrade is for development validation, not operational rollback. If an upgrade fails or
application verification fails, stop API/worker processes and restore the pre-upgrade database plus
file volumes together. Do not run a destructive downgrade against the only copy.

## Importing a legacy SQLite database

Stop writes to the legacy application, keep the SQLite file and document directories unchanged, and
ensure the PostgreSQL target is backed up. From `backend/`:

```bash
python -m app.cli.migrate_local_data path/to/job_agent.db \
  --database-url 'postgresql+psycopg://app_user:password@localhost:5432/ai_job_agent' \
  --backup-dir ./data/migration_backups
```

The command:

1. resolves the source, uses SQLite's backup API to capture a WAL-aware snapshot, verifies its
   integrity, and computes the snapshot SHA-256;
2. upgrades the target to Alembic head;
3. preserves compatible IDs and copies rows with parameterized statements and per-record savepoints;
4. normalizes legacy profile skills and reconciles job versions, requirements, and file metadata;
5. records inserted/existing/rejected counts and sanitized reasons in PostgreSQL;
6. prints a JSON report and never deletes or modifies the source.

The source checksum is unique in `local_data_migration_runs`; rerunning the same source returns
`ALREADY_MIGRATED`. A result of `COMPLETED_WITH_REJECTIONS` requires reviewing
`local_data_migration_errors` and resolving every rejected table/identifier before cutover. Error
records intentionally omit row contents and personal data.

Validate counts by domain, sample ownership-scoped reads, SHA-256 values for stored files, latest
profile/job/match versions, and application histories. Start the API and worker only after
`alembic current` reports head and validation succeeds. Retain the source and backup until the
retention window and rollback decision have passed.

## Backup and restore

For a native PostgreSQL database, use role-appropriate `pg_dump --format=custom` and test
`pg_restore` into a separate database. For Compose, a logical dump is preferred over copying a live
volume. Back up `cv_uploads` and `cv_exports` at the same application quiescence point. Encrypt
backups, restrict access, record checksums, define retention, and perform restore drills.

## Verification

`tests/test_postgres_integration.py` uses a real PostgreSQL database to validate the migration chain,
JSONB containment, foreign keys, rollback, concurrent normalized inserts, unique constraints,
legacy-import backup/idempotence, and restart persistence from profile through explainable match.
The fixture drops `public` and refuses database names that do not end in `test`.

```bash
TEST_POSTGRES_URL='postgresql+psycopg://jobagent_test:jobagent_test@localhost:55432/jobagent_test' \
  pytest -q tests/test_postgres_integration.py
```

CI is configured to run this test against a PostgreSQL 16 service. SQLite tests remain useful for
fast deterministic business checks, but they are not accepted as evidence for PostgreSQL-specific
behavior.

## Known migration risks

- JSON-to-JSONB conversion rewrites data and can lock large tables.
- Legacy records that violate new foreign keys, uniqueness, lengths, or non-null rules are rejected
  and reported rather than coerced silently.
- Files are not copied by the data importer; their existing private storage must be migrated and
  verified separately while preserving opaque storage keys.
- Concurrent legacy writes after checksum/backup are not captured; enforce a write freeze.
- Production deployment is still prohibited by the authentication/tenant startup guard. This
  persistence boundary is ready for matching work, but it is not a production-readiness claim.
