const API = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export type CoverLetterVariant = "BALANCED" | "TECHNICAL" | "BUSINESS_FOCUSED";
export type CoverLetterTone = "PROFESSIONAL" | "CONFIDENT" | "CONCISE" | "WARM" | "TECHNICAL" | "BUSINESS_ORIENTED" | "STARTUP_ORIENTED" | "CORPORATE";
export type CoverLetterLength = "SHORT" | "STANDARD" | "DETAILED";
export type CoverLetterIssue = { code: string; message: string; paragraph_index: number | null; text: string };
export type CoverLetterParagraph = {
  kind: string; text: string; baseline_text: string; candidate_fact_ids: string[];
  company_fact_ids: string[]; confidence: number;
};
export type CoverLetter = {
  id: string; job_id: string; parent_document_id: string | null; version: number;
  language: "en" | "es" | "pt"; status: string; cover_letter_status: string;
  variant: CoverLetterVariant; tone: CoverLetterTone; length: CoverLetterLength;
  selected: boolean; approved_at: string | null; created_at: string;
  content: {
    candidate_name: string; contact_line: string; date: string; company: string;
    job_title: string; greeting: string; paragraphs: CoverLetterParagraph[];
    signoff: string; word_count: number;
  };
  validation: { valid: boolean; checked_claims: number; issues: CoverLetterIssue[]; low_confidence_paragraphs: number[] };
  evidence: { fact_id: string; source_section: string; quote: string }[];
  configuration: {
    match_score?: number; missing_required_skills?: string[]; potential_blockers?: string[];
    reasons_to_apply?: string[]; [key: string]: unknown;
  };
  prompt_version: string; model: string;
};
export type CoverLetterExport = { id: string; format: "txt" | "docx" | "pdf"; size_bytes: number; sha256: string };

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
        ? detail.message
        : "Cover-letter request failed.";
    throw new Error(message);
  }
  return response.status === 204 ? undefined as T : response.json();
}

export const coverLetterApi = {
  list: (jobId: string) => request<CoverLetter[]>(`/v1/cover-letters?job_id=${encodeURIComponent(jobId)}`),
  generate: (payload: Record<string, unknown>) => request<CoverLetter[]>("/v1/cover-letters", { method: "POST", body: JSON.stringify(payload) }),
  edit: (id: string, payload: { greeting: string; paragraphs: string[]; signoff: string }) => request<CoverLetter>(`/v1/cover-letters/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  validate: (id: string) => request<CoverLetter>(`/v1/cover-letters/${id}/validate`, { method: "POST" }),
  select: (id: string) => request<CoverLetter>(`/v1/cover-letters/${id}/select`, { method: "POST" }),
  approve: (id: string) => request<CoverLetter>(`/v1/cover-letters/${id}/approve`, { method: "POST" }),
  regenerate: (id: string) => request<CoverLetter[]>(`/v1/cover-letters/${id}/regenerate`, { method: "POST" }),
  export: (id: string, format: "txt" | "docx" | "pdf") => request<CoverLetterExport>(`/v1/cover-letters/${id}/exports`, { method: "POST", body: JSON.stringify({ format }) }),
  downloadUrl: (id: string) => `${API}/v1/cover-letters/exports/${id}/download`,
};
