from __future__ import annotations

import os
import sys
import tempfile
from unittest.mock import patch

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def temp_db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def cos_db(temp_db_path):
    import config as config_mod
    import core.db as core_db

    with patch.object(config_mod, "DATABASE_PATH", temp_db_path):
        with patch.object(core_db, "DATABASE_PATH", temp_db_path):
            db = core_db.DatabaseManager()
            yield db


def test_create_task_from_assignment_duplicate_shows_info(qapp, cos_db, monkeypatch):
    from gui.chief_of_staff_tab import ChiefOfStaffTab

    aid = cos_db.agent_create_assignment(
        title="Duplicate task assignment",
        brief_md="Brief",
        requester_code="navi",
        assignee_code="atlas",
    )
    tab = ChiefOfStaffTab(cos_db)
    tab._current_assignment_id = int(aid)
    monkeypatch.setattr(tab, "_existing_assignment_task_ids", lambda: {int(aid)})

    called = {"info": False}

    def _info(*args, **kwargs):
        called["info"] = True
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "information", _info)
    tab._create_task_from_assignment()
    assert called["info"] is True


def test_create_task_from_assignment_invalid_due_warns(qapp, cos_db, monkeypatch):
    from gui.chief_of_staff_tab import ChiefOfStaffTab

    aid = cos_db.agent_create_assignment(
        title="Invalid due assignment",
        brief_md="Brief",
        requester_code="navi",
        assignee_code="atlas",
    )
    tab = ChiefOfStaffTab(cos_db)
    tab._current_assignment_id = int(aid)
    monkeypatch.setattr(tab, "_existing_assignment_task_ids", lambda: set())
    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *args, **kwargs: ("02-30-2026", True),
    )

    called = {"warn": False}

    def _warn(*args, **kwargs):
        called["warn"] = True
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", _warn)
    tab._create_task_from_assignment()
    assert called["warn"] is True


def test_bulk_set_filtered_priority_updates_rows(qapp, cos_db, monkeypatch):
    from gui.chief_of_staff_tab import ChiefOfStaffTab

    a1 = cos_db.agent_create_assignment(
        title="A1",
        brief_md="Brief",
        requester_code="navi",
        assignee_code="atlas",
        priority=3,
    )
    a2 = cos_db.agent_create_assignment(
        title="A2",
        brief_md="Brief",
        requester_code="navi",
        assignee_code="atlas",
        priority=4,
    )
    tab = ChiefOfStaffTab(cos_db)
    monkeypatch.setattr(tab, "_filtered_assignment_rows", lambda: [{"id": int(a1)}, {"id": int(a2)}])
    monkeypatch.setattr(QInputDialog, "getInt", lambda *args, **kwargs: (1, True))
    monkeypatch.setattr(tab, "_prompt_optional_bulk_note", lambda _title: (True, None))
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)

    tab._bulk_set_filtered_priority()
    assert int((cos_db.agent_get_assignment(int(a1)) or {}).get("priority") or 0) == 1
    assert int((cos_db.agent_get_assignment(int(a2)) or {}).get("priority") or 0) == 1


def test_bulk_set_filtered_due_rejects_invalid_calendar_date(qapp, cos_db, monkeypatch):
    from gui.chief_of_staff_tab import ChiefOfStaffTab

    aid = cos_db.agent_create_assignment(
        title="A3",
        brief_md="Brief",
        requester_code="navi",
        assignee_code="atlas",
        due_date="2026-03-10",
    )
    tab = ChiefOfStaffTab(cos_db)
    monkeypatch.setattr(tab, "_filtered_assignment_rows", lambda: [{"id": int(aid)}])
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("2026-02-30", True))

    called = {"warn": False}

    def _warn(*args, **kwargs):
        called["warn"] = True
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", _warn)
    tab._bulk_set_filtered_due()
    assert called["warn"] is True
    assert (cos_db.agent_get_assignment(int(aid)) or {}).get("due_date") == "2026-03-10"


def test_bulk_reassign_filtered_assignments_no_assignees(qapp, cos_db, monkeypatch):
    from gui.chief_of_staff_tab import ChiefOfStaffTab

    aid = cos_db.agent_create_assignment(
        title="A4",
        brief_md="Brief",
        requester_code="navi",
        assignee_code="atlas",
    )
    tab = ChiefOfStaffTab(cos_db)
    monkeypatch.setattr(tab, "_filtered_assignment_rows", lambda: [{"id": int(aid), "assignee_code": "atlas"}])
    monkeypatch.setattr(cos_db, "agents_list_active", lambda: [{"code": "navi", "display_name": "Navi"}])

    called = {"info": False}

    def _info(*args, **kwargs):
        called["info"] = True
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "information", _info)
    tab._bulk_reassign_filtered_assignments()
    assert called["info"] is True


def test_bulk_create_tasks_open_only_skips_closed_and_existing(qapp, cos_db, monkeypatch):
    from gui.chief_of_staff_tab import ChiefOfStaffTab

    open_aid = cos_db.agent_create_assignment(
        title="Open assignment",
        brief_md="Brief",
        requester_code="navi",
        assignee_code="atlas",
        status="queued",
        due_date="2026-03-10",
    )
    closed_aid = cos_db.agent_create_assignment(
        title="Closed assignment",
        brief_md="Brief",
        requester_code="navi",
        assignee_code="atlas",
        status="done",
    )
    existing_aid = cos_db.agent_create_assignment(
        title="Existing assignment",
        brief_md="Brief",
        requester_code="navi",
        assignee_code="atlas",
        status="queued",
    )

    # Seed an existing dashboard task linked to existing_aid.
    cos_db.add_task(
        session_id="seed",
        task_text=f"[A-{int(existing_aid):04d}] Existing assignment",
        due_date="",
        category="Business",
        recurrence="None",
        completed=0,
    )

    tab = ChiefOfStaffTab(cos_db)
    monkeypatch.setattr(
        tab,
        "_filtered_assignment_rows",
        lambda: [
            {"id": int(open_aid), "title": "Open assignment", "status": "queued", "due_date": "2026-03-10"},
            {"id": int(closed_aid), "title": "Closed assignment", "status": "done", "due_date": None},
            {"id": int(existing_aid), "title": "Existing assignment", "status": "queued", "due_date": None},
        ],
    )

    responses = iter(
        [
            ("Business", True),  # category
            ("Open only", True),  # include closed?
        ]
    )
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(tab, "_prompt_optional_bulk_note", lambda _title: (True, None))
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)

    tab._bulk_create_tasks_from_filtered_assignments()

    tasks = cos_db.get_tasks(category=None, date_filter=None, specific_date=None)
    texts = [str(t[1] or "") for t in tasks]
    assert any(f"[A-{int(open_aid):04d}]" in txt for txt in texts)
    assert not any(f"[A-{int(closed_aid):04d}]" in txt for txt in texts)
    # Existing one should still be singular.
    assert sum(1 for txt in texts if f"[A-{int(existing_aid):04d}]" in txt) == 1


def test_bulk_set_filtered_status_cancelled_confirmation_makes_no_changes(qapp, cos_db, monkeypatch):
    from gui.chief_of_staff_tab import ChiefOfStaffTab

    aid = cos_db.agent_create_assignment(
        title="Status target",
        brief_md="Brief",
        requester_code="navi",
        assignee_code="atlas",
        status="queued",
    )
    tab = ChiefOfStaffTab(cos_db)
    monkeypatch.setattr(tab, "_filtered_assignment_rows", lambda: [{"id": int(aid)}])
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args, **kwargs: ("done", True))
    monkeypatch.setattr(tab, "_prompt_optional_bulk_note", lambda _title: (True, None))
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No)

    tab._bulk_set_filtered_status()
    assert (cos_db.agent_get_assignment(int(aid)) or {}).get("status") == "queued"
