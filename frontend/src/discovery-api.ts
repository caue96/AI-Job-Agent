const API = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export type Provider = {
  key: string; name: string; access_type: string; implementation_status: string;
  automated_search: boolean; fallback: string; limitations: string;
  health: string; configured: boolean; last_successful_sync: string | null; last_error: string | null;
};
export type SearchProfile = {
  id: string; generated_terms: string[];
  preferences: {
    target_titles: string[]; alternative_titles: string[]; preferred_countries: string[];
    preferred_cities: string[]; workplace_preferences: string[]; excluded_companies: string[];
    excluded_keywords: string[]; required_keywords: string[]; minimum_salary: number | null;
    [key: string]: unknown;
  };
};
export type Configuration = {
  id: string; name: string; enabled: boolean; provider_settings: Record<string, { enabled: boolean; feed_url?: string }>;
  schedule_kind: string; schedule_time: string; timezone: string; hard_filters: Record<string, unknown>;
  next_run_at: string | null; last_run_at: string | null;
};
export type Match = {
  id: string; match_id: string; title: string; company: string; country: string | null; city: string | null;
  provider: string; url: string | null; workplace_type: string | null; posted_at: string | null;
  salary_min: number | null; salary_max: number | null; salary_currency: string | null;
  score: number; recommendation: string; hard_rejected: boolean; user_state: string;
  analysis: { matching_skills?: string[]; missing_required_skills?: string[]; potential_blockers?: string[];
    reasons_to_apply?: string[]; reasons_not_to_apply?: string[]; score_by_category?: Record<string, { score: number; maximum: number; explanation: string }> };
};
export type Run = { id: string; status: string; lifecycle_stage: string; counters: Record<string, number>; started_at: string };
export type Notification = { id: string; title: string; body: string; read_at: string | null; created_at: string };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : "Discovery request failed.");
  }
  return response.status === 204 ? undefined as T : response.json();
}

export const discoveryApi = {
  providers: () => request<Provider[]>("/v1/discovery/providers"),
  profile: () => request<SearchProfile>("/v1/discovery/search-profile"),
  generateProfile: () => request<SearchProfile>("/v1/discovery/search-profile/generate", { method: "POST" }),
  saveProfile: (preferences: SearchProfile["preferences"]) => request<SearchProfile>("/v1/discovery/search-profile", { method: "PUT", body: JSON.stringify(preferences) }),
  configurations: () => request<Configuration[]>("/v1/discovery/configurations"),
  createConfiguration: (body: unknown) => request<Configuration>("/v1/discovery/configurations", { method: "POST", body: JSON.stringify(body) }),
  run: (configurationId: string) => request<Run>("/v1/discovery/search-runs", { method: "POST", body: JSON.stringify({ configuration_id: configurationId }) }),
  runs: () => request<Run[]>("/v1/discovery/search-runs"),
  matches: (query = "") => request<Match[]>(`/v1/discovery/matches${query}`),
  notifications: () => request<Notification[]>("/v1/discovery/notifications"),
  action: (id: string, action: string) => request<Record<string, string>>(`/v1/discovery/matches/${id}/action`, { method: "POST", body: JSON.stringify({ action }) }),
  importManual: (body: unknown) => request<{ imported: number; duplicates: number }>("/v1/discovery/imports/manual", { method: "POST", body: JSON.stringify(body) }),
};
