"""Shared API utilities for path safety and artifact resolution."""

import os
import re
from pathlib import Path

from fastapi import HTTPException

JOB_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
ARTIFACT_ROOT = Path("artifacts").resolve()


def validate_safe_id(value: str, field: str = "id") -> str:
    if not JOB_ID_RE.match(value):
        raise HTTPException(status_code=400, detail=f"Invalid {field}")
    if ".." in value:
        raise HTTPException(status_code=400, detail=f"Invalid {field}")
    return value


def resolve_job_artifact(job_id: str, artifact: str) -> Path:
    """Resolve a job artifact path under ARTIFACT_ROOT."""
    validate_safe_id(job_id, "jobId")

    if artifact == "raw":
        filename = f"{job_id}.raw.wav"
    elif artifact == "mastered":
        filename = f"{job_id}.mastered.wav"
    else:
        raise HTTPException(status_code=400, detail="Invalid artifact type; use 'raw' or 'mastered'")

    candidate = (ARTIFACT_ROOT / "voice" / "mark" / filename).resolve()
    try:
        candidate.relative_to(ARTIFACT_ROOT)
    except ValueError:
        raise HTTPException(status_code=400, detail="Path escapes artifact root")

    return candidate
