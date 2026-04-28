"""Security boundary tests for Voice Foundry."""

import pytest
from fastapi.testclient import TestClient

from src.api.server import app

client = TestClient(app)


@pytest.mark.unit
def test_master_rejects_legacy_path_fields():
    res = client.post(
        "/voice/master",
        json={"inputPath": "/etc/passwd", "outputPath": "/tmp/out.wav"},
    )
    # Pydantic extra="forbid" rejects unknown fields with 422
    assert res.status_code == 422


@pytest.mark.unit
def test_qc_rejects_legacy_path_field():
    res = client.post(
        "/voice/qc",
        json={"audioPath": "/etc/passwd"},
    )
    assert res.status_code == 422


@pytest.mark.unit
def test_master_rejects_absolute_path_traversal():
    res = client.post(
        "/voice/master",
        json={"jobId": "../etc/passwd", "artifact": "raw"},
    )
    assert res.status_code == 400


@pytest.mark.unit
def test_qc_rejects_absolute_path_traversal():
    res = client.post(
        "/voice/qc",
        json={"jobId": "../../evil", "artifact": "mastered"},
    )
    assert res.status_code == 400


@pytest.mark.unit
def test_bakeoff_id_path_traversal_rejected():
    res = client.post(
        "/voice/bakeoff",
        json={"text": "probe", "bakeoffId": "../../evil"},
    )
    assert res.status_code == 422


@pytest.mark.unit
def test_bakeoff_id_with_dotdot_rejected():
    res = client.post(
        "/voice/bakeoff",
        json={"text": "probe", "bakeoffId": "foo..bar"},
    )
    assert res.status_code == 422
