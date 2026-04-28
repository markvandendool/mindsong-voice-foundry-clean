"""FastAPI application for Mindsong Voice Foundry."""

import os
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from .routes import synthesize, master, presets, qc, health, bakeoff

APP_DIR = Path(__file__).resolve().parent.parent.parent
ARTIFACTS_DIR = APP_DIR / "artifacts"
ARTIFACTS_DIR.mkdir(exist_ok=True)

# Local auth token — set VOICE_FOUNDRY_TOKEN env var to enforce
VOICE_FOUNDRY_TOKEN = os.environ.get("VOICE_FOUNDRY_TOKEN")
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
    if VOICE_FOUNDRY_TOKEN and request.url.path not in ("/", "/docs", "/openapi.json"):
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
