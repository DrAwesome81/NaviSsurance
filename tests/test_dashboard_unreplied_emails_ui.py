"""
Qt/UI tests for Dashboard unreplied-email paths.

Disabled by default. Enable with RUN_QT_TESTS=1.
"""

from __future__ import annotations

import os
import sys
import types

import pytest

if not os.getenv("RUN_QT_TESTS"):
    pytest.skip(
        "Qt/UI tests are disabled by default (set RUN_QT_TESTS=1 to enable).",
        allow_module_level=True,
    )

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QCheckBox, QDialog, QMessageBox, QTableWidget

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gui.dashboard_tab import DashboardTab


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _dash_email_stub() -> DashboardTab:
    d = DashboardTab.__new__(DashboardTab)
    d.unreplied_only_client = QCheckBox()
    d.unreplied_only_client.setChecked(True)
    d.unreplied_table = QTableWidget(0, 6)
    return d


def test_load_unreplied_emails_empty_shows_placeholder(qapp):
    d = _dash_email_stub()

    class _Db:
        def list_unreplied_emails(self, **kwargs):
            return []

    d.db = _Db()
    d.load_unreplied_emails()

    assert d.unreplied_table.rowCount() == 1
    first = d.unreplied_table.item(0, 0)
    assert first is not None
    assert "No unreplied emails" in first.text()


def test_load_unreplied_emails_populates_rows(qapp):
    d = _dash_email_stub()

    class _Db:
        def list_unreplied_emails(self, **kwargs):
            return [
                {
                    "id": "email-1",
                    "sender": "alice@example.com",
                    "subject": "Follow-up",
                    "folder": "Inbox",
                    "source": "outlook",
                    "timestamp": 0,
                }
            ]

    d.db = _Db()
    d.load_unreplied_emails()

    assert d.unreplied_table.rowCount() == 1
    assert d.unreplied_table.item(0, 0).text() == "alice@example.com"
    assert d.unreplied_table.item(0, 1).text() == "Follow-up"
    assert d.unreplied_table.cellWidget(0, 5) is not None


def test_mark_email_replied_success_refreshes(qapp):
    d = _dash_email_stub()
    called = {"db": 0, "refresh": 0}

    class _Db:
        def mark_email_replied(self, email_id, replied=0):
            called["db"] += 1
            assert email_id == "abc"
            assert replied == 1

    d.db = _Db()
    d.load_unreplied_emails = lambda: called.__setitem__("refresh", called["refresh"] + 1)
    d._mark_email_replied("abc")
    assert called == {"db": 1, "refresh": 1}


def test_mark_email_replied_error_shows_warning(qapp, monkeypatch):
    d = _dash_email_stub()
    called = {"warning": 0, "refresh": 0}

    class _Db:
        def mark_email_replied(self, email_id, replied=0):
            raise RuntimeError("db error")

    d.db = _Db()
    d.load_unreplied_emails = lambda: called.__setitem__("refresh", called["refresh"] + 1)
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args, **kwargs: called.__setitem__("warning", called["warning"] + 1),
    )
    d._mark_email_replied("abc")
    assert called == {"warning": 1, "refresh": 0}


def test_open_email_rules_accept_reclassifies_and_refreshes(qapp, monkeypatch):
    d = _dash_email_stub()
    called = {"reclassify": 0, "refresh": 0}

    class _Db:
        def reclassify_emails(self, days=0):
            called["reclassify"] += 1
            assert days == 30

    class _Dlg:
        def __init__(self, parent=None, db=None):
            self.parent = parent
            self.db = db

        def exec(self):
            return QDialog.DialogCode.Accepted

    fake_mod = types.ModuleType("gui.email_rules_dialog")
    fake_mod.EmailRulesDialog = _Dlg
    monkeypatch.setitem(sys.modules, "gui.email_rules_dialog", fake_mod)

    d.db = _Db()
    d.load_unreplied_emails = lambda: called.__setitem__("refresh", called["refresh"] + 1)
    d.open_email_rules()
    assert called == {"reclassify": 1, "refresh": 1}


def test_open_email_rules_import_error_shows_warning(qapp, monkeypatch):
    d = _dash_email_stub()
    d.db = object()
    called = {"warning": 0}

    monkeypatch.delitem(sys.modules, "gui.email_rules_dialog", raising=False)

    import builtins

    real_import = builtins.__import__

    def _import(name, *args, **kwargs):
        if name == "gui.email_rules_dialog":
            raise ImportError("module missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import)
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args, **kwargs: called.__setitem__("warning", called["warning"] + 1),
    )

    d.open_email_rules()
    assert called["warning"] == 1
