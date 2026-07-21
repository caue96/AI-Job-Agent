# Grounded cover letters

The cover-letter workflow creates complete job-specific drafts from an approved `ProfileVersion`,
the normalized vacancy, and its latest deterministic match result. It never reads the raw CV as its
source of truth, invents a missing qualification, submits an application, or approves a draft for
the user.

## Review workflow

1. Open a ranked opportunity and choose language (automatic, English, Spanish, or Portuguese),
   tone, length, and one or three variants.
2. Generate drafts. The first is selected initially, but selection is editable.
3. Compare variants and inspect cited evidence, known gaps, blockers, match score, and confidence.
4. Edit greeting, paragraphs, or closing. Saving creates a new immutable version linked to its
   parent; it does not overwrite history.
5. Validate. Unsupported numbers, skills, company claims, relocation/sponsorship statements,
   evidence IDs, or user-added proper nouns block approval.
6. Explicitly approve a valid version, then copy it or export TXT, DOCX, or PDF.

Approved or exported versions cannot be deleted. Generating, editing, selecting, validating,
approving, exporting, and deleting drafts write audit events. Approval never changes an application
to `SUBMITTED`.

## Grounding architecture

The configured provider receives escaped JSON data blocks and a developer instruction that marks
candidate and vacancy content as untrusted. Its strict structured output contains evidence IDs only.
Application code then:

- verifies every candidate ID against the approved profile snapshot;
- accepts company facts only when provider metadata explicitly marks each fact and its source as
  verified;
- excludes missing job requirements from candidate evidence;
- renders localized prose from deterministic templates;
- validates the rendered or user-edited document before display and approval.

The prompt is documented in [ai-architecture.md](ai-architecture.md). OpenAI mode uses the existing
timeout, retry, model, token, reasoning, cost, and fallback settings. Mock mode is deterministic and
is used by tests. Provider calls set `store=false`; prompts, CV bodies, vacancy bodies, and generated
letters are not logged.

## Language, tone, and greeting behavior

Automatic language selection considers job language, job country, and candidate languages in that
order. English is the final fallback. Supported tones are professional, confident, concise, warm,
technical, business-oriented, startup-oriented, and corporate.

| Length | Target words |
| --- | ---: |
| Short | 180-250 |
| Standard | 250-400 |
| Detailed | 400-550 |

A verified custom hiring-manager name takes precedence, followed by a verified recruiter contact.
Otherwise the localized generic greeting is used. Unverified names are rejected at the API boundary.

## Storage and retention

Cover-letter versions extend `generated_documents` with document type, job/profile lineage,
configuration, approval, variant, tone, and length fields. `document_exports` stores private storage
keys and integrity metadata. `CV_EXPORT_STORAGE_PATH` uses generated filenames, path-containment
checks, and no static web serving. Export downloads are user-scoped.

Deleting an unapproved draft deletes its export records/files, if any. Approved/exported documents
are retained for audit. Database and export storage must be backed up and restored together.

## Known limitations and troubleshooting

- Company mission, culture, products, and market claims are omitted unless stored as explicitly
  verified company facts.
- Candidate-entered facts can be inaccurate; human review remains mandatory.
- Generation is synchronous and occupies an API worker during an OpenAI call.
- Validation establishes grounding, not hiring effectiveness.
- `409 Candidate profile is required` means the CV/profile workflow is incomplete.
- `409 Approve the cover letter before export` means validation and approval are pending.
- `503 The cover-letter provider request failed` means OpenAI failed and deterministic fallback was
  disabled. Check configuration and provider health before retrying.
- Production startup remains blocked because authentication and tenant isolation are incomplete.

Automated tests use mocks and generated documents only; they never call a live model.
