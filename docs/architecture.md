# Architecture and data model

## Runtime architecture

The repository contains a React/Vite dashboard and a modular FastAPI API. Pydantic validates
the public boundary, service/domain modules own business rules, SQLAlchemy owns persistence,
and Alembic owns schema evolution. PostgreSQL is used by Compose; SQLite is supported for
native development and deterministic tests.

```mermaid
flowchart LR
  Browser["React review dashboard"] -->|"JSON over HTTP"| Routes["FastAPI routes"]
  Routes --> Services["Application services"]
  Services --> Matching["Deterministic matcher"]
  Services --> Generation["Grounded generation"]
  Services --> ORM["SQLAlchemy session"]
  ORM --> Database[("PostgreSQL or SQLite")]
  Generation --> Mock["Deterministic mock provider"]
  Generation -. "optional development mode" .-> OpenAI["OpenAI Responses API"]
```

The browser never contacts an AI provider. Provider calls are synchronous because the API
currently returns a completed document package. The service ends its read transaction before
the external request, then reacquires and revalidates the application row under a lock before
version allocation and persistence. No queue, worker, Redis, or shared cache exists.

## Module responsibilities

| Module | Responsibility |
| --- | --- |
| `app/main.py` | HTTP routes, dependency wiring, user-scoped resource loading, response compression |
| `app/services.py` | Workflow transitions, audit events, deduplication, analysis and document persistence |
| `app/matching.py` | Pure deterministic scoring and configurable hard blockers |
| `app/ai.py` | Candidate fact construction, prompt boundaries, providers, and grounding validation |
| `app/schemas.py` | Strict request validation and public response contracts |
| `app/models.py` | SQLAlchemy tables, relationships, constraints, and indexes |
| `app/config.py` | Typed environment configuration and production fail-closed guard |

## Deterministic matching

The matcher scores title (15), required skills (25), preferred skills (10), experience (10),
location/remote (10), language (10), EU work authorization (10), salary (5), and industry (5).
Environment variables configure allowed countries and hard-rejection policies. Matching never
changes an application to rejected or submitted; it stores an explanation and advances a newly
discovered application only to `ANALYZED`.

## AI generation and safety

Candidate facts and vacancy content are serialized into separate delimiter-safe data blocks.
The default mock provider is deterministic. OpenAI development mode uses the Responses API to
return only a strict Pydantic plan of existing candidate fact IDs. Application code validates the
plan and renders every document sentence from fixed multilingual templates and stored facts; no
model-authored prose reaches the response. Defense-in-depth validation still checks citations,
numbers, skills, sponsorship semantics, and keyword comparisons. Invalid versions cannot advance
application state. See [`ai-architecture.md`](ai-architecture.md) for every prompt and control.

## Data model

```mermaid
erDiagram
  USERS ||--o| CANDIDATE_PROFILES : owns
  USERS ||--o{ APPLICATIONS : owns
  USERS ||--o{ AUDIT_LOGS : creates
  CANDIDATE_PROFILES ||--o{ PROFILE_SKILLS : has
  CANDIDATE_PROFILES ||--o{ PROFILE_LANGUAGES : has
  CANDIDATE_PROFILES ||--o{ EMPLOYMENT_ENTRIES : has
  JOBS ||--o{ APPLICATIONS : tracks
  APPLICATIONS ||--o{ APPLICATION_STATUS_HISTORY : records
  APPLICATIONS ||--o{ GENERATED_DOCUMENTS : versions
```

Jobs are deduplicated by unique source/external ID, normalized URL, and a stable content hash.
Applications are unique per user/job. Status history and audit logs are append-only records of
workflow actions; generated documents are unique per application/version. Composite indexes
support ordered job, application, and history queries.

## Trust and authorization boundaries

Profile, application, history, and document routes scope queries to the current user dependency.
That dependency currently resolves one fixed local development user and is not authentication.
Jobs form a global catalog in the current single-user design. `APP_ENV=production` rejects
startup until real authentication and tenant ownership are implemented.

Vacancy text, profile free text, imported fields, and provider payloads are untrusted. They are
validated at the API boundary and never interpolated into SQL or system/developer instructions.

## Known scaling boundaries

- Job and application collection endpoints are unpaginated and grow linearly with record count.
- AI generation occupies a request worker while the provider responds; adding background work
  requires a new status/polling contract and durable queue.
- There is no shared response cache; mutable user data is read directly from the database.
- The frontend is intentionally a single-screen application and currently has no separate unit
  coverage threshold.
