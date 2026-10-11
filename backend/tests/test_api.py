import os
import time

os.environ["DATABASE_URL"] = "sqlite:///./test_proj_manager.db"
os.environ["JOB_STEP_DELAY"] = "0"
os.environ["ADMIN_TOKEN"] = "test-admin"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN = {"X-Admin-Token": "test-admin"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # runs lifespan: creates tables, seeds demo data
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_status_demo_mode(client):
    r = client.get("/api/status")
    body = r.json()
    assert r.status_code == 200
    assert body["demo_mode"] is True
    assert body["projects"] >= 2  # seeded samples


def test_project_crud(client):
    r = client.post("/api/projects", json={"name": "Test Project", "source_type": "sharepoint"})
    assert r.status_code == 201
    pid = r.json()["id"]
    r = client.get(f"/api/projects/{pid}")
    assert r.status_code == 200 and r.json()["name"] == "Test Project"
    r = client.delete(f"/api/projects/{pid}")
    assert r.status_code == 204


def test_job_run_completes(client):
    pid = client.get("/api/projects").json()[0]["id"]
    r = client.post("/api/jobs", json={"project_id": pid, "name": "Run me", "source_path": "/A", "target_path": "/B"})
    assert r.status_code == 201
    jid = r.json()["id"]
    assert client.post(f"/api/jobs/{jid}/run").status_code == 200
    deadline = time.time() + 15
    status = ""
    while time.time() < deadline:
        jobs = client.get("/api/jobs", params={"project_id": pid}).json()
        status = next(j["status"] for j in jobs if j["id"] == jid)
        if status == "completed":
            break
        time.sleep(0.2)
    assert status == "completed"


def test_maintenance_blocks_run_and_admin_complete(client):
    pid = client.get("/api/projects").json()[0]["id"]
    r = client.post("/api/admin/maintenance", json={"enabled": True, "message": "patching"}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["maintenance_mode"] is True
    r = client.post("/api/jobs", json={"project_id": pid, "name": "Blocked job"})
    jid = r.json()["id"]
    r = client.post(f"/api/jobs/{jid}/run")
    assert r.json()["status"] == "blocked"
    r = client.post("/api/admin/maintenance", json={"enabled": False}, headers=ADMIN)
    assert r.status_code == 200
    r = client.post(f"/api/admin/projects/{pid}/complete", headers=ADMIN)
    assert r.status_code == 200 and r.json()["status"] == "complete"


def test_admin_requires_token(client):
    r = client.post("/api/admin/maintenance", json={"enabled": True})
    assert r.status_code == 401


def test_graph_test_demo(client):
    r = client.post("/api/admin/graph/test", headers=ADMIN)
    assert r.status_code == 200 and r.json()["mode"] == "demo"
