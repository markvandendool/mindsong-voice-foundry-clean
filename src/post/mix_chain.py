"""FFmpeg-based voice mastering pipeline."""

import json
import subprocess
from pathlib import Path

LOUDNESS_PRESETS = {
    "rocky_live": {"I": -18, "TP": -2.0, "LRA": 7},
    "skybeam_youtube": {"I": -14, "TP": -1.5, "LRA": 8},
    "film_dialogue": {"I": -23, "TP": -2.0, "LRA": 12},
    "shorts_reels": {"I": -16, "TP": -1.0, "LRA": 6},
}


def _run_ffmpeg(args: list[str]) -> None:
    result = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + args,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {result.stderr}")


def measure_loudness(audio_path: str) -> dict:
    """Measure EBU R128 loudness using FFmpeg loudnorm with print_format=json."""
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i", audio_path,
            "-af", "loudnorm=print_format=json",
            "-f", "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    # Parse JSON from stderr
    lines = result.stderr.splitlines()
    json_lines = []
    in_json = False
    for line in lines:
        if line.strip() == "{":
            in_json = True
        if in_json:
            json_lines.append(line)
        if line.strip() == "}":
            break

    try:
        data = json.loads("\n".join(json_lines))
    except json.JSONDecodeError:
        return {"integrated_lufs": 0, "true_peak_db": 0, "lra": 0}

    return {
        "integrated_lufs": float(data.get("input_i", 0)),
        "true_peak_db": float(data.get("input_tp", 0)),
        "lra": float(data.get("input_lra", 0)),
        "threshold": float(data.get("input_thresh", 0)),
    }


def get_duration(audio_path: str) -> float:
    """Return audio duration in seconds using ffprobe."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return 0.0
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def master_take(input_path: str, output_path: str, preset: str = "skybeam_youtube") -> dict:
    """Apply the 14-step voice post chain."""
    settings = LOUDNESS_PRESETS.get(preset, LOUDNESS_PRESETS["skybeam_youtube"])
    I, TP, LRA = settings["I"], settings["TP"], settings["LRA"]

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".premaster.wav")

    # Step 1–12: Clean, EQ, compress, limit
    _run_ffmpeg([
        "-i", input_path,
        "-af",
        "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.08,"
        "highpass=f=75,"
        "lowpass=f=14500,"
        "afftdn=nf=-25,"
        "equalizer=f=220:t=q:w=1.0:g=-1.5,"
        "equalizer=f=3500:t=q:w=1.2:g=1.2,"
        "equalizer=f=7800:t=q:w=1.0:g=-1.0,"
        "acompressor=threshold=-20dB:ratio=2.2:attack=8:release=120:makeup=1.5,"
        "alimiter=limit=0.96",
        "-ar", "48000", "-ac", "1",
        str(tmp),
    ])

    # Step 13: Loudness normalization
    _run_ffmpeg([
        "-i", str(tmp),
        "-af", f"loudnorm=I={I}:TP={TP}:LRA={LRA}",
        "-ar", "48000", "-ac", "1",
        str(out),
    ])

    tmp.unlink(missing_ok=True)

    # Step 14: QC scan
    metrics = measure_loudness(str(out))
    metrics["preset"] = preset
    metrics["target_integrated_lufs"] = I
    metrics["target_true_peak_db"] = TP
    metrics["target_lra"] = LRA
    return metrics
