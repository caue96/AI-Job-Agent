# Dependency audit

Audit date: 2026-07-12

## Method and result

Every dependency declared directly in `backend/pyproject.toml` and
`frontend/package.json` was traced to code, configuration, tests, or CI. Registry metadata was
checked against PyPI and npm, the Python environment was rebuilt from scratch, and both complete
resolved dependency trees were scanned with `pip-audit` and `pnpm audit`.

- Unused direct packages removed: **none**.
- Abandoned direct packages replaced: **none**; every direct package has a current registry
  release. The deprecated Starlette TestClient fallback to HTTPX was proactively replaced by
  its supported `httpx2` backend.
- Known vulnerabilities in the resolved Python environment: **0**.
- Known vulnerabilities in the resolved frontend tree: **0**.
- Direct-license blockers found: **none**. Psycopg is LGPL-3.0-only; all other direct packages
  use permissive MIT, BSD-3-Clause, Apache-2.0, or Unlicense terms.

Vulnerability results are a point-in-time registry/advisory snapshot, not a guarantee that no
future advisory will be published. CI reruns both audits on every push and pull request.

## Backend runtime dependencies

| Dependency | Allowed version | Why it exists | License | Known CVEs |
| --- | --- | --- | --- | --- |
| Alembic | `>=1.18.5,<2` | Owns schema migrations and is invoked by Compose and CI. | MIT | None found |
| defusedxml | `>=0.7.1,<1` | Safely parses untrusted provider RSS without XML entity expansion. | Python-2.0 | None found |
| FastAPI | `>=0.139,<1` | HTTP routing, dependency injection, middleware integration, OpenAPI, and test client integration. | MIT | None found |
| email-validator | `>=2.3,<3` | Required by Pydantic's `EmailStr` profile validation. | Unlicense | None found |
| OpenAI | `>=2.45,<3` | Optional Responses API provider for grounded document generation. Imported only in OpenAI mode. | Apache-2.0 | None found |
| Pydantic | `>=2.13.4,<3` | Directly imported for strict request/response schemas, validation, and redacted secrets. It is now explicitly declared instead of relying on FastAPI transitively. | MIT | None found |
| pydantic-settings | `>=2.14.2,<3` | Typed environment and `.env` loading. | MIT | None found |
| Psycopg with binary extra | `>=3.3.4,<4` | PostgreSQL SQLAlchemy driver used by the Compose database URL; the binary extra provides local wheels. | LGPL-3.0-only | None found |
| pypdf | `>=6.13.3,<7` | Maintained direct-text PDF reader used for bounded page extraction and encrypted/corrupt detection; it does not execute embedded content. | BSD-3-Clause | None found |
| python-multipart | `>=0.0.31,<0.0.32` | FastAPI multipart parser required for the single streamed CV file field. Version 0.0.31 fixes CVE-2026-40347, CVE-2026-42561, CVE-2026-53538, CVE-2026-53539, and CVE-2026-53540; the upper bound avoids the incompatible 0.0.32 namespace layout observed with the current FastAPI runtime. | Apache-2.0 | None in the allowed range |
| SQLAlchemy | `>=2.0.51,<3` | ORM models, sessions, transactions, row locking, and parameterized queries. | MIT | None found |
| Uvicorn with standard extra | `>=0.51,<1` | ASGI server used by native setup and the API container; standard extras provide production event-loop/protocol support. | BSD-3-Clause | None found |

## Backend development dependencies

| Dependency | Allowed version | Why it exists | License | Known CVEs |
| --- | --- | --- | --- | --- |
| Bandit | `>=1.9.4,<2` | Python static security analysis in CI and hand-off checks. | Apache-2.0 | None found |
| httpx2 | `>=2.5,<3` | Supported transport for FastAPI/Starlette's synchronous `TestClient`, replacing its deprecated HTTPX fallback. | BSD-3-Clause | None found |
| mypy | `>=2.2,<3` | Static type checking for backend application modules. | MIT | None found |
| pip-audit | `>=2.10.1,<3` | Audits the resolved Python environment against PyPI vulnerability advisories. | Apache-2.0 | None found |
| pytest | `>=9.1.1,<10` | Deterministic unit and API test runner. | MIT | None found |
| pytest-cov | `>=7.1,<8` | Integrates branch-aware Coverage.py measurement with pytest. | MIT | None found |
| Ruff | `>=0.15.21,<1` | Formatter and lint gate. | MIT | None found |

## Frontend runtime dependencies

| Dependency | Pinned version | Why it exists | License | Known CVEs |
| --- | ---: | --- | --- | --- |
| React | `19.2.7` | Component/state model for the dashboard. | MIT | None found |
| React DOM | `19.2.7` | Mounts and renders the React application in the browser DOM. | MIT | None found |

## Frontend development dependencies

| Dependency | Pinned version | Why it exists | License | Known CVEs |
| --- | ---: | --- | --- | --- |
| @types/react | `19.2.17` | TypeScript declarations for React. | MIT | None found |
| @playwright/test | `1.58.2` | Browser-level test of the upload, review, edit, and confirmation workflow. It is development-only. | Apache-2.0 | None found |
| @types/react-dom | `19.2.3` | TypeScript declarations for React DOM. | MIT | None found |
| @vitejs/plugin-react | `6.0.3` | React JSX transform and refresh integration in Vite. | MIT | None found |
| ESLint | `10.7.0` | Frontend static lint runner. | MIT | None found |
| eslint-plugin-react-hooks | `7.1.1` | Enforces rules-of-hooks and effect dependency checks. | MIT | None found |
| TypeScript | `5.9.3` | Static compilation and type checking. | Apache-2.0 | None found |
| typescript-eslint | `8.63.0` | TypeScript parser and recommended ESLint rules. | MIT | None found |
| Vite | `8.1.4` | Development server and production frontend bundler. | MIT | None found |

The package manager is pinned separately as pnpm `11.12.0` through the `packageManager` field.
It is a build tool, not an installed project dependency.

## Changes made

- Added Pydantic as a direct backend dependency because application code imports it directly.
- Raised all Python minimum versions to the versions resolved and tested during this audit.
- Upgraded mypy from the 1.x line to 2.2.0 and verified the complete type check.
- Raised the pytest floor from 9.0.3 to 9.1.1.
- Replaced the direct HTTPX test dependency with httpx2 2.5.0, as required by current
  Starlette. HTTPX remains an OpenAI SDK transitive dependency, not a direct test dependency.
- Upgraded ESLint from 10.6.0 to 10.7.0 and regenerated the frozen pnpm lockfile.
- Updated the pnpm toolchain pin from 11.7.0 to 11.12.0.
- Corrected CI to audit the installed Python environment rather than an empty local-project
  target, and to include frontend development dependencies instead of production packages only.

The resolved frontend tree uses MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause, ISC, MPL-2.0,
and BlueOak-1.0.0 licenses. The MPL/BlueOak packages are transitive build-tool dependencies;
no GPL or AGPL package was reported in the frontend lockfile.

## Deliberately held upgrade

TypeScript 7.0.2 is available, but it is a major-version upgrade while the current
TypeScript-ESLint/Vite combination is validated on TypeScript 5.9.3. It was not classified as a
safe dependency refresh. Upgrade it in a dedicated change after the toolchain declares compatible
peer ranges and the frontend compile/lint behavior is reviewed.

## Reproduction commands

```bash
cd backend
python -m pip install -e '.[dev]'
mypy app
pytest -q --cov=app --cov-branch
bandit -q -r app
pip-audit --skip-editable

cd ../frontend
pnpm install --frozen-lockfile
pnpm outdated
pnpm audit --json
pnpm lint
pnpm build
pnpm test:e2e
```
