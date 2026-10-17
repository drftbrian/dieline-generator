import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.jobs import runner
from app.main import create_app

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Never read backend/.env in tests: no real API keys, no real spend.
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for k in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "FIGMA_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FLAT_LONG_EDGE", "1024")  # full 4K renders are tested in test_flat_render
    monkeypatch.delenv("FLAT_RENDER_MODE", raising=False)
    get_settings.cache_clear()
    with TestClient(create_app()) as c:
        yield c
        runner.drain()  # a job still running must not outlive this test's data directory
    get_settings.cache_clear()


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / f"{name}.pdf").read_bytes()


def wait_job(client: TestClient, job_id: str, timeout: float = 60) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} did not finish")


def upload(client: TestClient, name: str) -> tuple[str, dict]:
    pid = client.post("/api/projects", json={"name": name}).json()["id"]
    res = client.post(
        f"/api/projects/{pid}/upload",
        files={"file": (f"{name}.pdf", fixture_bytes(name), "application/pdf")},
    )
    assert res.status_code == 202, res.json()
    return pid, wait_job(client, res.json()["job_id"])
