# Test coverage report

## Current complete measurement

The complete backend suite reports 83.75% branch-aware coverage overall and 98% across
`app/ai.py`, `app/matching.py`, and `app/services.py`, exceeding the 80%/90% gates. The reduction
from the earlier percentage is the expected result of adding discovery, provider, CV import, and CV
optimization modules to the measured application surface. Live network branches remain unexecuted
by design: deterministic tests must never contact job sites or AI services.

Discovery tests cover multilingual term generation, provider queries and normalization, RSS parsing,
pagination decisions, retry/rate metadata, SSRF and malicious URLs, HTML sanitization, CSV/email imports,
weekday scheduling, partial failure, duplicate merging, matching, ranked results, application preparation,
notification deduplication, and the complete CV-to-strong-match browser journey.

CV optimization tests cover evidence catalogs, prompt-boundary escaping, deterministic plans,
unsupported skills/metrics/links/salary, dates, language levels, work authorization, review
decisions, immutable variants, PDF/DOCX exports, ownership, deletion, approval state, and the full
job-to-export integration path.

Cover-letter tests cover prompt-injection boundaries, differentiated structured plans, missing-skill
exclusion, verified company facts, English/Spanish/Portuguese rendering, all three word ranges,
greeting fallback, candidate/company fabrication, sponsorship semantics, empty vacancy metadata,
immutable edits, approval blocking, and TXT/DOCX/PDF export/download integrity.

Date: 2026-07-21

## Coverage policy

Coverage is measured with statement and branch coverage. CI enforces two independent gates:

1. **80% overall backend coverage** across `app/`.
2. **90% business-logic coverage** across `app/ai.py`, `app/matching.py`, and
   `app/services.py`.

The business-logic set contains grounding, deterministic matching, workflow transitions,
duplicate detection, and generated-document persistence. Routes, ORM declarations, and
database bootstrap code remain in the overall gate but cannot inflate the business-rule
result. These percentages cover the Python backend. The React client currently has no unit
test runner or coverage instrumentation and is therefore not included in the numeric gate.

## Baseline

Before the additional tests:

| Module | Branch-aware coverage | Assessment |
| --- | ---: | --- |
| `app/ai.py` | 83% | Poor: provider parsing and several grounding failures were uncovered |
| `app/matching.py` | 90% | At threshold, but location and optional-data branches were sparse |
| `app/services.py` | 93% | Good, with some duplicate and invalid-state branches uncovered |
| `app/main.py` | 78% | Poor route/error-path coverage |
| `app/db.py` | 78% | Low infrastructure coverage |
| **Overall** | **90%** | Already above the overall target |
| **Business logic aggregate** | **89%** | Below the required business target |

## Final verified result

The exact enforced CI commands completed successfully:

```bash
pytest -q --cov=app --cov-branch --cov-report=term-missing --cov-fail-under=80
coverage report --include='app/ai.py,app/matching.py,app/services.py' --fail-under=90
```

| Module | Branch-aware coverage |
| --- | ---: |
| `app/ai.py` | 100% |
| `app/matching.py` | 97% |
| `app/services.py` | 98% |
| **Overall** | **83.75%** |
| **Business logic aggregate** | **98%** |

The verified run executed **123 deterministic tests**. No snapshot tests were introduced.

## Tests added

- AI provider structured-response success, missing structured output, token accounting, and
  deterministic cost calculation.
- Grounding rejection for invalid fact IDs, non-candidate citations, and unsupported keyword
  comparisons.
- Candidate employment and highlight fact construction.
- OpenAI client creation failure without a key, without making a network request.
- Remote, relocation, remote-disabled, partial-experience, optional salary/industry, and
  incompatible work-authorization matching paths.
- Duplicate job precedence for source identifiers and content hashes.
- Missing-resource, duplicate-ownership, and invalid workflow-state API behavior.
- SQLite foreign-key enforcement, migration/index synchronization, and request rollback.
- Concurrent profile/job/application conflicts and local-user bootstrap recovery.
- Whitespace normalization, duplicate profile facts, code validation, and secret redaction.
- English, Spanish, and Portuguese deterministic generation and sponsorship contradictions.
- Strict fact-selection plans, deterministic rendering, prompt truncation, cached-token cost,
  latency metadata, provider fallback, and model/factory configuration.
- Loopback bindings, unprivileged runtime image, and Docker build-context exclusions.

All provider behavior is tested with deterministic in-memory fakes. The suite never calls a
live AI service and never depends on wall-clock timing.

## Remaining uncovered areas

### `app/db.py` non-SQLite engine branch

The session lifecycle, rollback path, SQLite connection hook, and foreign-key behavior are
covered. The remaining branch is construction of a non-SQLite engine. Exercising it without a
PostgreSQL service would test URL parsing rather than actual driver, transaction, and lock
semantics; that belongs in the planned PostgreSQL integration job.

### Defensive route branches

`app/main.py` retains a small number of defensive 404 branches, including a job disappearing
after an application with a valid foreign key has already been loaded. Those states cannot be
created through the public API while foreign keys are intact. Normal success paths, missing
top-level resources, ownership filters, and workflow errors are covered.

### Concurrent post-provider state change

`app/services.py` retains the defensive failure raised when an application changes to an
ineligible state during the AI request and fails the locked recheck. A faithful deterministic
test requires two PostgreSQL transactions coordinated around a provider barrier; SQLite does
not reproduce PostgreSQL row-lock behavior. The initial eligibility check and successful
locked persistence path are covered. This scenario belongs in a future PostgreSQL integration
suite rather than a misleading SQLite concurrency test.

### Equivalent matching-policy branch combinations

`app/matching.py` has complete statement coverage; the remaining uncovered branch edges are
combinations of hard-rejection toggles where the same reason is retained but is or is not also
added to the blocker list. Representative enabled/disabled policies and every scoring outcome
are covered. Exhaustively multiplying all boolean policy combinations would add test volume
without new behavior confidence.

### Live provider and database services

No live OpenAI request is included: network availability, provider latency, and model output
would make the suite nondeterministic and incur cost. SDK request construction, response
parsing, empty output, usage metadata, and cost computation are fully covered with fakes.
Likewise, PostgreSQL driver and Alembic behavior are verified separately by migration checks,
not counted as unit-test business coverage.

### Frontend coverage

The frontend does not yet produce a line-coverage percentage. It is verified by TypeScript,
ESLint, a production build, and two deterministic Playwright journeys. They cover CV import review
and discovery through evidence inspection, CV recommendation approval, CV preview/variant save,
cover-letter generation, versioned editing, approval, and export availability. The application
tracker still relies on compile/lint/build and backend integration coverage; add component coverage
before setting a frontend percentage threshold.

### CV-specific deterministic coverage

Backend tests cover valid extraction through profile version save, exact-evidence rejection,
review-provenance relabelling, deduplication, overlap-safe experience, path traversal guards,
rate limiting, retention, MIME/extension/signature/empty/corrupt/encrypted/scanned failures,
generated filename collisions, merge conflicts, deletion, export, and ownership scoping. PDF
fixtures are generated in memory and no test calls an AI provider.
