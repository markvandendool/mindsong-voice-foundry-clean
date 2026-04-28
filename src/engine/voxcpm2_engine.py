"""VoxCPM2 engine wrapper (direct import, same venv as Foundry)."""

import asyncio
import threading
from pathlib import Path

from voxcpm import VoxCPM


class VoxCPM2Engine:
    """Wraps VoxCPM2 for voice cloning and voice design.

    Cancellation is **cooperative (soft)**, not hard-kill:
    - The model.generate() call itself cannot be interrupted from the thread.
    - We check a cancellation event before writing output.
    - If cancelled, the output file is NOT written and the job ends gracefully.
    - The thread may continue GPU/CPU compute in the background until
      model.generate() returns. This is a known limitation.
    - For true hard-kill (process termination), VoxCPM2 must run in a
      subprocess worker (planned for GA / RC-2.2).

    See: Commander audit 2026-04-28 — VoxCPM2 cancellation classified as
    "cooperative no-publish cancel, not hard kill."
    """

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

        # Cooperative cancellation event shared with caller
        cancel_event = threading.Event()
        if proc_ref is not None:
            proc_ref["cancel_event"] = cancel_event
            proc_ref["cancel"] = cancel_event.set

        def _generate():
            model = self._load()
            kwargs = {"text": text, "cfg_value": 2.0, "inference_timesteps": 10}

            if ref_audio and Path(ref_audio).exists():
                kwargs["reference_wav_path"] = ref_audio
            elif voice_design:
                kwargs["text"] = f"({voice_design}){text}"

            wav = model.generate(**kwargs)

            # Check cancellation after generation (cooperative)
            if cancel_event.is_set():
                # Don't write output if cancelled
                return None

            import soundfile as sf
            sf.write(str(out_path), wav, model.tts_model.sample_rate)
            return str(out_path)

        # Run in thread with its own timeout so asyncio.wait_for on the caller
        # side can also enforce a ceiling.
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(None, _generate)
        try:
            result = await asyncio.wait_for(future, timeout=300.0)
        except asyncio.TimeoutError:
            cancel_event.set()
            raise RuntimeError("VoxCPM2 synthesis exceeded 300s timeout")

        if result is None:
            raise RuntimeError("VoxCPM2 synthesis cancelled")

        return result
