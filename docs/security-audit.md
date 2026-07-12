# Security audit

Date: 2026-07-12

## Executive summary

The application is safe for its intended local-development mode after the fixes in this
audit, but it is not ready to accept untrusted network users. It has no authentication
mechanism. Configuration deliberately refuses to start with `APP_ENV=production`, which
keeps that known design gap fail-closed. Production must remain blocked until an
authentication and tenant-ownership design is selected and implemented.

The audit reviewed the API, service and AI boundaries, database access, browser client,
container configuration, environment handling, and automated dependency scans. No file
upload, filesystem path, or server-side URL-fetch functionality exists in the current
product.

## Critical issues

### C1. Authentication is not implemented (open, deployment blocked)

Every request currently resolves a fixed development user. Anyone able to reach the API
would act as that user. Adding an identity provider, session lifecycle, account recovery,
and credential policy would change product and security requirements, so this audit does
not invent that design.

**Compensating control:** `APP_ENV=production` fails validation and prevents startup.
Do not remove that guard until real authentication is implemented and security-tested.

### C2. Production authorization and tenant isolation are not implemented (open,
deployment blocked)

Profile, application, history, and generated-document queries are scoped to the resolved
user, but there is no trustworthy authenticated identity to supply that user. The global
job catalog is consistent with the current single-user design. Production authorization
cannot be completed independently of C1.

**Compensating control:** the same production fail-closed guard prevents exposure.

## High-priority issues

### H1. Prompt boundary injection and model-authored candidate claims (fixed)

Untrusted vacancy content could contain literal closing prompt delimiters. Grounding also
accepted a known skill when a statement cited an unrelated fact, compared numeric claims
by substring, and did not detect sponsorship contradictions.

**Fix:** prompt JSON escapes delimiter-significant characters, and instructions state that both
vacancy content and candidate free text are data only. More importantly, the provider schema no
longer contains prose: it can return only existing fact IDs. Application code validates those IDs
and renders all displayed text from fixed templates plus stored facts. Numeric, skill,
sponsorship, citation, and keyword checks remain as defense in depth. Injection markers are audit
telemetry, not the security boundary.

### H2. Secrets and security-sensitive configuration were insufficiently validated
(fixed)

The OpenAI key was represented as a normal string, OpenAI mode could start without a key,
and CORS accepted arbitrary strings, including wildcard or credential-bearing origins.

**Fix:** API keys use Pydantic `SecretStr`, the provider unwraps the key only at the SDK
boundary, OpenAI mode requires a key at startup, and CORS allows only explicit HTTP(S)
origins without credentials, paths, query strings, or fragments. Compose already requires
the database password through the environment, and `.env` is ignored by source control.

### H3. Request schemas accepted unknown and insufficiently bounded data (fixed)

Pydantic silently ignored extra request properties. Several nested string and mapping
values were unbounded, profile PATCH accepted null for database-required fields, and
employment accepted inverted date ranges. These behaviors increase mass-assignment,
resource-exhaustion, and integrity risk.

**Fix:** all write-request models reject unknown fields; nested list, mapping key/value,
and workplace strings are bounded; required profile collections and scalar fields reject
explicit null; and employment ranges are validated.

### H4. Concurrent application mutations could race (fixed)

Analysis and status-transition writes did not lock the application row. Concurrent
requests could calculate or validate against stale state.

**Fix:** analysis, document generation, and status transitions now acquire a database row
lock before mutation. The existing explicit-approval and audit-log requirements for
submission remain unchanged.

### H5. Local services were exposed on every host interface (fixed)

Docker Compose and the Vite development script listened on all interfaces even though the API
has no authentication. Documentation warned against exposure, but the secure behavior was not
the default.

**Fix:** Compose publishes API and dashboard ports on `127.0.0.1` only, and `pnpm dev` now binds
to loopback. The API runtime image also excludes development dependencies and runs as an
unprivileged user.

## Medium-priority issues

### M1. No rate limiting or abuse quotas (open, production blocked)

The API has no per-user request limits or AI-generation budgets. A correct implementation
depends on the future authenticated identity and deployment topology. Add distributed,
identity-aware limits before enabling production; do not use an in-process counter in a
multi-worker deployment.

### M2. Browser security headers are incomplete at the repository proxy (open)

Nginx sets `nosniff`, referrer policy, and frame denial. CSP and HSTS are deployment- and
domain-specific; HSTS must only be emitted after HTTPS is guaranteed. Configure both at
the TLS edge. React uses escaped text rendering and contains no `dangerouslySetInnerHTML`
usage, so no application XSS sink was found.

### M3. CSRF policy depends on the future authentication mechanism (open)

There is currently no cookie-based authentication, so CSRF cannot grant an attacker an
authenticated capability. If browser cookies are introduced, use `Secure`, `HttpOnly`,
appropriate `SameSite` settings and an origin/CSRF-token check for state-changing routes.

## Low-priority improvements

### L1. Dormant password column

`users.password_hash` is unused. Remove it in a migration if an external identity provider
is selected, or define its hashing and credential lifecycle if local passwords become a
product requirement. It is not currently populated or exposed.

### L2. Add deployment-level request limits

Schema limits bound decoded application data. The production ingress should also cap raw
request-body size, header size, connection count, and request duration to reject oversized
traffic before JSON decoding. Values belong in the deployment configuration selected for
production.

## Attack-surface results

| Area | Result |
| --- | --- |
| Authentication | Missing; production fails closed (C1) |
| Authorization | User-scoped queries exist, but require real identity (C2) |
| Secrets management | Environment-only secrets; API key redacted and startup-validated |
| Environment variables | Typed and bounded settings; production and unsafe CORS fail closed |
| Prompt injection | Untrusted-data boundary escaped; instructions separated; output validated |
| SQL injection | SQLAlchemy expression API used; no raw user SQL; regression payload is stored as data |
| XSS | React escaping used; no raw HTML sink; baseline proxy headers present |
| CSRF | Not applicable without cookies; future requirement documented (M3) |
| SSRF | URLs are stored, never fetched; non-HTTP(S) schemes rejected |
| Path traversal | No user-controlled filesystem paths or filesystem operations |
| File uploads | No upload endpoint or multipart handling exists |
| Sensitive logging | No request/document/contact/secret body logging found; audit events contain metadata |
| AI prompt safety | Provider output is fact IDs only; prose is rendered from validated stored facts |
| User input validation | Unknown fields rejected; scalar, collection, mapping, URL, and date bounds enforced |

## Verification

The security changes are covered by API, configuration, and AI-grounding regression tests.
The hand-off verification includes the complete backend test suite, Ruff, mypy, Bandit,
`pip-audit`, frontend lint/build, and the frontend dependency audit.
