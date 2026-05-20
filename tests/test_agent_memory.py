import os
import sqlite3
import sys
import tempfile
from unittest.mock import patch

import pytest

from core import agent_chat_service
# Tests for agent memory cover Pulse private reflections (pulse_theme_reflection), Intel findings, and Shield [Security-Relevant] storage (private memory tests)


def _db_for_temp_path(path: str):
    import config as config_mod
    import core.db as core_db

    with patch.object(config_mod, "DATABASE_PATH", path):
        with patch.object(core_db, "DATABASE_PATH", path):
            return core_db.DatabaseManager()


def test_build_agent_memory_context_uses_only_requested_agent_memory():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = _db_for_temp_path(path)
        db.agent_memory_add(
            agent_code="atlas",
            kind="fact",
            content="Atlas has prior Acme context about FDA-first regulatory summaries.",
            approval_status="approved",
        )
        db.agent_memory_add(
            agent_code="quill",
            kind="fact",
            content="Quill prefers style-guide-heavy drafting language.",
            approval_status="approved",
        )

        from core.agent_memory import build_agent_memory_context

        # FTS-only retrieval: query must match indexed agent_memory content (recent list no longer merged).
        atlas_context = build_agent_memory_context(db, "atlas", "Acme FDA regulatory", limit=5, recent_limit=2)
        assert "Atlas has prior Acme context" in atlas_context
        assert "Quill prefers style-guide-heavy" not in atlas_context
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_build_supervisor_cross_memory_context_includes_agent_and_assignment_memory():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = _db_for_temp_path(path)
        db.agent_memory_add(
            agent_code="atlas",
            kind="fact",
            content="Atlas has prior Acme context about FDA-first regulatory summaries.",
            approval_status="approved",
        )
        db.assignment_memory_add(
            assignment_id=7,
            thread_id=12,
            agent_code="atlas",
            kind="fact",
            content="Predicate shortlist still needs confirmation.",
        )

        from core.agent_memory import build_supervisor_cross_memory_context

        context = build_supervisor_cross_memory_context(
            db,
            "What does Atlas remember about Acme and A-0007?",
            limit_agents=2,
            agent_memory_limit=3,
            assignment_memory_limit=4,
        )
        assert "Atlas has prior Acme context" in context
        assert "Predicate shortlist still needs confirmation." in context
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_agent_chat_response_injects_agent_memory_without_cross_agent_leakage():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = _db_for_temp_path(path)
        db.agent_memory_add(
            agent_code="atlas",
            kind="preference",
            content="Atlas should prioritize FDA-primary material for Acme.",
            approval_status="approved",
        )
        db.agent_memory_add(
            agent_code="quill",
            kind="preference",
            content="Quill should favor template-driven drafting.",
            approval_status="approved",
        )
        db.user_memory_add(
            kind="preference",
            content="User prefers concise answers.",
            approval_status="approved",
        )

        captured = {}

        def _fake_completion(messages, model=None):
            captured["messages"] = messages
            captured["model"] = model
            return "Atlas reply"

        with patch.object(agent_chat_service, "grok_available", return_value=(True, "available")):
            with patch.object(agent_chat_service, "grok_completion_messages", side_effect=_fake_completion):
                with patch.object(agent_chat_service, "auto_store_agent_memory", return_value=1) as store_mock:
                    out = agent_chat_service.agent_chat_response(
                        db,
                        agent_code="atlas",
                        user_message="Please help with Acme regulatory strategy.",
                        conversation_history=[],
                    )

        assert out == "Atlas reply"
        joined = "\n\n".join(str(m.get("content") or "") for m in captured["messages"])
        assert "Atlas should prioritize FDA-primary material for Acme." in joined
        assert "User prefers concise answers." in joined
        assert "Quill should favor template-driven drafting." not in joined
        assert store_mock.call_count == 1
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_store_teach_memory_routes_to_agent_memory():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = _db_for_temp_path(path)

        from core.user_memory import store_teach_memory

        response = store_teach_memory(db, "Teach Atlas: Acme means Acme Biotech.")

        assert response is not None
        assert "Atlas" in response
        rows = db.agent_memory_search(agent_code="atlas", query="Acme", approval_status="approved", limit=5)
        assert len(rows) == 1
        assert rows[0][2] == "alias"
        assert "Acme means Acme Biotech." in str(rows[0][3])
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def test_global_memory_dialog_filters_agent_scope(qapp):
    if sys.platform == "win32":
        pytest.skip("Qt dialog teardown is unstable on this Windows environment.")
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = _db_for_temp_path(path)
        db.agent_memory_add(
            agent_code="atlas",
            kind="fact",
            content="Atlas remembers Acme prefers FDA-primary summaries.",
            approval_status="approved",
        )
        db.agent_memory_add(
            agent_code="quill",
            kind="fact",
            content="Quill remembers the style guide version.",
            approval_status="approved",
        )

        from gui.chief_of_staff_tab import GlobalMemoryDialog

        dialog = GlobalMemoryDialog(db=db)
        dialog.scope_filter.setCurrentIndex(dialog.scope_filter.findData("agent"))
        dialog.agent_filter.setCurrentIndex(dialog.agent_filter.findData("atlas"))
        dialog._reload()

        assert dialog.memory_list.count() == 1
        label = dialog.memory_list.item(0).text()
        assert "atlas" in label.lower()
        assert "quill" not in label.lower()
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_promote_agent_memory_to_global_dedupes_exact_content():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = _db_for_temp_path(path)
        agent_mem_id = db.agent_memory_add(
            agent_code="atlas",
            kind="fact",
            content="Atlas learned Acme prefers FDA-primary summaries.",
            approval_status="approved",
        )

        from core.agent_memory import promote_agent_memory_to_global

        first_id, first_created = promote_agent_memory_to_global(db, memory_id=agent_mem_id)
        second_id, second_created = promote_agent_memory_to_global(db, memory_id=agent_mem_id)

        assert first_id > 0
        assert first_created is True
        assert second_id == first_id
        assert second_created is False

        rows = db.user_memory_search(
            query="Atlas learned Acme prefers FDA-primary summaries.",
            kind="fact",
            approval_status="approved",
            limit=10,
        )
        assert len(rows) == 1
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_assignment_memory_round_trip():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = _db_for_temp_path(path)
        mem_id = db.assignment_memory_add(
            assignment_id=7,
            thread_id=12,
            agent_code="atlas",
            kind="fact",
            content="Predicate shortlist still needs confirmation.",
            source="assignment_chat",
            json_data={"origin": "thread reply"},
        )
        assert mem_id > 0

        recent = db.assignment_memory_recent(assignment_id=7, limit=5)
        assert len(recent) == 1
        assert int(recent[0][1] or 0) == 7
        assert "Predicate shortlist" in str(recent[0][5])

        search = db.assignment_memory_search(query="Predicate", assignment_id=7, limit=5)
        assert len(search) == 1
        assert int(search[0][0]) == mem_id
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_agent_chat_response_injects_assignment_memory():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = _db_for_temp_path(path)
        db.assignment_memory_add(
            assignment_id=7,
            thread_id=12,
            agent_code="atlas",
            kind="fact",
            content="Predicate shortlist still needs confirmation.",
        )

        captured = {}

        def _fake_completion(messages, model=None):
            captured["messages"] = messages
            return "Atlas reply"

        with patch.object(agent_chat_service, "grok_available", return_value=(True, "available")):
            with patch.object(agent_chat_service, "grok_completion_messages", side_effect=_fake_completion):
                with patch.object(agent_chat_service, "auto_store_agent_memory", return_value=1):
                    with patch.object(agent_chat_service, "auto_store_assignment_memory", return_value=1):
                        out = agent_chat_service.agent_chat_response(
                            db,
                            agent_code="atlas",
                            user_message="What should I do next for this assignment?",
                            conversation_history=[],
                            assignment_id=7,
                            thread_id=12,
                        )

        assert out == "Atlas reply"
        joined = "\n\n".join(str(m.get("content") or "") for m in captured["messages"])
        assert "Predicate shortlist still needs confirmation." in joined
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_global_memory_dialog_promotes_agent_memory_to_global(qapp, monkeypatch):
    if sys.platform == "win32":
        pytest.skip("Qt dialog teardown is unstable on this Windows environment.")
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = _db_for_temp_path(path)
        db.agent_memory_add(
            agent_code="atlas",
            kind="fact",
            content="Atlas learned Acme prefers FDA-primary summaries.",
            approval_status="approved",
        )

        from PyQt6.QtWidgets import QMessageBox
        from gui.chief_of_staff_tab import GlobalMemoryDialog

        monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
        monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)

        dialog = GlobalMemoryDialog(db=db)
        dialog.scope_filter.setCurrentIndex(dialog.scope_filter.findData("agent"))
        dialog.agent_filter.setCurrentIndex(dialog.agent_filter.findData("atlas"))
        dialog._reload()
        dialog.memory_list.setCurrentRow(0)

        dialog._promote_selected_to_global()

        global_rows = db.user_memory_search(
            query="Atlas learned Acme prefers FDA-primary summaries.",
            kind="fact",
            approval_status="approved",
            limit=10,
        )
        assert len(global_rows) == 1
        assert "promoted_agent_memory" in str(global_rows[0][3])
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_promote_assignment_memory_to_agent_dedupes_exact_content():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = _db_for_temp_path(path)
        assignment_mem_id = db.assignment_memory_add(
            assignment_id=7,
            thread_id=12,
            agent_code="atlas",
            kind="fact",
            content="Predicate shortlist still needs confirmation.",
        )

        from core.agent_memory import promote_assignment_memory_to_agent

        first_id, first_created = promote_assignment_memory_to_agent(db, memory_id=assignment_mem_id)
        second_id, second_created = promote_assignment_memory_to_agent(db, memory_id=assignment_mem_id)

        assert first_id > 0
        assert first_created is True
        assert second_id == first_id
        assert second_created is False

        rows = db.agent_memory_search(
            agent_code="atlas",
            query="Predicate shortlist still needs confirmation.",
            kind="fact",
            approval_status="approved",
            limit=10,
        )
        assert len(rows) == 1
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_global_memory_dialog_filters_assignment_scope(qapp):
    if sys.platform == "win32":
        pytest.skip("Qt dialog teardown is unstable on this Windows environment.")
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = _db_for_temp_path(path)
        db.assignment_memory_add(
            assignment_id=7,
            thread_id=12,
            agent_code="atlas",
            kind="fact",
            content="Predicate shortlist still needs confirmation.",
        )
        db.assignment_memory_add(
            assignment_id=8,
            thread_id=13,
            agent_code="quill",
            kind="fact",
            content="Template selection still pending.",
        )

        from gui.chief_of_staff_tab import GlobalMemoryDialog

        dialog = GlobalMemoryDialog(db=db)
        dialog.scope_filter.setCurrentIndex(dialog.scope_filter.findData("assignment"))
        dialog.assignment_filter.setText("A-0007")
        dialog._reload()

        assert dialog.memory_list.count() == 1
        label = dialog.memory_list.item(0).text()
        assert "a-0007" in label.lower()
        assert "template selection still pending" not in label.lower()
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_global_memory_dialog_promotes_assignment_memory_to_agent(qapp, monkeypatch):
    if sys.platform == "win32":
        pytest.skip("Qt dialog teardown is unstable on this Windows environment.")
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = _db_for_temp_path(path)
        db.assignment_memory_add(
            assignment_id=7,
            thread_id=12,
            agent_code="atlas",
            kind="fact",
            content="Predicate shortlist still needs confirmation.",
        )

        from PyQt6.QtWidgets import QMessageBox
        from gui.chief_of_staff_tab import GlobalMemoryDialog

        monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
        monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)

        dialog = GlobalMemoryDialog(db=db)
        dialog.scope_filter.setCurrentIndex(dialog.scope_filter.findData("assignment"))
        dialog.assignment_filter.setText("A-0007")
        dialog._reload()
        dialog.memory_list.setCurrentRow(0)

        dialog._promote_selected_to_global()

        agent_rows = db.agent_memory_search(
            agent_code="atlas",
            query="Predicate shortlist still needs confirmation.",
            kind="fact",
            approval_status="approved",
            limit=10,
        )
        assert len(agent_rows) == 1
        assert "promoted_assignment_memory" in str(agent_rows[0][4])
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
