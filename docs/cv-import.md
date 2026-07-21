# PDF CV import

## User workflow

1. Select or drop one `.pdf` file (10 MB and 40 pages by default).
2. The API validates extension, MIME type, `%PDF-` signature, size, page count, encryption, and
   readability before parsing.
3. Text is extracted per page. A low-text document is marked as likely scanned; OCR is not enabled.
4. Deterministic section detection runs before one constrained structured extraction request.
5. Every provider fact must cite an exact excerpt and page. Unsupported provider output is removed
   and listed in validation metadata.
6. The user reviews and edits every section. Corrected or added values are explicitly relabelled as
   user-confirmed rather than provider-extracted.
7. An existing profile is compared before save. Merge keeps existing conflicting scalar values and
   requires explicit conflict acknowledgement; replace overwrites supported profile fields.
8. Confirmation creates an immutable `profile_versions` snapshot and audit event. The import reaches
   `PROFILE_SAVED` only after both are persisted in one transaction.

The states are `PDF_SELECTED`, `PDF_VALIDATED`, `TEXT_EXTRACTED`, `PROFILE_PARSED`,
`AWAITING_REVIEW`, `PROFILE_CONFIRMED`, and `PROFILE_SAVED`. Selection is a client state; persisted
imports begin after server validation. Synchronous processing may move across several states in one
request, while the stored result always records the last completed state.

## Extraction and grounding

`pypdf` performs direct text extraction; no PDF content is executed. `app.cv.identify_sections`
provides a deterministic layout hint. In mock mode, a conservative local parser extracts contact
details and a bounded skill vocabulary. In OpenAI mode, the Responses API uses
`CvProfileDraft` structured output and the prompt registered as `grounded-cv-extraction-v1`.

PDF text is always untrusted data. The developer instruction says it is data rather than
instructions, and the payload is JSON escaped inside a data boundary. More importantly, application
code independently checks that every non-null provider field has an exact quote on its cited page.
This makes unsupported provider claims unavailable to the review UI. User corrections are retained
with `method=user`, which distinguishes consented profile data from extracted claims.

Dates are normalized only when parseable as `YYYY` or `YYYY-MM`. Duplicate list facts are removed
case-insensitively. Calculated experience uses the union of covered months, so overlapping jobs are
not double counted. Declared and calculated experience remain separate in the version snapshot.

## Master and job-specific versions

Confirmed imports create immutable master `ProfileVersion` snapshots. Job-specific optimization
never edits these records: it deep-copies one approved snapshot into a separately versioned
`CvVariant`. Users preview the copy, explicitly save it, and can export it without changing future
matching inputs. See [cv-optimization.md](cv-optimization.md) for the complete review and variant
lifecycle.

## Storage, privacy, and retention

`LocalCvStorage` is rooted at `CV_STORAGE_PATH`. It accepts generated `<uuid>.pdf` keys only and
verifies the resolved parent directory before every access. The original name is metadata, never a
path. Writes use exclusive creation and stream through a size bound while calculating SHA-256.
Hashes and extracted page text are not returned by normal read APIs. Document bodies, contact data,
and storage paths are excluded from logs and audit metadata.

Compose mounts `cv_uploads` at `/app/data/cv_uploads`. Native development defaults to
`backend/data/cv_uploads`, which is ignored by Git. Files older than `CV_RETENTION_DAYS` are deleted
when a new upload starts; records and approved version snapshots remain. Users can also delete an
uploaded file immediately or delete the import record and file together. Filesystem deletion is
best effort; secure overwrite cannot be guaranteed on copy-on-write filesystems or SSDs.

Back up the database and CV volume according to the same privacy classification. Restrict volume
access to the API identity. Never serve this directory from Nginx or a static file route.

## Failure recovery

- Wrong type, signature, size, page count, empty, corrupt, unreadable, and encrypted files return
  HTTP 422 with an actionable message; partially stored files are removed.
- Likely scanned PDFs return a persisted `TEXT_EXTRACTED` record with `scanned_likely=true` so the
  UI can recommend a text-based export. OCR remains a future opt-in capability.
- Provider failure returns HTTP 503 and removes the stored file and incomplete record. When
  `AI_FALLBACK_TO_MOCK=true`, deterministic parsing is used instead.
- Draft validation errors return HTTP 422. Missing/invalid name or email blocks confirmation with
  HTTP 409. Merge conflicts also return 409 until explicitly acknowledged.
- Upload rate limiting is process-local because the product is local-only. A multi-worker release
  requires a shared authenticated rate limiter; production startup remains intentionally disabled.

## Manual verification

Use a normal text PDF, a blank scanned PDF, an encrypted PDF, and a renamed non-PDF. Confirm that
only the text PDF reaches review, evidence opens to exact page excerpts, editing changes the value to
user-confirmed provenance, merge conflicts require acknowledgement, and file deletion makes
`file_available` false without deleting the saved profile version.
