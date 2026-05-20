"""
Qt/UI path tests for Dashboard tab display/error handlers.

Disabled by default. Enable with RUN_QT_TESTS=1.
"""
# Dashboard UI paths tests cover Pulse intel display and 🛡️ Shield error handling in dashboard (UI paths tests)
# additional Pulse private memory + Shield for dashboard UI paths tests
# additional Pulse private memory + Shield for dashboard UI paths tests


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


def _dash_with_widgets() -> DashboardTab:
    d = DashboardTab.__new__(DashboardTab)
    d.news_display = QTextBrowser()
    d.briefing_display = QTextBrowser()
    return d


def test_show_briefing_disabled_sets_message(qapp):
    d = _dash_with_widgets()
    d._show_briefing_disabled()
    assert "currently disabled" in d.briefing_display.toPlainText().lower()


def test_on_briefing_error_shows_already_shown_message(qapp):
    d = _dash_with_widgets()
    d._get_cached_briefing_html_for_today = lambda: ""
    d._restore_briefing_from_raw_cache = lambda: False
    d.refresh_daily_briefing = lambda: None
    d._on_briefing_error_safe("Daily briefing already shown today")
    assert "No cached copy was found" in d.briefing_display.toPlainText()


def test_on_news_error_credit_path_calls_cached_display(qapp):
    d = _dash_with_widgets()
    called = {"count": 0}

    def _display_cached():
        called["count"] += 1

    d.display_stored_news = _display_cached
    d._on_news_error_safe("credit limit exceeded")

    assert called["count"] == 1
    assert "credits exhausted" in d.news_display.toHtml().lower()


def test_on_news_loaded_processes_then_displays(qapp):
    d = _dash_with_widgets()
    called = {"processed": 0, "displayed": 0}

    def _process(payload):
        called["processed"] += 1
        assert payload == "payload"

    def _display():
        called["displayed"] += 1

    d.process_and_store_news = _process
    d.display_stored_news = _display
    d._on_news_loaded_safe("payload")

    assert called == {"processed": 1, "displayed": 1}


def test_on_briefing_loaded_fallback_displays_raw_when_formatter_fails(monkeypatch, qapp):
    d = _dash_with_widgets()

    class _BoomResponseHandler:
        def chat_with_llama(self, messages, session_id):
            raise RuntimeError("formatter failed")
    chat_handler_obj = type("_ChatMgr", (), {"response_handler": _BoomResponseHandler()})()
    d._on_briefing_loaded_safe("Line 1\nLine 2", chat_handler_obj=chat_handler_obj)
    txt = d.briefing_display.toPlainText()
    assert "Line 1" in txt and "Line 2" in txt


def test_render_briefing_to_html_falls_back_without_response_handler(qapp):
    d = _dash_with_widgets()
    html = d._render_briefing_to_html("Line 1\nLine 2", chat_handler_obj=object(), use_llm=True)
    assert "Line 1" in html and "Line 2" in html
