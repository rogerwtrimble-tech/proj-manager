"""Microsoft Graph integration for SharePoint / OneDrive.

App-only (client credentials) auth via MSAL. When credentials are not
configured the client reports demo mode and the rest of the app works
against seeded sample data, so the stack can be evaluated before an
Azure app registration exists.
"""
from urllib.parse import urlparse

import requests

from .config import settings

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"


class GraphError(Exception):
    pass


class GraphClient:
    def __init__(self) -> None:
        self._token: str | None = None

    @property
    def configured(self) -> bool:
        return settings.graph_configured

    def _access_token(self) -> str:
        if self._token:
            return self._token
        import msal

        app = msal.ConfidentialClientApplication(
            client_id=settings.ms_client_id,
            client_credential=settings.ms_client_secret,
            authority=f"https://login.microsoftonline.com/{settings.ms_tenant_id}",
        )
        result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        if "access_token" not in result:
            raise GraphError(f"Token acquisition failed: {result.get('error_description', result)}")
        self._token = result["access_token"]
        return self._token

    def _get(self, path: str) -> dict:
        resp = requests.get(
            f"{GRAPH_ROOT}{path}",
            headers={"Authorization": f"Bearer {self._access_token()}"},
            timeout=30,
        )
        if resp.status_code >= 400:
            raise GraphError(f"Graph GET {path} -> {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    def resolve_site(self, site_url: str | None = None) -> dict:
        """Resolve a SharePoint site URL to its Graph site object."""
        url = site_url or settings.sharepoint_site_url
        if not url:
            raise GraphError("SHAREPOINT_SITE_URL is not set")
        parsed = urlparse(url)
        host = parsed.netloc
        path = parsed.path.rstrip("/")
        site = self._get(f"/sites/{host}:{path}")
        return {"id": site.get("id"), "name": site.get("displayName"), "web_url": site.get("webUrl")}

    def list_drives(self, site_id: str) -> list[dict]:
        data = self._get(f"/sites/{site_id}/drives")
        return [
            {"id": d.get("id"), "name": d.get("name"), "drive_type": d.get("driveType")}
            for d in data.get("value", [])
        ]

    def onedrive_root_count(self) -> int:
        """Item count in the configured user's OneDrive root."""
        if not settings.onedrive_user_upn:
            raise GraphError("ONEDRIVE_USER_UPN is not set")
        data = self._get(f"/users/{settings.onedrive_user_upn}/drive/root/children")
        return len(data.get("value", []))

    def test_connection(self) -> dict:
        if not self.configured:
            return {"ok": True, "mode": "demo", "detail": "No Microsoft credentials configured; running in demo mode."}
        site = self.resolve_site()
        drives = self.list_drives(site["id"])
        return {"ok": True, "mode": "live", "site": site, "drives": drives}


graph_client = GraphClient()
