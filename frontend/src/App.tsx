import { useCallback, useEffect, useState } from "react";
import { api, Job, PipelineRun, Project, ScriptItem, Status } from "./api";

type View = "dashboard" | "projects" | "pipeline" | "admin";

export default function App() {
  const [view, setView] = useState<View>("dashboard");
  const [status, setStatus] = useState<Status | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);

  const refresh = useCallback(async () => {
    const [s, p] = await Promise.all([api.status(), api.projects()]);
    setStatus(s);
    setProjects(p);
  }, []);

  useEffect(() => {
    refresh().catch(console.error);
    const t = setInterval(() => refresh().catch(() => undefined), 5000);
    return () => clearInterval(t);
  }, [refresh]);

  return (
    <div className="layout">
      <header>
        <h1>proj-manager</h1>
        <nav>
          {(["dashboard", "projects", "pipeline", "admin"] as View[]).map((v) => (
            <button key={v} className={view === v ? "active" : ""} onClick={() => setView(v)}>
              {v[0].toUpperCase() + v.slice(1)}
            </button>
          ))}
        </nav>
        <span className={status?.demo_mode ? "badge demo" : "badge live"}>
          {status ? (status.demo_mode ? "DEMO MODE" : "LIVE (Graph)") : "…"}
        </span>
      </header>

      {status?.maintenance_mode && (
        <div className="banner">⚠ Maintenance mode: {status.maintenance_message}</div>
      )}

      {view === "dashboard" && status && <Dashboard status={status} projects={projects} go={setView} refresh={refresh} />}
      {view === "projects" && <ProjectsView projects={projects} refresh={refresh} />}
      {view === "pipeline" && <PipelineView />}
      {view === "admin" && <AdminView projects={projects} status={status} refresh={refresh} />}
    </div>
  );
}


function PrepTile({ status, refresh }: { status: Status; refresh: () => Promise<void> }) {
  const today = new Date();
  const def = `${String(today.getMonth() + 1).padStart(2, "0")}.${String(today.getDate()).padStart(2, "0")}.${today.getFullYear()}`;
  const [date, setDate] = useState(def);
  const [askPw, setAskPw] = useState(false);
  const [pw, setPw] = useState("");
  const [msg, setMsg] = useState("");
  const prep = status.last_prep;
  const running = prep?.status === "running" || prep?.status === "created";

  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => refresh().catch(() => undefined), 3000);
    return () => clearInterval(t);
  }, [running, refresh]);

  async function start() {
    try {
      await api.quickRun(pw, date);
      setMsg("Prep started — this tile updates when it finishes.");
      setAskPw(false);
      setPw("");
      await refresh();
    } catch {
      setMsg("Wrong password, or locked after too many failed attempts — wait a few minutes.");
    }
  }

  return (
    <section className="panel" style={{ borderWidth: 2 }}>
      <div className="row">
        <h2 style={{ margin: 0 }}>Migration prep</h2>
        {prep && <span className={`pill ${prep.status}`}>{prep.status}</span>}
      </div>
      <p className="muted" style={{ marginTop: 6 }}>
        Start → unzip → re-check → update site status. Pulls the ZIP from the
        SharePoint folder <em>Migration - {date}</em>, builds the Combined CSVs,
        runs the pre-checks, and writes the log + .xlsx fix report.
      </p>
      {prep ? (
        <p>
          Last prep: <strong>{prep.migration_date}</strong> — {prep.errors} errors · {prep.warnings} warnings
          {prep.status === "completed" && (
            <> · <a href={`/api/pipeline/runs/${prep.run_id}/artifacts/log`} download>log</a>
            {" · "}<a href={`/api/pipeline/runs/${prep.run_id}/artifacts/xlsx`} download>.xlsx report</a></>
          )}
        </p>
      ) : (
        <p className="muted">No prep run yet.</p>
      )}
      <div className="form">
        <input value={date} onChange={(e) => setDate(e.target.value)} placeholder="mm.dd.yyyy" style={{ maxWidth: 130 }} />
        {!askPw && <button onClick={() => setAskPw(true)} disabled={running}>{running ? "Prep running…" : "Run prep"}</button>}
        {askPw && (
          <>
            <input type="password" placeholder="Site password" value={pw} autoFocus
              onChange={(e) => setPw(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && start()} />
            <button onClick={start}>Start prep</button>
            <button onClick={() => setAskPw(false)}>Cancel</button>
          </>
        )}
      </div>
      {msg && <p className="muted">{msg}</p>}
    </section>
  );
}

function Dashboard({ status, projects, go, refresh }: { status: Status; projects: Project[]; go: (v: View) => void; refresh: () => Promise<void> }) {
  return (
    <main>
      <PrepTile status={status} refresh={refresh} />
      <section className="cards">
        <div className="card"><h3>Projects</h3><p>{status.projects}</p></div>
        <div className="card"><h3>Jobs scheduled</h3><p>{status.jobs_scheduled}</p></div>
        <div className="card"><h3>Jobs running</h3><p>{status.jobs_running}</p></div>
        <div className="card"><h3>Jobs completed</h3><p>{status.jobs_completed} / {status.jobs_total}</p></div>
      </section>
      <section className="panel">
        <h2>SharePoint connection</h2>
        <p>Site URL: {status.sharepoint_site_url || <em>not set — running in demo mode</em>}</p>
        <p>
          {status.graph_configured
            ? "Microsoft Graph credentials configured."
            : "No Graph credentials yet. Add MS_TENANT_ID / MS_CLIENT_ID / MS_CLIENT_SECRET and SHAREPOINT_SITE_URL to .env, then restart."}
        </p>
      </section>
      <section className="panel">
        <h2>Projects</h2>
        {projects.map((p) => (
          <div key={p.id} className="row">
            <div>
              <strong>{p.name}</strong> <span className={`pill ${p.status}`}>{p.status}</span>
              <div className="muted">{p.source_type} · {p.jobs_completed}/{p.job_count} jobs complete</div>
            </div>
            <button onClick={() => go("projects")}>Open</button>
          </div>
        ))}
      </section>
    </main>
  );
}

function ProjectsView({ projects, refresh }: { projects: Project[]; refresh: () => Promise<void> }) {
  const [name, setName] = useState("");
  const [sourceType, setSourceType] = useState("sharepoint");
  const [sourceUrl, setSourceUrl] = useState("");
  const [targetUrl, setTargetUrl] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobName, setJobName] = useState("");
  const [jobWhen, setJobWhen] = useState("");

  const loadJobs = useCallback(async (pid: number) => setJobs(await api.jobs(pid)), []);

  useEffect(() => {
    if (selected) loadJobs(selected).catch(console.error);
  }, [selected, loadJobs, projects]);

  async function addProject(e: React.FormEvent) {
    e.preventDefault();
    await api.createProject({ name, source_type: sourceType, source_url: sourceUrl, target_url: targetUrl, status: "active" });
    setName(""); setSourceUrl(""); setTargetUrl("");
    await refresh();
  }

  async function addJob(e: React.FormEvent) {
    e.preventDefault();
    if (!selected) return;
    await api.createJob({
      project_id: selected,
      name: jobName,
      scheduled_at: jobWhen ? new Date(jobWhen).toISOString() : null,
    });
    setJobName(""); setJobWhen("");
    await loadJobs(selected);
    await refresh();
  }

  return (
    <main>
      <section className="panel">
        <h2>New project</h2>
        <form onSubmit={addProject} className="form">
          <input required placeholder="Project name" value={name} onChange={(e) => setName(e.target.value)} />
          <select value={sourceType} onChange={(e) => setSourceType(e.target.value)}>
            <option value="sharepoint">SharePoint</option>
            <option value="onedrive">OneDrive</option>
          </select>
          <input placeholder="Source URL" value={sourceUrl} onChange={(e) => setSourceUrl(e.target.value)} />
          <input placeholder="Target URL" value={targetUrl} onChange={(e) => setTargetUrl(e.target.value)} />
          <button type="submit">Create project</button>
        </form>
      </section>

      {projects.map((p) => (
        <section key={p.id} className="panel">
          <div className="row">
            <div>
              <strong>{p.name}</strong> <span className={`pill ${p.status}`}>{p.status}</span>
              <div className="muted">{p.source_url} → {p.target_url}</div>
            </div>
            <button onClick={() => setSelected(selected === p.id ? null : p.id)}>
              {selected === p.id ? "Hide jobs" : "Show jobs"}
            </button>
          </div>
          {selected === p.id && (
            <div>
              {jobs.map((j) => (
                <div key={j.id} className="job">
                  <div className="row">
                    <span>{j.name}</span>
                    <span className={`pill ${j.status}`}>{j.status}</span>
                    <span>{j.progress}%</span>
                    <button onClick={async () => { await api.runJob(j.id); await loadJobs(p.id); }}>Run now</button>
                    <button onClick={async () => { await api.completeJob(j.id); await loadJobs(p.id); await refresh(); }}>Mark complete</button>
                  </div>
                  <div className="bar"><div style={{ width: `${j.progress}%` }} /></div>
                  <div className="muted">
                    {j.source_path} → {j.target_path}
                    {j.scheduled_at ? ` · scheduled ${new Date(j.scheduled_at).toLocaleString()}` : ""}
                    {" · "}{j.items_done}/{j.items_total} items
                  </div>
                  {j.log && <pre className="log">{j.log}</pre>}
                </div>
              ))}
              <form onSubmit={addJob} className="form">
                <input required placeholder="Job name" value={jobName} onChange={(e) => setJobName(e.target.value)} />
                <input type="datetime-local" value={jobWhen} onChange={(e) => setJobWhen(e.target.value)} />
                <button type="submit">Add / schedule job</button>
              </form>
            </div>
          )}
        </section>
      ))}
    </main>
  );
}


function PipelineView() {
  const today = new Date();
  const def = `${String(today.getMonth() + 1).padStart(2, "0")}.${String(today.getDate()).padStart(2, "0")}.${today.getFullYear()}`;
  const [date, setDate] = useState(def);
  const [folder, setFolder] = useState("");
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [error, setError] = useState("");

  const load = useCallback(async () => setRuns(await api.runs()), []);
  useEffect(() => {
    load().catch(console.error);
    const t = setInterval(() => load().catch(() => undefined), 4000);
    return () => clearInterval(t);
  }, [load]);

  async function start() {
    try {
      await api.createRun(date, folder || `Migration - ${date}`);
      setError("");
      await load();
    } catch (e) {
      setError("Could not start run — check the admin token in the Admin view. " + String(e));
    }
  }

  return (
    <main>
      <section className="panel">
        <h2>Migration data pipeline</h2>
        <p className="muted">
          Stages the ZIP from the SharePoint folder (by URL, no mapped drives), builds the Combined
          CSVs (addresses / occupier / utilities), runs pre-checks (dry run), and writes the
          [ERROR]/[WARNING] log + .xlsx fix report. Artifacts are saved under
          data/mig/&lt;date&gt;/ and uploaded back to the folder's Results/ in live mode.
        </p>
        <div className="form">
          <input value={date} onChange={(e) => setDate(e.target.value)} placeholder="mm.dd.yyyy" />
          <input style={{ minWidth: 340 }} value={folder} onChange={(e) => setFolder(e.target.value)}
            placeholder={`SharePoint folder URL or path (default: Migration - ${date})`} />
          <button onClick={start}>Stage + pre-check + report</button>
        </div>
        {error && <p className="muted">{error}</p>}
      </section>
      {runs.map((r) => (
        <section key={r.id} className="panel">
          <div className="row">
            <strong>Run #{r.id} — {r.migration_date}</strong>
            <span className={`pill ${r.status}`}>{r.status}</span>
            <span>{r.errors} errors · {r.warnings} warnings</span>
            {r.log_artifact && <a href={`/api/pipeline/runs/${r.id}/artifacts/log`} download>Download log</a>}
            {r.xlsx_artifact && <a href={`/api/pipeline/runs/${r.id}/artifacts/xlsx`} download>Download .xlsx report</a>}
          </div>
          <div className="muted">{r.folder_url}</div>
          {r.log && <pre className="log">{r.log}</pre>}
        </section>
      ))}
    </main>
  );
}

function ScriptsPanel() {
  const [scripts, setScripts] = useState<ScriptItem[]>([]);
  const [editing, setEditing] = useState<ScriptItem | null>(null);
  const [name, setName] = useState("");
  const [code, setCode] = useState("print('hello from utility script')");

  const load = useCallback(async () => setScripts(await api.scripts()), []);
  useEffect(() => { load().catch(console.error); }, [load]);

  async function save() {
    if (editing) await api.updateScript(editing.id, editing.name, code, editing.description);
    else await api.createScript(name, code);
    setEditing(null);
    await load();
  }

  return (
    <section className="panel">
      <h2>Utility scripts (Python venv)</h2>
      <p className="muted">
        Scripts are stored in the app, edited here, and executed in the app's Python environment —
        no local setup for managers. They receive DATA_DIR and MIG_BASE environment variables.
        Editing and running require the admin token above.
      </p>
      {scripts.map((s) => (
        <div key={s.id} className="job">
          <div className="row">
            <span><strong>{s.name}</strong> — {s.description}</span>
            <span className="pill">{s.last_status || "not run"}</span>
            <button onClick={() => { setEditing(s); setCode(s.code); }}>Edit</button>
            <button onClick={async () => { await api.runScript(s.id); await load(); }}>Run</button>
          </div>
          {s.last_output && <pre className="log">{s.last_output}</pre>}
        </div>
      ))}
      <h3>{editing ? `Edit ${editing.name}` : "New script"}</h3>
      {!editing && (
        <div className="form">
          <input placeholder="script_name.py" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
      )}
      <textarea value={code} onChange={(e) => setCode(e.target.value)} rows={10}
        style={{ width: "100%", fontFamily: "monospace", fontSize: 13 }} />
      <div className="form">
        <button onClick={save}>{editing ? "Save changes" : "Create script"}</button>
        {editing && <button onClick={() => setEditing(null)}>Cancel</button>}
      </div>
    </section>
  );
}

function AdminView({ projects, status, refresh }: { projects: Project[]; status: Status | null; refresh: () => Promise<void> }) {
  const [token, setToken] = useState(localStorage.getItem("admin_token") || "");
  const [msg, setMsg] = useState("Scheduled maintenance in progress. Migrations are paused.");
  const [result, setResult] = useState("");
  const [audit, setAudit] = useState<Array<{ id: number; action: string; detail: string; created_at: string }>>([]);

  function saveToken(v: string) {
    setToken(v);
    localStorage.setItem("admin_token", v);
  }

  async function loadAudit() {
    try { setAudit(await api.audit()); } catch { setResult("Audit log needs a valid admin token."); }
  }

  return (
    <main>
      <section className="panel">
        <h2>Admin access</h2>
        <div className="form">
          <input type="password" placeholder="Admin token (ADMIN_TOKEN from .env)" value={token} onChange={(e) => saveToken(e.target.value)} />
        </div>
        <p className="muted">Admin calls send this as the X-Admin-Token header.</p>
      </section>

      <section className="panel">
        <h2>Site maintenance</h2>
        <p>Maintenance mode is currently <strong>{status?.maintenance_mode ? "ON" : "OFF"}</strong>. While ON, job runs are blocked and active projects show as in maintenance.</p>
        <div className="form">
          <input value={msg} onChange={(e) => setMsg(e.target.value)} />
          <button onClick={async () => { await api.setMaintenance(true, msg); setResult("Maintenance ON"); await refresh(); }}>Turn maintenance ON</button>
          <button onClick={async () => { await api.setMaintenance(false, msg); setResult("Maintenance OFF"); await refresh(); }}>Turn OFF</button>
        </div>
      </section>

      <section className="panel">
        <h2>SharePoint / Graph</h2>
        <button onClick={async () => { try { setResult(JSON.stringify(await api.graphTest())); } catch (e) { setResult(String(e)); } }}>
          Test connection
        </button>
      </section>

      <section className="panel">
        <h2>Mark migration complete</h2>
        {projects.map((p) => (
          <div key={p.id} className="row">
            <span>{p.name} <span className={`pill ${p.status}`}>{p.status}</span></span>
            <button disabled={p.status === "complete"} onClick={async () => { await api.completeProject(p.id); setResult(`${p.name} marked complete`); await refresh(); }}>
              Mark complete
            </button>
          </div>
        ))}
      </section>

      <ScriptsPanel />

      <section className="panel">
        <h2>Audit log</h2>
        <button onClick={loadAudit}>Load audit log</button>
        {audit.map((a) => (
          <div key={a.id} className="muted">{new Date(a.created_at).toLocaleString()} — {a.action}: {a.detail}</div>
        ))}
      </section>

      {result && <pre className="log">{result}</pre>}
    </main>
  );
}
