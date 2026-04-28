"""Health endpoint tests — must remain cheap."""

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
def test_health_exposes_auth_posture():
    res = client.get("/voice/health")
    assert res.status_code == 200
    data = res.json()
    assert "auth" in data
    assert "authRequired" in data["auth"]
    assert "devAuthBypass" in data["auth"]
    assert "releaseSafe" in data["auth"]


@pytest.mark.unit
def test_health_does_not_import_torch(monkeypatch):
    """If torch is imported during health, explode."""
    import sys

    class TorchExploder:
        def __getattr__(self, name):
            raise AssertionError("torch import detected in health path")

    monkeypatch.setitem(sys.modules, "torch", TorchExploder())

    # Force reimport of health module to catch lazy imports
    import importlib
    from src.api import routes

    importlib.reload(routes.health)
    res = client.get("/voice/health")
    assert res.status_code == 200
