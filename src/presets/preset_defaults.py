"""Default voice presets for Mark Voice OS."""

PRESETS = {
    "mark_rocky_tutor_warm": {
        "provider": "f5tts",
        "reference": "voices/mark/processed/references/novaxe_narration_20s_48k_24b_mono.wav",
        "mixPreset": "rocky_live",
        "speed": 1.0,
        "temperature": 0.75,
        "emotion": "warm_teacher",
        "description": "Friendly RockyAI tutor voice for interactive teaching.",
    },
    "mark_skybeam_creator_forward": {
        "provider": "f5tts",
        "reference": "voices/mark/processed/references/novaxe_narration_20s_48k_24b_mono.wav",
        "mixPreset": "skybeam_youtube",
        "speed": 1.04,
        "temperature": 0.82,
        "emotion": "energetic_creator",
        "description": "Forward creator narration for Skybeam videos.",
    },
    "mark_film_dialogue_deep": {
        "provider": "f5tts",
        "reference": "voices/mark/processed/references/novaxe_narration_20s_48k_24b_mono.wav",
        "mixPreset": "film_dialogue",
        "speed": 0.96,
        "temperature": 0.68,
        "emotion": "cinematic",
        "description": "Slower, deeper, high-dynamic-range cinematic narration.",
    },
    "mark_chatterbox_storytelling": {
        "provider": "chatterbox",
        "reference": "voices/mark/processed/references/novaxe_narration_20s_48k_24b_mono.wav",
        "mixPreset": "skybeam_youtube",
        "emotion": "storytelling",
        "description": "Chatterbox storytelling preset for long-form narration.",
    },
    "mark_voxcpm2_clone": {
        "provider": "voxcpm2",
        "reference": "voices/mark/processed/references/novaxe_narration_full_48k_24b_mono.wav",
        "mixPreset": "film_dialogue",
        "description": "VoxCPM2 voice clone with reference audio.",
    },
    "webspeech_fallback": {
        "provider": "webspeech",
        "mixPreset": "none",
        "description": "Fallback only. Not a clone.",
    },
}
