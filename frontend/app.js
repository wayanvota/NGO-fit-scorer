const { useState, useEffect } = React;

async function api(path, opts = {}) {
  const res = await fetch(path, {
    method: opts.method || "GET",
    headers: opts.form ? undefined : { "Content-Type": "application/json" },
    body: opts.form ? opts.form : opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) { let m = res.statusText; try { m = (await res.json()).detail || m; } catch (e) {} throw new Error(m); }
  const ct = res.headers.get("content-type") || "";
  return ct.includes("json") ? res.json() : res.text();
}

const tierClass = (t) => "tier-" + (t || "").replace(/\s+/g, "");

// --------------------------------------------------------------------------
function Login({ config, onLogin }) {
  const [email, setEmail] = useState(""); const [err, setErr] = useState("");
  const submit = async () => {
    setErr("");
    try { await api("/api/dev-login", { method: "POST", body: { email } }); onLogin(); }
    catch (e) { setErr(e.message); }
  };
  return (
    <div className="card login-card">
      <h2>{config.org.tool_name}</h2>
      <p className="muted">{config.org.tagline}</p>
      {config.google_oauth ? (
        <a className="btn" href="/api/login/google" style={{ display: "inline-block", marginTop: 12 }}>Sign in with Google</a>
      ) : config.dev_auth ? (
        <div>
          <label>Work email (allowed domain)</label>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.org" />
          <div style={{ marginTop: 12 }}><button className="btn" onClick={submit}>Sign in</button></div>
          <p className="muted" style={{ marginTop: 14 }}>Dev sign-in is for local use only. Configure Google SSO for production.</p>
        </div>
      ) : <p className="err">Sign-in is not configured. Set Google OAuth or enable DEV_AUTH.</p>}
      {err && <div className="err">{err}</div>}
    </div>
  );
}

// --------------------------------------------------------------------------
function DimensionBars({ dims, labels }) {
  return (
    <div>
      {Object.keys(dims || {}).map((k) => {
        const d = dims[k] || {};
        return (
          <div className="dim" key={k}>
            <div className="dh"><span>{labels[k] || k}</span><span>{Math.round(d.score || 0)}</span></div>
            <div className="bar"><span style={{ width: (d.score || 0) + "%" }}></span></div>
            {d.justification && <div className="why">{d.justification}</div>}
          </div>
        );
      })}
    </div>
  );
}

function ScoreCard({ opp, labels, onChanged }) {
  const s = opp.score; if (!s) return null;
  const hfr = s.hard_filter_result || {}; const dq = hfr.disqualified; const soft = hfr.soft || [];
  return (
    <div className="card">
      <div className="score-hero">
        <div className="score-num" style={{ color: dq ? "var(--dq)" : "var(--brand)" }}>{dq ? "0" : Math.round(s.overall_score)}</div>
        <div>
          <span className={"tier-badge " + tierClass(s.tier)}>{s.tier}</span>
          <div className="muted" style={{ marginTop: 6 }}>Confidence: {s.confidence} · Profile v{s.profile_version} · {s.model_used}</div>
        </div>
      </div>
      {dq && (
        <div className="knockout"><strong>Disqualified.</strong> Tripped: {(hfr.tripped || []).join(", ")}.
          <ul style={{ margin: "6px 0 0" }}>{(hfr.tripped || []).map((k) => <li key={k}>{(hfr.detail || {})[k]}</li>)}</ul></div>
      )}
      {!dq && soft.length > 0 && (
        <div className="conditional"><strong>Conditional: {soft.map((f) => f.key).join(", ")}.</strong> A blocker stands in the way but may be resolvable (e.g. via a partner). Tier capped at Watch until it clears.
          <ul style={{ margin: "6px 0 0" }}>{soft.map((f) => <li key={f.key}>{f.reason}</li>)}</ul></div>
      )}
      <h3>Dimension breakdown</h3>
      <DimensionBars dims={s.dimension_scores} labels={labels} />
      <h3>Go / no-go memo</h3>
      <div className="memo" dangerouslySetInnerHTML={{ __html: marked.parse(s.memo_markdown || "") }} />
      <FeedbackBox opp={opp} onChanged={onChanged} />
    </div>
  );
}

function FeedbackBox({ opp, onChanged }) {
  const s = opp.score;
  const [tier, setTier] = useState(opp.feedback?.override_tier || "");
  const [reason, setReason] = useState(opp.feedback?.override_reason || "");
  const [msg, setMsg] = useState(""); const [err, setErr] = useState("");
  const save = async () => {
    setMsg(""); setErr("");
    try { await api(`/api/scores/${s.id}/feedback`, { method: "POST", body: { override_tier: tier, override_reason: reason } });
      setMsg("Correction saved. It feeds the next recalibration."); onChanged && onChanged(); }
    catch (e) { setErr(e.message); }
  };
  return (
    <div style={{ marginTop: 16, borderTop: "1px solid var(--line)", paddingTop: 14 }}>
      <h3>Disagree? Log a correction</h3>
      <div className="row">
        <select value={tier} onChange={(e) => setTier(e.target.value)} style={{ width: 220 }}>
          <option value="">Your tier (optional)</option>
          {["Pursue", "Pursue with review", "Watch", "Pass", "Disqualified"].map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>
      <label>Why (short reason, this trains recalibration)</label>
      <input type="text" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Funder gives unrestricted despite the RFP language" />
      <div style={{ marginTop: 10 }}><button className="btn secondary" onClick={save}>Save correction</button></div>
      {msg && <div className="ok">{msg}</div>} {err && <div className="err">{err}</div>}
    </div>
  );
}

// --------------------------------------------------------------------------
function SubmitView({ labels, onScored }) {
  const [mode, setMode] = useState("text");
  const [text, setText] = useState(""); const [url, setUrl] = useState(""); const [file, setFile] = useState(null);
  const [warmth, setWarmth] = useState(""); const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(""); const [result, setResult] = useState(null);
  const submit = async () => {
    setBusy(true); setErr(""); setResult(null);
    try {
      let opp;
      if (mode === "file") {
        if (!file) throw new Error("Choose a PDF, Word, or text file first.");
        const fd = new FormData(); fd.append("file", file); if (warmth) fd.append("warmth", warmth);
        opp = await api("/api/opportunities/upload", { method: "POST", form: fd });
      } else {
        opp = await api("/api/opportunities", { method: "POST",
          body: { source_type: mode, text, url, variables: warmth ? { relationship_warmth: warmth } : {} } });
      }
      setResult(opp); onScored && onScored();
    } catch (e) { setErr(e.message); }
    setBusy(false);
  };
  return (
    <div>
      <div className="card">
        <h2>Score an opportunity</h2>
        <div className="seg" style={{ marginBottom: 10 }}>
          <button className={mode === "text" ? "on" : ""} onClick={() => setMode("text")}>Paste text</button>
          <button className={mode === "url" ? "on" : ""} onClick={() => setMode("url")}>From URL</button>
          <button className={mode === "file" ? "on" : ""} onClick={() => setMode("file")}>Upload file</button>
        </div>
        {mode === "text" && (<div><label>Opportunity text (RFP, grant call, or funder email)</label>
          <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste the full opportunity text..." /></div>)}
        {mode === "url" && (<div><label>Opportunity URL</label>
          <input type="text" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://funder.org/rfp/..." /></div>)}
        {mode === "file" && (<div><label>Upload the application page or RFP (PDF, Word, or text)</label>
          <input type="file" accept=".pdf,.docx,.txt,.md" onChange={(e) => setFile(e.target.files[0] || null)} />
          <p className="muted" style={{ marginTop: 6 }}>Print the application page to PDF and upload it. Scanned image-only PDFs won't work; the text must be selectable.</p></div>)}
        <label>Relationship with this funder (optional)</label>
        <select value={warmth} onChange={(e) => setWarmth(e.target.value)} style={{ maxWidth: 280 }}>
          <option value="">Not specified</option><option value="existing">Existing funder</option>
          <option value="warm_intro">Warm intro available</option><option value="cold">Cold / no relationship</option>
        </select>
        <div style={{ marginTop: 14 }}>
          <button className="btn" onClick={submit} disabled={busy}>{busy ? "Scoring..." : "Score it"}</button>
          {busy && <span className="spin" style={{ marginLeft: 12 }}>Parsing, scoring, and writing the memo...</span>}
        </div>
        {err && <div className="err">{err}</div>}
      </div>
      {result && <ScoreCard opp={result} labels={labels} onChanged={() => {}} />}
    </div>
  );
}

// --------------------------------------------------------------------------
function HistoryView({ onOpen }) {
  const [rows, setRows] = useState(null);
  useEffect(() => { api("/api/opportunities").then(setRows).catch(() => setRows([])); }, []);
  if (rows === null) return <div className="card spin">Loading...</div>;
  if (!rows.length) return <div className="card muted">No opportunities scored yet.</div>;
  return (
    <div className="card"><h2>Scored opportunities</h2>
      <table><thead><tr><th>Title</th><th>Funder</th><th>Score</th><th>Tier</th><th>Decision</th><th>Outcome</th></tr></thead>
        <tbody>{rows.map((o) => (
          <tr className="clk" key={o.id} onClick={() => onOpen(o.id)}>
            <td>{o.title || "Untitled"}</td><td>{o.parsed?.funder || "-"}</td>
            <td>{o.score ? Math.round(o.score.overall_score) : "-"}</td>
            <td>{o.score ? <span className={"tier-badge " + tierClass(o.score.tier)}>{o.score.tier}</span> : "-"}</td>
            <td>{o.decision || "-"}</td><td>{o.outcome ? o.outcome.outcome : "-"}</td>
          </tr>))}</tbody></table>
    </div>
  );
}

function DetailView({ oppId, labels, onBack }) {
  const [opp, setOpp] = useState(null); const [err, setErr] = useState("");
  const load = () => api(`/api/opportunities/${oppId}`).then(setOpp).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, [oppId]);
  if (err) return <div className="err">{err}</div>;
  if (!opp) return <div className="card spin">Loading...</div>;
  const setDecision = async (d) => { await api(`/api/opportunities/${oppId}/decision`, { method: "POST", body: { decision: d } }); load(); };
  return (
    <div>
      <button className="btn ghost" onClick={onBack} style={{ marginBottom: 14 }}>&larr; Back</button>
      <div className="card"><h2>{opp.title || "Untitled opportunity"}</h2>
        <div className="row" style={{ marginTop: 8 }}>
          <span className="muted">Decision:</span>
          {["pursue", "watch", "pass"].map((d) => (
            <button key={d} className={"btn " + (opp.decision === d ? "" : "secondary")} onClick={() => setDecision(d)}>{d}</button>))}
        </div>
      </div>
      <ScoreCard opp={opp} labels={labels} onChanged={load} />
      <OutcomeBox oppId={oppId} outcome={opp.outcome} onSaved={load} />
    </div>
  );
}

function OutcomeBox({ oppId, outcome, onSaved }) {
  const [o, setO] = useState(outcome?.outcome || ""); const [amount, setAmount] = useState(outcome?.amount || "");
  const [notes, setNotes] = useState(outcome?.notes || ""); const [msg, setMsg] = useState(""); const [err, setErr] = useState("");
  const save = async () => {
    setMsg(""); setErr("");
    try { await api(`/api/opportunities/${oppId}/outcome`, { method: "POST", body: { outcome: o, amount: amount ? Number(amount) : null, notes } });
      setMsg("Outcome logged. This feeds recalibration."); onSaved && onSaved(); } catch (e) { setErr(e.message); }
  };
  return (
    <div className="card"><h2>Log the outcome</h2>
      <p className="muted">Record what actually happened once the decision resolves. This is how the tool learns.</p>
      <div className="row">
        <select value={o} onChange={(e) => setO(e.target.value)} style={{ width: 180 }}>
          <option value="">Outcome...</option>{["won", "lost", "declined", "withdrawn"].map((x) => <option key={x} value={x}>{x}</option>)}</select>
        <input type="number" placeholder="Amount" value={amount} onChange={(e) => setAmount(e.target.value)} style={{ width: 160 }} />
      </div>
      <label>Notes</label><input type="text" value={notes} onChange={(e) => setNotes(e.target.value)} />
      <div style={{ marginTop: 12 }}><button className="btn" onClick={save} disabled={!o}>Save outcome</button></div>
      {msg && <div className="ok">{msg}</div>} {err && <div className="err">{err}</div>}
    </div>
  );
}

// --------------------------------------------------------------------------
// Setup: bootstrap a profile from a strategic plan
function SetupView({ onSaved }) {
  const [orgName, setOrgName] = useState(""); const [desc, setDesc] = useState(""); const [plan, setPlan] = useState("");
  const [draft, setDraft] = useState(null); const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(""); const [err, setErr] = useState("");
  const draftIt = async () => {
    setBusy(true); setErr(""); setMsg("");
    try { const d = await api("/api/setup/bootstrap", { method: "POST", body: { org_name: orgName, org_description: desc, plan_text: plan } });
      setDraft(d); setMsg("Draft generated. Review and edit below, then save."); } catch (e) { setErr(e.message); }
    setBusy(false);
  };
  const save = async () => {
    setErr(""); setMsg("");
    try {
      await api("/api/profile", { method: "POST", body: {
        name: orgName ? orgName + " profile" : "Profile", profile_doc: draft.profile_doc,
        dimensions: draft.dimensions, hard_filters: draft.hard_filters, thresholds: draft.thresholds, tiers: draft.tiers } });
      setMsg("Saved as your active profile."); onSaved && onSaved();
    } catch (e) { setErr(e.message); }
  };
  const wsum = draft ? draft.dimensions.reduce((a, d) => a + Number(d.weight), 0) : 0;
  return (
    <div className="card">
      <h2>Set up your scoring profile</h2>
      <p className="muted">Paste your strategic plan (or a rich description). A model drafts a sharp starting profile you then edit and approve. Read PROFILE_GUIDE.md first: the tool is only as good as this profile.</p>
      <label>Organization name</label><input type="text" value={orgName} onChange={(e) => setOrgName(e.target.value)} />
      <label>Short description (mission, who you serve)</label><textarea style={{ minHeight: 70 }} value={desc} onChange={(e) => setDesc(e.target.value)} />
      <label>Strategic plan / source material (paste text)</label><textarea value={plan} onChange={(e) => setPlan(e.target.value)} placeholder="Paste your strategic plan, theory of change, or priorities..." />
      <div style={{ marginTop: 12 }}><button className="btn" onClick={draftIt} disabled={busy}>{busy ? "Drafting..." : "Draft my profile"}</button></div>
      {msg && <div className="ok">{msg}</div>} {err && <div className="err">{err}</div>}
      {draft && (
        <div style={{ marginTop: 18, borderTop: "1px solid var(--line)", paddingTop: 14 }}>
          <h3>Draft rationale</h3><p className="muted">{draft.rationale}</p>
          <h3>Mission</h3>
          <textarea style={{ minHeight: 60 }} value={draft.profile_doc.mission || ""} onChange={(e) => setDraft({ ...draft, profile_doc: { ...draft.profile_doc, mission: e.target.value } })} />
          <h3>Dimensions (weights must sum to 100)</h3>
          {draft.dimensions.map((d, i) => (
            <div className="dimrow" key={i}>
              <div className="row"><input type="text" value={d.label} style={{ flex: 1 }}
                onChange={(e) => { const dd = [...draft.dimensions]; dd[i] = { ...d, label: e.target.value }; setDraft({ ...draft, dimensions: dd }); }} />
                <input type="number" value={d.weight}
                  onChange={(e) => { const dd = [...draft.dimensions]; dd[i] = { ...d, weight: Number(e.target.value) }; setDraft({ ...draft, dimensions: dd }); }} /></div>
              <div className="muted" style={{ marginTop: 4 }}>{d.description}</div>
            </div>))}
          <div className={wsum === 100 ? "ok" : "err"}>Weight sum: {wsum}</div>
          <h3>Hard filters</h3>
          {draft.hard_filters.map((f, i) => (
            <div className="filtrow" key={i}>
              <div className="row"><input type="checkbox" checked={f.enabled}
                onChange={(e) => { const ff = [...draft.hard_filters]; ff[i] = { ...f, enabled: e.target.checked }; setDraft({ ...draft, hard_filters: ff }); }} />
                <strong>{f.label}</strong>
                <select value={f.mode} onChange={(e) => { const ff = [...draft.hard_filters]; ff[i] = { ...f, mode: e.target.value }; setDraft({ ...draft, hard_filters: ff }); }}>
                  <option value="hard">hard (disqualify)</option><option value="soft">soft (cap at Watch)</option></select></div>
              <div className="muted" style={{ marginTop: 4 }}>{f.description}</div>
            </div>))}
          <div style={{ marginTop: 14 }}><button className="btn" onClick={save} disabled={wsum !== 100}>Save as active profile</button></div>
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
function AdminView() {
  const [profile, setProfile] = useState(null); const [recals, setRecals] = useState([]);
  const [msg, setMsg] = useState(""); const [err, setErr] = useState("");
  const load = () => { api("/api/profile/active").then(setProfile).catch((e) => setErr(e.message)); api("/api/recalibration").then(setRecals).catch(() => {}); };
  useEffect(load, []);
  if (!profile) return <div className="card spin">Loading profile...</div>;
  const wsum = (profile.dimensions || []).reduce((a, d) => a + Number(d.weight), 0);
  const setDim = (i, patch) => { const dd = [...profile.dimensions]; dd[i] = { ...dd[i], ...patch }; setProfile({ ...profile, dimensions: dd }); };
  const setFilt = (i, patch) => { const ff = [...profile.hard_filters]; ff[i] = { ...ff[i], ...patch }; setProfile({ ...profile, hard_filters: ff }); };
  const save = async () => {
    setMsg(""); setErr("");
    try { await api("/api/profile", { method: "POST", body: {
      name: profile.name, profile_doc: profile.profile_doc, dimensions: profile.dimensions,
      hard_filters: profile.hard_filters, thresholds: profile.thresholds, tiers: profile.tiers } });
      setMsg("Saved as a new active profile version."); load(); } catch (e) { setErr(e.message); }
  };
  const runRecal = async () => {
    setMsg(""); setErr("");
    try { const r = await api("/api/recalibration/run", { method: "POST" }); setMsg(r.created ? "Proposal created." : r.message); load(); } catch (e) { setErr(e.message); }
  };
  const act = async (id, a) => { await api(`/api/recalibration/${id}/${a}`, { method: "POST" }); load(); };
  return (
    <div>
      <div className="card">
        <h2>Strategy profile (v{profile.version})</h2>
        <p className="muted">Your scoring strategy as data. Every save creates a new active version; past scores keep their version.</p>
        <h3>Mission</h3>
        <textarea style={{ minHeight: 60 }} value={profile.profile_doc?.mission || ""} onChange={(e) => setProfile({ ...profile, profile_doc: { ...profile.profile_doc, mission: e.target.value } })} />
        <h3>Dimensions (weights must sum to 100)</h3>
        {(profile.dimensions || []).map((d, i) => (
          <div className="dimrow" key={i}>
            <div className="row"><input type="text" value={d.label} style={{ flex: 1 }} onChange={(e) => setDim(i, { label: e.target.value })} />
              <input type="number" value={d.weight} onChange={(e) => setDim(i, { weight: Number(e.target.value) })} /></div>
            <textarea style={{ minHeight: 44, marginTop: 6 }} value={d.description} onChange={(e) => setDim(i, { description: e.target.value })} />
          </div>))}
        <div className={wsum === 100 ? "ok" : "err"}>Weight sum: {wsum}</div>
        <h3>Hard filters</h3>
        {(profile.hard_filters || []).map((f, i) => (
          <div className="filtrow" key={i}>
            <div className="row"><input type="checkbox" checked={f.enabled} onChange={(e) => setFilt(i, { enabled: e.target.checked })} />
              <strong>{f.label}</strong>
              <select value={f.mode} onChange={(e) => setFilt(i, { mode: e.target.value })}>
                <option value="hard">hard (disqualify)</option><option value="soft">soft (cap at Watch)</option></select></div>
            <div className="muted" style={{ marginTop: 4 }}>{f.description}</div>
          </div>))}
        <div style={{ marginTop: 14 }}><button className="btn" onClick={save} disabled={wsum !== 100}>Save new version</button></div>
        {msg && <div className="ok">{msg}</div>} {err && <div className="err">{err}</div>}
        <p className="muted" style={{ marginTop: 12 }}>Export: <a href="/api/export.csv">fit_scorer_export.csv</a></p>
      </div>
      <div className="card">
        <h2>Recalibration</h2>
        <p className="muted">Reviews feedback and logged outcomes, then proposes weight changes for your sign-off.</p>
        <button className="btn secondary" onClick={runRecal}>Run recalibration check</button>
        {recals.map((r) => (
          <div key={r.id} className="conditional" style={{ background: "#f8fafc", borderColor: "var(--line)", color: "var(--ink)" }}>
            <div><strong>From v{r.from_profile_version}</strong> · {r.status}</div>
            <div style={{ marginTop: 6 }}>{r.rationale}</div>
            <div className="muted">{r.evidence?.expected_effect}</div>
            {r.status === "pending" && (<div className="row" style={{ marginTop: 8 }}>
              <button className="btn" onClick={() => act(r.id, "approve")}>Approve</button>
              <button className="btn ghost" onClick={() => act(r.id, "reject")}>Reject</button></div>)}
          </div>))}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------
function App() {
  const [config, setConfig] = useState(null);
  const [labels, setLabels] = useState({});
  const [view, setView] = useState("submit"); const [oppId, setOppId] = useState(null); const [tick, setTick] = useState(0);

  const loadConfig = () => api("/api/config").then((c) => {
    setConfig(c);
    document.title = c.org.tool_name || "Funding Fit Scorer";
    // brand_color drives the single accent (progress bars, brand mark, active nav).
    if (c.org.brand_color) document.documentElement.style.setProperty("--accent", c.org.brand_color);
  }).catch(() => setConfig({ org: { tool_name: "Funding Fit Scorer", tagline: "" }, user: null }));

  const loadLabels = () => api("/api/profile/active").then((p) => {
    const m = {}; (p.dimensions || []).forEach((d) => { m[d.key] = d.label; }); setLabels(m);
  }).catch(() => {});

  useEffect(() => { loadConfig(); }, []);
  useEffect(() => { if (config && config.user) loadLabels(); }, [config]);

  if (config === null) return <div className="wrap spin">Loading...</div>;
  if (!config.user) return <div className="wrap"><Login config={config} onLogin={loadConfig} /></div>;

  const open = (id) => { setOppId(id); setView("detail"); };
  const nav = (v) => { setView(v); setOppId(null); };
  const logout = async () => { await api("/api/logout", { method: "POST" }); loadConfig(); };
  const isAdmin = config.user.role === "admin";
  const afterSetup = () => { loadLabels(); loadConfig(); nav("submit"); };

  return (
    <div>
      <div className="topbar">
        <h1>{config.org.tool_name}</h1>
        <nav>
          <button className={view === "submit" ? "active" : ""} onClick={() => nav("submit")}>Score</button>
          <button className={view === "history" || view === "detail" ? "active" : ""} onClick={() => nav("history")}>History</button>
          {isAdmin && <button className={view === "admin" ? "active" : ""} onClick={() => nav("admin")}>Admin</button>}
          {isAdmin && <button className={view === "setup" ? "active" : ""} onClick={() => nav("setup")}>Setup</button>}
        </nav>
        <div className="spacer"></div>
        <span className="who">{config.user.name} ({config.user.role})</span>
        <button className="btn ghost" onClick={logout} style={{ padding: "6px 12px" }}>Sign out</button>
      </div>
      {config.mock_mode && <div className="banner mock">Mock mode: no Claude API key set, so scores use a keyword heuristic. Add ANTHROPIC_API_KEY for real scoring.</div>}
      {config.profile_is_placeholder && (
        <div className="banner placeholder">You're using the placeholder starter profile. {isAdmin ? <a href="#" onClick={(e) => { e.preventDefault(); nav("setup"); }}>Set up your real profile</a> : "Ask an admin to configure the profile."} for meaningful scores.</div>
      )}
      <div className="wrap">
        {view === "submit" && <SubmitView labels={labels} onScored={() => setTick(tick + 1)} />}
        {view === "history" && <HistoryView key={tick} onOpen={open} />}
        {view === "detail" && <DetailView oppId={oppId} labels={labels} onBack={() => nav("history")} />}
        {view === "admin" && isAdmin && <AdminView />}
        {view === "setup" && isAdmin && <SetupView onSaved={afterSetup} />}
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
