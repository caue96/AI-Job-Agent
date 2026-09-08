# Test coverage report

Date: 2026-09-08

## Current measurement

The complete local backend suite reports **82.22% branch-aware coverage overall** and **98%**
across `app/ai.py`, `app/matching.py`, and `app/services.py`. Both enforced gates (80% overall and
90% core business logic) pass.

| Module | Branch-aware coverage |
| --- | ---: |
| `app/ai.py` | 100% |
| `app/matching.py` | 97% |
| `app/services.py` | 97% |
| `app/repositories/sqlalchemy.py` | 74% |
| `app/cv.py` | 86% |
| `app/cover_letters.py` | 83% |
| **Overall** | **82.22%** |
| **Core business aggregate** | **98%** |

The verified local run executed **136 passing tests** and skipped **4 PostgreSQL integration tests**
because Docker/PostgreSQL was unavailable on this workstation. The CI workflow is configured to
supply PostgreSQL 16 and run the same integration module. No snapshot tests or live AI/job-provider
calls are used.

```bash
pytest -q --cov=app --cov-branch --cov-report=term-missing --cov-fail-under=80
coverage report --include='app/ai.py,app/matching.py,app/services.py' --fail-under=90
```

## Deterministic coverage

Tests cover strict input validation; authorization scoping; profile/job/application concurrency and
state transitions; deterministic matching and hard filters; prompt boundaries and grounded output;
CV extraction, evidence, correction, confirmation, retention, and exports; discovery provider
normalization, retry/failure isolation, duplicates, schedules, ranking, and notification
deduplication; CV optimization and cover-letter review/version/approval/export workflows; repository
commit/rollback/restart semantics; normalized skill reuse; relational match evidence and decisions;
and Alembic/ORM synchronization.

The real-PostgreSQL module additionally validates JSONB containment, foreign keys, rollback,
concurrent `INSERT ... ON CONFLICT`, unique constraints, migration upgrade/downgrade/re-upgrade,
legacy SQLite backup/report/idempotence, and profile/job/explainable-match survival after engine
restart. The configured CI workflow is the authoritative execution environment for these
PostgreSQL-specific assertions once it runs on the remote host.

Frontend line coverage is not measured. TypeScript, ESLint, production compilation, and two
deterministic Playwright journeys cover CV review and job discovery without network services.

## Remaining uncovered areas

- `app/cli/migrate_local_data.py` is 23% in the local aggregate because its meaningful success path
  requires a destructive disposable PostgreSQL schema and is intentionally exercised only by the
  PostgreSQL CI test. Unit-mocking SQL dialect behavior would provide misleading coverage.
- `app/discovery_worker.py` is not invoked by the unit suite. Its scheduling service is covered
  directly; the small process loop and sleep/error boundary require a process-level operational
  test rather than branch-oriented unit assertions.
- Route modules retain defensive ownership/not-found branches that cannot be reached through a
  valid foreign-key graph. Normal success, user-scoping, validation, and representative failures are
  covered.
- AI and compliant provider network calls remain excluded because they are nondeterministic, may
  cost money, and may violate test isolation. Request construction, parsing, retry/fallback, and
  safety behavior use fakes.
- A few matcher branch edges are equivalent combinations of policy toggles. Every score dimension
  and blocker behavior has a representative deterministic test; exhaustively multiplying boolean
  combinations would add volume without material confidence.

Coverage is a release gate, not the only correctness signal. PostgreSQL constraints, migrations,
frontend build/e2e checks, type checking, linting, Bandit, and dependency audits are separate gates.
