# Engineering conventions

## Stack and boundaries

- Use Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, and Alembic in `backend/`.
- Use Node.js 22, React, TypeScript, Vite, and pnpm in `frontend/`.
- Keep route handlers thin. Business rules belong in `services.py`, `matching.py`, `ai.py`, or
  a focused domain/service module.
- Use SQLAlchemy expressions and parameter binding; do not construct SQL from user input.
- Add an Alembic migration for every schema or index change and keep ORM metadata synchronized.
- Preserve API compatibility unless the task explicitly authorizes a contract change.

## Security and AI invariants

- Treat job descriptions, imported fields, candidate free text, and all provider payloads as
  untrusted data. They must never influence system or developer instructions.
- Never invent candidate qualifications. Generated content must be grounded to structured
  profile facts, cite fact IDs, and pass validation before display.
- No path may transition an application to `SUBMITTED` without a status-history record and
  explicit approval recorded in audit metadata.
- Scope profile, application, history, and document access to the current user dependency.
- Do not log contact data, document bodies, authorization details, credentials, or secrets.
- Keep secrets in environment variables. Never commit `.env` or real provider credentials.
- `APP_ENV=production` must remain fail-closed until authentication and tenant ownership are
  implemented and reviewed.

## Testing and quality

- Add deterministic tests for new behavior and bug fixes. Do not call live AI providers in
  tests and do not use snapshots where direct assertions express the rule.
- Maintain at least 80% branch-aware backend coverage overall and 90% across `app/ai.py`,
  `app/matching.py`, and `app/services.py`.
- Before hand-off, run from `backend/`:

```bash
ruff format --check app tests
ruff check .
mypy app
pytest -q --cov=app --cov-branch --cov-report=term-missing --cov-fail-under=80
coverage report --include='app/ai.py,app/matching.py,app/services.py' --fail-under=90
bandit -q -r app
```

- For dependency, migration, or frontend changes, also run the applicable checks:

```bash
pip-audit --skip-editable
DATABASE_URL=sqlite:///./migration_check.db alembic upgrade head
cd ../frontend && pnpm lint && pnpm build && pnpm audit --audit-level high
```

## Documentation and operations

- Update README, API, configuration, architecture, provider, and deployment documentation when
  their contracts change.
- Document every environment variable, including whether it is runtime, Compose-only, or
  frontend build-time configuration.
- Do not claim production readiness while the production startup guard is active.
- Do not introduce queues, caches, provider adapters, or external infrastructure without a
  concrete product workload and operational ownership.

## Definition of done

Changes include tests for behavior, migrations for schema changes, input validation,
authorization checks, updated API/configuration documentation where applicable, and a
successful local verification run. The hand-off identifies any check that could not run and
why.
