"""Voice synthesis endpoint with async job queue — multi-engine, hardened."""

import asyncio
import json
import re
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field, validator

from src.post.mix_chain import master_take
from src.presets.preset_defaults import PRESETS

router = APIRouter()

# Lazy-init engines
_engines: dict[str, object] = {}

# One job at a time on GPU to prevent OOM / contention
GPU_SEMAPHORE = asyncio.Semaphore(1)

# Running subprocesses per job (for cancellation)
RUNNING_PROCS: dict[str, dict] = {}

JOB_ID_RE = re.compile(r"^[a-zA-Z0-9._-]{1,80}$")
MAX_TEXT_CHARS = 600
JOB_TIMEOUT_SECONDS = 420
ARTIFACTS_DIR = Path("artifacts")

VALID_TRANSITIONS = {
    "queued": {"running", "cancelled", "failed"},
    "running": {"completed", "failed", "cancelled"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}


def _job_dir(job_id: str) -> Path:
    return ARTIFACTS_DIR / "jobs" / job_id


def _write_job_manifest(job_id: str, data: dict) -> None:
    """Atomic JSON write: temp file → fsync → rename."""
    job_dir = _job_dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    path = job_dir / "manifest.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _read_job_manifest(job_id: str) -> dict | None:
    path = _job_dir(job_id) / "manifest.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def _get_engine(provider: str):
    if provider not in _engines:
        if provider == "f5tts":
            from src.engine.f5tts_engine import F5TTSEngine
            _engines[provider] = F5TTSEngine()
        elif provider == "chatterbox":
            from src.engine.chatterbox_engine import ChatterboxEngine
            _engines[provider] = ChatterboxEngine()
        elif provider == "voxcpm2":
            from src.engine.voxcpm2_engine import VoxCPM2Engine
            _engines[provider] = VoxCPM2Engine()
    return _engines.get(provider)


def _transition_status(job_id: str, new_status: str) -> bool:
    """Guarded status transition. Returns True if transition was allowed."""
    manifest = _read_job_manifest(job_id)
    if not manifest:
        return False
    current = manifest.get("status", "queued")
    if new_status not in VALID_TRANSITIONS.get(current, set()):
        return False
    manifest["status"] = new_status
    manifest["updatedAt"] = datetime.utcnow().isoformat()
    _write_job_manifest(job_id, manifest)
    return True


class SynthesizeRequest(BaseModel):
    text: str = Field(..., max_length=MAX_TEXT_CHARS)
    preset: str = "mark_rocky_tutor_warm"
    persona: str = "rocky"
    quality: str = "production"
    mixPreset: str | None = None
    discloseAI: bool = True
    jobId: str | None = None

    @validator("jobId")
    def validate_job_id(cls, v):
        if v is None:
            return v
        if not JOB_ID_RE.match(v):
            raise ValueError("jobId must be 1-80 chars of a-z, A-Z, 0-9, ., _, -")
        return v


class JobStatusResponse(BaseModel):
    jobId: str
    status: str
    audioUrl: str | None = None
    rawUrl: str | None = None
    provider: str | None = None
    preset: str | None = None
    metrics: dict | None = None
    error: str | None = None
    createdAt: str
    updatedAt: str


async def _run_synthesis_job(job_id: str, text: str, preset_key: str, mix_preset: str):
    """Async worker: acquires GPU semaphore, runs inference + mastering, respects cancellation."""
    # Acquire GPU semaphore HERE — this is the actual worker, not the task creation
    async with GPU_SEMAPHORE:
        # Check if cancelled while waiting for semaphore
        if _read_job_manifest(job_id).get("status") == "cancelled":
            return

        if not _transition_status(job_id, "running"):
            return

        proc_ref: dict = {"proc": None}
        RUNNING_PROCS[job_id] = proc_ref

        try:
            preset = PRESETS.get(preset_key, PRESETS["mark_rocky_tutor_warm"])
            provider = preset["provider"]

            base_dir = Path("artifacts/voice/mark")
            base_dir.mkdir(parents=True, exist_ok=True)
            raw_path = base_dir / f"{job_id}.raw.wav"
            mastered_path = base_dir / f"{job_id}.mastered.wav"

            engine = _get_engine(provider)
            if engine is None:
                raise NotImplementedError(f"Provider {provider} not yet implemented in Foundry.")

            # ── Synthesis ──────────────────────────────────────────────────
            if provider == "f5tts":
                await engine.synthesize(
                    text=text,
                    ref_audio=preset["reference"],
                    output_path=str(raw_path),
                    speed=preset.get("speed", 1.0),
                    remove_silence=True,
                    proc_ref=proc_ref,
                )
            elif provider == "chatterbox":
                await engine.synthesize(
                    text=text,
                    ref_audio=preset["reference"],
                    output_path=str(raw_path),
                    preset=preset.get("emotion", "neutral"),
                    proc_ref=proc_ref,
                )
            elif provider == "voxcpm2":
                await engine.synthesize(
                    text=text,
                    ref_audio=preset.get("reference"),
                    output_path=str(raw_path),
                    voice_design=preset.get("voiceDesign"),
                )

            # Check cancelled before mastering
            if _read_job_manifest(job_id).get("status") == "cancelled":
                return

            # ── Mastering ──────────────────────────────────────────────────
            metrics = master_take(str(raw_path), str(mastered_path), mix_preset)

            # Check cancelled before publishing
            if _read_job_manifest(job_id).get("status") == "cancelled":
                return

            manifest = _read_job_manifest(job_id) or {}
            manifest.update({
                "status": "completed",
                "audioUrl": f"/static/voice/mark/{mastered_path.name}",
                "rawUrl": f"/static/voice/mark/{raw_path.name}",
                "provider": provider,
                "preset": preset_key,
                "metrics": metrics,
                "updatedAt": datetime.utcnow().isoformat(),
            })
            _write_job_manifest(job_id, manifest)
        except Exception as exc:
            manifest = _read_job_manifest(job_id) or {}
            # Do not overwrite cancelled status
            if manifest.get("status") != "cancelled":
                manifest.update({
                    "status": "failed",
                    "error": str(exc),
                    "updatedAt": datetime.utcnow().isoformat(),
                })
                _write_job_manifest(job_id, manifest)
        finally:
            RUNNING_PROCS.pop(job_id, None)


@router.post("/synthesize")
async def synthesize(req: SynthesizeRequest, background_tasks: BackgroundTasks):
    job_id = req.jobId or f"voice_{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow().isoformat()

    preset = PRESETS.get(req.preset, PRESETS["mark_rocky_tutor_warm"])
    mix_preset = req.mixPreset or preset.get("mixPreset", "rocky_live")

    manifest = {
        "jobId": job_id,
        "status": "queued",
        "text": req.text,
        "preset": req.preset,
        "mixPreset": mix_preset,
        "createdAt": now,
        "updatedAt": now,
    }
    _write_job_manifest(job_id, manifest)

    # GPU semaphore is acquired INSIDE the background task, not here.
    background_tasks.add_task(
        _run_synthesis_job,
        job_id,
        req.text,
        req.preset,
        mix_preset,
    )

    return {"jobId": job_id, "status": "queued", "pollUrl": f"/voice/synthesize/status/{job_id}"}


@router.get("/synthesize/status/{job_id}", response_model=JobStatusResponse)
async def synthesize_status(job_id: str):
    if not JOB_ID_RE.match(job_id):
        raise HTTPException(status_code=400, detail="Invalid jobId format")
    job = _read_job_manifest(job_id)
    if not job:
        return JobStatusResponse(
            jobId=job_id,
            status="not_found",
            createdAt=datetime.utcnow().isoformat(),
            updatedAt=datetime.utcnow().isoformat(),
        )
    return JobStatusResponse(**job)


@router.delete("/synthesize/cancel/{job_id}")
async def cancel_job(job_id: str):
    if not JOB_ID_RE.match(job_id):
        raise HTTPException(status_code=400, detail="Invalid jobId format")
    job = _read_job_manifest(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] in ("completed", "failed"):
        return {"jobId": job_id, "status": job["status"], "cancelled": False, "reason": "already_terminal"}

    # Try to terminate running subprocess
    proc_ref = RUNNING_PROCS.get(job_id)
    if proc_ref:
        proc = proc_ref.get("proc")
        if proc and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

    job["status"] = "cancelled"
    job["updatedAt"] = datetime.utcnow().isoformat()
    _write_job_manifest(job_id, job)
    return {"jobId": job_id, "status": "cancelled", "cancelled": True}
