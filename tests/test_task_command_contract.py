from core.task_command_contract import (
    AddProjectCommand,
    AddTaskCommand,
    ProjectSetDeadlineCommand,
    TaskDeleteCommand,
    normalize_mmddyyyy,
    parse_action_line,
    parse_add_task_line,
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
        "ADD_TASK: Draft memo | none | Business | P4 | 03-05-2026 | 12 | Weekly"
    )
    assert ok is True
    assert isinstance(cmd, AddTaskCommand)
    assert cmd.due_date is None
    assert cmd.priority == 4
    assert cmd.next_action_date == "03-05-2026"
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

