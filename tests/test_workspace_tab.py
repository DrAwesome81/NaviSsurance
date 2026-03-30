"""
Qt/UI tests for the Workspace tab.

Covers automated equivalents of key manual cases:
- TC-006: file list behavior and selectable rows
- TC-007: document preview loading
- TC-008: Generate Draft collaboration workflow behavior

Disabled by default. Enable with RUN_QT_TESTS=1.
"""

from __future__ import annotations

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

from PyQt6.QtWidgets import QApplication, QCheckBox, QInputDialog, QWidget

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.workspace_templates import TemplateFillTarget, WorkspaceTemplateSpec
from gui.workspace_tab import WorkspaceTab


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def workspace_tab(monkeypatch, qapp):
    # Keep WorkspaceTab lightweight for tests by stubbing AgentConsole.
    class _StubAgentConsole(QWidget):
        def __init__(self, db, agent_code="quill", parent=None, context_provider=None):
            super().__init__(parent)

    monkeypatch.setattr("gui.workspace_tab.AgentConsole", _StubAgentConsole)
    tab = WorkspaceTab(db=Mock(), chat_handler=Mock())
    return tab


def test_workspace_file_rows_are_clickable_and_markable(workspace_tab, tmp_path):
    sample = tmp_path / "sample.txt"
    sample.write_text("sample", encoding="utf-8")
    file_info = {
        "name": "sample.txt",
        "path": str(sample),
        "is_folder": False,
        "size": 10,
        "modified": "2026-02-19 10:00:00",
        "marked": False,
    }
    workspace_tab.add_file_to_list(file_info)

    assert workspace_tab.file_list.count() == 1
    item = workspace_tab.file_list.item(0)
    assert item.sizeHint().height() >= 40

    row_widget = workspace_tab.file_list.itemWidget(item)
    assert row_widget is not None
    checkbox = row_widget.findChild(QCheckBox)
    assert checkbox is not None
    checkbox.setChecked(True)
    assert file_info["marked"] is True


def test_workspace_preview_loads_selected_file(monkeypatch, workspace_tab, tmp_path):
    sample = tmp_path / "preview_test.txt"
    sample.write_text("Workspace preview content", encoding="utf-8")

    monkeypatch.setattr(
        "gui.workspace_tab.extract_text_from_file",
        lambda _path: "Workspace preview content",
    )

    file_info = {
        "name": "preview_test.txt",
        "path": str(sample),
        "is_folder": False,
        "size": sample.stat().st_size,
        "modified": "2026-02-19 10:00:00",
        "marked": False,
    }
    workspace_tab.add_file_to_list(file_info)
    item = workspace_tab.file_list.item(workspace_tab.file_list.count() - 1)

    workspace_tab.on_file_selected(item)

    assert "Workspace preview content" in workspace_tab.preview_text.toPlainText()
    assert "File preview loaded" in workspace_tab.status_label.text()


def test_workspace_has_single_generate_draft_button(workspace_tab):
    assert workspace_tab.generate_draft_btn.text() == "Generate Draft"
    assert not hasattr(workspace_tab, "actions_menu")


def test_workspace_generate_draft_button_click_triggers_workflow(monkeypatch, workspace_tab):
    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *args, **kwargs: ("", False),
    )

    workspace_tab.generate_draft_btn.click()
    assert "AI collaboration cancelled" in workspace_tab.status_label.text()


def test_workspace_save_markdown_writes_file(monkeypatch, workspace_tab, tmp_path):
    out_path = tmp_path / "workspace_doc.md"
    workspace_tab._current_markdown = "# Title\n\nBody"

    monkeypatch.setattr(
        "gui.workspace_tab.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(out_path), "Markdown Files (*.md)"),
    )
    workspace_tab.save_markdown()

    assert out_path.exists()
    assert out_path.read_text(encoding="utf-8") == "# Title\n\nBody"
    assert "Document saved" in workspace_tab.status_label.text()


def test_workspace_export_markdown_without_document_sets_status(workspace_tab):
    workspace_tab._current_markdown = None
    workspace_tab.export_markdown()
    assert "No document to export" in workspace_tab.status_label.text()


def test_workspace_template_export_blocks_invalid_payload(monkeypatch, workspace_tab, tmp_path):
    out_path = tmp_path / "workspace_template.docx"
    workspace_tab._current_markdown = "# Draft\n\nBody"
    workspace_tab._last_generated_template_spec = WorkspaceTemplateSpec(
        key="external:test",
        display_name="Test Template",
        title="Test Template",
        source="external",
        machine_path="machine.docx",
        human_path="human.docx",
        sections=[],
        instructions=[],
        fields=["scope"],
        values=["scope"],
        fill_targets=[
            TemplateFillTarget(
                key="value::scope",
                token_kind="VALUE",
                token_name="scope",
                label="Scope",
                order=0,
            )
        ],
    )
    workspace_tab._current_template_blocks = {"value::scope": "Applies to the pilot release."}
    workspace_tab._current_document_metadata = {}

    warning_calls = []
    monkeypatch.setattr(
        "gui.workspace_tab.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(out_path), "Word Document (*.docx)"),
    )
    monkeypatch.setattr(
        "gui.workspace_tab.QMessageBox.warning",
        lambda *args, **kwargs: warning_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        "gui.workspace_tab.render_workspace_template_to_docx",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("render should not run")),
    )

    workspace_tab.export_markdown()

    assert warning_calls
    assert "Template validation failed before export" in workspace_tab.status_label.text()


def test_workspace_collaboration_error_handler_updates_all_panes(workspace_tab):
    workspace_tab.progress_bar.setVisible(True)
    workspace_tab._on_collaboration_error_safe("unit test failure")

    assert "Error during workflow" in workspace_tab.status_label.text()
    assert workspace_tab.progress_bar.isHidden() is True
    assert "unit test failure" in workspace_tab.preview_text.toPlainText()
    assert "unit test failure" in workspace_tab.grok_text.toPlainText()
    assert "Workflow failed" in workspace_tab.chatgpt_text.toPlainText()


def test_workspace_collaboration_complete_enables_save_and_sets_markdown(workspace_tab):
    workspace_tab.save_button.setEnabled(False)
    workspace_tab.export_button.setEnabled(False)
    workspace_tab._current_markdown = ""
    result = {
        "markdown": "# Draft\n\nBody",
        "grok_output": "grok out",
        "chatgpt_output": "chatgpt out",
        "collaboration_history": [],
        "rounds": 2,
        "status": "complete",
    }

    workspace_tab._on_collaboration_complete_safe(result)

    assert workspace_tab._current_markdown == "# Draft\n\nBody"
    assert "# Draft" in workspace_tab.preview_text.toPlainText()
    assert workspace_tab.save_button.isEnabled() is True
    assert workspace_tab.export_button.isEnabled() is True
    assert "AI collaboration complete" in workspace_tab.status_label.text()
    assert "2 rounds" in workspace_tab.status_label.text()


def test_workspace_collaboration_cancelled_before_start(monkeypatch, workspace_tab):
    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *args, **kwargs: ("", False),
    )

    workspace_tab.run_ai_collaboration_workflow()
    assert "AI collaboration cancelled" in workspace_tab.status_label.text()
    assert workspace_tab._collaboration_worker is None


def test_workspace_collaboration_no_files_starts_worker(monkeypatch, workspace_tab):
    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *args, **kwargs: ("Research recent FDA AI guidance changes", True),
    )

    class _WorkerStub:
        def __init__(self, orchestrator, task_spec, file_contents):
            self.orchestrator = orchestrator
            self.task_spec = task_spec
            self.file_contents = file_contents
            self.started = False

            class _Sig:
                def connect(self, _fn):
                    return None

            self.progress_signal = _Sig()
            self.round_update_signal = _Sig()
            self.result_signal = _Sig()
            self.error_signal = _Sig()

        def start(self):
            self.started = True

    class _OrchestratorStub:
        def __init__(self, logger, grok_call, chatgpt_call):
            self.logger = logger
            self.grok_call = grok_call
            self.chatgpt_call = chatgpt_call

    monkeypatch.setattr("gui.workspace_tab.CollaborationWorker", _WorkerStub)
    monkeypatch.setattr("gui.workspace_tab.DualLLMOrchestrator", _OrchestratorStub)

    workspace_tab.selected_files = []  # explicit no-files path
    workspace_tab.run_ai_collaboration_workflow()

    assert workspace_tab._collaboration_worker is not None
    assert workspace_tab._collaboration_worker.started is True
    assert workspace_tab.progress_bar.isHidden() is False
    assert "AI collaboration" in workspace_tab.status_label.text()
    assert workspace_tab.save_button.isEnabled() is False
    assert workspace_tab.export_button.isEnabled() is False


def test_workspace_collaboration_setup_error_is_surfaceable(monkeypatch, workspace_tab):
    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *args, **kwargs: ("Create a draft from files", True),
    )
    # Force setup-time exception before worker starts.
    monkeypatch.setattr("gui.workspace_tab.WorkspaceTaskSpec", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("spec boom")))

    workspace_tab.selected_files = []
    workspace_tab.run_ai_collaboration_workflow()

    assert "Error during setup" in workspace_tab.status_label.text()
    assert "spec boom" in workspace_tab.preview_text.toPlainText()


def test_workspace_save_and_load_round_trip(monkeypatch, workspace_tab, tmp_path):
    sample = tmp_path / "alpha.txt"
    sample.write_text("alpha", encoding="utf-8")

    class _Db:
        def __init__(self):
            self.states = {}
            self.next_id = 1
            self.last_used = None
            self.session_payload = {}

        def workspace_state_upsert(self, *, name, state):
            existing = next((sid for sid, row in self.states.items() if row["name"] == name), None)
            workspace_id = existing or self.next_id
            self.states[workspace_id] = {
                "id": workspace_id,
                "name": name,
                "state_json": __import__("json").dumps(state),
            }
            if existing is None:
                self.next_id += 1
            return workspace_id

        def workspace_state_list(self):
            return [{"id": sid, "name": row["name"]} for sid, row in sorted(self.states.items())]

        def workspace_state_get(self, workspace_id):
            return self.states.get(int(workspace_id))

        def workspace_state_set_last_used(self, workspace_id):
            self.last_used = workspace_id

        def workspace_session_save(self, state):
            self.session_payload = dict(state)

        def workspace_session_load(self):
            return dict(self.session_payload)

    workspace_tab.db = _Db()
    file_info = {
        "name": "alpha.txt",
        "path": str(sample),
        "is_folder": False,
        "size": sample.stat().st_size,
        "modified": "2026-03-19 12:00:00",
        "marked": True,
    }
    workspace_tab.add_file_to_list(file_info)
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("Alpha Workspace", True))

    workspace_tab.save_workspace_as()
    assert workspace_tab.file_list.count() == 1
    assert "Workspace saved" in workspace_tab.status_label.text()

    workspace_tab.clear_workspace()
    idx = workspace_tab.saved_workspace_combo.findData(1)
    workspace_tab.saved_workspace_combo.setCurrentIndex(idx)
    workspace_tab.load_selected_workspace()

    assert workspace_tab.file_list.count() == 1
    assert workspace_tab.selected_files[0]["path"] == str(sample)
    assert workspace_tab.selected_files[0]["marked"] is True


def test_workspace_restores_last_session_on_startup(monkeypatch, qapp, tmp_path):
    sample = tmp_path / "restored.txt"
    sample.write_text("restored", encoding="utf-8")

    class _StubAgentConsole(QWidget):
        def __init__(self, db, agent_code="quill", parent=None, context_provider=None):
            super().__init__(parent)

    class _Db:
        def workspace_state_list(self):
            return []

        def workspace_state_get_last_used(self):
            return None

        def workspace_session_load(self):
            return {
                "files": [
                    {
                        "name": "restored.txt",
                        "path": str(sample),
                        "is_folder": False,
                        "size": sample.stat().st_size,
                        "modified": "2026-03-19 12:00:00",
                        "marked": True,
                    }
                ],
                "prompt_template_key": "custom",
                "document_template_key": "",
                "max_rounds": 3,
                "include_task_suggestions": True,
            }

        def workspace_session_save(self, state):
            self.state = state

    monkeypatch.setattr("gui.workspace_tab.AgentConsole", _StubAgentConsole)
    tab = WorkspaceTab(db=_Db(), chat_handler=Mock())

    assert tab.file_list.count() == 1
    assert tab.selected_files[0]["path"] == str(sample)
    assert tab.selected_files[0]["marked"] is True
