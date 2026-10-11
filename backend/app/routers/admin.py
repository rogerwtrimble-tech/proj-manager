from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .. import services
from ..config import settings
from ..db import get_db
from ..graph_client import GraphError, graph_client
from ..models import AuditEntry, MigrationJob, Project
from ..schemas import MaintenanceIn, ProjectOut
from .projects import _out

router = APIRouter(prefix="/api/admin", tags=["admin"])


def require_admin(x_admin_token: str = Header(default="")) -> None:
    if x_admin_token != settings.admin_token:
        raise HTTPException(401, "Invalid or missing X-Admin-Token")


@router.post("/maintenance")
def set_maintenance(payload: MaintenanceIn, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    services.set_setting(db, services.MAINTENANCE_KEY, "true" if payload.enabled else "false")
    services.set_setting(db, services.MAINTENANCE_MSG_KEY, payload.message)
    for p in db.query(Project).filter(Project.status == "active").all():
        p.status = "maintenance" if payload.enabled else "active"
    db.commit()
    services.audit(db, "admin.maintenance", f"Maintenance mode {'ON' if payload.enabled else 'OFF'}: {payload.message}")
    return {"maintenance_mode": payload.enabled, "message": payload.message}


@router.post("/projects/{project_id}/complete", response_model=ProjectOut)
def complete_project(project_id: int, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    """Admin tool: mark a migration project complete (and close its jobs)."""
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    from datetime import datetime, timezone

    p.status = "complete"
    for job in p.jobs:
        if job.status != "completed":
            job.status = "completed"
            job.progress = 100
            if job.items_total:
                job.items_done = job.items_total
            job.finished_at = datetime.now(timezone.utc)
            services._append_log(job, "Closed by admin: project marked complete.")
    db.commit()
    db.refresh(p)
    services.audit(db, "admin.project_complete", f"Project {p.id} ({p.name}) marked complete.")
    return _out(p)


@router.post("/graph/test")
def graph_test(_: None = Depends(require_admin)):
    try:
        return graph_client.test_connection()
    except GraphError as exc:
        raise HTTPException(502, str(exc))


@router.get("/audit")
def audit_log(db: Session = Depends(get_db), _: None = Depends(require_admin)):
    rows = db.query(AuditEntry).order_by(AuditEntry.id.desc()).limit(100).all()
    return [
        {"id": r.id, "action": r.action, "detail": r.detail, "created_at": r.created_at}
        for r in rows
    ]
