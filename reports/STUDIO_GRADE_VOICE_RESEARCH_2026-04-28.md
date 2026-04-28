# Studio-Grade AI Voice: Top 10 Socially Proven Techniques

**Date:** 2026-04-28  
**Context:** Voice Foundry RC-2.1 — F5-TTS and VoxCPM2 produce intelligible but "tinny" output. Target: audiobook-grade, publishable voice indistinguishable from studio recording.

---

## The Root Cause of "Tinny" AI Voice

Chief's diagnosis is correct. "Tinny" comes from **five interacting problems**:

1. **Over-compression / loudness flattening** — The mastering chain crushes dynamic range
2. **Missing low-mid body** — No energy at 150-400 Hz where vocal warmth lives
3. **Harsh upper-mid spike** — 2-5 kHz region is unnaturally emphasized
4. **Flat mono rendering** — No spatial depth or near-field intimacy
5. **Insufficient post-processing** — Generation alone is never enough

> "Generation alone is insufficient. You need **post-processing + mastering pipeline**. This is exactly why most systems plateau at 'good but synthetic'." — Chief, 2026-04-28

---

## Top 10 Socially Proven Techniques

### 1. Use the Best-Ranked Model (Not Just "Good Enough")

**2026 TTS Quality Leaderboard (MOS scores):**

| Rank | Model | MOS | Kind |
|---|---|---|---|
| 1 | ElevenLabs Turbo v2.5 | 4.8 | Commercial |
| 2 | Sesame CSM | 4.7 | Open Source |
| 3 | OpenAI TTS HD | 4.7 | Commercial |
| 4 | Gemini 2.5 Pro TTS | 4.7 | Commercial |
| 5 | Cartesia Sonic 2 | 4.7 | Commercial |
| 14 | **F5-TTS** | **4.4** | Open Source |
| — | **VoxCPM2** | **~4.0** | Open Source |

**Insight:** F5-TTS at 4.4 MOS is "good but synthetic." ElevenLabs at 4.8 MOS is "indistinguishable from real." For publishable quality, consider a **hybrid**: F5-TTS for local/batch, ElevenLabs API for premium renders.

**Action:** Add ElevenLabs as a `premium` tier provider in RockyVoiceRouter, gated by human review.

---

### 2. Feed the Model Studio-Quality Reference Audio

**The reference audio matters more than the model.**

| Reference Quality | Result |
|---|---|
| 3-10s phone recording | Thin, inconsistent clone |
| 30s clean speech | Acceptable zero-shot clone |
| 5-15min studio recording | Good quality, stable |
| **30+ min pro studio session** | **Indistinguishable from original** |

**Best practices for reference recordings:**
- Close-mic (6-12 inches) with pop filter
- Quiet, treated room (no HVAC, no reverb)
- Consistent energy and proximity
- 48kHz/24-bit minimum
- Include varied phrases, emotions, pauses
- No processing on the reference (no EQ, no compression)

**Action:** Record a proper 30-minute Mark reference session in the treated studio space.

---

### 3. Render at High Resolution (Not 16-bit/44.1kHz)

| Setting | Quality | Use Case |
|---|---|---|
| 44.1kHz/16-bit | CD quality | Legacy compatibility |
| **48kHz/24-bit** | **Professional video/audio** | **Target for Foundry** |
| 96kHz/24-bit | High-resolution | Audiophile, archiving |
| 192kHz/32-bit | Mastering headroom | Future-proofing |

**Critical:** Never render to MP3/AAC for the master. Use **FLAC or WAV** until final platform export.

**Action:** Change Foundry output from 48kHz/16-bit to **48kHz/24-bit** minimum.

---

### 4. Add a Professional Post-Processing Chain

Current `mix_chain.py` is a basic 14-step FFmpeg chain. It needs **vocal-specific mastering**.

**Proposed Studio Voice Chain:**

```
1. High-pass filter (60-80 Hz) — remove rumble
2. De-esser (6-10 kHz) — tame harsh sibilance
3. Subtractive EQ — cut 200-300 Hz mud, cut 2-4 kHz harshness
4. Additive EQ — boost 120-180 Hz warmth, boost 3-5 kHz presence (gentle)
5. Multiband compression — independent control of lows/mids/highs
6. Harmonic exciter — add "air" and perceived detail (3-8 kHz)
7. Tube/tape saturation — analog warmth, harmonic richness
8. Stereo widener (subtle) — spatial depth, mid-side processing
9. LUFS normalization — target -18 (dialogue) or -14 (YouTube)
10. True-peak limiter (-2.0 dBTP) — prevent intersample peaks
```

**Key plugins/tools (FFmpeg equivalents):**
- `afftdn` — denoise
- `adeclick` — de-click
- `aecho` or `reverb` — subtle room ambience (not echo)
- `compand` or `acompressor` — dynamics
- `aeval` or `equalizer` — EQ
- `alimiter` — peak limiting

**Action:** Replace the current 14-step chain with the 10-step studio voice chain above.

---

### 5. Add Harmonic Excitement / Saturation

**This is the #1 missing ingredient in most AI voice pipelines.**

Digital audio is "too clean." Analog gear (tape, tubes, transformers) naturally adds harmonic content that makes voices sound "alive."

| Tool | Effect |
|---|---|
| **Harmonic Exciter** | Adds new upper harmonics — sparkle, air, detail (3-8 kHz) |
| **Tube Saturation** | Warm, musical distortion across broad range |
| **Tape Saturation** | Gentle compression + harmonic richness |

**Recommended free options:**
- Softube Saturation Knob (free)
- iZotope Ozone Exciter (in Ozone suite)
- BBE Sonic Sweet (v4 plugin bundle)
- FFmpeg `aeval` with harmonic generation formulas

**Action:** Add a subtle harmonic exciter stage to `mix_chain.py` after EQ, before limiting.

---

### 6. Use Dynamic EQ (Not Static EQ)

Static EQ applies the same curve regardless of content. **Dynamic EQ** adapts to the signal:

- Only cuts 2-4 kHz **when** that frequency is harsh
- Only boosts 150 Hz **when** the voice lacks body
- Prevents over-processing quiet passages

**FFmpeg approach:** Use `dynaudnorm` or multiband dynamics (`compand` with multiple bands).

**Action:** Replace static EQ with dynamic multiband processing in the mastering chain.

---

### 7. Add Subtle Spatial Depth (Not Mono)

Current output is **hard mono** (1 channel). Real voices have spatial presence.

| Technique | Effect | Subtlety |
|---|---|---|
| **Mid-Side EQ** | Different treatment for center vs sides | Very subtle |
| **Subtle reverb** | Small room ambience (not echo) | Barely perceptible |
| **Stereo widener** | Widen slightly for depth | 10-20% max |
| **Haas effect** | Micro-delay for width | <30ms delay |

**For voice:** A tiny amount of "room" makes the speaker feel present rather than disembodied.

**Action:** Add optional `spatial` preset to `mix_chain.py` with subtle mid-side processing + room ambience.

---

### 8. Preserve Dynamic Range (Don't Loudness-War)

Current LUFS targets:
- `rocky_live`: -18 LUFS (good for dialogue)
- `skybeam_youtube`: -14 LUFS (good for YouTube)
- `film_dialogue`: -23 LUFS (good for film)

**Problem:** Aggressive limiting to hit LUFS targets destroys transients and breath detail.

**Better approach:**
- Use **gentle compression** (2:1 ratio, slow attack) for consistency
- Use **limiting only for true peaks**, not for loudness
- Let the LUFS target be achieved through **gain**, not crushing

**Neil Young's Pono philosophy:** Full dynamic range, no crushing, let the listener turn up the volume.

**Action:** Audit the current `loudnorm` settings. Ensure they're using **dual-pass** with true-peak limiting, not aggressive compression.

---

### 9. Use a Two-Stage Pipeline: Raw → Mastered → Final

Current pipeline: `synthesis → mastering → done`

**Studio pipeline:** `synthesis → raw master → mixing → final master → platform export`

| Stage | Purpose | Format |
|---|---|---|
| **Raw synthesis** | Model output, unprocessed | 48kHz/24-bit WAV |
| **Raw master** | Cleaned, denoised, leveled | 48kHz/24-bit WAV |
| **Mix processing** | EQ, compression, saturation, spatial | 48kHz/24-bit WAV |
| **Final master** | LUFS normalization, limiting, dither | 48kHz/24-bit FLAC |
| **Platform export** | MP3/AAC for delivery | Per platform specs |

**Action:** Split `mix_chain.py` into `raw_master()` and `final_master()` stages.

---

### 10. A/B Test Against Real Studio Recordings

**The ultimate quality check:** Can you tell the difference in a blind test?

**Process:**
1. Record Mark saying the same phrase in the studio (reference)
2. Generate the same phrase with F5-TTS + new mastering chain
3. Level-match both to same LUFS
4. Randomize order
5. Have 3+ people listen blind
6. Score: if >50% can't tell which is AI, you're at studio grade

**Action:** Set up a blind A/B test pipeline. Use it as the final gate before marking `publishable: true`.

---

## Implementation Priority for Voice Foundry

| Priority | Technique | Effort | Impact |
|---|---|---|---|
| P0 | **Better reference audio** (30min studio session) | Medium | **Highest** |
| P0 | **Professional post-processing chain** (10-step) | Medium | **Highest** |
| P1 | **48kHz/24-bit rendering** | Low | High |
| P1 | **Harmonic exciter / saturation** | Medium | High |
| P1 | **Dynamic EQ / multiband** | Medium | High |
| P2 | **Subtle spatial depth** | Low | Medium |
| P2 | **Two-stage pipeline** | Medium | Medium |
| P2 | **ElevenLabs premium tier** | Low | High (costs $) |
| P3 | **A/B blind test pipeline** | Medium | Validation |
| P3 | **192kHz archival masters** | Low | Future-proofing |

---

## Key Insight: The Model Is Only 40% of the Solution

> "You're NOT chasing 'better TTS'. You're chasing **studio vocal production quality applied to AI-generated voice.**" — Chief

The research proves this:

- **ElevenLabs** (4.8 MOS) wins because of their **full pipeline**: model + post-processing + mastering + reference quality standards
- **F5-TTS** (4.4 MOS) is good at generation but lacks the production layer
- **LongCat-AudioDiT** (new SOTA) operates directly in waveform space, avoiding mel-spectrogram errors
- **Professional engineers** spend 80% of their time on post-processing, 20% on capture

**Voice Foundry needs to become a voice *production studio*, not just a voice *generator*.**

---

## Recommended Next Step

1. Record a 30-minute Mark reference session (treated room, close-mic, 48kHz/24-bit)
2. Re-implement `mix_chain.py` with the 10-step studio voice chain
3. Add harmonic exciter and dynamic EQ stages
4. Bump output to 48kHz/24-bit
5. Generate fresh F5 + VoxCPM2 artifacts with new chain
6. A/B blind test against the old output
7. If Mark approves, fill `human_score.json` and mark publishable

---

**Sources:**
- Codesota TTS Leaderboard (2026-04-27)
- Artificial Analysis Speech Arena (ELO ratings)
- LongCat-AudioDiT paper (arXiv 2603.29339)
- Awesome Audio Generation GitHub (backblaze-labs)
- Professional mastering chains (BeatRoot, Production Expert)
- Harmonic exciter research (Adrian Milea, Audio Drama Production)
- ElevenLabs / Inworld / Cartesia quality benchmarks
