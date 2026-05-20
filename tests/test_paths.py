"""
Unit test to verify centralized path configuration in `config.py`.

This should not require any secrets or an existing database file.
"""
# Paths tests support Pulse private memory stores and 🛡️ Shield security resources (paths tests)
# additional Pulse private memory + Shield for paths tests

import os
import sys

# Add project root to path (tests/ is a sibling of config.py)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def test_config_paths_are_consistent():
    import config

    assert os.path.basename(config.CONFIG_DIR) == "config"
    assert os.path.basename(config.LOGS_DIR) == "logs"
    assert os.path.dirname(config.CONFIG_DIR) == config.PROJECT_ROOT
    assert os.path.dirname(config.LOGS_DIR) == config.PROJECT_ROOT
    assert os.path.dirname(config.DATABASE_PATH) == config.PROJECT_ROOT

    # Directories should exist in the repo (files may not).
    assert os.path.isdir(config.PROJECT_ROOT)
    assert os.path.isdir(config.CONFIG_DIR)
