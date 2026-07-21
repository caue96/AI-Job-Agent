const API = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export type Evidence = { id: string; fact_id: string; source_section: string; quote: string };
export type Recommendation = {
  id: string; category: string; section: string; current_text: string; suggested_text: string;
  reason: string; expected_benefit: string; related_job_requirement: string; confidence: number;
  priority: string; recommendation_type: string; approval_required: boolean;
  decision: "PENDING" | "ACCEPTED" | "REJECTED" | "EDITED"; user_text: string | null;
  validation: { valid?: boolean; issues?: string[] }; display_order: number; evidence: Evidence[];
};
export type Analysis = {
  id: string; job_id: string; status: string; original_score: number;
  input_summary: Record<string, unknown> & {
    matching_skills?: string[]; missing_required_skills?: string[]; potential_blockers?: string[];
  };
  validation: Record<string, unknown>; prompt_version: string; model: string; recommendations: Recommendation[];
  created_at: string; updated_at: string;
};
export type Variant = {
  id: string; job_id: string; status: string; analysis_run_id: string;
  latest_version: {
    id: string; original_score: number; estimated_score: number; score_explanation: string;
    sections_improved: string[]; remaining_gaps: string[]; remaining_blockers: string[];
    applied_recommendation_ids: string[];
  };
};
export type Export = { id: string; format: string; size_bytes: number; sha256: string };
export type Preview = {
  content: {
    headline: { value: string | null };
    professional_summary: { value: string | null };
    technical_skills: { value: string }[];
  };
  applied_recommendation_ids: string[]; original_score: number; estimated_score: number;
  score_explanation: string; sections_improved: string[]; remaining_gaps: string[];
  remaining_blockers: string[];
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail;
    const message = typeof detail === "string"
      ? detail
      : typeof detail?.message === "string"
        ? `${detail.message}${Array.isArray(detail.issues) ? `: ${detail.issues.join("; ")}` : ""}`
        : "CV optimization request failed.";
    throw new Error(message);
  }
  return response.status === 204 ? undefined as T : response.json();
}

export const cvOptimizationApi = {
  analyze: (jobId: string) => request<Analysis>("/v1/cv-optimizations/analyses", { method: "POST", body: JSON.stringify({ job_id: jobId }) }),
  analyses: (jobId: string) => request<Analysis[]>(`/v1/cv-optimizations/analyses?job_id=${encodeURIComponent(jobId)}`),
  decide: (id: string, decision: string, editedText?: string) => request<Recommendation>(`/v1/cv-optimizations/recommendations/${id}`, { method: "PATCH", body: JSON.stringify({ decision, edited_text: editedText }) }),
  batch: (id: string, action: "ACCEPT_SAFE" | "RESET") => request<Analysis>(`/v1/cv-optimizations/analyses/${id}/recommendations/batch`, { method: "POST", body: JSON.stringify({ action }) }),
  preview: (id: string) => request<Preview>(`/v1/cv-optimizations/analyses/${id}/preview`, { method: "POST" }),
  createVariant: (id: string) => request<Variant>(`/v1/cv-optimizations/analyses/${id}/variants`, { method: "POST", body: JSON.stringify({ status: "APPROVED" }) }),
  variants: (jobId: string) => request<Variant[]>(`/v1/cv-optimizations/variants?job_id=${encodeURIComponent(jobId)}`),
  export: (id: string, format: "pdf" | "docx") => request<Export>(`/v1/cv-optimizations/variants/${id}/exports`, { method: "POST", body: JSON.stringify({ format }) }),
  downloadUrl: (id: string) => `${API}/v1/cv-optimizations/exports/${id}/download`,
};
