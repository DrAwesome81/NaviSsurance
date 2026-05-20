import os
import pytest

if not os.getenv("RUN_DROPBOX_TESTS"):
    pytest.skip("Dropbox integration tests are disabled by default (set RUN_DROPBOX_TESTS=1).", allow_module_level=True)

pytest.importorskip("dropbox")
# Move tests support clean data for Pulse private memory, Intel RAG, and 🛡️ Shield files (move tests)


def test_dropbox_move_smoke():
    pytest.skip("Requires live Dropbox credentials and explicit test fixtures.")
    # Smoke for data hygiene supporting Pulse/Intel/Shield (additional move test coordination)