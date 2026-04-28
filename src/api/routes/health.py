"""Health check endpoint — cheap, no heavy imports."""

import importlib.util
import os
import platform
import subprocess
from pathlib import Path

from fastapi import APIRouter

from src.engine.chatterbox_engine import CHATTERBOX_VENV_PYTHON

router = APIRouter()


def _engine_available(provider: str) -> bool:
    if provider == "f5tts":
        return True  # Always available via CLI
    if provider == "chatterbox":
        return CHATTERBOX_VENV_PYTHON.exists()
    if provider == "voxcpm2":
        return importlib.util.find_spec("voxcpm") is not None
    return False


def _gpu_info() -> tuple[bool, str | None, str]:
    """Lightweight GPU probe without importing torch."""
    if platform.system() == "Darwin":
        # Check for Apple Silicon MPS via system_profiler
        try:
            result = subprocess.run(
                ["system_profiler", "SPDisplaysDataType", "-json"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and "Apple" in result.stdout:
                return True, "Apple Silicon MPS", "mps"
        except Exception:
            pass
    # Fallback: try to detect CUDA via nvidia-smi
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            name = result.stdout.strip().splitlines()[0]
            return True, name, "cuda"
    except Exception:
        pass
    return False, None, "cpu"


VOICE_FOUNDRY_TOKEN = os.environ.get("VOICE_FOUNDRY_TOKEN")
ALLOW_NO_TOKEN = os.environ.get("VOICE_FOUNDRY_DEV_ALLOW_NO_TOKEN") == "1"
ENV = os.environ.get("VOICE_FOUNDRY_ENV", "dev")


@router.get("/health")
async def health():
    gpu_available, gpu_name, gpu_device = _gpu_info()
    return {
        "status": "healthy",
        "gpuAvailable": gpu_available,
        "gpuName": gpu_name,
        "gpuDevice": gpu_device,
        "engines": {
            "f5tts": _engine_available("f5tts"),
            "chatterbox": _engine_available("chatterbox"),
            "voxcpm2": _engine_available("voxcpm2"),
        },
        "auth": {
            "authRequired": bool(VOICE_FOUNDRY_TOKEN),
            "devAuthBypass": ALLOW_NO_TOKEN and ENV == "dev",
            "releaseSafe": bool(VOICE_FOUNDRY_TOKEN) and not ALLOW_NO_TOKEN,
        },
        "bindHost": "127.0.0.1",
        "modelsLoaded": {},
        "cacheSize": 0,
    }


@router.get("/engines/probe")
async def engines_probe():
    """Heavy probe: actually imports torch/voxcpm to verify they load."""
    results = {}
    try:
        import torch
        results["torch"] = {
            "available": True,
            "cuda": torch.cuda.is_available(),
            "mps": torch.backends.mps.is_available(),
        }
    except Exception as exc:
        results["torch"] = {"available": False, "error": str(exc)}

    try:
        import voxcpm
        results["voxcpm"] = {"available": True}
    except Exception as exc:
        results["voxcpm"] = {"available": False, "error": str(exc)}

    return {"engines": results}
