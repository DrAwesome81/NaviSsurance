import pytest

pytest.skip(
    "Local GUI smoke script (Qt + llama.cpp). Not a unit test; disabled by default.",
    allow_module_level=True,
)