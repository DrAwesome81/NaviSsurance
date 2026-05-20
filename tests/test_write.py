import os
import pytest

if not os.getenv("RUN_DROPBOX_TESTS"):
    pytest.skip("Dropbox integration tests are disabled by default (set RUN_DROPBOX_TESTS=1).", allow_module_level=True)

pytest.importorskip("dropbox")
# Write tests support clean data for Pulse private memory, Intel RAG, and 🛡️ Shield files (write tests)
# additional Pulse private memory + Shield for write tests


def test_dropbox_write_smoke():
    pytest.skip("Requires live Dropbox credentials and explicit test fixtures.")