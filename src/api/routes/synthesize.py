"""Voice synthesis endpoint with async job queue."""

import asyncio
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from src.engine.f5tts_engine import F5TTSEngine
from src.post.mix_chain import master_take
from src.presets.preset_defaults import PRESETS

router = APIRouter()

# Lazy-init engine
_f5_engine = None

# In-memory job store (replace with Redis for multi-worker)
_jobs: dict[str, dict] = {}


def get_f5_engine():
    global _f5_engine
    if _f5_engine is None:
        _f5_engine = F5TTSEngine()
    return _f5_engine


class SynthesizeRequest(BaseModel):
    text: str
    preset: str = "mark_rocky_tutor_warm"
    persona: str = "rocky"
    quality: str = "production"
    mixPreset: str | None = None
    discloseAI: bool = True
    jobId: str | None = None


class JobStatusResponse(BaseModel):
    jobId: str
    status: str  # queued | running | completed | failed
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
    try:
        _jobs[job_id]["status"] = "running"
        _jobs[job_id]["updatedAt"] = datetime.utcnow().isoformat()

        preset = PRESETS.get(preset_key, PRESETS["mark_rocky_tutor_warm"])
        provider = preset["provider"]

        base_dir = Path("artifacts/voice/mark")
        base_dir.mkdir(parents=True, exist_ok=True)
        raw_path = base_dir / f"{job_id}.raw.wav"
        mastered_path = base_dir / f"{job_id}.mastered.wav"

        if provider == "f5tts":
            engine = get_f5_engine()
            ref_audio = preset["reference"]
            # f5tts_engine.synthesize is async; run it in a fresh event loop inside the thread
            asyncio.run(
                engine.synthesize(
                    text=text,
                    ref_audio=ref_audio,
                    output_path=str(raw_path),
                    speed=preset.get("speed", 1.0),
                    remove_silence=True,
                )
            )
        else:
            raise NotImplementedError(f"Provider {provider} not yet implemented in Foundry.")

        metrics = master_take(str(raw_path), str(mastered_path), mix_preset)

        _jobs[job_id].update({
            "status": "completed",
            "audioUrl": f"/static/voice/mark/{mastered_path.name}",
            "rawUrl": f"/static/voice/mark/{raw_path.name}",
            "provider": provider,
            "preset": preset_key,
            "metrics": metrics,
            "updatedAt": datetime.utcnow().isoformat(),
        })
    except Exception as exc:
        _jobs[job_id].update({
            "status": "failed",
            "error": str(exc),
            "updatedAt": datetime.utcnow().isoformat(),
        })


@router.post("/synthesize")
async def synthesize(req: SynthesizeRequest, background_tasks: BackgroundTasks):
    job_id = req.jobId or f"voice_{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow().isoformat()

    preset = PRESETS.get(req.preset, PRESETS["mark_rocky_tutor_warm"])
    mix_preset = req.mixPreset or preset.get("mixPreset", "rocky_live")

    _jobs[job_id] = {
        "jobId": job_id,
        "status": "queued",
        "createdAt": now,
        "updatedAt": now,
    }

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
    job = _jobs.get(job_id)
    if not job:
        return JobStatusResponse(
            jobId=job_id,
            status="not_found",
            createdAt=datetime.utcnow().isoformat(),
            updatedAt=datetime.utcnow().isoformat(),
        )
    return JobStatusResponse(**job)
