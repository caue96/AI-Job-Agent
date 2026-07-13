import type { CvComparison, CvDraft, CvImport, CvImportSummary } from "./cv-types";

const API = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

function detailMessage(body: unknown): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = body.detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string") return detail.message;
  }
  return "The request could not be completed.";
}

export async function cvRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) throw new Error(detailMessage(await response.json().catch(() => null)));
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function uploadCv(file: File, onProgress: (percent: number) => void): Promise<CvImport> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", `${API}/v1/cv-imports`);
    request.responseType = "json";
    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    });
    request.addEventListener("load", () => {
      if (request.status >= 200 && request.status < 300) resolve(request.response as CvImport);
      else reject(new Error(detailMessage(request.response)));
    });
    request.addEventListener("error", () => reject(new Error("Could not connect to the API.")));
    const data = new FormData();
    data.append("file", file);
    request.send(data);
  });
}

export const listCvImports = () => cvRequest<CvImportSummary[]>("/v1/cv-imports");
export const getCvImport = (id: string) => cvRequest<CvImport>(`/v1/cv-imports/${id}`);
export const compareCvImport = (id: string) => cvRequest<CvComparison>(`/v1/cv-imports/${id}/compare`);
export const saveCvDraft = (id: string, draft: CvDraft) => cvRequest<CvImport>(`/v1/cv-imports/${id}`, {
  method: "PATCH", body: JSON.stringify({ draft }),
});
export const confirmCvImport = (id: string, strategy: "replace" | "merge", acceptConflicts: boolean) => cvRequest(`/v1/cv-imports/${id}/confirm`, {
  method: "POST", body: JSON.stringify({ strategy, accept_conflicts: acceptConflicts }),
});
export const deleteCvImport = (id: string) => cvRequest<void>(`/v1/cv-imports/${id}`, { method: "DELETE" });
export const deleteCvFile = (id: string) => cvRequest<void>(`/v1/cv-imports/${id}/file`, { method: "DELETE" });
