"""FastAPI application for Mindsong Voice Foundry."""

import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

logger = logging.getLogger("voice_foundry")

# ── Auth: mandatory by default ──────────────────────────────────────────────
VOICE_FOUNDRY_TOKEN = os.environ.get("VOICE_FOUNDRY_TOKEN")
ALLOW_NO_TOKEN = os.environ.get("VOICE_FOUNDRY_DEV_ALLOW_NO_TOKEN") == "1"
ENV = os.environ.get("VOICE_FOUNDRY_ENV", "dev")

if not VOICE_FOUNDRY_TOKEN:
    if ALLOW_NO_TOKEN and ENV == "dev":
        logger.warning(
            "VOICE FOUNDRY RUNNING WITHOUT TOKEN — DEV MODE ONLY"
        )
    else:
        print(
            "\n[FATAL] VOICE_FOUNDRY_TOKEN is required.\n"
            "Set VOICE_FOUNDRY_ENV=dev and VOICE_FOUNDRY_DEV_ALLOW_NO_TOKEN=1 "
            "only for local throwaway dev.\n",
            file=sys.stderr,
        )
        sys.exit(1)

# Default dev origins; override with VOICE_FOUNDRY_ORIGINS=comma,separated,list
DEFAULT_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:4173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:4173",
]
_origins_env = os.environ.get("VOICE_FOUNDRY_ORIGINS")
ALLOWED_ORIGINS = _origins_env.split(",") if _origins_env else DEFAULT_ORIGINS

APP_DIR = Path(__file__).resolve().parent.parent.parent
ARTIFACTS_DIR = APP_DIR / "artifacts"
ARTIFACTS_DIR.mkdir(exist_ok=True)

from .routes import synthesize, master, presets, qc, health, bakeoff  # noqa: E402

app = FastAPI(
    title="Mindsong Voice Foundry",
    description="Production voice clone inference + mastering service",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-Voice-Foundry-Token"],
)


@app.middleware("http")
async def token_auth_middleware(request: Request, call_next):
    """Require token on all routes except root docs and health."""
    # Allow CORS preflight through without token (CORS middleware handles it)
    if request.method == "OPTIONS":
        return await call_next(request)

    if request.url.path in ("/", "/docs", "/openapi.json", "/voice/health"):
        return await call_next(request)

    # When token is configured, enforce it
    if VOICE_FOUNDRY_TOKEN:
        token = request.headers.get("X-Voice-Foundry-Token")
        if token != VOICE_FOUNDRY_TOKEN:
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized — set X-Voice-Foundry-Token header"},
            )

    return await call_next(request)


# Serve generated artifacts so the browser runtime can fetch mastered audio
app.mount("/static", StaticFiles(directory=str(ARTIFACTS_DIR)), name="static")

app.include_router(synthesize.router, prefix="/voice", tags=["Synthesize"])
app.include_router(master.router, prefix="/voice", tags=["Master"])
app.include_router(presets.router, prefix="/voice", tags=["Presets"])
app.include_router(qc.router, prefix="/voice", tags=["QC"])
app.include_router(health.router, prefix="/voice", tags=["Health"])
app.include_router(bakeoff.router, prefix="/voice", tags=["Bakeoff"])


@app.get("/")
async def root():
    return {"service": "mindsong-voice-foundry", "version": "0.1.0"}
