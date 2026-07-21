# Job-specific CV optimization

This workflow analyzes an approved, immutable `ProfileVersion` against an already-scored job. It
does not edit the master CV and does not infer qualifications from the vacancy.

## Lifecycle

`CV_ANALYSIS_REQUESTED` → `GAP_ANALYSIS_COMPLETED` → `IMPROVEMENTS_PROPOSED` →
`AWAITING_REVIEW` → `RECOMMENDATIONS_APPROVED` → `CV_VARIANT_GENERATED` →
`CV_VARIANT_SAVED`

The current implementation persists the externally visible milestones `CV_ANALYSIS_REQUESTED`,
`AWAITING_REVIEW`, `RECOMMENDATIONS_APPROVED`, and `CV_VARIANT_SAVED`. The intermediate enum
values are reserved for worker-based execution without changing the API contract.

## Grounding and safety

- The source is the latest user-owned `ProfileVersion.snapshot`, not raw PDF text.
- Contact data is excluded from the AI fact catalog. Every editable proposal cites exact stable
  fact IDs and exact evidence text.
- Candidate facts and vacancy text are serialized inside explicit untrusted-data boundaries.
- The model returns a strict Pydantic recommendation plan. It cannot write directly to a CV.
- Deterministic validation rejects unknown fact IDs, altered evidence, unsupported skills,
  metrics, numbers, links, salary claims, and wording not traceable to the cited evidence.
- Missing requirements remain deterministic analysis gaps and are never emitted as CV-edit
  recommendations. Consequently, every recommendation has at least one exact approved-profile
  evidence citation.
- User-edited recommendations pass the same grounding validator before persistence.
- Invalid provider recommendations are omitted and summarized in the analysis validation record.

The deterministic offline provider is the default. In OpenAI mode, the system uses the same
configured structured-output model, timeout, retry, and fallback settings as document generation.
The prompt version is `cv-optimization-evidence-plan-v2` and exists only to select safe presentation
changes from the supplied facts.

## Review, variants, and scores

Recommendations are independently accepted, rejected, or edited. Each decision creates an
append-only history record. “Accept safe edits” accepts every validated, evidence-backed proposal;
qualification gaps remain read-only analysis data.

Variant content is a deep copy of the approved snapshot. Supported edits cover headline and summary
wording, deterministic skill/language ordering, grounded employment bullets, and relevant
employment/project/education/certification ordering. A version records applied and rejected
recommendation IDs, user edits, remaining gaps and blockers, and validation results. The original
deterministic match score remains unchanged: presentation improvements do not create qualifications.

## Exports and retention

Validated variants can be rendered deterministically to PDF or DOCX. Files use random storage
keys under `CV_EXPORT_STORAGE_PATH`, are never placed below the frontend static root, and are only
downloadable through a user-scoped API query. Deleting a variant removes its export files. Export
records store SHA-256 and byte size; generated document bodies are not logged.
The dashboard previews the revised content before saving it as approved; draft variants created by
other API clients cannot be exported until they are approved.

## Known limitations

- The product remains local-development only because production authentication and tenant review
  are intentionally blocked by the startup guard.
- Optimization execution is synchronous. The schema and lifecycle support later worker execution,
  but no new queue was introduced without operational ownership.
- Rich free-form rewrites are intentionally conservative. Unsupported paraphrases are discarded;
  truthfulness takes precedence over stylistic variety.
- The approved structured profile does not retain enough original PDF layout information to grade
  columns, tables, graphics, or visual ATS parsing reliably. The system reports no ATS guarantee.
- A variant currently has one immutable generated version. Regeneration requires a fresh analysis.
