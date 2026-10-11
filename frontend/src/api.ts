export interface Project {
  id: number;
  name: string;
  description: string;
  source_type: string;
  source_url: string;
  target_url: string;
  status: string;
  job_count: number;
  jobs_completed: number;
}

export interface Job {
  id: number;
  project_id: number;
  name: string;
  source_path: string;
  target_path: string;
  scheduled_at: string | null;
  status: string;
  progress: number;
  items_total: number;
  items_done: number;
  log: string;
}

export interface Status {
  graph_configured: boolean;
  demo_mode: boolean;
  sharepoint_site_url: string;
  maintenance_mode: boolean;
  maintenance_message: string;
  projects: number;
  jobs_total: number;
  jobs_scheduled: number;
  jobs_running: number;
  jobs_completed: number;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

function adminHeaders(): Record<string, string> {
  return { "X-Admin-Token": localStorage.getItem("admin_token") || "" };
}

export const api = {
  status: () => req<Status>("/api/status"),
  projects: () => req<Project[]>("/api/projects"),
  createProject: (p: Partial<Project>) =>
    req<Project>("/api/projects", { method: "POST", body: JSON.stringify(p) }),
  jobs: (projectId: number) => req<Job[]>(`/api/jobs?project_id=${projectId}`),
  createJob: (j: Partial<Job>) =>
    req<Job>("/api/jobs", { method: "POST", body: JSON.stringify(j) }),
  runJob: (id: number) => req<Job>(`/api/jobs/${id}/run`, { method: "POST" }),
  completeJob: (id: number) => req<Job>(`/api/jobs/${id}/complete`, { method: "POST" }),
  setMaintenance: (enabled: boolean, message: string) =>
    req<{ maintenance_mode: boolean }>("/api/admin/maintenance", {
      method: "POST",
      headers: adminHeaders(),
      body: JSON.stringify({ enabled, message }),
    }),
  completeProject: (id: number) =>
    req<Project>(`/api/admin/projects/${id}/complete`, {
      method: "POST",
      headers: adminHeaders(),
    }),
  graphTest: () =>
    req<unknown>("/api/admin/graph/test", { method: "POST", headers: adminHeaders() }),
  audit: () =>
    req<Array<{ id: number; action: string; detail: string; created_at: string }>>(
      "/api/admin/audit",
      { headers: adminHeaders() }
    ),
};
