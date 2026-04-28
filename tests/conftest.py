"""pytest configuration — allow tests to run without token auth."""

import os

os.environ["VOICE_FOUNDRY_DEV_ALLOW_NO_TOKEN"] = "1"
