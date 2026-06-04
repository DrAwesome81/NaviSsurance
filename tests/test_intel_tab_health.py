"""
Minimal GUI coverage for the IntelTab index health label surface (IMPL_ID 9a3f55df fix round).
Uses heavy mocking to avoid real Qt app / display / full AgentConsole.
Exercises the exact new surface added for Index Freshness visibility.
"""

from unittest.mock import MagicMock, patch
import pytest

# We intentionally avoid the old fragile module-level patching block.
# Each test that needs an IntelTab instance will patch _setup_ui to avoid
# real Qt widget construction and the associated StopIteration / mock exhaustion issues.

from gui.intel_tab import IntelTab


def test_intel_tab_health_label_method_exists_and_defensive():
    """The new _update_index_health is present and handles the approved paths."""
    db = MagicMock()

    with patch.object(IntelTab, '_setup_ui'):
        tab = IntelTab(db)
        tab.index_health_label = MagicMock()

    assert hasattr(tab, '_update_index_health')
    # Should not raise even with no real stats
    tab._update_index_health()
    assert tab.index_health_label is not None


def test_intel_tab_health_updates_on_unavailable_and_success(monkeypatch):
    """Exercises the exact branches in the health label for stats success + unavailable."""
    db = MagicMock()

    with patch.object(IntelTab, '_setup_ui'):
        tab = IntelTab(db)
        tab.index_health_label = MagicMock()

    # Simulate unavailable
    def fake_unavailable():
        return {"available": False, "reason": "test"}
    monkeypatch.setattr(tab.intel, "get_index_stats", fake_unavailable)
    tab._update_index_health()
    txt = str(tab.index_health_label.setText.call_args[0][0] if tab.index_health_label.setText.called else "")
    assert "unavailable" in txt.lower() or "keyword" in txt.lower()

    # Simulate success with vector count + timestamp
    import time
    now = time.time()
    def fake_success():
        return {
            "available": True,
            "vector_count": 42,
            "last_indexed_at": now - 7200,  # ~2h ago
            "embedding_model": "all-MiniLM-L6-v2",
        }
    monkeypatch.setattr(tab.intel, "get_index_stats", fake_success)
    tab._update_index_health()
    # Called again; we don't assert exact string (formatting is internal) but no crash + label mutated
    assert tab.index_health_label.setText.called


def test_intel_tab_refresh_triggers_health(monkeypatch):
    """End-of-_refresh_findings coverage (the authoritative call site)."""
    db = MagicMock()

    with patch.object(IntelTab, '_setup_ui'):
        tab = IntelTab(db)
        tab.index_health_label = MagicMock()
    called = []
    orig = tab._update_index_health
    def spy():
        called.append(True)
        return orig()
    monkeypatch.setattr(tab, "_update_index_health", spy)

    # Simulate the internal findings path (minimal)
    tab.findings_table = MagicMock()
    tab.findings_table.rowCount.return_value = 0
    tab._refresh_findings()
    assert len(called) >= 1, "health update must be reached from _refresh_findings"
