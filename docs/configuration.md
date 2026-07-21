# Environment configuration

Discovery runtime variables are `ITJOBS_API_KEY`, `INFOJOBS_CLIENT_ID`, `INFOJOBS_CLIENT_SECRET`,
`DISCOVERY_PROVIDER_TIMEOUT_SECONDS`, `DISCOVERY_MAX_PROVIDER_RESPONSE_BYTES`, and
`DISCOVERY_SCHEDULER_POLL_SECONDS`. Secrets are server-only, masked, and never persisted. A Tecnoempleo
feed URL is a per-search, non-secret setting.

The backend uses Pydantic Settings. Variable names are case-insensitive and are read from the
process environment or a `.env` file in the backend's current working directory. Docker Compose
loads the repository-root `.env` explicitly.

## Backend runtime variables

| Variable | Default | Validation and purpose |
| --- | --- | --- |
| `APP_ENV` | `development` | `development`, `test`, or `production`. Production intentionally fails startup until authentication and tenant isolation exist. |
| `DATABASE_URL` | `sqlite:///./job_agent.db` | SQLAlchemy URL. Compose overrides this with its PostgreSQL service URL. |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated explicit HTTP(S) origins. Wildcards, credentials, paths, queries, and fragments are rejected. |
| `OPENAI_API_KEY` | unset | Secret required only when `AI_GENERATION_MODE=openai`; represented as a redacted secret value. |
| `OPENAI_MODEL` | `gpt-5.4-mini-2026-03-17` | Snapshot used for structured relevance selection. Override only after evaluation. |
| `OPENAI_REASONING_EFFORT` | `none` | `none`, `low`, `medium`, or `high`; selection defaults to the lowest-latency setting. |
| `AI_GENERATION_MODE` | `mock` | `mock` for deterministic local generation or `openai` for the configured external provider. |
| `AI_MAX_RETRIES` | `1` | SDK retry count, from 0 through 2. Deterministic fallback makes long retry chains unnecessary. |
| `AI_REQUEST_TIMEOUT_SECONDS` | `45` | Per-attempt provider timeout greater than 0 and no more than 120 seconds. |
| `AI_MAX_OUTPUT_TOKENS` | `800` | Structured-plan output cap, from 100 through 4,000 tokens. |
| `AI_MAX_JOB_DESCRIPTION_CHARS` | `12000` | Maximum vacancy-description characters sent to the provider, from 1,000 through 50,000. |
| `AI_FALLBACK_TO_MOCK` | `true` | On provider or plan failure, use deterministic fact selection instead of returning 502. |
| `AI_INPUT_COST_PER_MILLION_USD` | `0` | Non-negative accounting rate used to estimate request cost. It does not control provider billing. |
| `AI_CACHED_INPUT_COST_PER_MILLION_USD` | `0` | Non-negative cached-input accounting rate used when the provider reports cached tokens. |
| `AI_OUTPUT_COST_PER_MILLION_USD` | `0` | Non-negative accounting rate used to estimate response cost. |
| `CV_STORAGE_PATH` | `./data/cv_uploads` | Runtime directory for private generated PDF keys. Compose overrides it with `/app/data/cv_uploads`. Never place this under a static web root. |
| `CV_EXPORT_STORAGE_PATH` | `./data/cv_exports` | Runtime directory for private job-specific CV and cover-letter TXT/PDF/DOCX exports. Compose mounts `/app/data/cv_exports`. Never place this under a static web root. |
| `CV_MAX_UPLOAD_BYTES` | `10485760` | Streamed PDF size limit, from 1 KB through 25 MB. The UI advertises the default 10 MB limit. |
| `CV_MAX_PAGES` | `40` | Maximum PDF page count, from 1 through 200. |
| `CV_MIN_EXTRACTED_CHARACTERS` | `80` | Non-whitespace text below this threshold marks the PDF as likely scanned instead of invoking AI. |
| `CV_RETENTION_DAYS` | `30` | Uploaded-file retention, from 1 through 3,650 days. Expired files are purged when an upload begins; records remain. |
| `CV_UPLOADS_PER_MINUTE` | `10` | Per-user, process-local upload attempt limit, from 1 through 120. Suitable only for the local single-process release. |
| `MATCHING_PERMITTED_COUNTRIES` | `ES,PT,IE` | Comma-separated two-letter alphabetic country codes, normalized and deduplicated at startup. |
| `MATCHING_ALLOW_REMOTE` | `true` | Enables remote-work matching. |
| `MATCHING_HARD_REJECT_MISSING_REQUIRED_SKILLS` | `false` | Converts missing recognized required skills into hard blockers. |
| `MATCHING_HARD_REJECT_MISSING_LANGUAGE` | `true` | Converts a missing required language into a hard blocker. |
| `MATCHING_HARD_REJECT_SALARY_BELOW_MIN` | `true` | Hard-blocks jobs whose known maximum is below the profile minimum. |
| `MATCHING_HARD_REJECT_OUTSIDE_LOCATION` | `true` | Hard-blocks incompatible location/remote results. |
| `MATCHING_HARD_REJECT_SENIORITY_GAP` | `true` | Hard-blocks experience gaps beyond the configured tolerance. |
| `MATCHING_HARD_REJECT_INCOMPATIBLE_WORK_AUTHORIZATION` | `true` | Hard-blocks a vacancy whose authorization requirement is incompatible with the profile. |
| `MATCHING_SENIORITY_GAP_YEARS` | `2` | Non-negative seniority tolerance, maximum 20 years. |

## Docker Compose variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `POSTGRES_DB` | `jobagent` | Database created by the PostgreSQL container. |
| `POSTGRES_USER` | `jobagent` | PostgreSQL role used by the API. |
| `POSTGRES_PASSWORD` | none; required | Required by Compose interpolation. Use a non-empty URL-safe local password because it is interpolated into `DATABASE_URL`. |

Compose supplies its own PostgreSQL `DATABASE_URL` to the API, so the SQLite value in
`.env.example` is used only by native development.

## Frontend build-time variable

| Variable | Default | Purpose |
| --- | --- | --- |
| `VITE_API_URL` | `http://localhost:8000` | API base URL compiled into the Vite bundle. Set it in the shell before `pnpm dev` or `pnpm build`. The current Compose topology uses the default localhost URL. |

Vite variables are build-time values, not backend runtime secrets. Never put an API key or
credential in a `VITE_*` variable because it becomes public browser code.

## Safe examples

Local deterministic development:

```dotenv
APP_ENV=development
DATABASE_URL=sqlite:///./job_agent.db
CORS_ORIGINS=http://localhost:5173
AI_GENERATION_MODE=mock
CV_STORAGE_PATH=./data/cv_uploads
CV_EXPORT_STORAGE_PATH=./data/cv_exports
```

OpenAI development mode:

```dotenv
APP_ENV=development
AI_GENERATION_MODE=openai
OPENAI_API_KEY=replace-locally
OPENAI_MODEL=gpt-5.4-mini-2026-03-17
OPENAI_REASONING_EFFORT=none
AI_REQUEST_TIMEOUT_SECONDS=45
```

Do not commit populated `.env` files. `.env.example` is the canonical non-secret template.
