"""
Qt/UI tests for Leads tab local behaviors.

Disabled by default. Enable with RUN_QT_TESTS=1.
"""
# Leads tab UI tests support Pulse private memory and 🛡️ Shield regulatory intel in leads (leads tab UI tests)
# additional Pulse private memory + Shield for leads tab UI tests


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

from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gui.leads_tab import LeadsTab


class _DbStub:
    def __init__(self):
        self.last_list_kwargs = {}
        self.set_contacted_calls = []
        self.deleted_ids = []
        self.updated_ids = []
        self.added_tasks = []
        self._rows = [
            {
                "id": 1,
                "name": "Alex Doe",
                "company": "MedTech Co",
                "title": "VP Regulatory",
                "total_score": 77,
                "status": "new",
                "contacted": 0,
                "contact_date": "",
                "next_action_date": "",
                "message": "Hello there",
                "sources": ["https://example.com/a"],
                "signals": ["510k filed"],
                "rationale": "Good fit",
                "linkedin_url": "linkedin.com/in/alex-doe",
                "company_url": "https://medtech.example.com",
                "notes": "",
            }
        ]

    def list_leads(self, **kwargs):
        self.last_list_kwargs = dict(kwargs)
        if kwargs.get("limit") == 1:
            return self._rows[:1]
        return list(self._rows)

    def set_lead_contacted(self, lead_id: int, contacted: bool):
        self.set_contacted_calls.append((int(lead_id), bool(contacted)))

    def delete_lead_by_id(self, lead_id: int):
        self.deleted_ids.append(int(lead_id))

    def update_lead_by_id(self, lead_id: int, **kwargs):
        self.updated_ids.append((int(lead_id), dict(kwargs)))

    def add_task(self, session_id, task_text, due_date, category="Business"):
        self.added_tasks.append((session_id, task_text, due_date, category))


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def leads_tab(monkeypatch, qapp, tmp_path):
    class _StubAgentConsole(QWidget):
        def __init__(self, db, agent_code="scout", parent=None):
            super().__init__(parent)

    monkeypatch.setattr("gui.leads_tab.AgentConsole", _StubAgentConsole)

    class _Parent(QWidget):
        def open_settings(self):
            return None

    parent = _Parent()
    parent.db = _DbStub()
    tab = LeadsTab(chat_handler=None, data_dir=str(tmp_path), parent=parent)
    return tab


def test_refresh_leads_passes_filter_values_to_db(leads_tab):
    leads_tab.status_filter.setCurrentText("new")
    leads_tab.min_score_filter.setValue(50)
    leads_tab.hide_contacted.setChecked(True)
    leads_tab.refresh_leads()

    kwargs = leads_tab.db.last_list_kwargs
    assert kwargs.get("status") == "new"
    assert kwargs.get("contacted") == 0
    assert kwargs.get("min_score") == 50
    assert leads_tab.leadsTable.rowCount() >= 1


def test_toggle_contacted_by_id_updates_db_and_refreshes(monkeypatch, leads_tab):
    called = {"refresh": 0}
    monkeypatch.setattr(leads_tab, "refresh_leads", lambda: called.__setitem__("refresh", called["refresh"] + 1))

    leads_tab.toggle_contacted_by_id(1, True)

    assert leads_tab.db.set_contacted_calls[-1] == (1, True)
    assert called["refresh"] == 1


def test_delete_lead_by_id_respects_confirmation(monkeypatch, leads_tab):
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No)
    leads_tab.delete_lead_by_id(1)
    assert leads_tab.db.deleted_ids == []

    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(leads_tab, "refresh_leads", lambda: None)
    leads_tab.delete_lead_by_id(1)
    assert leads_tab.db.deleted_ids == [1]


def test_show_message_dialog_copy_sets_clipboard_text(monkeypatch, leads_tab):
    copied = {"text": None}

    class _Clipboard:
        def setText(self, text):
            copied["text"] = text

    def _exec(self):
        for button in self.buttons():
            if self.buttonRole(button) == QMessageBox.ButtonRole.ActionRole:
                button.click()
                break
        return 0

    monkeypatch.setattr("gui.leads_tab.QApplication.clipboard", lambda: _Clipboard())
    monkeypatch.setattr(QMessageBox, "exec", _exec)

    leads_tab.show_message_dialog("Hello there")
    assert copied["text"] == "Hello there"


def test_create_followup_task_adds_task_and_updates_next_action_date(monkeypatch, leads_tab):
    monkeypatch.setattr(leads_tab, "refresh_leads", lambda: None)
    lead = {
        "id": 1,
        "name": "Alex Doe",
        "company": "MedTech Co",
        "next_action_date": "",
    }
    leads_tab.create_followup_task(lead)

    assert len(leads_tab.db.added_tasks) == 1
    session_id, task_text, due_date, category = leads_tab.db.added_tasks[0]
    assert session_id == "lead_gen"
    assert "Alex Doe" in task_text and "MedTech Co" in task_text
    assert category == "Business"
    assert due_date.count("-") == 2  # MM-DD-YYYY
    assert leads_tab.db.updated_ids and leads_tab.db.updated_ids[-1][0] == 1


def test_on_cell_clicked_opens_linkedin_url(monkeypatch, leads_tab):
    called = {"count": 0}

    def _open_url(_qurl):
        called["count"] += 1
        return True

    monkeypatch.setattr("gui.leads_tab.QDesktopServices.openUrl", _open_url)

    # Row 0, col 0 corresponds to Name; update_leads_table already loaded one row.
    leads_tab.on_cell_clicked(0, 0)
    assert called["count"] == 1


def test_edit_lead_accepted_updates_db(monkeypatch, leads_tab):
    class _AcceptedDialog:
        def __init__(self, parent, lead):
            self._lead = lead

        def resize(self, *_args, **_kwargs):
            return None

        def exec(self):
            return 1  # QDialog.DialogCode.Accepted

        def values(self):
            return {
                "status": "contacted",
                "next_action_date": "2026-03-15",
                "notes": "Reached out with personalized note",
            }

    monkeypatch.setattr("gui.leads_tab.LeadsTab._EditLeadDialog", _AcceptedDialog)
    monkeypatch.setattr(leads_tab, "refresh_leads", lambda: None)
    lead = dict(leads_tab.db._rows[0])

    leads_tab.edit_lead(lead)
    assert leads_tab.db.updated_ids
    lead_id, payload = leads_tab.db.updated_ids[-1]
    assert lead_id == 1
    assert payload["status"] == "contacted"
    assert payload["next_action_date"] == "2026-03-15"
