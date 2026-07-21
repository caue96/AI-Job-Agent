import { useCallback, useEffect, useState } from "react";
import { Analysis, cvOptimizationApi, Preview, Recommendation, Variant } from "./cv-optimization-api";

const human = (value: string) => value.replaceAll("_", " ").toLowerCase();

export function CvOptimizationPanel({ jobId, jobTitle, originalScore }: { jobId: string; jobTitle: string; originalScore: number }) {
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [variant, setVariant] = useState<Variant | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [edits, setEdits] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    const [analyses, variants] = await Promise.all([cvOptimizationApi.analyses(jobId), cvOptimizationApi.variants(jobId)]);
    setAnalysis(analyses[0] ?? null); setVariant(variants[0] ?? null);
  }, [jobId]);
  useEffect(() => { void load().catch(() => undefined); }, [load]);

  const act = async (name: string, action: () => Promise<void>, success: string) => {
    setBusy(name); setError(""); setMessage(""); setPreview(null);
    try { await action(); setMessage(success); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "CV optimization failed."); }
    finally { setBusy(""); }
  };
  const decide = (item: Recommendation, decision: "ACCEPTED" | "REJECTED" | "EDITED") => act(
    `${decision}-${item.id}`,
    async () => { await cvOptimizationApi.decide(item.id, decision, decision === "EDITED" ? edits[item.id] : undefined); },
    `Recommendation ${human(decision)}.`,
  );
  const exportVariant = (format: "pdf" | "docx") => act(`export-${format}`, async () => {
    const result = await cvOptimizationApi.export(variant!.id, format);
    window.location.assign(cvOptimizationApi.downloadUrl(result.id));
  }, `${format.toUpperCase()} export prepared.`);

  return <section className="cv-optimization" aria-labelledby="cv-optimization-title">
    <div className="panel-heading"><div><p className="eyebrow">JOB-SPECIFIC CV</p><h3 id="cv-optimization-title">Improve CV for {jobTitle}</h3><p>Every suggestion cites approved CV evidence. Your master CV is never changed.</p></div>
      {!analysis && <button className="button" disabled={Boolean(busy)} onClick={() => act("analyze", async () => { setAnalysis(await cvOptimizationApi.analyze(jobId)); }, "Evidence-grounded analysis created.")}>{busy === "analyze" ? "Analyzing…" : "Analyze CV"}</button>}
    </div>
    {error && <div className="notice notice--error" role="alert">{error}</div>}
    {message && <div className="notice" role="status">{message}</div>}
    {analysis && <>
      <div className="cv-score-summary"><div><span>Original deterministic score</span><strong>{analysis.original_score}</strong></div><p>Presentation can improve clarity and keyword placement. It cannot create experience or remove factual blockers.</p></div>
      {analysis.input_summary.missing_required_skills?.length ? <div className="notice notice--warning"><b>Remaining qualification gaps:</b> {analysis.input_summary.missing_required_skills.join(", ")}. These are not offered as CV edits because the approved profile has no supporting evidence.</div> : null}
      <div className="recommendation-toolbar"><span>{analysis.recommendations.filter((item) => item.decision === "PENDING").length} awaiting review</span><div><button className="text-button" disabled={Boolean(busy)} onClick={() => act("accept-safe", async () => { setAnalysis(await cvOptimizationApi.batch(analysis.id, "ACCEPT_SAFE")); }, "All validated edit recommendations accepted.")}>Accept safe edits</button><button className="text-button" disabled={Boolean(busy)} onClick={() => act("reset", async () => { setAnalysis(await cvOptimizationApi.batch(analysis.id, "RESET")); }, "Review decisions reset.")}>Reset</button></div></div>
      <div className="recommendation-list">{analysis.recommendations.map((item) => <article className={`recommendation recommendation--${item.priority.toLowerCase()}`} key={item.id}><header><div><span>{human(item.category)} · {human(item.recommendation_type)}</span><h4>{item.section}</h4></div><b>{human(item.priority)}</b></header>
        {item.current_text && <div className="text-comparison"><div><small>Current</small><p>{item.current_text}</p></div><div><small>Suggested</small><p>{item.suggested_text}</p></div></div>}
        {!item.current_text && <p>{item.reason}</p>}<p><b>Why:</b> {item.reason}</p><p><b>Expected benefit:</b> {item.expected_benefit}</p>
        <details><summary>View supporting evidence</summary>{item.evidence.map((evidence) => <blockquote key={evidence.id}><b>{evidence.source_section}</b><p>{evidence.quote}</p></blockquote>)}</details>
        <label className="edit-recommendation">Edit suggestion<textarea rows={3} value={edits[item.id] ?? item.suggested_text} onChange={(event) => setEdits((current) => ({ ...current, [item.id]: event.target.value }))} /></label><footer><span className={`decision decision--${item.decision.toLowerCase()}`}>{human(item.decision)}</span><div><button className="text-button" disabled={Boolean(busy)} onClick={() => decide(item, "REJECTED")}>Reject</button><button className="text-button" disabled={Boolean(busy)} onClick={() => decide(item, "EDITED")}>Save edit</button><button className="button secondary" disabled={Boolean(busy)} onClick={() => decide(item, "ACCEPTED")}>Accept</button></div></footer>
      </article>)}</div>
      {!variant && !preview && <button className="button" disabled={Boolean(busy) || !analysis.recommendations.some((item) => ["ACCEPTED", "EDITED"].includes(item.decision))} onClick={() => act("preview", async () => { setPreview(await cvOptimizationApi.preview(analysis.id)); }, "Preview generated. Review it before saving.")}>{busy === "preview" ? "Generating preview…" : "Preview revised CV"}</button>}
      {!variant && preview && <section className="variant-summary" aria-label="Revised CV preview"><h4>Revised CV preview</h4><p><b>Headline:</b> {preview.content.headline.value}</p><p><b>Summary:</b> {preview.content.professional_summary.value}</p><p><b>Skills:</b> {preview.content.technical_skills.map((item) => item.value).join(", ")}</p><p>{preview.score_explanation}</p>{preview.remaining_gaps.length > 0 && <p><b>Remaining gaps:</b> {preview.remaining_gaps.join(", ")}</p>}<div><button className="text-button" disabled={Boolean(busy)} onClick={() => setPreview(null)}>Back to review</button><button className="button" disabled={Boolean(busy)} onClick={() => act("variant", async () => { setVariant(await cvOptimizationApi.createVariant(analysis.id)); }, "Job-specific CV variant saved.")}>{busy === "variant" ? "Saving…" : "Save this variant"}</button></div></section>}
      {variant && <section className="variant-summary"><h4>Variant ready</h4><p>{variant.latest_version.score_explanation}</p><p><b>Improved sections:</b> {variant.latest_version.sections_improved.join(", ")}</p>{variant.latest_version.remaining_gaps.length > 0 && <p><b>Remaining gaps:</b> {variant.latest_version.remaining_gaps.join(", ")}</p>}<div><button className="button secondary" disabled={Boolean(busy)} onClick={() => exportVariant("pdf")}>Export PDF</button><button className="button secondary" disabled={Boolean(busy)} onClick={() => exportVariant("docx")}>Export DOCX</button></div></section>}
    </>}
    {!analysis && <p className="muted">Analyze after the approved CV profile and deterministic job match are available. Current match: {originalScore}/100.</p>}
  </section>;
}
