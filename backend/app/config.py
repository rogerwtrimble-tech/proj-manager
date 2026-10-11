import os


class Settings:
    """Environment-driven settings. Everything optional: with no Microsoft
    credentials the app runs in demo mode against seeded sample data."""

    def __init__(self) -> None:
        self.database_url: str = os.environ.get("DATABASE_URL", "sqlite:///./proj_manager.db")
        self.sharepoint_site_url: str = os.environ.get("SHAREPOINT_SITE_URL", "")
        self.ms_tenant_id: str = os.environ.get("MS_TENANT_ID", "")
        self.ms_client_id: str = os.environ.get("MS_CLIENT_ID", "")
        self.ms_client_secret: str = os.environ.get("MS_CLIENT_SECRET", "")
        self.onedrive_user_upn: str = os.environ.get("ONEDRIVE_USER_UPN", "")
        self.admin_token: str = os.environ.get("ADMIN_TOKEN", "change-me")
        # Shared secret for the dashboard "Migration prep" tile.
        # Falls back to ADMIN_TOKEN when RUN_PASSWORD is not set.
        self.run_password: str = os.environ.get("RUN_PASSWORD", "") or self.admin_token
        self.frontend_dist: str = os.environ.get("FRONTEND_DIST", "")
        self.job_step_delay: float = float(os.environ.get("JOB_STEP_DELAY", "0.4"))
        self.data_dir: str = os.path.abspath(os.environ.get("DATA_DIR", "/data" if os.path.isdir("/data") else "./data"))
        self.script_timeout: int = int(os.environ.get("SCRIPT_TIMEOUT", "120"))

    @property
    def graph_configured(self) -> bool:
        return bool(self.ms_tenant_id and self.ms_client_id and self.ms_client_secret)


settings = Settings()
