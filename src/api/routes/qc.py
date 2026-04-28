"""QC scan endpoint — jobId-based, duration-aware."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.api.utils import resolve_job_artifact, validate_safe_id
from src.post.mix_chain import measure_loudness, get_duration

router = APIRouter()


class QCRequest(BaseModel):
    model_config = {"extra": "forbid"}

    jobId: str
    artifact: str = Field(default="mastered", pattern=r"^(raw|mastered)$")


class QCResponse(BaseModel):
    jobId: str
    artifact: str
    durationSec: float
    deliveryQc: dict
    voiceQc: dict
    publishable: bool


@router.post("/qc", response_model=QCResponse)
async def qc_scan(req: QCRequest):
    # Reject legacy raw-path key if present
    if hasattr(req, "audioPath"):
        raise HTTPException(status_code=410, detail="Legacy path-based API removed. Use jobId + artifact.")

    validate_safe_id(req.jobId, "jobId")
    audio_path = resolve_job_artifact(req.jobId, req.artifact)

    if not audio_path.exists():
        raise HTTPException(status_code=404, detail=f"Artifact not found: {audio_path.name}")

    metrics = measure_loudness(str(audio_path))
    duration_sec = get_duration(str(audio_path))

    # Duration-aware LRA policy
    if duration_sec < 6:
        min_lra = 0.0
        lra_severity = "info"
    elif duration_sec < 15:
        min_lra = 1.0
        lra_severity = "warn"
    else:
        min_lra = 2.0
        lra_severity = "fail"

    delivery_issues = []
    if metrics.get("integrated_lufs", 0) > -10:
        delivery_issues.append("Too loud: integrated LUFS > -10")
    if metrics.get("true_peak_db", 0) > -0.5:
        delivery_issues.append("True peak too high: > -0.5 dB")
    if metrics.get("lra", 100) < min_lra:
        delivery_issues.append(f"Loudness range too narrow: < {min_lra} LU ({lra_severity})")

    delivery_pass = len(delivery_issues) == 0

    delivery_qc = {
        "pass": delivery_pass,
        "issues": delivery_issues,
        "metrics": metrics,
        "durationSec": duration_sec,
        "lraPolicy": {"minLra": min_lra, "severity": lra_severity},
    }

    voice_qc = {
        "speakerSimilarity": None,
        "intelligibility": None,
        "artifacting": None,
        "creepiness": None,
        "humanReviewRequired": True,
        "pass": False,
    }

    return QCResponse(
        jobId=req.jobId,
        artifact=req.artifact,
        durationSec=duration_sec,
        deliveryQc=delivery_qc,
        voiceQc=voice_qc,
        publishable=False,
    )
