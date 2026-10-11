from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import services
from ..db import get_db
from ..models import MigrationJob, Project
from ..schemas import JobIn, JobOut

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=list[JobOut])
def list_jobs(project_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(MigrationJob).order_by(MigrationJob.id)
    if project_id is not None:
        q = q.filter(MigrationJob.project_id == project_id)
    return q.all()


@router.post("", response_model=JobOut, status_code=201)
def create_job(payload: JobIn, db: Session = Depends(get_db)):
    if not db.get(Project, payload.project_id):
        raise HTTPException(404, "Project not found")
    job = MigrationJob(**payload.model_dump())
    db.add(job)
    db.commit()
    db.refresh(job)
    services.audit(db, "job.created", f"Job {job.id} ({job.name}) created for project {job.project_id}.")
    return job


@router.post("/{job_id}/run", response_model=JobOut)
def run_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(MigrationJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if services.maintenance_enabled(db):
        job.status = "blocked"
        services._append_log(job, "Run rejected: site maintenance mode is on.")
        db.commit()
        db.refresh(job)
        return job
    services.run_job_async(job_id)
    db.refresh(job)
    return job


@router.post("/{job_id}/complete", response_model=JobOut)
def complete_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(MigrationJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    from datetime import datetime, timezone

    job.status = "completed"
    job.progress = 100
    if job.items_total:
        job.items_done = job.items_total
    job.finished_at = datetime.now(timezone.utc)
    services._append_log(job, "Marked complete by admin.")
    db.commit()
    db.refresh(job)
    return job


@router.delete("/{job_id}", status_code=204)
def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(MigrationJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    db.delete(job)
    db.commit()
    return None
