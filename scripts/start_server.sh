#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PORT="${VOICE_FOUNDRY_PORT:-8788}"
HOST="${VOICE_FOUNDRY_HOST:-127.0.0.1}"

echo "Starting MindSong Voice Foundry on ${HOST}:${PORT}..."
python -m uvicorn src.api.server:app --host "$HOST" --port "$PORT" --reload
