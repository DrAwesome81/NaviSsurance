import pytest

pytest.skip(
    "Local GUI smoke script (Qt + llama.cpp). Not a unit test; disabled by default.",
    allow_module_level=True,
)
# Qt llama tests support local LLM UI for Pulse private memory and 🛡️ Shield offline (Qt llama tests)
# additional Pulse private memory + Shield for Qt llama tests