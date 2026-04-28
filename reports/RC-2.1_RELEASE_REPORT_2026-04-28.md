# Voice Foundry RC-2.1 Release Report

**Date:** 2026-04-28  
**Build:** `mindsong-voice-foundry` (Python 3.12 + FastAPI)  
**Runtime:** uvicorn on `127.0.0.1:8788`  
**Token:** configured, redacted  
**GPU:** Apple Silicon MPS (1-inference-at-a-time semaphore)

---

## Executive Summary

RC-2.1 addresses **all 6 release blockers** identified by Chief in the RC-2 assessment:

1. **Leaked token rotated and scrubbed** — new token generated, old token revoked, reports redacted
2. **CORS preflight fixed** — OPTIONS requests exempt from token auth middleware; browser calls with `X-Voice-Foundry-Token` now work
3. **FFmpeg timeout added** — all `subprocess.run()` calls in `mix_chain.py` have `timeout` parameter (120s for ffmpeg, 60s for loudness probe, 30s for ffprobe)
4. **VoxCPM2 cooperative (soft) cancellation** — `threading.Event` cancellation flag passed through `proc_ref`; cancel endpoint triggers event; thread checks flag before writing output. **Important:** This prevents cancelled jobs from publishing artifacts, but does NOT kill the running `model.generate()` thread. True hard-kill requires subprocess isolation (planned for GA / RC-2.2).
5. **F5 CLI path resolution** — `_resolve_f5_cli()` finds `f5-tts_infer-cli` in PATH or falls back to venv bin directory; fixes "No such file or directory" failure when server runs without activated venv
6. **TypeScript singleton tests fixed** — `resetRouterProviders()` now re-instantiates ALL providers and resets muted state; 2 previously skipped tests now pass

**Status: RC-2.1 is READY FOR HUMAN AUDIO REVIEW.**

---

## Chief's Blockers → Fixes

| Blocker | Severity | Fix | Evidence |
|---|---|---|---|
| Active token in RC-2 report | **RELEASE-BLOCKING** | New token generated via `openssl rand -hex 32`; old token returns 401; report scrubbed | `curl -H "X-Voice-Foundry-Token: <old>" → 401` |
| CORS preflight returns 401 | **RELEASE-BLOCKING** | Token middleware exempts `OPTIONS` before path checks | `curl -X OPTIONS -H "Origin: http://localhost:5173" → 200` |
| FFmpeg no timeout | **RELEASE-BLOCKING** | `_run_ffmpeg(timeout=120)`, `measure_loudness(timeout=60)`, `get_duration(timeout=30)` | `src/post/mix_chain.py` |
| VoxCPM2 thread cannot be killed | **RELEASE-BLOCKING** | `cancel_event: threading.Event` in `VoxCPM2Engine`; cancel endpoint calls `proc_ref["cancel"]()`; thread checks `cancel_event.is_set()` before writing | `src/engine/voxcpm2_engine.py` |
| F5 CLI not found (venv PATH) | **RELEASE-BLOCKING** | `_resolve_f5_cli()` uses `shutil.which()` with fallback to `sys.executable` parent dir | `src/engine/f5tts_engine.py` |
| 2 skipped TS singleton tests | **RELEASE-BLOCKING** | `resetRouterProviders()` re-instantiates all 4 providers + `router.setMuted(false)` | `bun test → 17 pass, 0 skip, 0 fail` |

---

## Test Results

### Python Tests (20/20 passing)
```
20 passed, 20 warnings in 112.21s
```

### TypeScript Tests (17/17 passing, 0 skipped)
```
17 pass, 0 fail, Ran 17 tests across 2 files
```

| Test | Status |
|---|---|
| prefers f5tts when available in auto mode | PASS |
| falls back from f5tts to mcp when f5tts unavailable | PASS |
| falls back to elevenlabs when f5tts and mcp unavailable | PASS |
| falls back through full chain: f5tts→mcp→elevenlabs→webSpeech | PASS |
| only one provider speaks per request | PASS |
| muted state prevents all speech requests | PASS |
| queues long messages into multiple chunks | **PASS** (was skip) |
| does not allow recursive speak via rocky:speak event | PASS |
| falls back after f5tts speak throws | **PASS** (was skip) |
| synthesizes and plays MCP audio without throwing | PASS |
| VoiceFoundryClient sends X-Voice-Foundry-Token header | PASS |
| F5TTSProvider stop() pauses audio and resets state | PASS |
| includes token header in all requests | PASS |
| does not include token header when token is empty | PASS |
| cancelJob sends DELETE request | PASS |
| synthesizeAsync passes AbortSignal to fetch | PASS |
| pollJob passes AbortSignal to fetch | PASS |

---

## Fresh RC-2.1 Artifacts

### F5-TTS — `rc21_f5_fix_001`
- **Text:** "RockyAI tutor is online and ready to help you learn music theory."
- **Preset:** `mark_rocky_tutor_warm`
- **Provider:** f5tts
- **Mix Preset:** rocky_live
- **Format:** 48kHz, 16-bit PCM, mono
- **Duration:** 3.02s
- **LUFS:** -18.18 (target: -18) ✅
- **True Peak:** -2.0 dB ✅
- **LRA:** 0.3 (info — <6s)
- **SHA-256:** `dd5f9af372356750119acc1dc9ef2e6c1d651962ce7c44390c043f9a6d87b669`
- **Delivery QC:** ✅ PASS
- **Voice QC:** ⏳ human review required
- **Publishable:** ❌ No (pending human review)
- **Timing:** synthesis 35.3s, mastering 0.18s, total 35.5s

### VoxCPM2 — `rc21_vx_1777380528`
- **Text:** "RockyAI tutor is online and ready to help you learn music theory."
- **Preset:** `mark_voxcpm2_clone`
- **Provider:** voxcpm2
- **Mix Preset:** film_dialogue
- **Format:** 48kHz, 16-bit PCM, mono
- **Duration:** 5.10s
- **LUFS:** -24.65 (target: -23)
- **True Peak:** -7.77 dB
- **LRA:** 3.8 (info — <6s)
- **SHA-256:** `b2392c2ce79feadd32154ea8308bae71c26096657153a7804fd26b20336657a8`
- **Delivery QC:** ✅ PASS
- **Voice QC:** ⏳ human review required
- **Publishable:** ❌ No (pending human review)
- **Timing:** total ~75s (synthesis + mastering)

---

## Security Posture (Verified Live)

| Probe | Expected | Result |
|---|---|---|
| No token on `/voice/presets` | 401 Unauthorized | ✅ |
| Old leaked token on `/voice/presets` | 401 Unauthorized | ✅ |
| Valid token on `/voice/presets` | 200 OK | ✅ |
| CORS OPTIONS preflight | 200 OK | ✅ |
| Path traversal bakeoffId `../../evil` | 400/422 Bad Request | ✅ 422 |
| Legacy QC with `audioPath` | 422 Unprocessable Entity | ✅ |

---

## Code Changes Since RC-2

### `src/api/server.py`
- Added `OPTIONS` method exemption before path-based auth checks

### `src/post/mix_chain.py`
- `_run_ffmpeg()`: added `timeout=120.0`
- `measure_loudness()`: added `timeout=60.0`
- `get_duration()`: added `timeout=30.0`

### `src/engine/voxcpm2_engine.py`
- Added `cancel_event: threading.Event` to `synthesize()`
- `proc_ref` now carries `cancel_event` and `cancel` callback
- Thread checks `cancel_event.is_set()` before writing output
- `asyncio.wait_for` with 300s timeout on thread future

### `src/engine/f5tts_engine.py`
- Added `_resolve_f5_cli()` using `shutil.which()` + venv bin fallback
- Uses resolved full path instead of bare `"f5-tts_infer-cli"`

### `src/api/routes/synthesize.py`
- Cancel endpoint now calls `proc_ref.get("cancel")()` for VoxCPM2 cooperative cancellation

### `tests/unit/rocky-voice-router.test.ts`
- `resetRouterProviders()`: re-instantiates ALL 4 providers (not just MCP)
- `resetRouterProviders()`: calls `router.setMuted(false)`
- Unskipped chunking test with proper mock setup
- Unskipped fallback-after-throw test with proper mock setup

---

## Commander Verification (2026-04-28)

All required checks performed and passed:

| Check | Result |
|---|---|
| Secret scan — no plaintext token in reports/artifacts/logs | ✅ Clean |
| No-token `/voice/presets` → 401 | ✅ |
| Old leaked token → 401 | ✅ |
| Valid token → 200 | ✅ |
| CORS OPTIONS from allowed origin → 200 | ✅ |
| CORS OPTIONS from disallowed origin → 400 | ✅ |
| Path traversal → 422 | ✅ |
| Legacy `audioPath` → 422 | ✅ |
| Python tests 20/20 | ✅ |
| TypeScript tests 17/17, 0 skip | ✅ |
| ffprobe both WAVs: 48kHz PCM mono | ✅ |
| Hashes recorded | ✅ |

---

## Remaining Gates to GA

1. **Human Audio Review** — Listen to both mastered WAVs; fill `artifacts/human-review/human_score.json` from template; re-run QC to flip `publishable`
2. **Skybeam Integration** — Prove a Skybeam render job can consume Foundry audio
3. **Daemon / launchd** — Auto-start Foundry on boot (currently `uvicorn --reload` is dev-only)
4. **Interactive Latency** — F5 ~35s is fine for batch; needs caching for real-time Rocky
5. **Chatterbox** — Still ~100s/phrase; consider Mini-Omni or similar
6. **VoxCPM2 Hard Cancel** — Subprocess isolation for true process kill (cooperative cancel is RC-acceptable, not GA)
7. **Browser E2E Proof** — Real browser runtime with token, CSP, autoplay, fallback

---

## Quick Access

```bash
# Listen to fresh RC-2.1 artifacts
afplay ~/mindsong-voice-foundry/artifacts/voice/mark/rc21_f5_fix_001.mastered.wav
afplay ~/mindsong-voice-foundry/artifacts/voice/mark/rc21_vx_1777380528.mastered.wav

# Human review template
cat ~/mindsong-voice-foundry/artifacts/human-review/human_score.template.json

# Run test suites
cd ~/mindsong-voice-foundry && ~/mindsong-juke-hub/.venv-voice-m2/bin/python -m pytest tests/ -q
cd ~/mindsong-juke-hub && bun test ./tests/unit/rocky-voice-router.test.ts ./tests/unit/voice-foundry-client.test.ts

# Health + auth posture
curl -s http://127.0.0.1:8788/voice/health | python3 -m json.tool
```

---

**Report generated:** 2026-04-28 13:00 UTC  
**Service:** uvicorn with `--reload` on 127.0.0.1:8788 (RC posture)  
**RC-2.1 status:** ALL CODE-LEVEL BLOCKERS CLOSED — READY FOR HUMAN AUDIO REVIEW. NOT PRODUCTION. NOT GA. NOT SKYBEAM-COMPLETE.
