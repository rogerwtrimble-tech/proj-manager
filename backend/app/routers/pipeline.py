import hmac
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import pipeline, services
from ..config import settings
from ..db import SessionLocal, get_db
from ..models import PipelineRun, Script
from .admin import require_admin

router = APIRouter(prefix="/api", tags=["pipeline"])


class PipelineRunIn(BaseModel):
    migration_date: str  # mm.dd.yyyy
    folder_url: str = ""
    project_id: int | None = None
    steps: list[str] = ["stage", "normalize", "precheck", "report"]


class ScriptIn(BaseModel):
    name: str
    description: str = ""
    code: str = ""


def _run_out(r: PipelineRun) -> dict:
    return {
        "id": r.id, "project_id": r.project_id, "migration_date": r.migration_date,
        "folder_url": r.folder_url, "status": r.status, "stage": r.stage,
        "errors": r.errors, "warnings": r.warnings, "log": r.log,
        "workdir": r.workdir, "log_artifact": r.log_artifact, "xlsx_artifact": r.xlsx_artifact,
        "created_at": r.created_at, "finished_at": r.finished_at,
    }


def _execute(run_id: int, steps: list[str]) -> None:
    db = SessionLocal()
    try:
        run = db.get(PipelineRun, run_id)
        run.status = "running"
        db.commit()

        def log(line: str) -> None:
            run.log = (run.log + "\n" + line).strip()
            db.commit()

        counts = pipeline.run_pipeline_steps(run, steps, log)
        run.errors, run.warnings = counts["errors"], counts["warnings"]
        run.status = "completed"
        run.stage = "done"
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        services.audit(db, "pipeline.completed",
                       f"Run {run.id} ({run.migration_date}): {run.errors} errors, {run.warnings} warnings.")
    except Exception as exc:
        run = db.get(PipelineRun, run_id)
        if run:
            run.status = "failed"
            run.log = (run.log + f"\n[ERROR] Pipeline failed: {exc}").strip()
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


@router.post("/pipeline/runs", status_code=201)
def create_run(payload: PipelineRunIn, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    run = PipelineRun(
        migration_date=payload.migration_date,
        folder_url=payload.folder_url or f"Migration - {payload.migration_date}",
        project_id=payload.project_id,
        workdir=pipeline.mig_dir(payload.migration_date),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    threading.Thread(target=_execute, args=(run.id, payload.steps), daemon=True).start()
    return _run_out(run)


@router.get("/pipeline/runs")
def list_runs(db: Session = Depends(get_db)):
    return [_run_out(r) for r in db.query(PipelineRun).order_by(PipelineRun.id.desc()).all()]


@router.get("/pipeline/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(PipelineRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return _run_out(run)


@router.get("/pipeline/runs/{run_id}/artifacts/{kind}")
def download_artifact(run_id: int, kind: str, db: Session = Depends(get_db)):
    run = db.get(PipelineRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    name = run.log_artifact if kind == "log" else run.xlsx_artifact if kind == "xlsx" else ""
    if not name:
        raise HTTPException(404, "Artifact not available")
    path = os.path.join(run.workdir, "reports", name)
    if not os.path.isfile(path):
        raise HTTPException(404, "Artifact file missing")
    media = "text/plain" if kind == "log" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return FileResponse(path, filename=name, media_type=media)


class QuickRunIn(BaseModel):
    password: str
    migration_date: str = ""  # mm.dd.yyyy; defaults to today
    folder_url: str = ""


# Simple in-memory throttle for the shared-password tile endpoint:
# after 5 failed attempts, lock for 5 minutes.
_attempts: dict = {"fails": 0, "locked_until": 0.0}


@router.post("/pipeline/run-quick", status_code=202)
def quick_run(payload: QuickRunIn, db: Session = Depends(get_db)):
    """Dashboard tile entry point for site visitors who know the shared
    secret (RUN_PASSWORD, falling back to ADMIN_TOKEN). Runs the full
    chain: stage (download + unzip) -> normalize -> pre-check -> report,
    then the dashboard status reflects the result."""
    now = time.time()
    if now < _attempts["locked_until"]:
        raise HTTPException(429, "Too many failed attempts — try again in a few minutes")
    if not payload.password or not hmac.compare_digest(payload.password, settings.run_password):
        _attempts["fails"] += 1
        if _attempts["fails"] >= 5:
            _attempts["locked_until"] = now + 300
            _attempts["fails"] = 0
        raise HTTPException(403, "Wrong password")
    _attempts["fails"] = 0
    date = payload.migration_date.strip() or datetime.now().strftime("%m.%d.%Y")
    run = PipelineRun(
        migration_date=date,
        folder_url=payload.folder_url or f"Migration - {date}",
        workdir=pipeline.mig_dir(date),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    threading.Thread(target=_execute, args=(run.id, ["stage", "normalize", "precheck", "report"]), daemon=True).start()
    services.audit(db, "pipeline.quick_run", f"Run {run.id} started from the dashboard tile for {date}.")
    return {"run_id": run.id, "migration_date": date, "status": run.status}


# ---------------------------------------------------------------------------
# Utility scripts: stored in the DB, edited in the UI, executed in the app
# venv (admin only). Scripts receive DATA_DIR / MIG_BASE env vars.
# ---------------------------------------------------------------------------
def _script_out(s: Script) -> dict:
    return {
        "id": s.id, "name": s.name, "description": s.description, "code": s.code,
        "last_status": s.last_status, "last_output": s.last_output,
        "last_run_at": s.last_run_at, "updated_at": s.updated_at,
    }


@router.get("/scripts")
def list_scripts(db: Session = Depends(get_db)):
    return [_script_out(s) for s in db.query(Script).order_by(Script.name).all()]


@router.post("/scripts", status_code=201)
def create_script(payload: ScriptIn, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    if db.query(Script).filter(Script.name == payload.name).first():
        raise HTTPException(409, "Script name already exists")
    s = Script(**payload.model_dump())
    db.add(s)
    db.commit()
    db.refresh(s)
    return _script_out(s)


@router.put("/scripts/{script_id}")
def update_script(script_id: int, payload: ScriptIn, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    s = db.get(Script, script_id)
    if not s:
        raise HTTPException(404, "Script not found")
    s.name, s.description, s.code = payload.name, payload.description, payload.code
    db.commit()
    db.refresh(s)
    return _script_out(s)


@router.delete("/scripts/{script_id}", status_code=204)
def delete_script(script_id: int, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    s = db.get(Script, script_id)
    if not s:
        raise HTTPException(404, "Script not found")
    db.delete(s)
    db.commit()
    return None


@router.post("/scripts/{script_id}/run")
def run_script(script_id: int, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    s = db.get(Script, script_id)
    if not s:
        raise HTTPException(404, "Script not found")
    scripts_dir = os.path.join(settings.data_dir, "scripts")
    os.makedirs(scripts_dir, exist_ok=True)
    path = os.path.join(scripts_dir, f"{s.id}_{s.name}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(s.code)
    env = {**os.environ, "DATA_DIR": settings.data_dir, "MIG_BASE": os.path.join(settings.data_dir, "mig")}
    try:
        proc = subprocess.run(
            [sys.executable, path], capture_output=True, text=True,
            timeout=settings.script_timeout, cwd=settings.data_dir, env=env,
        )
        s.last_status = "ok" if proc.returncode == 0 else "error"
        s.last_output = (proc.stdout + proc.stderr)[-20000:]
    except subprocess.TimeoutExpired:
        s.last_status = "timeout"
        s.last_output = f"Script exceeded {settings.script_timeout}s timeout."
    s.last_run_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(s)
    services.audit(db, "script.run", f"Script {s.id} ({s.name}) ran: {s.last_status}.")
    return _script_out(s)
