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
| Rust | *Deferred — reconsidered and held* | Enhancement 1 (ZIP/CSV/XLSX data pipeline) was the test case for pivoting to Rust; see the decision note below. |

## Quickstart (demo mode — no Microsoft account needed)

```bash
cp .env.example .env        # defaults are fine for demo mode
docker compose up --build
```

Open **http://localhost:8080** — the published UI entry point.
You get seeded sample projects/jobs, working scheduling, maintenance mode,
and admin tools, all against demo data.

## Decision note — Rust reconsidered (Enhancement 1)

Enhancement 1 added a data pipeline (ZIP staging, CSV normalization,
validation, XLSX reporting) — exactly the kind of workload where Rust is
usually proposed. Reconsidered against the actual work:

- The pipeline is **data-wrangling, not compute**: ZIP extraction, CSV
  shaping, rule checks, and XLSX authoring over thousands of rows. Python's
  stdlib + openpyxl do this natively; the Rust equivalents (polars,
  rust_xlsxwriter, a hand-rolled Graph client) cost multiples of the code
  for zero user-visible gain at this scale.
- The validation rules are the part that will change most ("fix data,
  rinse, repeat"). Python rules edit-and-rerun in seconds; Rust turns every
  rule tweak into a compile-and-redeploy cycle, and breaks the in-app
  script editor/runner the managers use.
- Rust's real trigger is named, not vague: if raw files reach
  tens of millions of rows or a streaming copy engine is needed, a Rust
  worker slots in behind the same job API without touching the UI or the
  Python services.

**Verdict: Python for API + pipeline, TypeScript for UI, Rust deferred.**

## Migration data pipeline

Per migration date, a SharePoint folder named `Migration - mm.dd.yyyy`
holds a ZIP of raw house data (per city/state CSVs: location, price,
occupied, owner/rental, occupier contacts, utilities). From the
**Pipeline** view, a manager clicks once to:

1. **Stage** — the ZIP is downloaded via its SharePoint/OneDrive URL
   (Microsoft Graph only, never mapped drives; minimizes per-user setup)
   into `DATA_DIR/mig/<mm.dd.yyyy>/` (`/data/mig/...` in the container).
2. **Normalize** — builds `combined/addresses.csv`, `combined/occupier.csv`
   (name, email, cell), and `combined/utilities.csv`.
3. **Pre-check (dry run)** — validation rules (missing/invalid email or
   price, duplicates, occupied-without-occupier, missing utilities, …)
   produce `reports/precheck-<date>.log.txt` with `[ERROR]` / `[WARNING]`
   lines.
4. **Report** — `reports/summary-<date>.xlsx` with Summary / Errors /
   Warnings sheets plus per-file `*_Fixes` sheets listing exactly which
   rows need fixing. In live mode the artifacts are also uploaded back to
   the SharePoint folder under `Results/`. Fix the data, re-run, repeat.

Raw column names are matched through an alias table
(`backend/app/pipeline.py: ALIASES`) — extend it when a new raw layout
appears.

## Utility scripts (click-to-run Python)

Admin → Scripts stores Python utilities **in the app**: a manager can edit
a script in the browser and click **Run**; it executes in the app's Python
environment (the same venv as the API) with `DATA_DIR` / `MIG_BASE` env
vars, a timeout, and captured output — built for routine jobs and
on-the-fly fixes without touching anyone's laptop. A starter
`row_counts.py` is seeded. For heavier editing, an optional code-server
(online VS Code) profile is included in `docker-compose.yml`:
`docker compose --profile editor up -d`.

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
