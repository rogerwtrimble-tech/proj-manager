import { useCallback, useEffect, useState } from "react";
import { api, Job, Project, Status } from "./api";

type View = "dashboard" | "projects" | "admin";

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
          {(["dashboard", "projects", "admin"] as View[]).map((v) => (
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

      {view === "dashboard" && status && <Dashboard status={status} projects={projects} go={setView} />}
      {view === "projects" && <ProjectsView projects={projects} refresh={refresh} />}
      {view === "admin" && <AdminView projects={projects} status={status} refresh={refresh} />}
    </div>
  );
}

function Dashboard({ status, projects, go }: { status: Status; projects: Project[]; go: (v: View) => void }) {
  return (
    <main>
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
