import { useEffect, useRef, useState } from "react";
import {
  compareCvImport,
  confirmCvImport,
  deleteCvFile,
  deleteCvImport,
  getCvImport,
  listCvImports,
  saveCvDraft,
  uploadCv,
} from "./cv-api";
import type { CvComparison, CvDraft, CvImport, CvImportSummary, CvListValue, CvValue } from "./cv-types";

const MAX_BYTES = 10 * 1024 * 1024;
const steps = ["PDF_SELECTED", "PDF_VALIDATED", "TEXT_EXTRACTED", "PROFILE_PARSED", "AWAITING_REVIEW", "PROFILE_CONFIRMED", "PROFILE_SAVED"];
const personalLabels: Record<string, string> = {
  full_name: "Full name", email: "Email", phone: "Phone", city: "City", country: "Country",
  linkedin_url: "LinkedIn", github_url: "GitHub", portfolio_url: "Portfolio",
  work_authorization: "Work authorization",
};
const scalarLabels: [keyof CvDraft, string][] = [
  ["headline", "Professional headline"], ["professional_summary", "Professional summary"],
  ["salary_expectation", "Salary expectation"], ["availability", "Availability"],
  ["declared_years_experience", "Declared experience (years)"],
  ["calculated_years_experience", "Calculated experience (years)"],
];
const listLabels: [keyof CvDraft, string][] = [
  ["technical_skills", "Technical skills"], ["soft_skills", "Soft skills"],
  ["languages", "Languages"], ["achievements", "Achievements"], ["citizenships", "Citizenships"],
  ["preferred_locations", "Preferred locations"], ["preferred_titles", "Preferred roles"],
  ["preferred_industries", "Preferred industries"], ["workplace_preferences", "Workplace preferences"],
];

const userEvidence = (value: string) => [{ page: 1, quote: value || "User-provided during review", method: "user" as const }];

function Evidence({ field }: { field: CvValue | CvListValue }) {
  return field.evidence.length ? (
    <details className="cv-evidence">
      <summary>Evidence · {Math.round(field.confidence * 100)}% confidence</summary>
      {field.evidence.map((item, index) => <blockquote key={`${item.page}-${index}`}>Page {item.page}: “{item.quote}”</blockquote>)}
    </details>
  ) : <small className="cv-uncertain">Not found in the PDF — confirm or add manually.</small>;
}

function StringField({ label, field, onChange, multiline = false, readOnly = false }: {
  label: string; field: CvValue; onChange: (value: string) => void; multiline?: boolean; readOnly?: boolean;
}) {
  const input = multiline
    ? <textarea value={String(field.value ?? "")} readOnly={readOnly} onChange={(event) => onChange(event.target.value)} rows={4} />
    : <input value={String(field.value ?? "")} readOnly={readOnly} onChange={(event) => onChange(event.target.value)} />;
  return <label className={`cv-field ${field.ambiguous || field.confidence < .7 ? "cv-field--uncertain" : ""}`}><span>{label}{readOnly ? " (derived)" : ""}</span>{input}<Evidence field={field} /></label>;
}

function JsonSection({ label, value, onChange }: { label: string; value: Record<string, unknown>[]; onChange: (value: Record<string, unknown>[]) => void }) {
  const [text, setText] = useState(() => JSON.stringify(value, null, 2));
  const [error, setError] = useState("");
  useEffect(() => setText(JSON.stringify(value, null, 2)), [value]);
  const apply = () => {
    try {
      const parsed: unknown = JSON.parse(text);
      if (!Array.isArray(parsed)) throw new Error("Use a JSON array.");
      onChange(parsed as Record<string, unknown>[]); setError("");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Invalid JSON"); }
  };
  return <details className="cv-json-section"><summary>{label} <span>{value.length} entries</span></summary><p>Edit, add, or remove structured entries. Keep evidence beside extracted values.</p><textarea aria-label={`${label} structured data`} value={text} onChange={(event) => setText(event.target.value)} rows={10} /><button className="button secondary" type="button" onClick={apply}>Apply {label.toLowerCase()} edits</button>{error && <p className="field-error" role="alert">{error}</p>}</details>;
}

export function CvImportPanel() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [selected, setSelected] = useState<File | null>(null);
  const [record, setRecord] = useState<CvImport | null>(null);
  const [draft, setDraft] = useState<CvDraft | null>(null);
  const [history, setHistory] = useState<CvImportSummary[]>([]);
  const [comparison, setComparison] = useState<CvComparison | null>(null);
  const [strategy, setStrategy] = useState<"replace" | "merge">("merge");
  const [acceptConflicts, setAcceptConflicts] = useState(false);
  const [busy, setBusy] = useState("");
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState<{ kind: "error" | "success"; text: string } | null>(null);

  const refreshHistory = () => listCvImports().then(setHistory).catch(() => undefined);
  useEffect(() => { refreshHistory(); }, []);

  const choose = (file?: File) => {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pdf") || file.type !== "application/pdf") {
      setMessage({ kind: "error", text: "Choose a PDF file. Renamed or non-PDF files are rejected by the server." }); return;
    }
    if (!file.size || file.size > MAX_BYTES) {
      setMessage({ kind: "error", text: file.size ? "The PDF must be 10 MB or smaller." : "The selected PDF is empty." }); return;
    }
    setSelected(file); setRecord(null); setDraft(null); setComparison(null); setMessage(null); setProgress(0);
  };

  const beginUpload = async () => {
    if (!selected) return;
    setBusy("Uploading PDF"); setMessage(null);
    try {
      const imported = await uploadCv(selected, (value) => { setProgress(value); if (value === 100) setBusy("Extracting and parsing securely"); });
      setRecord(imported); setDraft(imported.draft); setProgress(100);
      if (imported.draft) setComparison(await compareCvImport(imported.id));
      setMessage({ kind: "success", text: imported.draft ? "Extraction complete. Review every field before saving." : "Text extraction completed, but this appears to be a scanned PDF." });
      await refreshHistory();
    } catch (error) { setMessage({ kind: "error", text: error instanceof Error ? error.message : "Upload failed." }); }
    finally { setBusy(""); }
  };

  const load = async (id: string) => {
    setBusy("Loading import"); setMessage(null);
    try { const imported = await getCvImport(id); setRecord(imported); setDraft(imported.draft); setComparison(imported.draft ? await compareCvImport(id) : null); }
    catch (error) { setMessage({ kind: "error", text: error instanceof Error ? error.message : "Could not load the import." }); }
    finally { setBusy(""); }
  };

  const updateScalar = (key: keyof CvDraft, value: string) => setDraft((current) => current ? ({ ...current, [key]: { ...(current[key] as CvValue), value, confidence: 1, ambiguous: false, evidence: userEvidence(value) } }) : current);
  const updatePersonal = (key: string, value: string) => setDraft((current) => current ? ({ ...current, personal: { ...current.personal, [key]: { ...current.personal[key], value, confidence: 1, ambiguous: false, evidence: userEvidence(value) } } }) : current);
  const updateList = (key: keyof CvDraft, value: string) => setDraft((current) => current ? ({ ...current, [key]: value.split(",").map((item) => item.trim()).filter(Boolean).map((item) => ({ value: item, confidence: 1, evidence: userEvidence(item) })) }) : current);

  const save = async () => {
    if (!record || !draft) return;
    setBusy("Saving draft");
    try { const updated = await saveCvDraft(record.id, draft); setRecord(updated); setDraft(updated.draft); setMessage({ kind: "success", text: "Review edits saved as a draft." }); }
    catch (error) { setMessage({ kind: "error", text: error instanceof Error ? error.message : "Could not save." }); }
    finally { setBusy(""); }
  };

  const confirm = async () => {
    if (!record || !draft) return;
    if (!window.confirm(`Save this reviewed CV using the ${strategy} strategy?`)) return;
    setBusy("Saving profile");
    try { await saveCvDraft(record.id, draft); await confirmCvImport(record.id, strategy, acceptConflicts); const updated = await getCvImport(record.id); setRecord(updated); setMessage({ kind: "success", text: "Profile saved with a versioned, auditable snapshot." }); await refreshHistory(); }
    catch (error) { setMessage({ kind: "error", text: error instanceof Error ? error.message : "Could not save the profile." }); }
    finally { setBusy(""); }
  };

  const cancel = async () => {
    if (record && window.confirm("Delete this import draft and its uploaded PDF?")) { await deleteCvImport(record.id); await refreshHistory(); }
    setSelected(null); setRecord(null); setDraft(null); setComparison(null); setMessage(null); setProgress(0);
  };

  return <section className="panel cv-import" id="cv-import" aria-busy={Boolean(busy)}>
    <div className="panel-heading"><div><p className="eyebrow">PROFILE FOUNDATION</p><h2>Import your CV</h2><p className="muted">PDF text is extracted privately, grounded to page evidence, and never saved to your profile until you confirm it.</p></div><span>PDF · 10 MB max</span></div>
    {message && <div className={`notice notice--${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>{message.text}</div>}
    {!record && <>
      <div className="cv-dropzone" role="button" tabIndex={0} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") inputRef.current?.click(); }} onClick={() => inputRef.current?.click()} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); choose(event.dataTransfer.files[0]); }}>
        <input ref={inputRef} className="sr-only" type="file" accept="application/pdf,.pdf" onChange={(event) => choose(event.target.files?.[0])} />
        <b>{selected ? selected.name : "Drop a PDF here or choose a file"}</b><span>{selected ? `${(selected.size / 1024).toFixed(0)} KB ready to upload` : "The original filename is metadata only; storage uses a generated private name."}</span>
      </div>
      {busy && <div className="cv-progress" role="status"><progress value={progress} max="100" />{busy} · {progress}%</div>}
      <div className="cv-actions"><button className="button" disabled={!selected || Boolean(busy)} onClick={beginUpload}>Upload and extract</button>{selected && <button className="button secondary" onClick={() => setSelected(null)}>Clear</button>}</div>
    </>}
    {record && <ol className="cv-steps" aria-label="Import progress">{steps.map((step) => <li key={step} className={steps.indexOf(step) <= steps.indexOf(record.status) ? "done" : ""}>{step.replaceAll("_", " ").toLowerCase()}</li>)}</ol>}
    {record?.validation.scanned_likely && <div className="cv-scanned" role="alert"><b>This PDF appears to contain images rather than selectable text.</b><p>OCR is intentionally not enabled. Upload a text-based PDF or enter the profile manually through the API.</p></div>}
    {record && draft && <div className="cv-review">
      <header><h3>Review extracted profile</h3><p>Low-confidence and missing fields are highlighted. Evidence opens beneath each value.</p></header>
      <fieldset><legend>Personal details</legend><div className="cv-field-grid">{Object.entries(draft.personal).map(([key, field]) => <StringField key={key} label={personalLabels[key] ?? key} field={field} onChange={(value) => updatePersonal(key, value)} />)}</div></fieldset>
      <fieldset><legend>Profile summary</legend><div className="cv-field-grid">{scalarLabels.map(([key, title]) => <StringField key={key} label={title} field={draft[key] as CvValue} multiline={key === "professional_summary"} readOnly={key === "calculated_years_experience"} onChange={(value) => updateScalar(key, value)} />)}</div></fieldset>
      <fieldset><legend>Skills, languages, and preferences</legend><div className="cv-field-grid">{listLabels.map(([key, title]) => { const items = draft[key] as CvListValue[]; return <label className="cv-field" key={key}><span>{title}</span><textarea rows={3} value={items.map((item) => item.value).join(", ")} onChange={(event) => updateList(key, event.target.value)} />{items.slice(0, 3).map((item, index) => <Evidence key={index} field={item} />)}</label>; })}</div></fieldset>
      <fieldset><legend>Consent and mobility</legend><div className="cv-checkboxes">{(["requires_sponsorship", "relocation_available"] as const).map((key) => <label key={key}><input type="checkbox" checked={draft[key].value === true} onChange={(event) => setDraft({ ...draft, [key]: { ...draft[key], value: event.target.checked, confidence: 1, ambiguous: false, evidence: userEvidence(String(event.target.checked)) } })} />{key.replaceAll("_", " ")}</label>)}</div></fieldset>
      <fieldset><legend>Detailed history</legend>{(["employment", "education", "certifications", "projects"] as const).map((key) => <JsonSection key={key} label={key[0].toUpperCase() + key.slice(1)} value={draft[key]} onChange={(value) => setDraft({ ...draft, [key]: value })} />)}</fieldset>
      {comparison?.profile_exists && <section className="cv-comparison"><h3>Existing profile comparison</h3>{comparison.conflicts.length ? <><p>{comparison.conflicts.length} conflicting fields require attention.</p><ul>{comparison.conflicts.map((item) => <li key={item.field}><b>{item.field}</b>: existing “{String(item.existing)}” / imported “{String(item.imported)}”</li>)}</ul></> : <p>No scalar conflicts found.</p>}<label>Save strategy <select value={strategy} onChange={(event) => { setStrategy(event.target.value as "replace" | "merge"); setAcceptConflicts(false); }}><option value="merge">Merge missing information</option><option value="replace">Replace existing profile</option></select></label>{strategy === "merge" && comparison.conflicts.length > 0 && <label><input type="checkbox" checked={acceptConflicts} onChange={(event) => setAcceptConflicts(event.target.checked)} />I reviewed these conflicts; keep existing values where they differ.</label>}</section>}
      <div className="cv-actions"><button className="button secondary" disabled={Boolean(busy)} onClick={save}>Save draft</button><button className="button" disabled={Boolean(busy) || (strategy === "merge" && Boolean(comparison?.conflicts.length) && !acceptConflicts)} onClick={confirm}>Confirm and save profile</button>{record.file_available && <button className="button secondary" onClick={async () => { await deleteCvFile(record.id); setRecord({ ...record, file_available: false }); }}>Delete uploaded PDF</button>}<button className="button danger" onClick={cancel}>Cancel import</button></div>
    </div>}
    {history.length > 0 && <details className="cv-history"><summary>Previous imports ({history.length})</summary><ul>{history.map((item) => <li key={item.id}><button className="text-button" onClick={() => load(item.id)}>{item.original_filename}</button><span>{item.status.replaceAll("_", " ").toLowerCase()} · {new Date(item.created_at).toLocaleDateString()}</span></li>)}</ul></details>}
  </section>;
}
