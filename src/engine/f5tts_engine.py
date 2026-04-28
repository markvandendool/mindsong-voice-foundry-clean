"""F5-TTS inference engine wrapper."""

import asyncio
import shutil
import sys
from pathlib import Path


def _resolve_f5_cli() -> str:
    """Find f5-tts_infer-cli in PATH or in the same bin dir as the Python executable."""
    cli = shutil.which("f5-tts_infer-cli")
    if cli:
        return cli
    # Fallback: look next to the current Python interpreter (venv case)
    venv_bin = Path(sys.executable).parent
    candidate = venv_bin / "f5-tts_infer-cli"
    if candidate.exists():
        return str(candidate)
    raise RuntimeError("f5-tts_infer-cli not found in PATH or venv bin")


class F5TTSEngine:
    """Wraps the f5-tts_infer-cli command for async generation."""

    def __init__(self, device: str = "mps"):
        self.model = "F5TTS_v1_Base"
        self.device = device
        self._fallback_to_cpu = False

    async def synthesize(
        self,
        text: str,
        ref_audio: str,
        output_path: str,
        speed: float = 1.0,
        remove_silence: bool = True,
        proc_ref: dict | None = None,
    ) -> str:
        ref_path = Path(ref_audio)
        if not ref_path.is_absolute():
            ref_path = Path.cwd() / ref_audio

        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            _resolve_f5_cli(),
            "--model", self.model,
            "--ref_audio", str(ref_path),
            "--ref_text", "",
            "--gen_text", text,
            "--output_dir", str(out_path.parent),
            "--output_file", out_path.name,
            "--speed", str(speed),
            "--device", self.device if not self._fallback_to_cpu else "cpu",
        ]
        if remove_silence:
            cmd.append("--remove_silence")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        if proc_ref is not None:
            proc_ref["proc"] = proc

        try:
            stdout, stderr = await proc.communicate()
        finally:
            if proc_ref is not None:
                proc_ref.pop("proc", None)

        if proc.returncode != 0:
            err = stderr.decode()
            # Auto-fallback to CPU on MPS-specific failure
            if (
                self.device == "mps"
                and not self._fallback_to_cpu
                and ("mps" in err.lower() or "metal" in err.lower())
            ):
                self._fallback_to_cpu = True
                return await self.synthesize(
                    text, ref_audio, output_path, speed, remove_silence, proc_ref
                )
            raise RuntimeError(f"F5-TTS failed: {err}")

        # Fallback: if the CLI didn't honor --output_file, rename the default
        default_out = out_path.parent / "infer_cli_basic.wav"
        if default_out.exists() and str(default_out) != str(out_path):
            default_out.rename(out_path)

        return str(out_path)
