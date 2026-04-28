"""Model bakeoff endpoint — run same text through all installed engines."""

import json
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from .synthesize import _run_synthesis_job, _read_job_manifest, _write_job_manifest, JOB_ID_RE

router = APIRouter()

# Bakeoff aggregations persisted to filesystem
BAKEOFF_DIR = Path("artifacts/bakeoffs")
BAKEOFF_DIR.mkdir(parents=True, exist_ok=True)

# Engines participating in bakeoff
BAKEOFF_ENGINE_PRESETS = {
    "f5tts": "mark_rocky_tutor_warm",
    "chatterbox": "mark_chatterbox_storytelling",
    "voxcpm2": "mark_voxcpm2_clone",
}


class BakeoffRequest(BaseModel):
    text: str
    mixPreset: str = "rocky_live"
    bakeoffId: str | None = None


class BakeoffResponse(BaseModel):
    bakeoffId: str
    status: str
    jobs: list[dict]
    createdAt: str
    updatedAt: str


def _bakeoff_path(bakeoff_id: str) -> Path:
    return BAKEOFF_DIR / f"{bakeoff_id}.json"


@router.post("/bakeoff")
async def bakeoff(req: BakeoffRequest, background_tasks: BackgroundTasks):
    bid = req.bakeoffId or f"bake_{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow().isoformat()

    jobs_meta = []
    for engine, preset in BAKEOFF_ENGINE_PRESETS.items():
        job_id = f"{bid}_{engine}"
        manifest = {
            "jobId": job_id,
            "status": "queued",
            "createdAt": now,
            "updatedAt": now,
        }
        _write_job_manifest(job_id, manifest)
        # GPU semaphore is acquired INSIDE each background task worker.
        background_tasks.add_task(
            _run_synthesis_job,
            job_id,
            req.text,
            preset,
            req.mixPreset,
        )
        jobs_meta.append({"jobId": job_id, "engine": engine, "preset": preset, "status": "queued"})

    bake = {
        "bakeoffId": bid,
        "status": "running",
        "jobs": jobs_meta,
        "createdAt": now,
        "updatedAt": now,
    }
    _bakeoff_path(bid).write_text(json.dumps(bake, indent=2, default=str))

    return {"bakeoffId": bid, "status": "running", "jobs": jobs_meta}


@router.get("/bakeoff/status/{bakeoff_id}")
async def bakeoff_status(bakeoff_id: str):
    if not JOB_ID_RE.match(bakeoff_id):
        return {"bakeoffId": bakeoff_id, "status": "invalid_id", "jobs": []}

    path = _bakeoff_path(bakeoff_id)
    if not path.exists():
        return {"bakeoffId": bakeoff_id, "status": "not_found", "jobs": []}

    bake = json.loads(path.read_text())

    # Aggregate latest job statuses from manifests
    all_completed = True
    any_failed = False
    updated_jobs = []
    for j in bake.get("jobs", []):
        job = _read_job_manifest(j["jobId"]) or {}
        j["status"] = job.get("status", "unknown")
        j["audioUrl"] = job.get("audioUrl")
        j["metrics"] = job.get("metrics")
        j["error"] = job.get("error")
        updated_jobs.append(j)
        if j["status"] not in ("completed", "failed", "cancelled"):
            all_completed = False
        if j["status"] == "failed":
            any_failed = True

    bake["jobs"] = updated_jobs
    if all_completed:
        bake["status"] = "completed"
    elif any_failed:
        bake["status"] = "partial_failure"

    bake["updatedAt"] = datetime.utcnow().isoformat()
    path.write_text(json.dumps(bake, indent=2, default=str))

    return bake
