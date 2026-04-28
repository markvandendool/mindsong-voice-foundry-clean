"""pytest suite for Voice Foundry synthesis + job lifecycle."""

import pytest
from fastapi.testclient import TestClient

from src.api.server import app

client = TestClient(app)


@pytest.mark.unit
def test_health_returns_engines():
    res = client.get("/voice/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["gpuDevice"] in ("mps", "cuda", "cpu")
    assert "engines" in data


@pytest.mark.unit
def test_synthesize_rejects_invalid_job_id():
    res = client.post(
        "/voice/synthesize",
        json={"text": "hello", "jobId": "../../../etc/passwd"},
    )
    assert res.status_code == 422


@pytest.mark.unit
def test_synthesize_rejects_too_long_text():
    res = client.post(
        "/voice/synthesize",
        json={"text": "x" * 601},
    )
    assert res.status_code == 422


@pytest.mark.unit
def test_synthesize_accepts_valid_request():
    res = client.post(
        "/voice/synthesize",
        json={"text": "hello world", "jobId": "pytest_001"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "queued"
    assert data["jobId"] == "pytest_001"


@pytest.mark.unit
def test_status_returns_not_found_for_missing_job():
    res = client.get("/voice/synthesize/status/nonexistent_job_12345")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "not_found"


@pytest.mark.unit
def test_cancel_rejects_invalid_job_id():
    res = client.delete("/voice/synthesize/cancel/bad id")
    assert res.status_code == 400


@pytest.mark.unit
def test_cancel_returns_not_found_for_missing_job():
    res = client.delete("/voice/synthesize/cancel/missing_job_12345")
    assert res.status_code == 404


@pytest.mark.unit
def test_cancel_returns_already_terminal_for_completed():
    import json
    from pathlib import Path
    job_id = "pytest_terminal_001"
    manifest = {
        "jobId": job_id,
        "status": "completed",
        "createdAt": "2024-01-01T00:00:00",
        "updatedAt": "2024-01-01T00:00:00",
    }
    job_dir = Path("artifacts/jobs") / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "manifest.json").write_text(json.dumps(manifest))

    res = client.delete(f"/voice/synthesize/cancel/{job_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["cancelled"] is False
    assert data["reason"] == "already_terminal"


@pytest.mark.unit
def test_cancelled_job_cannot_be_completed():
    import json
    from pathlib import Path
    from src.api.routes.synthesize import _transition_status, _write_job_manifest

    job_id = "pytest_cancel_guard_001"
    manifest = {
        "jobId": job_id,
        "status": "cancelled",
        "createdAt": "2024-01-01T00:00:00",
        "updatedAt": "2024-01-01T00:00:00",
    }
    _write_job_manifest(job_id, manifest)

    # Attempt to transition cancelled → completed
    ok = _transition_status(job_id, "completed", {"audioUrl": "/static/test.wav"})
    assert ok is False

    # Verify status remains cancelled
    job_dir = Path("artifacts/jobs") / job_id
    refreshed = json.loads((job_dir / "manifest.json").read_text())
    assert refreshed["status"] == "cancelled"


@pytest.mark.unit
def test_status_transition_guard_blocks_invalid():
    import json
    from pathlib import Path
    from src.api.routes.synthesize import _transition_status, _write_job_manifest

    job_id = "pytest_transition_001"
    manifest = {
        "jobId": job_id,
        "status": "completed",
        "createdAt": "2024-01-01T00:00:00",
        "updatedAt": "2024-01-01T00:00:00",
    }
    _write_job_manifest(job_id, manifest)

    # completed → running is invalid
    ok = _transition_status(job_id, "running")
    assert ok is False


@pytest.mark.unit
def test_bakeoff_queues_jobs():
    res = client.post(
        "/voice/bakeoff",
        json={"text": "bakeoff test", "bakeoffId": "pytest_bake_001"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "running"
    assert len(data["jobs"]) == 3
