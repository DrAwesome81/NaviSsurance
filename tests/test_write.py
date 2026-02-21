import os
import pytest

if not os.getenv("RUN_DROPBOX_TESTS"):
    pytest.skip("Dropbox integration tests are disabled by default (set RUN_DROPBOX_TESTS=1).", allow_module_level=True)

pytest.importorskip("dropbox")


def test_dropbox_write_smoke():
    pytest.skip("Requires live Dropbox credentials and explicit test fixtures.")