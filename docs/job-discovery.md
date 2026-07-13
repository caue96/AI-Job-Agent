# Job discovery

## Architecture and trust boundary

`discovery_providers.py` owns the compliance registry, provider contract, allowlisted transport,
retries, rate-limit metadata, and normalization. `discovery.py` owns deterministic search-profile
generation, canonicalization, duplicate detection, hard filters, matching, notifications, and
scheduling. `discovery_api.py` scopes and serializes requests. The optional database-backed worker
calls the same orchestration service.

External job data is untrusted. Responses are size-bounded, only approved HTTPS hosts are reachable,
HTML is converted to plain text, credential-bearing URLs are discarded, and external text never becomes
an AI instruction. The existing deterministic matching engine stores every score component. Unknown
sponsorship is not incompatible when the profile declares EU work authorization.

```mermaid
flowchart LR
  A[Approved CV profile] --> B[Editable multilingual search profile]
  B --> C[Search configuration]
  C --> D[Permitted providers and user imports]
  D --> E[Bounded raw records]
  E --> F[Normalized jobs]
  F --> G[Canonical duplicate groups]
  G --> H[Hard filters and deterministic scoring]
  H --> I[Ranked matches and notifications]
```

Provider failures are isolated in provider-run and safe-error records. A run is `PARTIAL` when another
provider succeeds. Search-run counters, queries, retry counts, API usage, cursors, last success, and
rate-limit state remain inspectable.

## Provider compliance matrix

The registry in `backend/app/discovery_providers.py` is authoritative. An automated adapter cannot be
built unless its registry entry declares automated access and approved hosts.

| Provider | Coverage | Classification | Auth | Automated | Fallback | Status and restriction |
|---|---|---|---|---|---|---|
| LinkedIn Jobs | Global | `MANUAL_URL_IMPORT` | None | No | URL plus description or alert | Fallback only. Official APIs post jobs for approved partners; no general search API or scraping. |
| Tecnoempleo | Spain | `PUBLIC_FEED` | Provider RSS URL | Yes, daily maximum | Description or CSV | Implemented for a user-supplied Tecnoempleo RSS URL; pages are not scraped. |
| ITJobs.pt | Portugal | `OFFICIAL_API` | `ITJOBS_API_KEY` | Yes, daily maximum | Description or CSV | Implemented; the key is requested from ITJobs.pt. |
| Landing.jobs | EU | `EMAIL_ALERT_INGESTION` | Imported alert | No | `.eml`, CSV, description | Fallback only; no documented public search API identified. |
| IrishJobs.ie | Ireland | `EMAIL_ALERT_INGESTION` | Imported alert | No | `.eml`, CSV, description | Fallback only; personalized alert links remain private. |
| InfoJobs | Spain | `OFFICIAL_API` | client ID/secret | Yes, daily maximum | Description or CSV | Implemented with documented public offer operations only. |
| EURES | EU | `DOCUMENTED_PARTNER_API` | Partner authorization | No | URL plus description or CSV | Partner access required; no public vacancy API is assumed. |
| Indeed | Global | `MANUAL_DESCRIPTION_IMPORT` | None | No | Description, CSV, alert | Fallback only; documented APIs are partner workflows, not general aggregation. |
| Wellfound | Global | `EMAIL_ALERT_INGESTION` | Imported alert | No | `.eml` or description | Fallback only; terms prohibit automated scraping. |
| Welcome to the Jungle (Otta successor) | Global | `MANUAL_DESCRIPTION_IMPORT` | None | No | URL plus description or CSV | Fallback only; current terms prohibit scraping and automated copying. |

Provider-controlled references:

- LinkedIn: <https://www.linkedin.com/legal/l/api-terms-of-use> and <https://learn.microsoft.com/en-us/linkedin/talent/job-postings/api/overview>
- Tecnoempleo: <https://www.tecnoempleo.com/ayuda.php>
- ITJobs.pt: <https://www.itjobs.pt/api> and <https://www.itjobs.pt/api/docs/job>
- Landing.jobs: <https://wp.landing.jobs/blog/what-we-shipped-in-the-new-landing-jobs/>
- IrishJobs.ie: <https://www.irishjobs.ie/about/help-and-support>
- InfoJobs: <https://developer.infojobs.net/documentation/operation/offer-list-9.xhtml> and <https://developer.infojobs.net/documentation/app-auth/index.xhtml>
- EURES: <https://eures.europa.eu/employers/advertise-job_en>
- Indeed: <https://docs.indeed.com/api-guides/> and <https://www.indeed.com/legal>
- Wellfound: <https://wellfound.com/terms> and <https://help.wellfound.com/article/782-saved-searches>
- Otta rebrand and current terms: <https://solutions.welcometothejungle.com/en/otta-is-now-welcome-to-the-jungle> and <https://www.welcometothejungle.com/en/pages/terms>

Terms can change. Revalidate the registry before enabling a provider in production.

## Scheduling and operations

Manual runs use `POST /v1/discovery/search-runs`. Daily and weekday schedules store an IANA timezone,
local `HH:MM`, and the next UTC run. A unique scheduled key prevents duplicate execution. Polling is
never configured more frequently than daily per provider. Run once from cron with:

```bash
cd backend
python -m app.discovery_worker --once
```

Or use `docker compose --profile automation up --build`. The optional worker waits for API health and
shares PostgreSQL. No Redis, queue, cache, or browser automation is needed for the current workload.

## Imports, privacy, and retention

Manual URLs are metadata only; the server never retrieves restricted pages. CSV requires
`company,title,description`. Email ingestion accepts a user-imported RFC 5322 message and never asks for
a mailbox password. Only allowlisted provider URLs survive normalization.

Raw results, normalized jobs, matches, and notifications remain until account deletion or an operator's
documented retention process. Credentials are environment-only and excluded from payloads and logs.
Before multi-tenant production, implement authenticated deletion and a scheduled retention policy;
production startup remains intentionally blocked until authentication and ownership review are complete.

## Troubleshooting and limitations

- `CONFIGURATION`: set the required server secret or Tecnoempleo feed URL.
- `UNSAFE_URL`: the URL is not HTTPS or outside the provider allowlist.
- `RESPONSE_TOO_LARGE`: the response exceeded `DISCOVERY_MAX_PROVIDER_RESPONSE_BYTES`.
- Provider failures do not cancel other providers; inspect the safe provider error and retry state.
- Only ITJobs.pt, InfoJobs, and configured Tecnoempleo RSS have automated adapters.
- Generic imported-email parsing treats the readable message body as the description.
- Automated tests never call live providers.
- In-app notification delivery is active; email/other channels are extension points only.
