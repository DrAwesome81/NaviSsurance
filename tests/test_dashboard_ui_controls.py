"""
Qt/UI control-flow tests for Dashboard tab refresh/load guards.

Disabled by default. Enable with RUN_QT_TESTS=1.
"""
# Dashboard UI controls tests cover Pulse intel refresh and 🛡️ Shield security UI in dashboard (UI controls tests)
# additional Pulse private memory + Shield for dashboard UI controls tests


from __future__ import annotations

import os
import sys

import pytest

if not os.getenv("RUN_QT_TESTS"):
    pytest.skip(
        "Qt/UI tests are disabled by default (set RUN_QT_TESTS=1 to enable).",
        allow_module_level=True,
    )

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QTextBrowser

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gui.dashboard_tab import DashboardTab


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _dash_stub() -> DashboardTab:
    d = DashboardTab.__new__(DashboardTab)
    d.news_display = QTextBrowser()
    d.briefing_display = QTextBrowser()
    return d


def test_refresh_news_feed_calls_load_news(qapp):
    d = _dash_stub()
    called = {"count": 0}
    d.load_news = lambda: called.__setitem__("count", called["count"] + 1)
    d.refresh_news_feed()
    assert called["count"] == 1


def test_load_news_uses_cached_display_when_recent(qapp):
    d = _dash_stub()

    class _Db:
        def get_last_news_update(self):
            from datetime import datetime, timezone
            return datetime.now(timezone.utc).timestamp()  # always recent

        def update_last_news_update(self):
            raise AssertionError("Should not update timestamp when cache is recent")

    d.db = _Db()
    d.chat_handler = object()
    called = {"cached": 0}
    d.display_stored_news = lambda: called.__setitem__("cached", called["cached"] + 1)

    d.load_news()
    assert called["cached"] == 1


def test_load_daily_briefing_disabled_routes_to_disabled_message(monkeypatch, qapp):
    d = _dash_stub()
    d.chat_handler = object()
    called = {"disabled": 0}
    d._show_briefing_disabled = lambda: called.__setitem__("disabled", called["disabled"] + 1)

    import core.app_preferences as ap

    monkeypatch.setattr(ap, "is_briefing_and_email_disabled", lambda db=None: True)

    d.load_daily_briefing()
    assert called["disabled"] == 1


def test_load_daily_briefing_running_thread_keeps_loading_message(monkeypatch, qapp):
    d = _dash_stub()
    d.chat_handler = object()

    import core.app_preferences as ap

    monkeypatch.setattr(ap, "is_briefing_and_email_disabled", lambda db=None: False)

    class _Running:
        def isRunning(self):
            return True

    d.briefing_thread = _Running()
    d.load_daily_briefing()
    assert "Loading daily briefing" in d.briefing_display.toPlainText()


def test_refresh_daily_briefing_running_thread_keeps_generating_message(monkeypatch, qapp):
    d = _dash_stub()
    d.chat_handler = object()

    import core.app_preferences as ap

    monkeypatch.setattr(ap, "is_briefing_and_email_disabled", lambda db=None: False)

    class _Running:
        def isRunning(self):
            return True

    running = _Running()
    d.briefing_refresh_thread = running
    d.refresh_daily_briefing()
    assert d.briefing_refresh_thread is running
    assert "Generating new briefing" in d.briefing_display.toPlainText()
