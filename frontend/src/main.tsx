import { useCallback, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

type Job = {
  id: string;
  company: string;
  title: string;
  country: string | null;
  city: string | null;
  workplace_type: string | null;
  url: string | null;
  description: string;
  requirements: string[];
  preferred_qualifications: string[];
};

type Score = { score: number; maximum: number; explanation: string };
type Analysis = {
  overall_score: number;
  score_by_category: Record<string, Score>;
  matching_skills: string[];
  missing_required_skills: string[];
  missing_preferred_skills: string[];
  potential_blockers: string[];
  reasons_to_apply: string[];
  reasons_not_to_apply: string[];
  confidence_level: string;
  recommendation: string;
  hard_rejected: boolean;
};

type Application = {
  id: string;
  job_id: string;
  status: string;
  match_score: number | null;
  match_analysis: Analysis;
  notes: string | null;
  created_at: string;
};

type Statement = { text: string; fact_ids: string[] };
type DocumentPackage = {
  professional_summary: Statement[];
  cv_highlights: Statement[];
  cover_letter_paragraphs: Statement[];
  recruiter_introduction: Statement;
  linkedin_message: Statement;
  application_answers: { question: string; answer: Statement }[];
  keyword_comparison: { matching_keywords: string[]; missing_keywords: string[] };
};
type DocumentVersion = {
  id: string;
  version: number;
  language: string;
  status: "VALID" | "INVALID";
  content: DocumentPackage | null;
  validation: { valid: boolean; unsupported_claims: string[]; invalid_fact_ids: string[] };
  created_at: string;
};
type Notice = { kind: "success" | "error"; text: string };
type DocumentsState = {
  applicationId: string | null;
  versions: DocumentVersion[];
  loading: boolean;
};

const API = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const statusOrder = [
  "DISCOVERED",
  "ANALYZED",
  "SHORTLISTED",
  "DOCUMENTS_PREPARED",
  "AWAITING_REVIEW",
  "APPROVED",
  "READY_TO_SUBMIT",
  "SUBMITTED",
  "INTERVIEW",
  "OFFER",
  "REJECTED",
  "WITHDRAWN",
];
const workflowGuidance: Record<string, string> = {
  DISCOVERED: "Start with a deterministic match analysis.",
  ANALYZED: "Review the score and blockers, then shortlist or reject this opportunity.",
  SHORTLISTED: "Generate a grounded document package for review.",
  DOCUMENTS_PREPARED: "Review every generated section before marking the package ready.",
  AWAITING_REVIEW: "Confirm the package is accurate before approval.",
  APPROVED: "Confirm the destination and application data before preparing submission.",
  READY_TO_SUBMIT: "Submit manually on the employer site, then record that action here.",
  SUBMITTED: "Track interview, offer, rejection, or withdrawal outcomes.",
  INTERVIEW: "Record the next outcome when it is known.",
  OFFER: "Review the offer; withdraw the tracked application if it is no longer active.",
  REJECTED: "This application is closed as rejected.",
  WITHDRAWN: "This application is closed as withdrawn.",
};

const label = (value: string) => value.replaceAll("_", " ").toLowerCase();

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return "Something went wrong. Please try again.";
}

function responseError(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (!item || typeof item !== "object") return null;
        const message = "msg" in item ? item.msg : null;
        const location = "loc" in item && Array.isArray(item.loc) ? item.loc.slice(1).join(" → ") : "";
        return typeof message === "string" ? `${location ? `${location}: ` : ""}${message}` : null;
      })
      .filter(Boolean);
    if (messages.length) return messages.join("; ");
  }
  return "The request could not be completed. Check the entered data and try again.";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API}${path}`, {
      headers: { "Content-Type": "application/json", ...init?.headers },
      ...init,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new Error("Could not connect to the API. Confirm the backend is running and try again.");
  }
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const detail = body && typeof body === "object" && "detail" in body ? body.detail : body;
    throw new Error(responseError(detail));
  }
  return response.json() as Promise<T>;
}

function Metric({ label: title, value, accent = false }: { label: string; value: string | number; accent?: boolean }) {
  return (
    <article className={`metric ${accent ? "metric--accent" : ""}`}>
      <span>{title}</span>
      <strong>{value}</strong>
    </article>
  );
}

function List({ items, empty = "None" }: { items: string[]; empty?: string }) {
  return items.length ? (
    <ul className="plain-list">
      {items.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}
    </ul>
  ) : <p className="muted">{empty}</p>;
}

function App() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [applications, setApplications] = useState<Application[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [documentState, setDocumentState] = useState<DocumentsState>({
    applicationId: null,
    versions: [],
    loading: false,
  });
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [activeAction, setActiveAction] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);

  const refresh = useCallback(async (announce = false) => {
    setRefreshing(true);
    try {
      const [nextJobs, nextApplications] = await Promise.all([
        request<Job[]>("/v1/jobs"),
        request<Application[]>("/v1/applications"),
      ]);
      setJobs(nextJobs);
      setApplications(nextApplications);
      setSelectedId((current) => (
        current && nextApplications.some((item) => item.id === current)
          ? current
          : nextApplications[0]?.id ?? null
      ));
      if (announce) setNotice({ kind: "success", text: "Dashboard data is up to date." });
    } finally {
      setRefreshing(false);
    }
  }, []);

  const updateApplication = (updated: Application) => {
    setApplications((current) => current.map((item) => item.id === updated.id ? updated : item));
  };

  useEffect(() => {
    refresh()
      .catch((error) => setNotice({ kind: "error", text: errorMessage(error) }))
      .finally(() => setLoading(false));
  }, [refresh]);

  const jobsById = useMemo(() => new Map(jobs.map((job) => [job.id, job])), [jobs]);
  const applicationsById = useMemo(
    () => new Map(applications.map((item) => [item.id, item])),
    [applications],
  );
  const selected = selectedId ? applicationsById.get(selectedId) ?? null : null;
  const selectedJob = selected ? jobsById.get(selected.job_id) ?? null : null;
  const selectedApplicationId = selected?.id;
  const documents = documentState.applicationId === selectedId ? documentState.versions : [];
  const documentsLoading =
    documentState.applicationId === selectedId && documentState.loading;
  const normalizedQuery = query.trim().toLowerCase();
  const visibleApplications = useMemo(() => applications.filter((application) => {
    const job = jobsById.get(application.job_id);
    const text = `${job?.company ?? ""} ${job?.title ?? ""}`.toLowerCase();
    return (statusFilter === "ALL" || application.status === statusFilter)
      && text.includes(normalizedQuery);
  }), [applications, jobsById, normalizedQuery, statusFilter]);

  useEffect(() => {
    const applicationId = selectedApplicationId;
    if (!applicationId) {
      setDocumentState({ applicationId: null, versions: [], loading: false });
      return;
    }
    const controller = new AbortController();
    setDocumentState({ applicationId, versions: [], loading: true });
    request<DocumentVersion[]>(
      `/v1/applications/${applicationId}/documents?latest_valid=true`,
      { signal: controller.signal },
    )
      .then((versions) => setDocumentState((current) => (
        current.applicationId === applicationId
          ? { applicationId, versions, loading: false }
          : current
      )))
      .catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setNotice({ kind: "error", text: errorMessage(error) });
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setDocumentState((current) => (
            current.applicationId === applicationId
              ? { ...current, loading: false }
              : current
          ));
        }
      });
    return () => controller.abort();
  }, [selectedApplicationId]);

  const act = async (name: string, action: () => Promise<void>, success: string) => {
    setActiveAction(name);
    setNotice(null);
    try {
      await action();
      setNotice({ kind: "success", text: success });
    } catch (error) {
      setNotice({ kind: "error", text: errorMessage(error) });
    } finally {
      setActiveAction(null);
    }
  };

  const transition = (toStatus: string, approvedByUser = false) => act(
    `transition-${toStatus}`,
    async () => updateApplication(await request<Application>(
      `/v1/applications/${selected!.id}/transition`,
      { method: "POST", body: JSON.stringify({ to_status: toStatus, approved_by_user: approvedByUser }) },
    )),
    `Application moved to ${label(toStatus)}.`,
  );

  const confirmTransition = (toStatus: "REJECTED" | "SUBMITTED") => {
    const message = toStatus === "REJECTED"
      ? "Reject this application? This closes the current workflow and cannot be undone here."
      : "Confirm that you submitted this application manually on the employer site. This does not submit anything for you.";
    if (window.confirm(message)) transition(toStatus, toStatus === "SUBMITTED");
  };

  const analyze = () => act("analyze", async () => {
    const analysis = await request<Analysis>(
      `/v1/applications/${selected!.id}/analyze`,
      { method: "POST" },
    );
    updateApplication({
      ...selected!,
      status: "ANALYZED",
      match_score: analysis.overall_score,
      match_analysis: analysis,
    });
  }, "Match analysis updated. Review the evidence before shortlisting.");

  const generate = () => {
    const application = selected!;
    return act("generate", async () => {
    const version = await request<DocumentVersion>(
      `/v1/applications/${application.id}/documents/generate`,
      { method: "POST", body: JSON.stringify({ language: "en" }) },
    );
    setDocumentState((current) => current.applicationId === application.id
      ? { ...current, versions: [version, ...current.versions] }
      : current);
    if (version.status === "VALID" && application.status === "SHORTLISTED") {
      updateApplication({ ...application, status: "DOCUMENTS_PREPARED" });
    }
    }, "Grounded document package created. Review every section before approval.");
  };

  const metrics = useMemo(() => {
    const counts: Record<string, number> = {};
    let scoreTotal = 0;
    let scored = 0;
    for (const item of applications) {
      counts[item.status] = (counts[item.status] ?? 0) + 1;
      if (item.match_score !== null) {
        scoreTotal += item.match_score;
        scored += 1;
      }
    }
    return { counts, scored, averageScore: scored ? scoreTotal / scored : 0 };
  }, [applications]);
  const document = documents.find((item) => item.status === "VALID" && item.content) ?? null;
  const busy = activeAction !== null;
  const filtersActive = statusFilter !== "ALL" || normalizedQuery.length > 0;
  const clearFilters = () => { setStatusFilter("ALL"); setQuery(""); };

  return (
    <div className="shell">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <aside className="sidebar" aria-label="Workspace navigation">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">✦</span>
          <div><b>EU Job Agent</b><small>Approval-first workspace</small></div>
        </div>
        <nav aria-label="Dashboard sections">
          <a href="#tracker">Overview</a>
          <a href="#review">Applications</a>
          <a href="#safety">Approval</a>
        </nav>
        <div className="sidebar-foot"><span className="live-dot" aria-hidden="true" />Manual submission only</div>
      </aside>

      <main id="main-content" aria-busy={loading || refreshing || busy}>
        <header className="topbar">
          <div>
            <p className="eyebrow">APPLICATION COMMAND CENTER</p>
            <h1>Make every application count.</h1>
            <p className="subhead">Review the evidence, prepare grounded material, then submit on your own terms.</p>
          </div>
          <button
            className="button secondary"
            disabled={refreshing || busy}
            onClick={() => refresh(true).catch((error) => setNotice({ kind: "error", text: errorMessage(error) }))}
          >
            {refreshing ? "Refreshing…" : "Refresh data"}
          </button>
        </header>

        {notice && (
          <div className={`notice notice--${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>
            <span>{notice.text}</span>
            <button type="button" aria-label="Dismiss message" onClick={() => setNotice(null)}>×</button>
          </div>
        )}

        <section className="metrics" id="tracker" aria-label="Application overview">
          <Metric label="Discovered" value={metrics.counts.DISCOVERED ?? 0} />
          <Metric label="Shortlisted" value={metrics.counts.SHORTLISTED ?? 0} />
          <Metric label="Awaiting review" value={metrics.counts.AWAITING_REVIEW ?? 0} accent />
          <Metric label="Submitted" value={metrics.counts.SUBMITTED ?? 0} />
          <Metric label="Interviews" value={metrics.counts.INTERVIEW ?? 0} />
          <Metric label="Average match" value={metrics.scored ? `${Math.round(metrics.averageScore)}%` : "—"} />
        </section>

        <section className="workspace" id="review">
          <div className="tracker-panel panel">
            <div className="panel-heading">
              <div><p className="eyebrow">APPLICATION TRACKER</p><h2>Opportunities</h2></div>
              <span>{visibleApplications.length} of {applications.length}</span>
            </div>
            <div className="filters">
              <label><span>Search</span><input placeholder="Company or role" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
              <label><span>Status</span><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                <option value="ALL">All statuses</option>
                {statusOrder.map((status) => <option value={status} key={status}>{label(status)} ({metrics.counts[status] ?? 0})</option>)}
              </select></label>
            </div>
            {filtersActive && <button type="button" className="text-button" onClick={clearFilters}>Clear search and filters</button>}

            <div className="application-list" aria-live="polite">
              {loading ? <LoadingState label="Loading applications" /> : visibleApplications.length ? visibleApplications.map((application) => {
                const job = jobsById.get(application.job_id);
                return (
                  <button
                    className={`application-row ${application.id === selected?.id ? "selected" : ""}`}
                    key={application.id}
                    aria-pressed={application.id === selected?.id}
                    onClick={() => setSelectedId(application.id)}
                  >
                    <span className="score" aria-label={application.match_score === null ? "Not scored" : `Match score ${application.match_score}`}>{application.match_score ?? "—"}</span>
                    <span className="application-name">
                      <b>{job?.title ?? "Unknown role"}</b>
                      <small>{job?.company ?? "Unknown company"} · {[job?.city, job?.country].filter(Boolean).join(", ") || "Location pending"}</small>
                    </span>
                    <span className={`status status--${application.status.toLowerCase()}`}>{label(application.status)}</span>
                  </button>
                );
              }) : filtersActive ? (
                <div className="empty"><h3>No matching applications</h3><p>Try a different company, role, or status.</p><button className="button secondary" onClick={clearFilters}>Clear filters</button></div>
              ) : (
                <FirstRunState />
              )}
            </div>
          </div>

          <section className="detail-panel panel" aria-label="Selected application">
            {selected && selectedJob ? (
              <>
                <div className="panel-heading detail-heading">
                  <div><p className="eyebrow">REVIEW WORKSPACE</p><h2>{selectedJob.title}</h2><p>{selectedJob.company} · {[selectedJob.city, selectedJob.country].filter(Boolean).join(", ") || "Location pending"}</p></div>
                  <span className={`status status--${selected.status.toLowerCase()}`}>{label(selected.status)}</span>
                </div>
                <p className="workflow-hint"><b>Next step:</b> {workflowGuidance[selected.status] ?? "Review this application."}</p>
                <div className="action-bar">
                  <button className="button" disabled={busy || !["DISCOVERED", "ANALYZED"].includes(selected.status)} onClick={analyze}>{activeAction === "analyze" ? "Analyzing…" : "Analyze match"}</button>
                  <button className="button secondary" disabled={busy || selected.status !== "ANALYZED"} onClick={() => transition("SHORTLISTED")}>{activeAction === "transition-SHORTLISTED" ? "Shortlisting…" : "Shortlist"}</button>
                  <button className="button danger" disabled={busy || !["DISCOVERED", "ANALYZED", "SHORTLISTED", "AWAITING_REVIEW"].includes(selected.status)} onClick={() => confirmTransition("REJECTED")}>Reject</button>
                  {selectedJob.url && <a className="button link-button" href={selectedJob.url} target="_blank" rel="noopener noreferrer">Open original job <span aria-hidden="true">↗</span><span className="sr-only"> in a new tab</span></a>}
                </div>

                <div className="review-grid">
                  <article className="match-card"><div className="match-score"><strong>{selected.match_score ?? "—"}</strong><span>match score</span></div><div><p className="eyebrow">{selected.match_analysis?.recommendation ? label(selected.match_analysis.recommendation) : "not analyzed"}</p><p className="muted">Confidence: {selected.match_analysis?.confidence_level ? label(selected.match_analysis.confidence_level) : "—"}</p></div></article>
                  <article><h3>Potential blockers</h3><List items={selected.match_analysis?.potential_blockers ?? []} empty={selected.match_score === null ? "Analyze the application to identify blockers." : "No blockers identified."} /></article>
                  <article><h3>Skill comparison</h3><p><b>Matches:</b> {(selected.match_analysis?.matching_skills ?? []).join(", ") || "—"}</p><p><b>Missing required:</b> {(selected.match_analysis?.missing_required_skills ?? []).join(", ") || "—"}</p></article>
                </div>

                {selected.match_analysis?.score_by_category && <div className="score-breakdown"><h3>Explainable score</h3>{Object.entries(selected.match_analysis.score_by_category).map(([category, score]) => <div className="score-line" key={category}><span>{label(category)}</span><div className="bar" role="progressbar" aria-label={`${label(category)} score`} aria-valuemin={0} aria-valuemax={score.maximum} aria-valuenow={score.score}><i style={{ width: `${(score.score / score.maximum) * 100}%` }} /></div><b>{score.score}/{score.maximum}</b><small>{score.explanation}</small></div>)}</div>}

                <div className="job-details"><details><summary>Job description and requirements</summary><p>{selectedJob.description}</p><h3>Requirements</h3><List items={selectedJob.requirements} /><h3>Preferred qualifications</h3><List items={selectedJob.preferred_qualifications} /></details></div>

                <section className="documents" aria-busy={documentsLoading}>
                  <div className="panel-heading"><div><p className="eyebrow">GROUNDED MATERIAL</p><h2>Document review</h2></div><button className="button" disabled={busy || !["SHORTLISTED", "DOCUMENTS_PREPARED"].includes(selected.status)} onClick={generate}>{activeAction === "generate" ? "Generating…" : "Generate version"}</button></div>
                  {documentsLoading ? <LoadingState label="Loading document package" /> : document?.content ? <DocumentPreview document={document} /> : <div className="empty"><h3>No validated document package yet</h3><p>{selected.status === "SHORTLISTED" ? "Generate a grounded package, then review every section." : "Shortlist this opportunity before generating application material."}</p></div>}
                </section>

                <section className="approval" id="safety">
                  <div><p className="eyebrow">HUMAN APPROVAL GATE</p><h2>Manual submission checklist</h2><p>No status can reach submitted without your explicit action. Review the job, score, blockers, document package, answers, and destination first.</p></div>
                  <div className="approval-actions">
                    <button className="button secondary" disabled={busy || selected.status !== "DOCUMENTS_PREPARED"} onClick={() => transition("AWAITING_REVIEW")}>Ready for review</button>
                    <button className="button secondary" disabled={busy || selected.status !== "AWAITING_REVIEW"} onClick={() => transition("APPROVED")}>Approve package</button>
                    <button className="button secondary" disabled={busy || selected.status !== "APPROVED"} onClick={() => transition("READY_TO_SUBMIT", true)}>Confirm data &amp; prepare</button>
                    <button className="button danger" disabled={busy || selected.status !== "READY_TO_SUBMIT"} onClick={() => confirmTransition("SUBMITTED")}>Mark as submitted</button>
                  </div>
                </section>
              </>
            ) : loading ? <LoadingState label="Loading review workspace" large /> : <div className="empty detail-empty"><h2>No application selected</h2><p>Choose an opportunity from the tracker to inspect its score, material, and approval path.</p></div>}
          </section>
        </section>
      </main>
    </div>
  );
}

function LoadingState({ label: text, large = false }: { label: string; large?: boolean }) {
  return <div className={`loading-state ${large ? "loading-state--large" : ""}`} role="status"><span className="spinner" aria-hidden="true" />{text}…</div>;
}

function FirstRunState() {
  return (
    <div className="empty onboarding">
      <p className="eyebrow">GET STARTED</p>
      <h3>Your application tracker is empty</h3>
      <ol><li>Create your candidate profile.</li><li>Import a vacancy.</li><li>Create an application for that job.</li></ol>
      <p>These setup actions currently use the API. The interactive documentation provides the request forms and examples.</p>
      <a className="button secondary" href={`${API}/docs`} target="_blank" rel="noopener noreferrer">Open API setup <span aria-hidden="true">↗</span><span className="sr-only"> in a new tab</span></a>
    </div>
  );
}

function DocumentPreview({ document }: { document: DocumentVersion }) {
  const content = document.content!;
  return (
    <div className="document-preview">
      <div className="document-meta"><span>Version {document.version}</span><span>{document.language.toUpperCase()}</span><span>Automated checks passed <span aria-hidden="true">✓</span></span></div>
      <h3>Professional summary</h3><p>{content.professional_summary.map((item) => item.text).join(" ")}</p>
      <h3>CV highlights</h3><List items={content.cv_highlights.map((item) => item.text)} />
      <h3>Cover letter</h3>{content.cover_letter_paragraphs.map((item, index) => <p key={`${item.text}-${index}`}>{item.text}</p>)}
      <div className="document-columns"><div><h3>Recruiter introduction</h3><p>{content.recruiter_introduction.text}</p></div><div><h3>LinkedIn message</h3><p>{content.linkedin_message.text}</p></div></div>
      <h3>Suggested answers</h3>{content.application_answers.length ? <dl>{content.application_answers.map((item, index) => <div key={`${item.question}-${index}`}><dt>{item.question}</dt><dd>{item.answer.text}</dd></div>)}</dl> : <p className="muted">No suggested answers in this version.</p>}
      <h3>Keyword comparison</h3><p><b>Matching:</b> {content.keyword_comparison.matching_keywords.join(", ") || "—"}</p><p><b>Missing:</b> {content.keyword_comparison.missing_keywords.join(", ") || "—"}</p>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
