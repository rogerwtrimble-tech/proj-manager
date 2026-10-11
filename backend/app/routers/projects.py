from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Project
from ..schemas import ProjectIn, ProjectOut

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _out(p: Project) -> ProjectOut:
    out = ProjectOut.model_validate(p)
    out.job_count = len(p.jobs)
    out.jobs_completed = sum(1 for j in p.jobs if j.status == "completed")
    return out


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return [_out(p) for p in db.query(Project).order_by(Project.id).all()]


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(payload: ProjectIn, db: Session = Depends(get_db)):
    p = Project(**payload.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return _out(p)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    return _out(p)


@router.put("/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, payload: ProjectIn, db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    for key, value in payload.model_dump().items():
        setattr(p, key, value)
    db.commit()
    db.refresh(p)
    return _out(p)


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: int, db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    db.delete(p)
    db.commit()
    return None
