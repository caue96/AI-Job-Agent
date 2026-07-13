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
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Find the right roles without scraping" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Data Analyst" })).toBeVisible();
  await expect(page.getByText("92")).toBeVisible();
  await page.getByRole("button", { name: "Run search" }).click();
  await expect(page.getByText("Search completed. Provider failures, if any, were isolated.")).toBeVisible();
  await page.getByRole("heading", { name: "Data Analyst" }).click();
  await expect(page.getByLabel("Detailed match analysis")).toContainText("Preferred title matches.");
});
