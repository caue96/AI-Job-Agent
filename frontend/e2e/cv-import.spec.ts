import { expect, test } from "@playwright/test";

const evidence = (value: string) => ({ value, confidence: .95, ambiguous: false, evidence: [{ page: 1, quote: value, method: "deterministic" }] });
const missing = () => ({ value: null, confidence: 0, ambiguous: false, evidence: [] });
const draft = {
  personal: {
    full_name: evidence("Jane Candidate"), email: evidence("jane@example.com"), phone: missing(),
    city: missing(), country: missing(), linkedin_url: missing(), github_url: missing(),
    portfolio_url: missing(), work_authorization: missing(),
  },
  headline: evidence("Senior Python Engineer"), professional_summary: missing(),
  technical_skills: [{ value: "Python", confidence: .95, evidence: [{ page: 1, quote: "Python", method: "deterministic" }] }],
  soft_skills: [], languages: [], employment: [], education: [], certifications: [], projects: [],
  achievements: [], citizenships: [], preferred_locations: [], preferred_titles: [],
  preferred_industries: [], workplace_preferences: [], salary_expectation: missing(), availability: missing(),
  declared_years_experience: missing(), calculated_years_experience: missing(),
  requires_sponsorship: missing(), relocation_available: missing(),
};
const imported = {
  id: "cv-1", status: "AWAITING_REVIEW", original_filename: "resume.pdf", media_type: "application/pdf",
  size_bytes: 1234, page_count: 1, draft, file_available: true,
  validation: { scanned_likely: false, unsupported_claims: [], user_edited: false }, model_metadata: {},
  created_at: "2026-07-12T12:00:00Z", updated_at: "2026-07-12T12:00:00Z",
};

test("uploads, reviews, edits, and confirms a grounded CV", async ({ page }) => {
  await page.route("**/v1/jobs", (route) => route.fulfill({ json: [] }));
  await page.route("**/v1/applications", (route) => route.fulfill({ json: [] }));
  await page.route("**/v1/cv-imports**", async (route) => {
    const url = route.request().url();
    const method = route.request().method();
    if (url.endsWith("/compare")) return route.fulfill({ json: { profile_exists: false, conflicts: [], additions: [] } });
    if (url.endsWith("/confirm")) return route.fulfill({ json: { id: "v1", profile_id: "p1", cv_import_id: "cv-1", version: 1, strategy: "merge", snapshot: draft, created_at: imported.created_at } });
    if (method === "GET" && url.endsWith("/v1/cv-imports")) return route.fulfill({ json: [] });
    if (method === "PATCH") return route.fulfill({ json: { ...imported, draft: JSON.parse(route.request().postDataJSON().draft ? JSON.stringify(route.request().postDataJSON().draft) : JSON.stringify(draft)), validation: { ...imported.validation, user_edited: true } } });
    return route.fulfill({ status: method === "POST" ? 201 : 200, json: imported });
  });
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles({ name: "resume.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4 test") });
  await page.getByRole("button", { name: "Upload and extract" }).click();
  await expect(page.getByRole("heading", { name: "Review extracted profile" })).toBeVisible();
  const name = page.getByLabel("Full name");
  await name.fill("Jane A. Candidate");
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByText("Review edits saved as a draft.")).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Confirm and save profile" }).click();
  await expect(page.getByText("Profile saved with a versioned, auditable snapshot.")).toBeVisible();
});
