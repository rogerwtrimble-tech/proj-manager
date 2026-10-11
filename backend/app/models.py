from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    source_type = Column(String(20), default="sharepoint")  # sharepoint | onedrive
    source_url = Column(String(500), default="")
    target_url = Column(String(500), default="")
    # planning | active | maintenance | complete
    status = Column(String(20), default="planning")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    jobs = relationship("MigrationJob", back_populates="project", cascade="all, delete-orphan")


class MigrationJob(Base):
    __tablename__ = "migration_jobs"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    name = Column(String(200), nullable=False)
    source_path = Column(String(500), default="/")
    target_path = Column(String(500), default="/")
    scheduled_at = Column(DateTime, nullable=True)
    # scheduled | running | completed | failed | blocked
    status = Column(String(20), default="scheduled")
    progress = Column(Integer, default=0)
    items_total = Column(Integer, default=0)
    items_done = Column(Integer, default=0)
    log = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    project = relationship("Project", back_populates="jobs")


class SiteSetting(Base):
    __tablename__ = "site_settings"

    key = Column(String(100), primary_key=True)
    value = Column(String(500), default="")


class AuditEntry(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True)
    action = Column(String(200), nullable=False)
    detail = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    migration_date = Column(String(20), nullable=False)  # mm.dd.yyyy
    folder_url = Column(String(500), default="")
    # created | running | completed | failed
    status = Column(String(20), default="created")
    stage = Column(String(50), default="")  # current/last step
    errors = Column(Integer, default=0)
    warnings = Column(Integer, default=0)
    log = Column(Text, default="")
    workdir = Column(String(500), default="")
    log_artifact = Column(String(200), default="")
    xlsx_artifact = Column(String(200), default="")
    created_at = Column(DateTime, default=utcnow)
    finished_at = Column(DateTime, nullable=True)


class Script(Base):
    __tablename__ = "scripts"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), unique=True, nullable=False)
    description = Column(Text, default="")
    code = Column(Text, default="")
    last_status = Column(String(20), default="")  # ok | error | timeout
    last_output = Column(Text, default="")
    last_run_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
