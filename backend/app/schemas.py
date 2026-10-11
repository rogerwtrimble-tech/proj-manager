from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ProjectIn(BaseModel):
    name: str
    description: str = ""
    source_type: str = "sharepoint"
    source_url: str = ""
    target_url: str = ""
    status: str = "planning"


class ProjectOut(ProjectIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime
    job_count: int = 0
    jobs_completed: int = 0


class JobIn(BaseModel):
    project_id: int
    name: str
    source_path: str = "/"
    target_path: str = "/"
    scheduled_at: Optional[datetime] = None


class JobOut(JobIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    progress: int
    items_total: int
    items_done: int
    log: str
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class MaintenanceIn(BaseModel):
    enabled: bool
    message: str = "Scheduled maintenance in progress. Migrations are paused."


class StatusOut(BaseModel):
    graph_configured: bool
    demo_mode: bool
    sharepoint_site_url: str
    maintenance_mode: bool
    maintenance_message: str
    projects: int
    jobs_total: int
    jobs_scheduled: int
    jobs_running: int
    jobs_completed: int
