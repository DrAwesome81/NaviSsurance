"""
Qt/UI tests for Compliance tab local behaviors.

Disabled by default. Enable with RUN_QT_TESTS=1.
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import Mock

import pytest

if not os.getenv("RUN_QT_TESTS"):
    pytest.skip(
        "Qt/UI tests are disabled by default (set RUN_QT_TESTS=1 to enable).",
        allow_module_level=True,
    )

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication, QFileDialog, QPushButton, QWidget

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gui.compliance_tab import ComplianceTab


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def compliance_tab(monkeypatch, qapp, tmp_path):
    class _StubAgentConsole(QWidget):
        def __init__(self, db, agent_code="sentinel", parent=None):
            super().__init__(parent)

    monkeypatch.setattr("gui.compliance_tab.AgentConsole", _StubAgentConsole)
    tab = ComplianceTab(db=Mock(), chat_handler=Mock())
    tab.data_dir = str(tmp_path)
    # isolate from any pre-existing loaded entries
    tab.ref_list.clear()
    tab.assess_list.clear()
    return tab


def test_compliance_add_urls_and_persist(compliance_tab):
    compliance_tab.ref_url_input.setText("https://example.com/ref")
    compliance_tab.add_ref_url()
    compliance_tab.assess_url_input.setText("https://example.com/assess")
    compliance_tab.add_assess_url()

    assert compliance_tab.ref_list.count() == 1
    assert compliance_tab.assess_list.count() == 1
    assert compliance_tab.ref_url_input.text() == ""
    assert compliance_tab.assess_url_input.text() == ""

    cfg = os.path.join(compliance_tab.data_dir, "compliance_documents.json")
    assert os.path.exists(cfg)
    with open(cfg, "r", encoding="utf-8") as f:
        payload = json.load(f)
    assert payload["reference_documents"] == ["https://example.com/ref"]
    assert payload["assessed_documents"] == ["https://example.com/assess"]


def test_compliance_load_document_lists(compliance_tab):
    compliance_tab.ref_list.clear()
    compliance_tab.assess_list.clear()
    cfg = os.path.join(compliance_tab.data_dir, "compliance_documents.json")
    with open(cfg, "w", encoding="utf-8") as f:
        json.dump(
            {
                "reference_documents": ["r1", "r2"],
                "assessed_documents": ["a1"],
            },
            f,
            indent=2,
        )

    compliance_tab.load_document_lists()
    assert compliance_tab.ref_list.count() == 2
    assert compliance_tab.assess_list.count() == 1


def test_compliance_run_check_requires_both_lists(compliance_tab):
    compliance_tab.ref_list.clear()
    compliance_tab.assess_list.clear()
    compliance_tab.run_compliance_check()
    assert "Add at least one reference and assessed document" in compliance_tab.results_text.toPlainText()


def test_compliance_save_report_to_json(monkeypatch, compliance_tab, tmp_path):
    out_path = tmp_path / "report.json"
    monkeypatch.setattr(
        "gui.compliance_tab.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(out_path), "JSON Files (*.json)"),
    )

    compliance_tab.results_text.setPlainText("Line 1\nLine 2")
    compliance_tab.save_compliance_report()

    assert out_path.exists()
    with open(out_path, "r", encoding="utf-8") as f:
        arr = json.load(f)
    assert arr == ["Line 1", "Line 2"]


def test_compliance_clear_dataset_and_link_message(compliance_tab, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = data_dir / "fine_tune.jsonl"
    jsonl_path.write_text("{}", encoding="utf-8")

    cwd = os.getcwd()
    try:
        os.chdir(str(tmp_path))
        compliance_tab.clear_dataset()
        assert not jsonl_path.exists()
    finally:
        os.chdir(cwd)

    compliance_tab.link_to_crm()
    assert "CRM integration TBD" in compliance_tab.results_text.toPlainText()


def test_compliance_complete_success_formats_html(compliance_tab):
    payload = {
        "success": True,
        "data": {
            "overview": "Overall compliant with minor gaps.",
            "key_alignments": "Clear traceability to requirements.",
            "improvements": [
                {
                    "section": "4.2",
                    "issue": "Missing documented review cadence.",
                    "fix": "Add monthly review step.",
                    "reference": "ISO 13485 4.2",
                }
            ],
            "recommendations": "Prioritize documentation updates this sprint.",
        },
    }
    compliance_tab._on_compliance_complete_safe(payload)
    html = compliance_tab.results_text.toHtml()
    text = compliance_tab.results_text.toPlainText()
    assert "Overview" in html
    assert "Key Alignments" in html
    assert "Recommendations" in html
    assert "Missing documented review cadence." in text


def test_compliance_complete_error_sets_error_text(compliance_tab):
    compliance_tab._on_compliance_complete_safe({"success": False, "error": "network timeout"})
    assert "Error: network timeout" in compliance_tab.results_text.toPlainText()


def test_upload_reference_file_persists_and_stores_dataset(monkeypatch, compliance_tab, tmp_path):
    ref_path = tmp_path / "ref.txt"
    ref_path.write_text("ref", encoding="utf-8")

    class _Db:
        def __init__(self):
            self.entries = []

        def store_dataset_entry(self, path):
            self.entries.append(path)

    db = _Db()
    compliance_tab.db = db
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(ref_path), "Documents (*.txt)"),
    )

    before = compliance_tab.ref_list.count()
    compliance_tab.upload_ref_file()

    assert compliance_tab.ref_list.count() == before + 1
    assert db.entries[-1] == str(ref_path)


def test_upload_assess_file_cancel_does_not_mutate(monkeypatch, compliance_tab):
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: ("", ""),
    )
    before = compliance_tab.assess_list.count()
    compliance_tab.upload_assess_file()
    assert compliance_tab.assess_list.count() == before


def test_save_report_without_results_sets_message(compliance_tab):
    compliance_tab.results_text.clear()
    compliance_tab.save_compliance_report()
    assert "No results to save." in compliance_tab.results_text.toPlainText()


def test_compliance_complete_success_without_sections_sets_fallback(compliance_tab):
    compliance_tab._on_compliance_complete_safe({"success": True, "data": {}})
    assert "No results found." in compliance_tab.results_text.toPlainText()


def test_run_compliance_check_click_starts_thread_and_disables_button(monkeypatch, compliance_tab):
    compliance_tab.ref_list.addItem("https://example.com/ref")
    compliance_tab.assess_list.addItem("https://example.com/assess")

    class _ThreadStub:
        def __init__(self, checker, ref_items, assess_items, session_id, conversation_history):
            self.checker = checker
            self.ref_items = ref_items
            self.assess_items = assess_items
            self.session_id = session_id
            self.conversation_history = conversation_history
            self.started = False
            self._cb = None
            self.result_signal = self

        def connect(self, cb):
            self._cb = cb

        def start(self):
            self.started = True

    monkeypatch.setattr("gui.compliance_tab.ComplianceThread", _ThreadStub)
    monkeypatch.setattr("gui.compliance_tab.ComplianceChecker", lambda ch: object())

    run_btn = None
    for b in compliance_tab.findChildren(QPushButton):
        if b.text() == "Run Compliance Check":
            run_btn = b
            break
    assert run_btn is not None
    assert run_btn.isEnabled() is True

    run_btn.click()

    assert run_btn.isEnabled() is False
    assert compliance_tab.progress_bar.isHidden() is False
    assert "Running compliance check..." in compliance_tab.results_text.toPlainText()
    assert getattr(compliance_tab, "compliance_thread").started is True


def test_show_ref_context_menu_remove_deletes_selected_item(monkeypatch, compliance_tab):
    compliance_tab.ref_list.clear()
    compliance_tab.ref_list.addItem("r1")
    compliance_tab.ref_list.addItem("r2")
    compliance_tab.ref_list.show()
    compliance_tab.ref_list.repaint()

    class _MenuStub:
        def __init__(self):
            self._remove_action = object()

        def addAction(self, text):
            assert text == "Remove"
            return self._remove_action

        def exec(self, pos):
            return self._remove_action

    monkeypatch.setattr("gui.compliance_tab.QMenu", _MenuStub)
    item0 = compliance_tab.ref_list.item(0)
    pt = compliance_tab.ref_list.visualItemRect(item0).center()
    compliance_tab.show_ref_context_menu(pt)

    assert [compliance_tab.ref_list.item(i).text() for i in range(compliance_tab.ref_list.count())] == ["r2"]


def test_show_ref_context_menu_non_remove_keeps_items(monkeypatch, compliance_tab):
    compliance_tab.ref_list.clear()
    compliance_tab.ref_list.addItem("r1")
    compliance_tab.ref_list.addItem("r2")

    class _MenuStub:
        def addAction(self, text):
            assert text == "Remove"
            return object()

        def exec(self, pos):
            return None

    monkeypatch.setattr("gui.compliance_tab.QMenu", _MenuStub)
    compliance_tab.show_ref_context_menu(QPoint(1, 1))

    assert [compliance_tab.ref_list.item(i).text() for i in range(compliance_tab.ref_list.count())] == ["r1", "r2"]


def test_show_assess_context_menu_remove_deletes_selected_item(monkeypatch, compliance_tab):
    compliance_tab.assess_list.clear()
    compliance_tab.assess_list.addItem("a1")
    compliance_tab.assess_list.addItem("a2")
    compliance_tab.assess_list.show()
    compliance_tab.assess_list.repaint()

    class _MenuStub:
        def __init__(self):
            self._remove_action = object()

        def addAction(self, text):
            assert text == "Remove"
            return self._remove_action

        def exec(self, pos):
            return self._remove_action

    monkeypatch.setattr("gui.compliance_tab.QMenu", _MenuStub)
    item0 = compliance_tab.assess_list.item(0)
    pt = compliance_tab.assess_list.visualItemRect(item0).center()
    compliance_tab.show_assess_context_menu(pt)

    assert [compliance_tab.assess_list.item(i).text() for i in range(compliance_tab.assess_list.count())] == ["a2"]
