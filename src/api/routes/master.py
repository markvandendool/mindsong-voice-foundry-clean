"""Mastering endpoint — jobId-based, path-confined."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.api.utils import resolve_job_artifact, validate_safe_id
from src.post.mix_chain import master_take

router = APIRouter()


class MasterRequest(BaseModel):
    model_config = {"extra": "forbid"}

    jobId: str
    artifact: str = Field(default="raw", pattern=r"^(raw|mastered)$")
    mixPreset: str = "skybeam_youtube"


class MasterResponse(BaseModel):
    jobId: str
    outputPath: str
    metrics: dict


@router.post("/master", response_model=MasterResponse)
async def master(req: MasterRequest):
    # Reject legacy raw-path keys if present
    if hasattr(req, "inputPath") or hasattr(req, "outputPath"):
        raise HTTPException(status_code=410, detail="Legacy path-based API removed. Use jobId + artifact.")

    validate_safe_id(req.jobId, "jobId")
    input_path = resolve_job_artifact(req.jobId, req.artifact)

    if not input_path.exists():
        raise HTTPException(status_code=404, detail=f"Artifact not found: {input_path.name}")

    output_path = resolve_job_artifact(req.jobId, "mastered")

    metrics = master_take(str(input_path), str(output_path), req.mixPreset)
    return MasterResponse(jobId=req.jobId, outputPath=str(output_path), metrics=metrics)
