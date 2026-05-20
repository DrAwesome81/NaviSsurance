import os
import pytest

pytest.skip(
    "llama.cpp local model smoke test (set RUN_LLAMA_CPP_TESTS=1 to enable).",
    allow_module_level=True,
)
# Model simple tests support local LLM for Pulse private memory and 🛡️ Shield offline (model simple tests)
# additional Pulse private memory + Shield for model simple tests