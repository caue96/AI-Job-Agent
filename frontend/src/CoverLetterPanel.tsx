import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { CoverLetter, coverLetterApi, CoverLetterLength, CoverLetterTone } from "./cover-letter-api";

const human = (value: string) => value.replaceAll("_", " ").toLowerCase();

export function CoverLetterPanel({ jobId, jobTitle }: { jobId: string; jobTitle: string }) {
  const [letters, setLetters] = useState<CoverLetter[]>([]);
  const [activeId, setActiveId] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [language, setLanguage] = useState("");
  const [tone, setTone] = useState<CoverLetterTone>("PROFESSIONAL");
  const [length, setLength] = useState<CoverLetterLength>("STANDARD");
  const [allVariants, setAllVariants] = useState(true);
  const [greeting, setGreeting] = useState("");
  const [paragraphs, setParagraphs] = useState<string[]>([]);
  const [signoff, setSignoff] = useState("");

  const load = useCallback(async () => {
    const records = await coverLetterApi.list(jobId);
    setLetters(records);
    setActiveId((current) => records.some((item) => item.id === current) ? current : records.find((item) => item.selected)?.id ?? records[0]?.id ?? "");
  }, [jobId]);
  useEffect(() => { void load().catch(() => undefined); }, [load]);
  const active = useMemo(() => letters.find((item) => item.id === activeId) ?? null, [activeId, letters]);
  useEffect(() => {
    if (!active) return;
    setGreeting(active.content.greeting);
    setParagraphs(active.content.paragraphs.map((item) => item.text));
    setSignoff(active.content.signoff);
  }, [active]);

  const act = async (name: string, action: () => Promise<void>, success: string) => {
    setBusy(name); setError(""); setMessage("");
    try { await action(); setMessage(success); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Cover-letter action failed."); }
    finally { setBusy(""); }
  };
  const generate = (event: FormEvent) => {
    event.preventDefault();
    void act("generate", async () => {
      const created = await coverLetterApi.generate({
        job_id: jobId, language: language || null, tone, length,
        variants: allVariants ? ["BALANCED", "TECHNICAL", "BUSINESS_FOCUSED"] : ["BALANCED"],
      });
      setActiveId(created[0]?.id ?? "");
    }, "Grounded draft variants generated for review.");
  };
  const save = () => active && act("save", async () => {
    const updated = await coverLetterApi.edit(active.id, { greeting, paragraphs, signoff });
    setActiveId(updated.id);
  }, "Edits saved as a new version; the prior version is preserved.");
  const copy = async () => {
    if (!active) return;
    const text = [greeting, ...paragraphs, signoff, active.content.candidate_name].join("\n\n");
    try { await navigator.clipboard.writeText(text); setMessage("Cover letter copied to the clipboard."); }
    catch { setError("Clipboard access was denied. Select the text and copy it manually."); }
  };
  const exportLetter = (format: "txt" | "docx" | "pdf") => active && act(`export-${format}`, async () => {
    const result = await coverLetterApi.export(active.id, format);
    window.location.assign(coverLetterApi.downloadUrl(result.id));
  }, `${format.toUpperCase()} export prepared.`);

  return <section className="cover-letter" aria-labelledby="cover-letter-title">
    <div className="panel-heading"><div><p className="eyebrow">GROUNDED COVER LETTER</p><h3 id="cover-letter-title">Write for {jobTitle}</h3><p>AI selects approved evidence; deterministic templates render the prose. Nothing is submitted automatically.</p></div></div>
    {error && <div className="notice notice--error" role="alert">{error}</div>}
    {message && <div className="notice" role="status">{message}</div>}
    <form className="cover-letter-config" onSubmit={generate}>
      <label>Language<select value={language} onChange={(event) => setLanguage(event.target.value)}><option value="">Automatic</option><option value="en">English</option><option value="es">Spanish</option><option value="pt">Portuguese</option></select></label>
      <label>Tone<select value={tone} onChange={(event) => setTone(event.target.value as CoverLetterTone)}>{["PROFESSIONAL", "CONFIDENT", "CONCISE", "WARM", "TECHNICAL", "BUSINESS_ORIENTED", "STARTUP_ORIENTED", "CORPORATE"].map((item) => <option key={item}>{item}</option>)}</select></label>
      <label>Length<select value={length} onChange={(event) => setLength(event.target.value as CoverLetterLength)}><option>SHORT</option><option>STANDARD</option><option>DETAILED</option></select></label>
      <label className="checkbox-label"><input type="checkbox" checked={allVariants} onChange={(event) => setAllVariants(event.target.checked)} /> Generate balanced, technical, and business variants</label>
      <button className="button" disabled={Boolean(busy)}>{busy === "generate" ? "Generating…" : letters.length ? "Generate new drafts" : "Generate drafts"}</button>
    </form>
    {letters.length > 0 && <>
      <div className="cover-letter-tabs" role="tablist" aria-label="Cover-letter versions">{letters.map((item) => <button role="tab" aria-selected={item.id === activeId} className={item.id === activeId ? "active" : ""} key={item.id} onClick={() => setActiveId(item.id)}>{human(item.variant)} <small>v{item.version}</small>{item.selected ? " •" : ""}</button>)}</div>
      {active && <div className="cover-letter-review">
        <aside><dl><div><dt>Match score</dt><dd>{String(active.configuration.match_score ?? "—")}</dd></div><div><dt>Words</dt><dd>{active.content.word_count}</dd></div><div><dt>Status</dt><dd>{human(active.cover_letter_status)}</dd></div><div><dt>Language</dt><dd>{active.language.toUpperCase()}</dd></div></dl>
          {active.configuration.missing_required_skills?.length ? <div className="notice notice--warning"><b>Unsupported gaps</b><p>{active.configuration.missing_required_skills.join(", ")}</p></div> : null}
          {active.configuration.potential_blockers?.length ? <div className="notice notice--warning"><b>Potential blockers</b><p>{active.configuration.potential_blockers.join("; ")}</p></div> : null}
          <details><summary>Evidence used</summary>{active.evidence.map((item) => <blockquote key={item.fact_id}><b>{human(item.source_section)}</b><p>{item.quote}</p></blockquote>)}</details>
        </aside>
        <div className="cover-letter-editor">
          <label>Greeting<input value={greeting} onChange={(event) => setGreeting(event.target.value)} /></label>
          {active.content.paragraphs.map((item, index) => <label key={`${active.id}-${item.kind}`}><span>{human(item.kind)} <small>{Math.round(item.confidence * 100)}% evidence confidence</small></span><textarea rows={Math.max(3, Math.ceil((paragraphs[index]?.length ?? 0) / 100))} value={paragraphs[index] ?? ""} onChange={(event) => setParagraphs((current) => current.map((value, position) => position === index ? event.target.value : value))} /></label>)}
          <label>Closing<input value={signoff} onChange={(event) => setSignoff(event.target.value)} /></label>
          {!active.validation.valid && <div className="notice notice--error" role="alert"><b>Approval blocked</b>{active.validation.issues.map((item) => <p key={`${item.code}-${item.paragraph_index}`}>{item.message}</p>)}</div>}
          {active.validation.low_confidence_paragraphs.length > 0 && <div className="notice notice--warning">Review low-confidence paragraphs: {active.validation.low_confidence_paragraphs.map((item) => item + 1).join(", ")}.</div>}
          <div className="cover-letter-actions"><button className="button secondary" type="button" disabled={Boolean(busy)} onClick={() => void save()}>Save as new version</button><button className="text-button" type="button" onClick={() => void copy()}>Copy</button><button className="text-button" type="button" disabled={Boolean(busy)} onClick={() => void act("validate", async () => { setActiveId((await coverLetterApi.validate(active.id)).id); }, "Validation completed.")}>Validate</button><button className="text-button" type="button" disabled={Boolean(busy)} onClick={() => void act("select", async () => { await coverLetterApi.select(active.id); }, "Variant selected.")}>Select</button>{active.approved_at ? null : <button className="button" type="button" disabled={Boolean(busy) || !active.validation.valid} onClick={() => void act("approve", async () => { await coverLetterApi.approve(active.id); }, "Cover letter approved for export.")}>Approve</button>}</div>
          {active.approved_at && <div className="cover-letter-actions"><button className="button secondary" type="button" disabled={Boolean(busy)} onClick={() => void exportLetter("txt")}>Export TXT</button><button className="button secondary" type="button" disabled={Boolean(busy)} onClick={() => void exportLetter("docx")}>Export DOCX</button><button className="button secondary" type="button" disabled={Boolean(busy)} onClick={() => void exportLetter("pdf")}>Export PDF</button></div>}
        </div>
      </div>}
    </>}
  </section>;
}
