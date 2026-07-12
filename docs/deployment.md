# Local setup and deployment guide

## Deployment status

The repository supports reproducible local development with Docker Compose or native tools.
It does **not** support production deployment yet: `APP_ENV=production` deliberately fails
startup because authentication and tenant isolation are absent. Keep the API bound to trusted
local development networks.

## Docker Compose setup from scratch

Prerequisites: Docker Engine/Desktop with Compose v2 and ports 5173 and 8000 available.

1. From the repository root, create the local environment file:

```powershell
Copy-Item .env.example .env
```

POSIX equivalent:

```bash
cp .env.example .env
```

2. Edit `.env` and set a non-empty, URL-safe `POSTGRES_PASSWORD`. Keep these first-run values:

```dotenv
APP_ENV=development
AI_GENERATION_MODE=mock
CORS_ORIGINS=http://localhost:5173
```

3. Validate interpolation and start the stack:

```bash
docker compose config -q
docker compose up --build
```

The database health check must pass before the API starts. The API command automatically runs
`alembic upgrade head`; do not run a second migration process concurrently.

Both published ports are bound to `127.0.0.1`. Do not replace the loopback bindings with
all-interface bindings while authentication is absent.

4. Verify the services:

```bash
curl http://localhost:8000/health
curl -I http://localhost:5173/
```

Expected API response: `{"status":"ok"}`. Interactive OpenAPI documentation is at
<http://localhost:8000/docs>.

5. Stop without deleting data:

```bash
docker compose down
```

To deliberately delete the local PostgreSQL volume and start clean:

```bash
docker compose down --volumes
```

## Native setup from scratch

Prerequisites: Python 3.12, Node.js 22, Corepack, and ports 5173 and 8000 available.

### Backend on Windows PowerShell

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item ..\.env.example .env
$env:DATABASE_URL = "sqlite:///./job_agent.db"
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Backend on POSIX shells

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
cp ../.env.example .env
export DATABASE_URL='sqlite:///./job_agent.db'
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The local SQLite path is relative to `backend/`. Alembic creates the schema; application code
does not call `create_all` at startup.

### Frontend

In a second terminal:

```bash
cd frontend
corepack enable
pnpm install --frozen-lockfile
pnpm dev
```

`VITE_API_URL` defaults to `http://localhost:8000`. Set it before `pnpm dev` or `pnpm build` if
the API uses another origin. Any custom frontend origin must also be present in
`CORS_ORIGINS` before the backend starts.

## Verification and migrations

Run migrations against an explicit disposable URL when checking the migration chain:

```bash
cd backend
DATABASE_URL=sqlite:///./migration_check.db alembic upgrade head
DATABASE_URL=sqlite:///./migration_check.db alembic check
```

On PowerShell:

```powershell
cd backend
$env:DATABASE_URL = "sqlite:///./migration_check.db"
alembic upgrade head
alembic check
```

Run the complete quality commands from the README before hand-off. Back up any persistent
database before upgrading it. Alembic downgrade paths exist for development but are not a
substitute for a backup and restore plan.

## OpenAI development mode

Set `AI_GENERATION_MODE=openai` and provide `OPENAI_API_KEY`. The API validates the key at
startup, reuses one SDK client per process, and applies the configured timeout/retry values.
Generated output remains subject to structured parsing and deterministic grounding validation.
Use `mock` mode for tests and offline development.

## Production prerequisites

Do not remove the production startup guard until all of the following have reviewed designs
and tests:

- authenticated sessions or OIDC and tenant ownership on every resource;
- identity-aware distributed rate limiting and AI budgets;
- managed PostgreSQL, TLS termination, secret management, backups, and recovery drills;
- structured redacted logging, metrics, tracing, and alerting;
- deployment-specific CSP, HSTS, request-size, connection, and timeout controls;
- PostgreSQL migration/integration tests and a release migration strategy;
- a reviewed release topology and image-signing/provenance process.

The current Compose file is a local development topology, not a production manifest.
