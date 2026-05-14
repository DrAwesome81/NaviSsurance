from core.task_command_contract import (
    AddProjectCommand,
    AddTaskCommand,
    ProjectSetDeadlineCommand,
    TaskDeleteCommand,
    extract_first_duration_phrase,
    normalize_mmddyyyy,
    parse_action_line,
    parse_add_task_line,
    parse_duration_to_minutes,
)


def test_normalize_mmddyyyy_accepts_none_and_iso():
    ok, v = normalize_mmddyyyy("none")
    assert ok is True
    assert v is None

    ok, v = normalize_mmddyyyy("2026-03-01")
    assert ok is True
    assert v == "03-01-2026"

    ok, v = normalize_mmddyyyy("03-01-2026")
    assert ok is True
    assert v == "03-01-2026"


def test_parse_add_task_line_canonical_minimal():
    ok, cmd, reason = parse_add_task_line("ADD_TASK: Call client | 03-01-2026 | Business")
    assert ok is True
    assert reason == ""
    assert isinstance(cmd, AddTaskCommand)
    assert cmd.description == "Call client"
    assert cmd.due_date == "03-01-2026"
    assert cmd.category == "Business"


def test_parse_add_task_line_with_optional_fields():
    ok, cmd, _reason = parse_add_task_line(
        "ADD_TASK: Draft memo | none | Business | P4 | Mason | 12 | Weekly"
    )
    assert ok is True
    assert isinstance(cmd, AddTaskCommand)
    assert cmd.due_date is None
    assert cmd.priority == 4
    assert cmd.assigned_to == "Mason"
    assert cmd.project_id == 12
    assert cmd.recurrence == "Weekly"


def test_parse_add_task_line_legacy_next_action_field_is_ignored():
    ok, cmd, _reason = parse_add_task_line(
        "ADD_TASK: Draft memo | none | Business | P4 | 03-05-2026 | 12 | Weekly"
    )
    assert ok is True
    assert isinstance(cmd, AddTaskCommand)
    assert cmd.assigned_to is None
    assert cmd.project_id == 12
    assert cmd.recurrence == "Weekly"


def test_parse_action_line_task_delete_and_project_deadline():
    cmd = parse_action_line("TASK_DELETE: 123")
    assert isinstance(cmd, TaskDeleteCommand)
    assert cmd.task_id == 123

    cmd2 = parse_action_line("ADD_PROJECT: Proj | Client | Active")
    assert isinstance(cmd2, AddProjectCommand)
    assert cmd2.status == "Active"

    cmd3 = parse_action_line("PROJECT_SET_DEADLINE: 5 | 03-01-2026")
    assert isinstance(cmd3, ProjectSetDeadlineCommand)
    assert cmd3.project_id == 5
    assert cmd3.deadline == "2026-03-01"


def test_parse_action_line_task_set_assigned_to():
    cmd = parse_action_line("TASK_SET_ASSIGNED_TO: 7 | Quill")
    assert cmd is not None
    assert cmd.task_id == 7
    assert cmd.assigned_to == "Quill"


def test_parse_add_task_line_with_estimate_minutes_trailing():
    ok, cmd, _reason = parse_add_task_line(
        "ADD_TASK: Draft memo | none | Business | P4 | Mason | 12 | Weekly | 90"
    )
    assert ok is True
    assert isinstance(cmd, AddTaskCommand)
    assert cmd.recurrence == "Weekly"
    assert cmd.estimate_minutes == 90


def test_parse_add_task_line_invalid_estimate_ignored():
    ok, cmd, _reason = parse_add_task_line(
        "ADD_TASK: Draft memo | none | Business | P4 | Mason | 12 | Weekly | lots"
    )
    assert ok is True
    assert isinstance(cmd, AddTaskCommand)
    assert cmd.estimate_minutes is None


def test_parse_duration_to_minutes_variants():
    assert parse_duration_to_minutes("90") == 90
    assert parse_duration_to_minutes("1 hr 15 min") == 75
    assert parse_duration_to_minutes("2 hours 30 minutes") == 150
    assert parse_duration_to_minutes("2 hours") == 120
    assert parse_duration_to_minutes("45 min") == 45
    assert parse_duration_to_minutes("1h15m") == 75
    assert parse_duration_to_minutes("1hr15m") == 75
    assert parse_duration_to_minutes("1.5 hours") == 90
    assert parse_duration_to_minutes("none") is None
    assert parse_duration_to_minutes("lots") is None


def test_parse_add_task_line_estimate_duration_trailing():
    ok, cmd, _reason = parse_add_task_line(
        "ADD_TASK: Draft memo | none | Business | P4 | Mason | 12 | Weekly | 1 hr 15 min"
    )
    assert ok is True
    assert isinstance(cmd, AddTaskCommand)
    assert cmd.estimate_minutes == 75


def test_extract_first_duration_phrase_strips_once():
    mins, rest = extract_first_duration_phrase("Call Acme about Q1 1 hr 15 min tomorrow")
    assert mins == 75
    assert "1 hr 15 min" not in rest
    assert "Call Acme" in rest

