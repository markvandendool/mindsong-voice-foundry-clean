"""Voice synthesis endpoint with async job queue — multi-engine, hardened."""

import asyncio
import json
import re
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field, validator

from src.engine.f5tts_engine import F5TTSEngine
from src.engine.chatterbox_engine import ChatterboxEngine
from src.engine.voxcpm2_engine import VoxCPM2Engine
from src.post.mix_chain import master_take
from src.presets.preset_defaults import PRESETS

router = APIRouter()

# Lazy-init engines
_engines: dict[str, object] = {}

# One job at a time on GPU to prevent OOM / contention
GPU_SEMAPHORE = asyncio.Semaphore(1)

JOB_ID_RE = re.compile(r"^[a-zA-Z0-9._-]{1,80}$")
MAX_TEXT_CHARS = 600
JOB_TIMEOUT_SECONDS = 420
ARTIFACTS_DIR = Path("artifacts")


def _job_dir(job_id: str) -> Path:
    return ARTIFACTS_DIR / "jobs" / job_id


def _write_job_manifest(job_id: str, data: dict) -> None:
    job_dir = _job_dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "manifest.json").write_text(json.dumps(data, indent=2, default=str))


def _read_job_manifest(job_id: str) -> dict | None:
    path = _job_dir(job_id) / "manifest.json"
    if path.exists():
        return json.loads(path.read_text())
    return None


def _get_engine(provider: str):
    if provider not in _engines:
        if provider == "f5tts":
            _engines[provider] = F5TTSEngine()
        elif provider == "chatterbox":
            _engines[provider] = ChatterboxEngine()
        elif provider == "voxcpm2":
            _engines[provider] = VoxCPM2Engine()
    return _engines.get(provider)


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


def _run_synthesis_job(job_id: str, text: str, preset_key: str, mix_preset: str):
    """Blocking worker for background synthesis + mastering."""
    now = datetime.utcnow().isoformat()
    manifest = {
        "jobId": job_id,
        "status": "running",
        "text": text,
        "preset": preset_key,
        "mixPreset": mix_preset,
        "updatedAt": now,
    }
    _write_job_manifest(job_id, manifest)

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

        if provider == "f5tts":
            asyncio.run(
                engine.synthesize(
                    text=text,
                    ref_audio=preset["reference"],
                    output_path=str(raw_path),
                    speed=preset.get("speed", 1.0),
                    remove_silence=True,
                )
            )
        elif provider == "chatterbox":
            asyncio.run(
                engine.synthesize(
                    text=text,
                    ref_audio=preset["reference"],
                    output_path=str(raw_path),
                    preset=preset.get("emotion", "neutral"),
                )
            )
        elif provider == "voxcpm2":
            asyncio.run(
                engine.synthesize(
                    text=text,
                    ref_audio=preset.get("reference"),
                    output_path=str(raw_path),
                    voice_design=preset.get("voiceDesign"),
                )
            )

        metrics = master_take(str(raw_path), str(mastered_path), mix_preset)

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
        manifest.update({
            "status": "failed",
            "error": str(exc),
            "updatedAt": datetime.utcnow().isoformat(),
        })
        _write_job_manifest(job_id, manifest)


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

    async with GPU_SEMAPHORE:
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
    job["status"] = "cancelled"
    job["updatedAt"] = datetime.utcnow().isoformat()
    _write_job_manifest(job_id, job)
    return {"jobId": job_id, "status": "cancelled", "cancelled": True}
