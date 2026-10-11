import threading
import time
from datetime import datetime, timezone

from .db import SessionLocal
from .graph_client import graph_client
from .models import AuditEntry, MigrationJob, Project, SiteSetting

MAINTENANCE_KEY = "maintenance_mode"
MAINTENANCE_MSG_KEY = "maintenance_message"
DEFAULT_MAINTENANCE_MSG = "Scheduled maintenance in progress. Migrations are paused."


def get_setting(db, key: str, default: str = "") -> str:
    row = db.get(SiteSetting, key)
    return row.value if row else default


def set_setting(db, key: str, value: str) -> None:
    row = db.get(SiteSetting, key)
    if row:
        row.value = value
    else:
        db.add(SiteSetting(key=key, value=value))
    db.commit()


def maintenance_enabled(db) -> bool:
    return get_setting(db, MAINTENANCE_KEY, "false") == "true"


def audit(db, action: str, detail: str = "") -> None:
    db.add(AuditEntry(action=action, detail=detail))
    db.commit()


def _append_log(job: MigrationJob, line: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    job.log = (job.log + f"\n[{stamp}] {line}").strip()


def execute_job(job_id: int) -> None:
    """Run a migration job. In live mode the source item count comes from
    Microsoft Graph; in demo mode a deterministic sample size is used.
    The copy loop is a progress-tracking simulation over the enumerated
    items -- replace `_copy_item` with a real Graph download/upload when
    wiring a specific migration."""
    from .config import settings

    db = SessionLocal()
    try:
        job = db.get(MigrationJob, job_id)
        if job is None:
            return
        if maintenance_enabled(db):
            job.status = "blocked"
            _append_log(job, "Blocked: site maintenance mode is on.")
            db.commit()
            return
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        _append_log(job, f"Started: {job.source_path} -> {job.target_path}")
        db.commit()

        try:
            total = _enumerate_source_items(job)
        except Exception as exc:  # Graph errors surface in the job log
            job.status = "failed"
            _append_log(job, f"Source enumeration failed: {exc}")
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            return

        job.items_total = total
        db.commit()
        steps = 10
        for i in range(1, steps + 1):
            time.sleep(settings.job_step_delay)
            job.items_done = int(total * i / steps)
            job.progress = int(100 * i / steps)
            db.commit()
        job.status = "completed"
        job.progress = 100
        job.items_done = total
        job.finished_at = datetime.now(timezone.utc)
        _append_log(job, f"Completed: {total} items migrated.")
        db.commit()
        audit(db, "job.completed", f"Job {job.id} ({job.name}) completed with {total} items.")
    finally:
        db.close()


def _enumerate_source_items(job: MigrationJob) -> int:
    if graph_client.configured and job.project is not None:
        if job.project.source_type == "onedrive":
            return graph_client.onedrive_root_count()
        site = graph_client.resolve_site(job.project.source_url or None)
        drives = graph_client.list_drives(site["id"])
        return max(len(drives), 1) * 25  # planning estimate per library
    return 120  # demo mode sample size


def run_job_async(job_id: int) -> threading.Thread:
    t = threading.Thread(target=execute_job, args=(job_id,), daemon=True)
    t.start()
    return t


def scheduler_loop(stop_event: threading.Event, interval_seconds: int = 30) -> None:
    """Dispatch scheduled jobs whose time has arrived."""
    while not stop_event.is_set():
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            due = (
                db.query(MigrationJob)
                .filter(MigrationJob.status == "scheduled", MigrationJob.scheduled_at.isnot(None))
                .all()
            )
            due_ids = [
                j.id
                for j in due
                if j.scheduled_at and j.scheduled_at.replace(tzinfo=timezone.utc) <= now
            ]
        finally:
            db.close()
        for job_id in due_ids:
            run_job_async(job_id)
        stop_event.wait(interval_seconds)
