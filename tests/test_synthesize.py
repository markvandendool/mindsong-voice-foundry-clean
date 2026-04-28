"""pytest suite for Voice Foundry synthesis + job lifecycle."""

import pytest
from fastapi.testclient import TestClient

from src.api.server import app

client = TestClient(app)


def test_health_returns_engines():
    res = client.get("/voice/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["gpuDevice"] in ("mps", "cuda", "cpu")
    assert "engines" in data


def test_synthesize_rejects_invalid_job_id():
    res = client.post(
        "/voice/synthesize",
        json={"text": "hello", "jobId": "../../../etc/passwd"},
    )
    assert res.status_code == 422


def test_synthesize_rejects_too_long_text():
    res = client.post(
        "/voice/synthesize",
        json={"text": "x" * 601},
    )
    assert res.status_code == 422


def test_synthesize_accepts_valid_request():
    res = client.post(
        "/voice/synthesize",
        json={"text": "hello world", "jobId": "pytest_001"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "queued"
    assert data["jobId"] == "pytest_001"


def test_status_returns_not_found_for_missing_job():
    res = client.get("/voice/synthesize/status/nonexistent_job_12345")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "not_found"


def test_cancel_rejects_invalid_job_id():
    res = client.delete("/voice/synthesize/cancel/bad id")
    assert res.status_code == 400


def test_cancel_returns_not_found_for_missing_job():
    res = client.delete("/voice/synthesize/cancel/missing_job_12345")
    assert res.status_code == 404


def test_bakeoff_queues_jobs():
    res = client.post(
        "/voice/bakeoff",
        json={"text": "bakeoff test", "bakeoffId": "pytest_bake_001"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "running"
    assert len(data["jobs"]) == 3
