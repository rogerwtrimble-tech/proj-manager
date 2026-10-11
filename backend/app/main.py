import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import services
from .config import settings
from .db import Base, SessionLocal, engine, get_db
from .graph_client import graph_client
from .models import MigrationJob, Project
from .routers import admin, jobs, pipeline as pipeline_router, projects
from .schemas import StatusOut


SAMPLE_SCRIPT = '''"""Starter utility: count rows in the latest Combined CSVs.
Edit me in Admin -> Scripts. Env: DATA_DIR, MIG_BASE."""
import csv, glob, os
base = os.environ.get("MIG_BASE", "data/mig")
runs = sorted(glob.glob(os.path.join(base, "*")))
if not runs:
    print("No migration data staged yet.")
else:
    latest = runs[-1]
    print("Latest migration:", os.path.basename(latest))
    for name in ("addresses.csv", "occupier.csv", "utilities.csv"):
        path = os.path.join(latest, "combined", name)
        rows = sum(1 for _ in open(path)) - 1 if os.path.isfile(path) else 0
        print(f"{name}: {rows} rows")
'''


def seed_demo_data() -> None:
    db = SessionLocal()
    try:
        if db.query(Project).count() > 0:
            return
        finance = Project(
            name="Finance SharePoint Migration",
            description="Move Finance document libraries to the new SharePoint site.",
            source_type="sharepoint",
            source_url=settings.sharepoint_site_url or "https://contoso.sharepoint.com/sites/Finance-Old",
            target_url="https://contoso.sharepoint.com/sites/Finance",
            status="active",
        )
        exec_od = Project(
            name="Executive OneDrive Consolidation",
            description="Consolidate executive OneDrive content into the shared library.",
            source_type="onedrive",
            source_url="OneDrive (executive accounts)",
            target_url="https://contoso.sharepoint.com/sites/Executive",
            status="planning",
        )
        db.add_all([finance, exec_od])
        db.commit()
        now = datetime.now(timezone.utc)
        db.add_all(
            [
                MigrationJob(
                    project_id=finance.id, name="Shared Documents library",
                    source_path="/Shared Documents", target_path="/Documents",
                    status="completed", progress=100, items_total=120, items_done=120,
                    log="Seeded sample: completed.", started_at=now - timedelta(days=2),
                    finished_at=now - timedelta(days=2),
                ),
                MigrationJob(
                    project_id=finance.id, name="Archive library",
                    source_path="/Archive", target_path="/Archive",
                    scheduled_at=now + timedelta(days=1), status="scheduled",
                    log="Seeded sample: scheduled.",
                ),
                MigrationJob(
                    project_id=exec_od.id, name="Executive drive root",
                    source_path="/", target_path="/Executive",
                    status="scheduled", log="Seeded sample: awaiting schedule.",
                ),
            ]
        )
        db.commit()
        from .models import Script

        if db.query(Script).count() == 0:
            db.add(Script(name="row_counts.py", description="Count rows in the latest Combined CSVs", code=SAMPLE_SCRIPT))
            db.commit()
    finally:
        db.close()


_stop = threading.Event()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    seed_demo_data()
    t = threading.Thread(target=services.scheduler_loop, args=(_stop,), daemon=True)
    t.start()
    yield
    _stop.set()


app = FastAPI(title="proj-manager", version="1.0.0", lifespan=lifespan)
app.include_router(projects.router)
app.include_router(jobs.router)
app.include_router(admin.router)
app.include_router(pipeline_router.router)


@app.get("/api/health")
def health():
    return {"ok": True, "service": "proj-manager"}


@app.get("/api/status", response_model=StatusOut)
def status(db: Session = Depends(get_db)):
    jobs_all = db.query(MigrationJob).all()
    return StatusOut(
        graph_configured=graph_client.configured,
        demo_mode=not graph_client.configured,
        sharepoint_site_url=settings.sharepoint_site_url,
        maintenance_mode=services.maintenance_enabled(db),
        maintenance_message=services.get_setting(db, services.MAINTENANCE_MSG_KEY, services.DEFAULT_MAINTENANCE_MSG),
        projects=db.query(Project).count(),
        jobs_total=len(jobs_all),
        jobs_scheduled=sum(1 for j in jobs_all if j.status == "scheduled"),
        jobs_running=sum(1 for j in jobs_all if j.status == "running"),
        jobs_completed=sum(1 for j in jobs_all if j.status == "completed"),
    )


# --- Built frontend (single-container deployment) -------------------------
_dist = settings.frontend_dist or os.path.join(os.path.dirname(__file__), "..", "..", "frontend_dist")
_dist = os.path.normpath(_dist)
if os.path.isdir(_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(_dist, "assets")), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        candidate = os.path.join(_dist, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_dist, "index.html"))
else:

    @app.get("/")
    def root():
        return JSONResponse(
            {"service": "proj-manager", "ui": "frontend not built; API at /api, docs at /docs"}
        )
