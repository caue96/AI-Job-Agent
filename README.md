# EU Job Agent

An approval-first workspace for importing vacancies, scoring them deterministically, preparing
grounded application material, and tracking manual job applications. The system never submits
an application automatically.

The profile workflow accepts text-based PDF CVs, validates and stores them under generated names,
extracts page-grounded candidate facts, and requires an editable review plus explicit merge or
replace confirmation before anything reaches the candidate profile.

## Current status

Phases 2–6 are implemented:

- FastAPI, SQLAlchemy, Alembic, PostgreSQL/SQLite configuration;
- candidate profiles, normalized jobs, applications, history, and audit events;
- deterministic matching with configurable hard-rejection rules and explainable scores;
- grounded AI document generation with mock and OpenAI provider modes;
- a React review dashboard with an explicit submission-approval workflow;
- secure PDF CV upload, extraction, evidence review, merge/replace, and profile version history;
- compliant job discovery through documented APIs/public feeds and user-authorized imports, with
  multilingual search profiles, duplicate merging, schedules, explainable rankings, and notifications;
- security, performance, coverage, migration, and dependency quality gates.

Version 1.0 is a local-only release. Authentication and tenant isolation are not implemented,
and `APP_ENV=production` intentionally prevents startup. Do not expose the API to untrusted
networks.

Provider access decisions, scheduling, imports, retention, and troubleshooting are documented in
[`docs/job-discovery.md`](docs/job-discovery.md).

## Prerequisites

Choose one workflow:

- Docker Compose: Docker Engine/Desktop with Compose v2.
- Native development: Python 3.12, Node.js 22, and Corepack. The repository pins pnpm through
  `frontend/package.json`.

## Quick start with Docker Compose

1. Copy `.env.example` to `.env`.
2. Set `POSTGRES_PASSWORD` to a non-empty, URL-safe development password.
3. Keep `APP_ENV=development` and `AI_GENERATION_MODE=mock` for the first run.
4. Start the stack:

```bash
docker compose config -q
docker compose up --build
```

Compose waits for PostgreSQL, applies all Alembic migrations, then starts the API. Open:

- Dashboard: <http://localhost:5173>
- API documentation: <http://localhost:8000/docs>
- Health check: <http://localhost:8000/health>

Compose publishes both HTTP ports on `127.0.0.1` only. Changing those bindings exposes an
unauthenticated development service and is unsupported.

## Native local setup

From `backend/`, create a virtual environment, install development dependencies, copy the
environment template into that directory, and use SQLite:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item ..\.env.example .env
$env:DATABASE_URL = "sqlite:///./job_agent.db"
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

In another terminal:

```powershell
cd frontend
corepack enable
pnpm install --frozen-lockfile
$env:VITE_API_URL = "http://localhost:8000"
pnpm dev
```

The dashboard is then available at <http://localhost:5173>. See the
[deployment guide](docs/deployment.md) for POSIX commands, verification, shutdown, and reset
instructions.

## Quality commands

```bash
cd backend
ruff format --check app tests
ruff check .
mypy app
pytest -q --cov=app --cov-branch --cov-report=term-missing --cov-fail-under=80
coverage report --include='app/ai.py,app/matching.py,app/services.py' --fail-under=90
bandit -q -r app
pip-audit --skip-editable
DATABASE_URL=sqlite:///./migration_check.db alembic upgrade head
DATABASE_URL=sqlite:///./migration_check.db alembic check

cd ../frontend
pnpm lint
pnpm build
pnpm test:e2e
pnpm audit --audit-level high
```

## Documentation

- [Architecture and data model](docs/architecture.md)
- [API reference](docs/api.md)
- [Environment configuration](docs/configuration.md)
- [Local and container deployment](docs/deployment.md)
- [Provider integration](docs/providers.md)
- [AI architecture and prompt registry](docs/ai-architecture.md)
- [CV import workflow and operations](docs/cv-import.md)
- [Roadmap and limitations](docs/roadmap.md)
- [Production-readiness review](docs/production-readiness-review.md)
- [Security audit](docs/security-audit.md)
- [Performance profile](docs/performance-profile.md)
- [Test coverage](docs/test-coverage.md)
- [Dependency audit](docs/dependency-audit.md)
- [First-time UX review](docs/ux-review.md)
- [Changelog](CHANGELOG.md)

## Safety invariants

- Vacancy text, imported fields, candidate free text, and provider payloads are untrusted data,
  never instructions.
- Providers select structured candidate fact IDs only; application code renders the prose and
  validates provenance before display.
- No path can reach `SUBMITTED` without a validated status-history transition and explicit user
  approval recorded in audit metadata.
- Contact data, document bodies, authorization details, and secrets must not be logged.
