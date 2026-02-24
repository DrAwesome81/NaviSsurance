"""
Tests for the Chief of Staff (CoS) feature: DB layer, service layer, and UI smoke.

- Database: CoS tables and CRUD using a temporary SQLite file (no real DB modified).
- Service: cos_response with mocked Grok (no API calls).
- UI: ChiefOfStaffTab instantiates and builds sub-views (requires Qt).

Run: pytest tests/test_chief_of_staff.py -v
     pytest tests/test_chief_of_staff.py -v -m "not qt"   # skip Qt test
"""

import json
import os
import sys
import tempfile
from datetime import datetime, UTC
from unittest.mock import patch, MagicMock

import pytest

# Add project root for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# -----------------------------------------------------------------------------
# Database layer tests (isolated temp DB)
# -----------------------------------------------------------------------------


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
    """DatabaseManager using a temporary DB file so CoS tables exist after migration."""
    import config as config_mod
    import core.db as core_db
    with patch.object(config_mod, "DATABASE_PATH", temp_db_path):
        with patch.object(core_db, "DATABASE_PATH", temp_db_path):
            db = core_db.DatabaseManager()
            yield db


class TestCosDatabaseProjects:
    """Test cos_projects CRUD."""

    def test_insert_and_get_project(self, cos_db):
        pid = cos_db.cos_insert_project(
            name="Test Project",
            client="Acme",
            description="A test",
            status="Active",
            priority=1,
            deadline="2025-03-01",
            next_action="Do something",
            blockers="None",
            tags="DHF, Audit",
        )
        assert pid is not None
        row = cos_db.cos_get_project(pid)
        assert row is not None
        assert row[1] == "Test Project"
        assert row[2] == "Acme"
        assert row[4] == "Active"
        assert row[9] == "DHF, Audit"

    def test_get_projects_filter_status(self, cos_db):
        cos_db.cos_insert_project(name="A", status="Active")
        cos_db.cos_insert_project(name="B", status="Waiting")
        cos_db.cos_insert_project(name="C", status="Active")
        active = cos_db.cos_get_projects(status="Active")
        assert len(active) == 2
        all_rows = cos_db.cos_get_projects()
        assert len(all_rows) >= 3

    def test_update_project(self, cos_db):
        pid = cos_db.cos_insert_project(name="Original", status="Active")
        cos_db.cos_update_project(pid, name="Updated", status="Done")
        row = cos_db.cos_get_project(pid)
        assert row[1] == "Updated"
        assert row[4] == "Done"

    def test_delete_project(self, cos_db):
        pid = cos_db.cos_insert_project(name="To delete", status="Active")
        cos_db.cos_delete_project(pid)
        assert cos_db.cos_get_project(pid) is None


class TestCosDatabaseChats:
    """Test cos_chats (chat list for CoS sidebar)."""

    def test_cos_create_chat_and_get_chats(self, cos_db):
        cid = cos_db.cos_create_chat(title="Weekly planning", project="NaviSsurance")
        assert cid is not None
        chats = cos_db.cos_get_chats()
        assert len(chats) >= 1
        id_, title, project, created_at, updated_at = chats[0]
        assert id_ == cid
        assert title == "Weekly planning"
        assert project == "NaviSsurance"

    def test_cos_update_chat(self, cos_db):
        cid = cos_db.cos_create_chat(title="Old", project=None)
        cos_db.cos_update_chat(cid, title="New title", project="Work")
        row = cos_db.cos_get_chat(cid)
        assert row[1] == "New title"
        assert row[2] == "Work"


class TestCosDatabasePreferences:
    """Test cos_preferences (single row id=1)."""

    def test_get_preferences_empty(self, cos_db):
        row = cos_db.cos_get_preferences()
        assert row is not None
        operating_system_md, blocked_times_json, deep_work_hours, behavior_prefs_json, updated_at = row
        assert operating_system_md is None or operating_system_md == ""
        assert deep_work_hours is None or deep_work_hours == 0

    def test_set_and_get_preferences(self, cos_db):
        cos_db.cos_set_preferences(
            operating_system_md="# Priorities\nTime freedom first.",
            blocked_times_json='[{"day":"weekday","start":"11:00","end":"12:00"}]',
            deep_work_hours=3,
            behavior_prefs_json='{"tone":"direct"}',
        )
        row = cos_db.cos_get_preferences()
        assert row is not None
        assert "Time freedom" in (row[0] or "")
        assert "11:00" in (row[1] or "")
        assert row[2] == 3
        assert "direct" in (row[3] or "")


class TestCosDatabasePlans:
    """Test cos_weekly_plans and cos_daily_plans."""

    def test_insert_weekly_plan(self, cos_db):
        plan_id = cos_db.cos_insert_weekly_plan(
            week_start="2025-02-10",
            plan_md="# Weekly Objective\nShip the thing.",
            inputs_snapshot_json='{"week_start":"2025-02-10"}',
        )
        assert plan_id is not None
        plans = cos_db.cos_get_weekly_plans(limit=5)
        assert len(plans) >= 1
        id_, week_start, plan_md, snapshot, created = plans[0]
        assert week_start == "2025-02-10"
        assert "Weekly Objective" in plan_md

    def test_get_latest_weekly_plan(self, cos_db):
        cos_db.cos_insert_weekly_plan("2025-02-03", "Old plan", None)
        cos_db.cos_insert_weekly_plan("2025-02-10", "New plan", None)
        latest = cos_db.cos_get_latest_weekly_plan()
        assert latest is not None
        # One of the two plans (order by created_at DESC; ties possible in same second)
        assert latest[2] in ("Old plan", "New plan")
        assert latest[1] in ("2025-02-03", "2025-02-10")

    def test_insert_daily_plan(self, cos_db):
        plan_id = cos_db.cos_insert_daily_plan("2025-02-11", "# Focus\nWrite tests.")
        assert plan_id is not None
        row = cos_db.cos_get_daily_plan_for_date("2025-02-11")
        assert row is not None
        assert "Write tests" in row[2]


class TestAgentAssignments:
    """Test assignment summary + artifact linkage helpers."""

    def test_result_summary_and_artifacts(self, cos_db):
        aid = cos_db.agent_create_assignment(
            title="Summarize findings",
            brief_md="Prepare concise summary",
            requester_code="navi",
            assignee_code="atlas",
            priority=2,
        )
        assert aid is not None and aid > 0

        ok = cos_db.agent_set_assignment_result_summary(
            assignment_id=int(aid),
            summary_md="Key findings captured with recommended next steps.",
            actor_code="atlas",
        )
        assert ok is True
        row = cos_db.agent_get_assignment(int(aid))
        assert row is not None
        assert "Key findings" in (row.get("result_summary_md") or "")

        art_id = cos_db.agent_add_artifact(
            artifact_type="agent_reply",
            assignment_id=int(aid),
            title="Atlas update",
            content_md="Draft summary artifact body.",
        )
        assert art_id is not None and art_id > 0
        arts = cos_db.agent_list_artifacts(assignment_id=int(aid), limit=10)
        assert any(int(a.get("id") or 0) == int(art_id) for a in arts)

        events = cos_db.agent_get_assignment_events(assignment_id=int(aid), limit=50)
        assert any(str(e.get("event_type") or "") == "result_summary_updated" for e in events)


# -----------------------------------------------------------------------------
# Service layer tests (mocked Grok, no network)
# -----------------------------------------------------------------------------


@patch("core.chief_of_staff_service.grok_completion")
class TestChiefOfStaffService:
    """Test cos_response with mocked grok_completion."""

    def test_cos_response_returns_model_output(self, mock_grok, cos_db):
        mock_grok.return_value = "Focus on Project A for the next 90 minutes. Defer the rest."
        from core.chief_of_staff_service import cos_response
        result = cos_response(cos_db, "What should I focus on right now?")
        assert "Focus" in result or "Project" in result
        # Calendar/memory extraction may be gated; core response should still call Grok at least once.
        assert mock_grok.call_count >= 1

    def test_cos_response_default_prompt_when_empty_message(self, mock_grok, cos_db):
        mock_grok.return_value = "Here’s what I recommend."
        from core.chief_of_staff_service import cos_response
        result = cos_response(cos_db, "")
        assert "recommend" in result or "Here" in result
        assert mock_grok.call_count >= 1
        # grok_completion(system, user, ...) — user is second positional
        user_passed = mock_grok.call_args[0][1]
        assert "What should I focus on right now" in user_passed

    def test_cos_response_on_error_returns_message(self, mock_grok, cos_db):
        mock_grok.side_effect = Exception("API error")
        from core.chief_of_staff_service import cos_response
        result = cos_response(cos_db, "Help")
        assert "Error" in result

    def test_cos_response_injects_dashboard_tasks_into_prompt(self, mock_grok, cos_db):
        """Dashboard tasks are included in the prompt sent to Grok."""
        cos_db.add_task(
            session_id="test_sess",
            task_text="Ship the DHF report",
            due_date="02-20-2026",
            category="Business",
            recurrence="None",
            completed=0,
        )
        mock_grok.return_value = "Focus on the report first."
        from core.chief_of_staff_service import cos_response
        cos_response(cos_db, "What should I do today?")
        user_passed = mock_grok.call_args[0][1]
        assert "**Dashboard tasks:**" in user_passed
        assert "Ship the DHF report" in user_passed

    def test_cos_response_parses_single_add_task_and_adds_to_db(self, mock_grok, cos_db):
        """One ADD_TASK line in the reply is parsed, task inserted, line stripped from reply."""
        mock_grok.return_value = "Here is my advice.\nADD_TASK: Send follow-up to client | 02-25-2026 | Business\nHope that helps."
        from core.chief_of_staff_service import cos_response
        result = cos_response(cos_db, "Add a follow-up task.")
        tasks = cos_db.get_tasks(category=None, date_filter=None, specific_date=None)
        assert len(tasks) == 1
        assert tasks[0][1] == "Send follow-up to client"
        assert tasks[0][2] == "02-25-2026"
        assert tasks[0][3] == "Business"
        assert "Added 1 task(s)" in result
        assert "ADD_TASK:" not in result

    def test_cos_response_parses_multiple_add_tasks(self, mock_grok, cos_db):
        """Multiple ADD_TASK lines in one reply add multiple tasks."""
        mock_grok.return_value = (
            "I've added these:\n"
            "ADD_TASK: Call dentist | none | Personal\n"
            "ADD_TASK: Review Q1 numbers | 02-28-2026 | Business\n"
            "Done."
        )
        from core.chief_of_staff_service import cos_response
        result = cos_response(cos_db, "Add these tasks.")
        tasks = cos_db.get_tasks(category=None, date_filter=None, specific_date=None)
        assert len(tasks) == 2
        texts = {t[1] for t in tasks}
        assert "Call dentist" in texts
        assert "Review Q1 numbers" in texts
        assert "Added 2 task(s)" in result

    def test_cos_response_add_task_with_none_date(self, mock_grok, cos_db):
        """ADD_TASK with due date 'none' stores task with no date."""
        mock_grok.return_value = "ADD_TASK: Call mom | none | Personal"
        from core.chief_of_staff_service import cos_response
        cos_response(cos_db, "Add a personal task.")
        tasks = cos_db.get_tasks(category=None, date_filter=None, specific_date=None)
        assert len(tasks) == 1
        assert tasks[0][1] == "Call mom"
        assert tasks[0][2] in (None, "", "none")
        assert tasks[0][3] == "Personal"

    def test_cos_response_parses_add_cal_block_and_creates_event(self, mock_grok, cos_db):
        """ADD_CAL_BLOCK creates one Google Calendar event and strips command line from response."""
        mock_grok.return_value = (
            "Done.\n"
            "ADD_CAL_BLOCK: Deep work - DHF | 2026-02-25T13:00:00-05:00 | 2026-02-25T14:30:00-05:00 | primary"
        )
        from core.chief_of_staff_service import cos_response

        with patch("core.chief_of_staff_service.create_calendar_event") as mock_create:
            mock_create.return_value = (True, "", {"id": "evt_123"})
            result = cos_response(cos_db, "Please schedule this on my calendar.")

        assert mock_create.call_count == 1
        kwargs = mock_create.call_args.kwargs
        assert kwargs.get("summary") == "Deep work - DHF"
        assert kwargs.get("calendar_id") == "primary"
        assert "ADD_CAL_BLOCK:" not in result
        assert "Scheduled 1 calendar block(s)" in result

    def test_cos_response_add_cal_block_invalid_time(self, mock_grok, cos_db):
        """Invalid ADD_CAL_BLOCK datetime input reports failure and does not call calendar API."""
        mock_grok.return_value = "ADD_CAL_BLOCK: Deep work | not-a-date | still-not-a-date | primary"
        from core.chief_of_staff_service import cos_response

        with patch("core.chief_of_staff_service.create_calendar_event") as mock_create:
            result = cos_response(cos_db, "Schedule a block.")

        assert mock_create.call_count == 0
        assert "Could not schedule 1 calendar block(s)" in result

    def test_cos_response_parses_assign_and_creates_assignment(self, mock_grok, cos_db):
        """ASSIGN line creates one delegation assignment and strips command line from output."""
        mock_grok.return_value = (
            "Done.\n"
            "ASSIGN: Atlas | FDA PCCP research brief | Summarize latest FDA PCCP guidance with citations. | P1 | 2026-03-01"
        )
        from core.chief_of_staff_service import cos_response

        result = cos_response(cos_db, "Please delegate this research.")
        rows = cos_db.agent_list_assignments(assignee_code="atlas", limit=10)
        assert len(rows) == 1
        assert rows[0]["title"] == "FDA PCCP research brief"
        assert rows[0]["priority"] == 1
        assert rows[0]["due_date"] == "2026-03-01"
        assert rows[0]["source_thread_id"] is not None
        thread = cos_db.agent_get_thread(int(rows[0]["source_thread_id"]))
        assert thread is not None
        assert str(thread[1]).lower() == "atlas"
        assert "Created 1 assignment(s)" in result
        assert "ASSIGN:" not in result

    def test_cos_response_assign_unknown_agent_reports_failure(self, mock_grok, cos_db):
        """ASSIGN with unknown assignee should not create assignment and should report failure."""
        mock_grok.return_value = "ASSIGN: NotARealAgent | Task | Brief | P2 | none"
        from core.chief_of_staff_service import cos_response

        result = cos_response(cos_db, "Delegate this.")
        rows = cos_db.agent_list_assignments(limit=10)
        assert len(rows) == 0
        assert "Could not process 1 assignment action(s)" in result

    def test_cos_response_updates_assignment_status(self, mock_grok, cos_db):
        """UPDATE_ASSIGNMENT_STATUS updates assignment state by reference id."""
        aid = cos_db.agent_create_assignment(
            title="Initial assignment",
            brief_md="Do work",
            requester_code="navi",
            assignee_code="atlas",
            priority=3,
        )
        mock_grok.return_value = f"UPDATE_ASSIGNMENT_STATUS: A-{int(aid):04d} | in_progress | Started"
        from core.chief_of_staff_service import cos_response

        result = cos_response(cos_db, "Mark it started.")
        row = cos_db.agent_get_assignment(int(aid))
        assert row is not None
        assert str(row.get("status") or "") == "in_progress"
        assert "Updated 1 assignment(s)" in result
        assert "UPDATE_ASSIGNMENT_STATUS:" not in result

    def test_cos_response_updates_assignment_status_synonym(self, mock_grok, cos_db):
        """Natural status synonym like 'completed' should normalize to canonical 'done'."""
        aid = cos_db.agent_create_assignment(
            title="Close assignment",
            brief_md="Finish task",
            requester_code="navi",
            assignee_code="atlas",
            priority=3,
        )
        mock_grok.return_value = f"UPDATE_ASSIGNMENT_STATUS: A-{int(aid):04d} | completed | Wrapped up"
        from core.chief_of_staff_service import cos_response

        result = cos_response(cos_db, "Mark it complete.")
        row = cos_db.agent_get_assignment(int(aid))
        assert row is not None
        assert str(row.get("status") or "") == "done"
        assert "Updated 1 assignment(s)" in result

    def test_cos_response_reassigns_assignment(self, mock_grok, cos_db):
        """REASSIGN moves assignment to a new assignee and relinks source thread."""
        aid = cos_db.agent_create_assignment(
            title="Draft document",
            brief_md="Write draft",
            requester_code="navi",
            assignee_code="atlas",
            priority=2,
        )
        mock_grok.return_value = f"REASSIGN: A-{int(aid):04d} | Quill | Better fit for writing"
        from core.chief_of_staff_service import cos_response

        result = cos_response(cos_db, "Reassign this one.")
        row = cos_db.agent_get_assignment(int(aid))
        assert row is not None
        assert str(row.get("assignee_code") or "") == "quill"
        assert row.get("source_thread_id") is not None
        thread = cos_db.agent_get_thread(int(row.get("source_thread_id")))
        assert thread is not None
        assert str(thread[1]).lower() == "quill"
        assert "Reassigned 1 assignment(s)" in result
        assert "REASSIGN:" not in result

    def test_cos_response_updates_assignment_summary(self, mock_grok, cos_db):
        """UPDATE_ASSIGNMENT_SUMMARY stores result summary on assignment."""
        aid = cos_db.agent_create_assignment(
            title="Summarize run",
            brief_md="Prepare summary",
            requester_code="navi",
            assignee_code="atlas",
            priority=2,
        )
        mock_grok.return_value = (
            f"UPDATE_ASSIGNMENT_SUMMARY: A-{int(aid):04d} | "
            "Atlas completed analysis and attached references."
        )
        from core.chief_of_staff_service import cos_response

        result = cos_response(cos_db, "Record the assignment summary.")
        row = cos_db.agent_get_assignment(int(aid))
        assert row is not None
        assert "Atlas completed analysis" in str(row.get("result_summary_md") or "")
        assert "Updated summary for 1 assignment(s)" in result
        assert "UPDATE_ASSIGNMENT_SUMMARY:" not in result


@patch("core.chief_of_staff_service.grok_completion_messages")
def test_cos_response_with_history_uses_multi_turn(mock_grok_messages, cos_db):
    """With conversation_history, cos_response uses grok_completion_messages."""
    mock_grok_messages.return_value = "Given that, I'd still prioritize the DHF first."
    from core.chief_of_staff_service import cos_response
    history = [("user", "I'm on the DHF."), ("assistant", "Focus 90 min on it.")]
    result = cos_response(cos_db, "But the client asked for a quote by Friday.", conversation_history=history)
    assert "prioritize" in result or "DHF" in result
    assert mock_grok_messages.call_count >= 1
    call_messages = mock_grok_messages.call_args[0][0]
    assert any(m.get("role") == "assistant" and "Focus 90" in (m.get("content") or "") for m in call_messages)


# -----------------------------------------------------------------------------
# UI smoke test (Chief of Staff tab builds; requires Qt)
# -----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def qapp():
    """QApplication for Qt-dependent tests."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.mark.qt
def test_chief_of_staff_tab_creates(qapp, cos_db):
    """ChiefOfStaffTab: only chat window, entry box, and chat history panel on the right."""
    from gui.chief_of_staff_tab import ChiefOfStaffTab

    tab = ChiefOfStaffTab(cos_db)
    assert tab is not None
    assert hasattr(tab, "chat_display")
    assert hasattr(tab, "chat_list")
    assert hasattr(tab, "ask_input")
    assert hasattr(tab, "ask_btn")
