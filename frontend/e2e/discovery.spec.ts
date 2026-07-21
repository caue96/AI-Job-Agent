import { expect, test } from "@playwright/test";

const profile = {
  id: "search-profile-1",
  generated_terms: ["Data Analyst", "Analista de Datos", "Analista de Dados"],
  preferences: {
    target_titles: ["Data Analyst"], alternative_titles: ["Analista de Datos"],
    seniority_levels: [], technical_skills: ["SQL", "Power BI"], business_skills: [],
    languages: ["English"], preferred_countries: ["ES", "PT"], preferred_cities: ["Madrid", "Porto"],
    workplace_preferences: ["REMOTE", "HYBRID"], work_authorization: ["EU"],
    sponsorship_required: false, relocation_available: true, minimum_salary: 35000,
    salary_currency: "EUR", preferred_industries: [], excluded_industries: [], excluded_companies: [],
    excluded_keywords: [], required_keywords: [], optional_keywords: [],
  },
  created_at: "2026-07-12T10:00:00Z", updated_at: "2026-07-12T10:00:00Z",
};
const configuration = {
  id: "config-1", name: "EU roles", enabled: true,
  provider_settings: { itjobs: { enabled: true } }, schedule_kind: "WEEKDAYS",
  schedule_time: "09:00", timezone: "Europe/Lisbon", hard_filters: { minimum_score: 50 },
  next_run_at: "2026-07-13T08:00:00Z", last_run_at: null,
  created_at: "2026-07-12T10:00:00Z", updated_at: "2026-07-12T10:00:00Z",
};
const match = {
  id: "job-1", match_id: "match-1", title: "Data Analyst", company: "Acme", country: "PT",
  city: "Porto", provider: "itjobs", url: "https://www.itjobs.pt/oferta/data-analyst",
  workplace_type: "REMOTE", posted_at: "2026-07-12T10:00:00Z", salary_min: 40000,
  salary_max: 50000, salary_currency: "EUR", score: 92, recommendation: "STRONG_MATCH",
  hard_rejected: false, user_state: "NEW", analysis: { matching_skills: ["sql", "power bi"],
    missing_required_skills: [], potential_blockers: [], reasons_to_apply: ["Skills and location match."],
    reasons_not_to_apply: [], score_by_category: { job_title: { score: 15, maximum: 15, explanation: "Preferred title matches." } } },
};

test("configures and runs discovery then shows a canonical strong match", async ({ page }) => {
  let recommendationDecision = "PENDING";
  let variantSaved = false;
  let analysisCreated = false;
  let coverLetters: Record<string, unknown>[] = [];
  let coverLetterVersion = 1;
  const recommendation = {
    id: "recommendation-1", category: "HEADLINE", section: "headline",
    current_text: "Data Analyst", suggested_text: "Data Analyst | Targeting Data Analyst",
    reason: "Align the verified headline.", expected_benefit: "Improves scanability.",
    related_job_requirement: "Data Analyst", confidence: .98, priority: "HIGH",
    recommendation_type: "REWRITE", approval_required: true, decision: recommendationDecision,
    user_text: null, validation: { valid: true, issues: [] }, display_order: 0,
    evidence: [{ id: "evidence-1", fact_id: "candidate:headline", source_section: "headline", quote: "Data Analyst" }],
  };
  const analysis = () => ({
    id: "analysis-1", job_id: "job-1", profile_version_id: "profile-version-1",
    match_result_id: "match-1", status: "AWAITING_REVIEW", original_score: 92,
    input_summary: {}, validation: { valid: true }, prompt_version: "cv-optimization-evidence-plan-v2",
    model: "mock", recommendations: [{ ...recommendation, decision: recommendationDecision }],
    created_at: "2026-07-12T10:00:00Z", updated_at: "2026-07-12T10:00:00Z",
  });
  const variant = {
    id: "variant-1", job_id: "job-1", status: "APPROVED", analysis_run_id: "analysis-1",
    latest_version: { id: "variant-version-1", original_score: 92, estimated_score: 92,
      score_explanation: "The deterministic match score is unchanged.", sections_improved: ["headline"],
      remaining_gaps: [], remaining_blockers: [], applied_recommendation_ids: ["recommendation-1"] },
  };
  await page.route("**/v1/jobs", (route) => route.fulfill({ json: [] }));
  await page.route("**/v1/applications", (route) => route.fulfill({ json: [] }));
  await page.route("**/v1/cv-imports", (route) => route.fulfill({ json: [] }));
  await page.route("**/v1/discovery/**", async (route) => {
    const url = route.request().url();
    if (url.includes("/providers")) return route.fulfill({ json: [{ key: "itjobs", name: "ITJobs.pt", access_type: "OFFICIAL_API", implementation_status: "IMPLEMENTED_CONFIG_REQUIRED", automated_search: true, fallback: "CSV", limitations: "Official API only", health: "HEALTHY", last_successful_sync: null, last_error: null }] });
    if (url.includes("/search-profile")) return route.fulfill({ json: profile });
    if (url.includes("/configurations")) return route.fulfill({ json: [configuration] });
    if (url.includes("/search-runs") && route.request().method() === "POST") return route.fulfill({ status: 201, json: { id: "run-1", configuration_id: "config-1", status: "SUCCEEDED", trigger: "MANUAL", lifecycle_stage: "USER_NOTIFIED", counters: { new_jobs: 1, duplicates: 1, strong_matches: 1 }, started_at: "2026-07-12T10:00:00Z", ended_at: "2026-07-12T10:00:01Z" } });
    if (url.includes("/search-runs")) return route.fulfill({ json: [] });
    if (url.includes("/matches")) return route.fulfill({ json: [match] });
    if (url.includes("/notifications")) return route.fulfill({ json: [] });
    return route.fulfill({ json: {} });
  });
  await page.route("**/v1/cv-optimizations/**", async (route) => {
    const url = route.request().url(); const method = route.request().method();
    if (url.includes("/recommendations/") && method === "PATCH") {
      recommendationDecision = route.request().postDataJSON().decision;
      return route.fulfill({ json: { ...recommendation, decision: recommendationDecision } });
    }
    if (url.endsWith("/preview") && method === "POST") return route.fulfill({ json: {
      content: { headline: { value: "Data Analyst | Targeting Data Analyst" },
        professional_summary: { value: "Verified analyst." }, technical_skills: [{ value: "SQL" }] },
      applied_recommendation_ids: ["recommendation-1"], rejected_recommendation_ids: [],
      original_score: 92, estimated_score: 92, score_explanation: "The deterministic match score is unchanged.",
      sections_improved: ["headline"], remaining_gaps: [], remaining_blockers: [],
    } });
    if (url.endsWith("/variants") && method === "POST") { variantSaved = true; return route.fulfill({ status: 201, json: variant }); }
    if (url.includes("/variants?")) return route.fulfill({ json: variantSaved ? [variant] : [] });
    if (url.includes("/analyses?") && method === "GET") return route.fulfill({ json: analysisCreated ? [analysis()] : [] });
    if (url.endsWith("/analyses") && method === "POST") { analysisCreated = true; return route.fulfill({ status: 201, json: analysis() }); }
    if (url.includes("/analyses/") && method === "GET") return route.fulfill({ json: analysis() });
    return route.fulfill({ json: [] });
  });
  const letter = (id: string, status = "VALIDATED") => ({
    id, application_id: "application-1", job_id: "job-1", profile_version_id: "profile-version-1",
    parent_document_id: null, version: coverLetterVersion, language: "en", status: "VALID",
    cover_letter_status: status, variant: "BALANCED", tone: "PROFESSIONAL", length: "STANDARD",
    selected: true, approved_at: status === "APPROVED" ? "2026-07-12T10:00:00Z" : null,
    content: { candidate_name: "Ana Silva", contact_line: "ana@example.com", date: "2026-07-12",
      company: "Acme", job_title: "Data Analyst", greeting: "Dear Hiring Team,", word_count: 280,
      signoff: "Sincerely,", paragraphs: [
        { kind: "OPENING", text: "I am applying with verified Data Analyst experience.", baseline_text: "I am applying with verified Data Analyst experience.", candidate_fact_ids: ["candidate:headline"], company_fact_ids: [], confidence: 1 },
        { kind: "QUALIFICATIONS", text: "My approved profile records SQL and Power BI.", baseline_text: "My approved profile records SQL and Power BI.", candidate_fact_ids: ["candidate:skill:0"], company_fact_ids: [], confidence: 1 },
        { kind: "CLOSING", text: "Thank you for your consideration.", baseline_text: "Thank you for your consideration.", candidate_fact_ids: [], company_fact_ids: [], confidence: 1 },
      ] },
    validation: { valid: true, checked_claims: 2, issues: [], low_confidence_paragraphs: [] },
    evidence: [{ fact_id: "candidate:headline", source_section: "headline", quote: "Data Analyst" }],
    configuration: { match_score: 92, missing_required_skills: [], potential_blockers: [] },
    prompt_version: "cover-letter-evidence-plan-v1", model: "mock", created_at: "2026-07-12T10:00:00Z",
  });
  await page.route("**/v1/cover-letters**", async (route) => {
    const url = route.request().url(); const method = route.request().method();
    if (method === "GET") return route.fulfill({ json: coverLetters });
    if (url.endsWith("/approve") && method === "POST") {
      coverLetters = [{ ...coverLetters[0], cover_letter_status: "APPROVED", approved_at: "2026-07-12T10:00:00Z" }];
      return route.fulfill({ json: coverLetters[0] });
    }
    if (method === "PATCH") {
      coverLetterVersion += 1; coverLetters = [{ ...letter("letter-2"), version: coverLetterVersion, parent_document_id: "letter-1" }, ...coverLetters];
      return route.fulfill({ status: 201, json: coverLetters[0] });
    }
    if (url.endsWith("/v1/cover-letters") && method === "POST") {
      coverLetters = [letter("letter-1")]; return route.fulfill({ status: 201, json: coverLetters });
    }
    return route.fulfill({ json: coverLetters[0] ?? {} });
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Find the right roles without scraping" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Data Analyst" })).toBeVisible();
  await expect(page.getByText("92")).toBeVisible();
  await page.getByRole("button", { name: "Run search" }).click();
  await expect(page.getByText("Search completed. Provider failures, if any, were isolated.")).toBeVisible();
  await page.getByRole("heading", { name: "Data Analyst" }).click();
  await expect(page.getByLabel("Detailed match analysis")).toContainText("Preferred title matches.");
  await page.getByRole("button", { name: "Analyze CV" }).click();
  await expect(page.getByText("Align the verified headline.")).toBeVisible();
  await page.getByRole("button", { name: "Accept", exact: true }).click();
  await page.getByRole("button", { name: "Preview revised CV" }).click();
  await expect(page.getByLabel("Revised CV preview")).toContainText("Targeting Data Analyst");
  await page.getByRole("button", { name: "Save this variant" }).click();
  await expect(page.getByText("Variant ready")).toBeVisible();
  await page.getByRole("button", { name: "Generate drafts" }).click();
  await expect(page.getByText("Grounded draft variants generated for review.")).toBeVisible();
  await page.getByLabel("Greeting").fill("Dear Analytics Team,");
  await page.getByRole("button", { name: "Save as new version" }).click();
  await expect(page.getByText("prior version is preserved")).toBeVisible();
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByLabel("Write for Data Analyst").getByRole("button", { name: "Export PDF" })).toBeVisible();
});
