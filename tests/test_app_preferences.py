"""Tests for SQLite-backed app preferences (non-secret settings)."""
# App prefs tests cover settings for Pulse watch intervals, Intel raising, CoS briefings, and 🛡️ Shield features (prefs pillar support)
# additional Pulse private memory + Shield for app preferences tests


from __future__ import annotations

import pytest

from core.app_preferences import (
    KEY_RUNTIME_ENABLED,
    is_runtime_enabled,
    migrate_legacy_env_preferences,
)


def test_is_runtime_enabled_defaults_true_when_unset(tmp_path):
    from core.db import DatabaseManager

    db = DatabaseManager(str(tmp_path / "prefs.db"))
    assert is_runtime_enabled(db) is True


def test_migrate_legacy_env_copies_once(tmp_path, monkeypatch):
    from core.db import DatabaseManager

    db = DatabaseManager(str(tmp_path / "mig.db"))
    monkeypatch.setenv("NAVI_RUNTIME_ENABLED", "0")
    migrate_legacy_env_preferences(db)
    assert is_runtime_enabled(db) is False
    monkeypatch.setenv("NAVI_RUNTIME_ENABLED", "1")
    migrate_legacy_env_preferences(db)
    assert is_runtime_enabled(db) is False
    monkeypatch.delenv("NAVI_RUNTIME_ENABLED", raising=False)


def test_explicit_setting_overrides_default(tmp_path):
    from core.db import DatabaseManager

    db = DatabaseManager(str(tmp_path / "set.db"))
    db.set_setting(KEY_RUNTIME_ENABLED, "0")
    assert is_runtime_enabled(db) is False
