"""Voice synthesis endpoint with async job queue — multi-engine, hardened."""

import asyncio
import json
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field, validator

from src.api.utils import validate_safe_id
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


def write_json_atomic(path: Path, data: dict) -> None:
    """Atomic JSON write: temp file → fsync → rename → dir fsync."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(data, indent=2, default=str, sort_keys=True)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    dir_fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _write_job_manifest(job_id: str, data: dict) -> None:
    write_json_atomic(_job_dir(job_id) / "manifest.json", data)


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


def _transition_status(job_id: str, new_status: str, patch: dict | None = None) -> bool:
    """Guarded status transition. Returns True if transition was allowed."""
    manifest = _read_job_manifest(job_id)
    if not manifest:
        return False
    current = manifest.get("status", "queued")
    if new_status not in VALID_TRANSITIONS.get(current, set()):
        return False
    manifest["status"] = new_status
    manifest["updatedAt"] = datetime.utcnow().isoformat()
    if patch:
        manifest.update(patch)
    _write_job_manifest(job_id, manifest)
    return True


def _mark_failed(job_id: str, reason: str, timing: dict | None = None) -> None:
    manifest = _read_job_manifest(job_id) or {}
    if manifest.get("status") == "cancelled":
        return
    update = {
        "status": "failed",
        "error": reason,
        "updatedAt": datetime.utcnow().isoformat(),
    }
    if timing:
        update["timing"] = timing
    manifest.update(update)
    _write_job_manifest(job_id, manifest)


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
    timing: dict | None = None
    error: str | None = None
    createdAt: str
    updatedAt: str


async def _do_synthesis(
    job_id: str, text: str, preset_key: str, mix_preset: str,
    t0: float,
) -> dict:
    """Inner worker: acquires GPU semaphore, runs inference + mastering.
    Returns timing dict for the caller to use on failure."""
    timing: dict = {"submittedMs": round(t0 * 1000)}
    async with GPU_SEMAPHORE:
        # Check if cancelled while waiting for semaphore
        if _read_job_manifest(job_id).get("status") == "cancelled":
            return timing

        if not _transition_status(job_id, "running"):
            return timing

        t_running = time.time()
        timing["startedMs"] = round(t_running * 1000)
        proc_ref: dict = {"proc": None}
        RUNNING_PROCS[job_id] = proc_ref
        t_synth_start = None
        t_master_start = None

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
            t_synth_start = time.time()
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
                # VoxCPM2 runs in-thread; cooperative (soft) cancel only
                await engine.synthesize(
                    text=text,
                    ref_audio=preset.get("reference"),
                    output_path=str(raw_path),
                    voice_design=preset.get("voiceDesign"),
                )

            # Check cancelled before mastering
            if _read_job_manifest(job_id).get("status") == "cancelled":
                return timing

            t_master_start = time.time()
            # ── Mastering ──────────────────────────────────────────────────
            metrics = master_take(str(raw_path), str(mastered_path), mix_preset)

            # Check cancelled before publishing
            if _read_job_manifest(job_id).get("status") == "cancelled":
                return timing

            t_done = time.time()
            timing.update({
                "synthesisMs": round((t_master_start - t_synth_start) * 1000),
                "masteringMs": round((t_done - t_master_start) * 1000),
                "totalMs": round((t_done - t0) * 1000),
            })
            patch = {
                "audioUrl": f"/static/voice/mark/{mastered_path.name}",
                "rawUrl": f"/static/voice/mark/{raw_path.name}",
                "provider": provider,
                "preset": preset_key,
                "metrics": metrics,
                "timing": timing,
            }
            _transition_status(job_id, "completed", patch)
        except Exception as exc:
            t_done = time.time()
            timing["totalMs"] = round((t_done - t0) * 1000)
            _mark_failed(job_id, str(exc), timing)
        finally:
            RUNNING_PROCS.pop(job_id, None)
    return timing


async def _run_synthesis_job(job_id: str, text: str, preset_key: str, mix_preset: str):
    """Async worker with timeout wrapper."""
    t0 = time.time()
    try:
        await asyncio.wait_for(
            _do_synthesis(job_id, text, preset_key, mix_preset, t0),
            timeout=JOB_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        t_done = time.time()
        _mark_failed(job_id, f"Job exceeded {JOB_TIMEOUT_SECONDS}s timeout", {
            "submittedMs": round(t0 * 1000),
            "totalMs": round((t_done - t0) * 1000),
        })
        proc_ref = RUNNING_PROCS.pop(job_id, None)
        if proc_ref:
            proc = proc_ref.get("proc")
            if proc and proc.returncode is None:
                proc.kill()
                await proc.wait()


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

    # GPU semaphore is acquired INSIDE the background task worker.
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

    # Try to terminate running work (subprocess for F5/Chatterbox, event for VoxCPM2)
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
        # VoxCPM2 cooperative cancellation
        cancel_fn = proc_ref.get("cancel")
        if cancel_fn:
            cancel_fn()

    _transition_status(job_id, "cancelled")
    return {"jobId": job_id, "status": "cancelled", "cancelled": True}
