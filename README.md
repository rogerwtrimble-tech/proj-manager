# proj-manager

Dashboard and admin console for planning, scheduling, and tracking
**SharePoint / OneDrive migrations** — projects, migration jobs, scheduling,
site maintenance mode, and migration-complete sign-off, in one container.

## Stack decision

| Layer | Choice | Why |
|---|---|---|
| API / migration logic | **Python 3.12 + FastAPI** | Best Microsoft Graph ecosystem (MSAL), Roger's existing stack |
| UI | **TypeScript + React (Vite)** | The app-language adoption winner; type-safe API client |
| Shell / delivery | **Docker Compose, single container** | Download → build → run; nothing else to install |
| Data | SQLite (SQLAlchemy) | Zero-config; swap `DATABASE_URL` for Postgres later |
| Rust | *Deferred, deliberately* | A dashboard + Graph integration gains nothing from Rust today. If a high-throughput local copy engine is ever added, it slots in as a sidecar behind the same API. |

## Quickstart (demo mode — no Microsoft account needed)

```bash
cp .env.example .env        # defaults are fine for demo mode
docker compose up --build
```

Open **http://localhost:8080** — the published UI entry point.
You get seeded sample projects/jobs, working scheduling, maintenance mode,
and admin tools, all against demo data.

## Go live with your SharePoint

1. In the Azure portal, register an app (single tenant).
2. Grant **application permissions**: `Sites.Read.All` (or `Sites.Selected`)
   and `Files.Read.All`; grant admin consent.
3. Create a client secret.
4. Put these in `.env` and restart (`docker compose up --build -d`):

```
SHAREPOINT_SITE_URL=https://yourtenant.sharepoint.com/sites/YourSite
MS_TENANT_ID=...
MS_CLIENT_ID=...
MS_CLIENT_SECRET=...
ADMIN_TOKEN=<long random string>
```

The dashboard badge flips from **DEMO MODE** to **LIVE (Graph)**, and
Admin → *Test connection* resolves your site and lists its document
libraries (drives) via Microsoft Graph.

## Features

- **Dashboard** — project/job counts, connection state, maintenance banner.
- **Projects** — create SharePoint or OneDrive migration projects with
  source and target URLs; per-project job lists with live progress bars.
- **Migration jobs** — run now, or **schedule** for a date/time (a background
  scheduler dispatches due jobs every 30s). Job logs are kept per job.
- **Admin tools** (token-gated):
  - **Site maintenance mode** — pauses all migration runs (runs are blocked
    and logged), banner shown across the UI.
  - **Mark migration complete** — closes a project and its remaining jobs.
  - **Graph connection test** and an **audit log** of admin/job events.

> The copy loop tracks progress over items enumerated from Graph (live) or a
> deterministic sample (demo). Wiring a specific tenant's item-level
> download/upload into `backend/app/services.py::_copy_item` is the one
> deliberate extension point — enumeration, scheduling, state, and reporting
> around it are complete.

## API

Interactive docs at `/docs` once running. Core routes:

- `GET /api/status`, `GET /api/health`
- `GET|POST /api/projects`, `GET|PUT|DELETE /api/projects/{id}`
- `GET|POST /api/jobs`, `POST /api/jobs/{id}/run`, `POST /api/jobs/{id}/complete`
- Admin (`X-Admin-Token` header): `POST /api/admin/maintenance`,
  `POST /api/admin/projects/{id}/complete`, `POST /api/admin/graph/test`,
  `GET /api/admin/audit`

## Local development (without Docker)

```bash
cd backend && python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pytest                      # test suite
uvicorn app.main:app --port 8080

cd ../frontend && npm install && npm run build   # or: npm run dev (proxies /api)
```

## Layout

```
backend/    FastAPI app (routers: projects, jobs, admin), Graph client, scheduler
frontend/   TypeScript/React dashboard (Dashboard / Projects / Admin views)
Dockerfile  Multi-stage: node builds the UI, python serves API + UI
docker-compose.yml  One service, one volume (SQLite data)
```
