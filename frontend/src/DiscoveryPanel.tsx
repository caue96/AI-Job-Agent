import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Configuration, discoveryApi, Match, Notification, Provider, Run, SearchProfile } from "./discovery-api";

const split = (value: string) => value.split(",").map((item) => item.trim()).filter(Boolean);
const human = (value: string) => value.replaceAll("_", " ").toLowerCase();

export function DiscoveryPanel() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [profile, setProfile] = useState<SearchProfile | null>(null);
  const [configs, setConfigs] = useState<Configuration[]>([]);
  const [matches, setMatches] = useState<Match[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [selected, setSelected] = useState<Match | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [score, setScore] = useState(50);
  const [country, setCountry] = useState("");

  const refresh = useCallback(async () => {
    const settled = await Promise.allSettled([
      discoveryApi.providers(), discoveryApi.profile(), discoveryApi.configurations(),
      discoveryApi.matches(`?min_score=${score}`), discoveryApi.runs(), discoveryApi.notifications(),
    ]);
    if (settled[0].status === "fulfilled") setProviders(settled[0].value);
    if (settled[1].status === "fulfilled") setProfile(settled[1].value);
    if (settled[2].status === "fulfilled") setConfigs(settled[2].value);
    if (settled[3].status === "fulfilled") setMatches(settled[3].value);
    if (settled[4].status === "fulfilled") setRuns(settled[4].value);
    if (settled[5].status === "fulfilled") setNotifications(settled[5].value);
  }, [score]);
  useEffect(() => { void refresh(); }, [refresh]);

  const visible = useMemo(() => matches.filter((item) => !country || item.country === country), [matches, country]);
  const act = async (action: () => Promise<unknown>, success: string) => {
    setBusy(true); setError("");
    try { await action(); setNotice(success); await refresh(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Discovery action failed."); }
    finally { setBusy(false); }
  };

  const generate = () => act(async () => setProfile(await discoveryApi.generateProfile()), "Search profile generated from approved CV facts.");
  const saveProfile = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (!profile) return;
    const data = new FormData(event.currentTarget);
    const preferences = { ...profile.preferences, target_titles: split(String(data.get("titles") ?? "")), preferred_countries: split(String(data.get("countries") ?? "")).map((item) => item.toUpperCase()), preferred_cities: split(String(data.get("cities") ?? "")), excluded_companies: split(String(data.get("excludedCompanies") ?? "")), minimum_salary: Number(data.get("salary")) || null };
    await act(async () => setProfile(await discoveryApi.saveProfile(preferences)), "Search preferences saved.");
  };
  const createConfig = () => act(async () => {
    const available = providers.filter((item) => item.automated_search && item.configured);
    if (!available.length) throw new Error("Configure an official API credential or Tecnoempleo feed first.");
    const enabled = available.reduce<Record<string, { enabled: boolean }>>((all, item) => ({ ...all, [item.key]: { enabled: true } }), {});
    await discoveryApi.createConfiguration({ name: "Daily EU opportunities", provider_settings: enabled, schedule_kind: "WEEKDAYS", schedule_time: "09:00", timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, hard_filters: { countries: profile?.preferences.preferred_countries ?? [], minimum_score: 50 } });
  }, "Automatic search configured.");
  const importJob = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const data = Object.fromEntries(new FormData(event.currentTarget));
    await act(() => discoveryApi.importManual(data), "Job imported, deduplicated, and scored.");
    event.currentTarget.reset();
  };

  return <section className="discovery" id="discovery" aria-labelledby="discovery-title">
    <header className="discovery-hero">
      <div><p className="eyebrow">COMPLIANT JOB DISCOVERY</p><h2 id="discovery-title">Find the right roles without scraping</h2><p>Official APIs and public feeds run automatically. Restricted sources use imports you explicitly provide.</p></div>
      <button className="button" disabled={busy || !configs.length} onClick={() => act(() => discoveryApi.run(configs[0].id), "Search completed. Provider failures, if any, were isolated.")}>Run search</button>
    </header>
    {error && <div className="notice notice--error" role="alert">{error}</div>}
    {notice && <div className="notice" role="status">{notice}</div>}

    <div className="discovery-metrics">
      <article><span>Ranked matches</span><strong>{visible.length}</strong></article>
      <article><span>Strong matches</span><strong>{matches.filter((item) => item.recommendation === "STRONG_MATCH").length}</strong></article>
      <article><span>Provider errors</span><strong>{providers.filter((item) => item.last_error).length}</strong></article>
      <article><span>Unread alerts</span><strong>{notifications.filter((item) => !item.read_at).length}</strong></article>
    </div>

    <div className="discovery-grid">
      <section className="panel discovery-settings"><div className="panel-heading"><div><h3>Search profile</h3><p>Deterministic and editable</p></div>{!profile && <button className="button secondary" disabled={busy} onClick={generate}>Generate from CV</button>}</div>
        {profile ? <form onSubmit={saveProfile} className="discovery-form">
          <label>Target roles<input name="titles" defaultValue={profile.preferences.target_titles.join(", ")} /></label>
          <label>Countries<input name="countries" defaultValue={profile.preferences.preferred_countries.join(", ")} /></label>
          <label>Cities<input name="cities" defaultValue={profile.preferences.preferred_cities.join(", ")} /></label>
          <label>Minimum salary<input name="salary" type="number" min="0" defaultValue={profile.preferences.minimum_salary ?? ""} /></label>
          <label className="wide">Excluded companies<input name="excludedCompanies" defaultValue={profile.preferences.excluded_companies.join(", ")} /></label>
          <button className="button secondary" disabled={busy}>Save preferences</button>
        </form> : <p className="muted">Confirm a CV-based profile, then generate reviewable search preferences.</p>}
      </section>
      <section className="panel"><div className="panel-heading"><div><h3>Automatic search</h3><p>{configs.length ? `${human(configs[0].schedule_kind)} at ${configs[0].schedule_time}` : "Not configured"}</p></div>{!configs.length && profile && <button className="button secondary" onClick={createConfig}>Configure</button>}</div>
        <div className="provider-list">{providers.map((item) => <article key={item.key}><div><b>{item.name}</b><small>{human(item.access_type)} · {human(item.implementation_status)}</small></div><span className={`provider-health ${item.last_error ? "failed" : ""}`}>{item.last_error ? "Error" : item.automated_search ? item.health : "Import"}</span><p>{item.automated_search ? item.limitations : `Fallback: ${item.fallback}`}</p></article>)}</div>
      </section>
    </div>

    <section className="panel discovery-results"><div className="panel-heading"><div><h3>Ranked opportunities</h3><p>One canonical card per vacancy</p></div><div className="discovery-filters"><label>Minimum score<input aria-label="Minimum match score" type="range" min="0" max="100" value={score} onChange={(event) => setScore(Number(event.target.value))} /><span>{score}</span></label><label>Country<select aria-label="Country filter" value={country} onChange={(event) => setCountry(event.target.value)}><option value="">All</option><option>ES</option><option>PT</option><option>IE</option></select></label></div></div>
      <div className="job-card-grid">{visible.map((item) => <article className="discovery-card" key={item.id} onClick={() => setSelected(item)}><header><div><span>{item.provider}</span><h4>{item.title}</h4><p>{item.company} · {[item.city, item.country].filter(Boolean).join(", ")}</p></div><strong>{item.score}</strong></header><div className="skill-chips">{item.analysis.matching_skills?.slice(0, 4).map((skill) => <span key={skill}>{skill}</span>)}</div><p className="blocker">{item.analysis.potential_blockers?.[0] ?? "No hard blocker recorded"}</p><footer><b>{human(item.recommendation)}</b><div><button className="text-button" onClick={(event) => { event.stopPropagation(); void act(() => discoveryApi.action(item.match_id, "SAVE"), "Opportunity saved."); }}>Save</button><button className="text-button" onClick={(event) => { event.stopPropagation(); void act(() => discoveryApi.action(item.match_id, "REJECT"), "Opportunity rejected."); }}>Reject</button>{item.url && <a href={item.url} target="_blank" rel="noopener noreferrer">Original ↗</a>}</div></footer></article>)}</div>
      {!visible.length && <div className="empty"><h4>No ranked opportunities yet</h4><p>Run an enabled provider or import a vacancy description below.</p></div>}
    </section>

    {selected && <section className="panel match-detail" aria-label="Detailed match analysis"><button className="text-button" onClick={() => setSelected(null)}>Close analysis</button><h3>{selected.title} at {selected.company}</h3><p>{selected.analysis.reasons_to_apply?.join(" ")}</p><div className="analysis-grid">{Object.entries(selected.analysis.score_by_category ?? {}).map(([key, value]) => <article key={key}><b>{human(key)}</b><strong>{value.score}/{value.maximum}</strong><p>{value.explanation}</p></article>)}</div><button className="button" onClick={() => act(() => discoveryApi.action(selected.match_id, "PREPARE_APPLICATION"), "Application preparation created. Nothing was submitted.")}>Prepare application</button></section>}

    <div className="discovery-grid"><form className="panel discovery-form" onSubmit={importJob}><div className="panel-heading"><div><h3>Import a restricted-source job</h3><p>Paste the description; the server does not scrape the URL.</p></div></div><label>Source<select name="provider" required>{providers.map((item) => <option key={item.key} value={item.key}>{item.name}</option>)}</select></label><label>URL<input name="url" type="url" /></label><label>Company<input name="company" required maxLength={200} /></label><label>Job title<input name="title" required maxLength={200} /></label><label className="wide">Description<textarea name="description" required maxLength={50000} rows={5} /></label><button className="button secondary" disabled={busy}>Import and score</button></form>
      <section className="panel"><div className="panel-heading"><div><h3>Activity</h3><p>Search history and notifications</p></div></div><ul className="activity-list">{notifications.slice(0, 5).map((item) => <li key={item.id}><b>{item.title}</b><span>{item.body}</span></li>)}{runs.slice(0, 5).map((run) => <li key={run.id}><b>{human(run.status)} search</b><span>{run.counters.new_jobs ?? 0} new · {run.counters.strong_matches ?? 0} strong</span></li>)}</ul></section>
    </div>
  </section>;
}
