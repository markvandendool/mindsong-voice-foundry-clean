"""VoxCPM2 engine wrapper (direct import, same venv as Foundry)."""

import asyncio
from pathlib import Path

from voxcpm import VoxCPM


class VoxCPM2Engine:
    """Wraps VoxCPM2 for voice cloning and voice design."""

    def __init__(self, model_id: str = "openbmb/VoxCPM2"):
        self.model_id = model_id
        self._model = None

    def _load(self):
        if self._model is None:
            self._model = VoxCPM.from_pretrained(self.model_id, load_denoiser=False)
        return self._model

    async def synthesize(
        self,
        text: str,
        ref_audio: str | None = None,
        output_path: str = "output.wav",
        voice_design: str | None = None,
        proc_ref: dict | None = None,
    ) -> str:
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Run blocking model inference in thread pool
        def _generate():
            model = self._load()
            kwargs = {"text": text, "cfg_value": 2.0, "inference_timesteps": 10}

            if ref_audio and Path(ref_audio).exists():
                kwargs["reference_wav_path"] = ref_audio
            elif voice_design:
                kwargs["text"] = f"({voice_design}){text}"

            wav = model.generate(**kwargs)
            import soundfile as sf
            sf.write(str(out_path), wav, model.tts_model.sample_rate)
            return str(out_path)

        return await asyncio.to_thread(_generate)
