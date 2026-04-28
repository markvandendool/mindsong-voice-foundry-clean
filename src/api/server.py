"""FastAPI application for Mindsong Voice Foundry."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routes import synthesize, master, presets, qc, health

APP_DIR = Path(__file__).resolve().parent.parent.parent
ARTIFACTS_DIR = APP_DIR / "artifacts"
ARTIFACTS_DIR.mkdir(exist_ok=True)

app = FastAPI(
    title="Mindsong Voice Foundry",
    description="Production voice clone inference + mastering service",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve generated artifacts so the browser runtime can fetch mastered audio
app.mount("/static", StaticFiles(directory=str(ARTIFACTS_DIR)), name="static")

app.include_router(synthesize.router, prefix="/voice", tags=["Synthesize"])
app.include_router(master.router, prefix="/voice", tags=["Master"])
app.include_router(presets.router, prefix="/voice", tags=["Presets"])
app.include_router(qc.router, prefix="/voice", tags=["QC"])
app.include_router(health.router, tags=["Health"])


@app.get("/")
async def root():
    return {"service": "mindsong-voice-foundry", "version": "0.1.0"}
