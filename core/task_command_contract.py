from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Literal, Optional

TaskCategory = Literal["Business", "Personal"]
ProjectStatus = Literal["Active", "Waiting", "On Hold", "Done", "Cancelled"]


def normalize_mmddyyyy(value: str | None) -> tuple[bool, Optional[str]]:
    """
    Normalize dashboard/task-tab dates into MM-DD-YYYY.

    Accepts:
    - MM-DD-YYYY
    - YYYY-MM-DD
    - none/null/n/a/blank -> None
    """
    raw = (value or "").strip().strip('"').strip("'")
    if not raw or raw.lower() in {"none", "null", "n/a", "na"}:
        return True, None
    if re.fullmatch(r"\d{2}-\d{2}-\d{4}", raw):
        try:
            dt = datetime.strptime(raw, "%m-%d-%Y")
        except Exception:
            return False, None
        return True, dt.strftime("%m-%d-%Y")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d")
        except Exception:
            return False, None
        return True, dt.strftime("%m-%d-%Y")
    return False, None


def parse_task_priority(value: str | None) -> Optional[int]:
    """
    Parse dashboard task priority into 0..5.
    Accepts: P0..P5, 0..5, none/null/n/a/blank -> None.
    """
    s = str(value or "").strip()
    if not s or s.lower() in {"none", "null", "n/a", "na"}:
        return None
    digits = "".join(ch for ch in s if ch.isdigit())
    if digits == "":
        return None
    try:
        p = int(digits)
    except Exception:
        return None
    if p < 0:
        p = 0
    if p > 5:
        p = 5
    return p


def normalize_task_category(value: str | None) -> Optional[TaskCategory]:
    s = (value or "").strip().lower()
    if s in {"business", "biz"}:
        return "Business"
    if s in {"personal", "pers"}:
        return "Personal"
    return None


def parse_int_or_none(value: str | None) -> Optional[int]:
    s = (value or "").strip().strip('"').strip("'")
    if not s or s.lower() in {"none", "null", "n/a", "na"}:
        return None
    try:
        v = int(s)
        return v if v > 0 else None
    except Exception:
        return None


def _split_pipe_payload(payload: str, *, maxsplit: int | None = None) -> list[str]:
    if maxsplit is None:
        parts = payload.split("|")
    else:
        parts = payload.split("|", maxsplit)
    return [p.strip() for p in parts]


@dataclass(frozen=True)
class AddTaskCommand:
    description: str
    due_date: Optional[str]  # MM-DD-YYYY or None
    category: TaskCategory
    priority: Optional[int] = None  # 0..5
    next_action_date: Optional[str] = None  # MM-DD-YYYY or None
    project_id: Optional[int] = None
    recurrence: str = "None"


@dataclass(frozen=True)
class TaskUpdatePriorityCommand:
    task_id: int
    priority: int  # 0..5


@dataclass(frozen=True)
class TaskCompleteCommand:
    task_id: int


@dataclass(frozen=True)
class TaskSetDueCommand:
    task_id: int
    due_date: Optional[str]


@dataclass(frozen=True)
class TaskSetNextActionCommand:
    task_id: int
    next_action_date: Optional[str]


@dataclass(frozen=True)
class TaskSnoozeCommand:
    task_id: int
    days: int


@dataclass(frozen=True)
class TaskDeleteCommand:
    task_id: int


@dataclass(frozen=True)
class TaskSetProjectCommand:
    task_id: int
    project_id: Optional[int]


@dataclass(frozen=True)
class AddProjectCommand:
    name: str
    client: Optional[str]
    status: ProjectStatus


@dataclass(frozen=True)
class ProjectUpdateStatusCommand:
    project_id: int
    status: ProjectStatus


@dataclass(frozen=True)
class ProjectSetDeadlineCommand:
    project_id: int
    deadline: Optional[str]  # YYYY-MM-DD or None


@dataclass(frozen=True)
class ProjectDeleteCommand:
    project_id: int


AnyCommand = (
    AddTaskCommand
    | TaskUpdatePriorityCommand
    | TaskCompleteCommand
    | TaskSetDueCommand
    | TaskSetNextActionCommand
    | TaskSnoozeCommand
    | TaskDeleteCommand
    | TaskSetProjectCommand
    | AddProjectCommand
    | ProjectUpdateStatusCommand
    | ProjectSetDeadlineCommand
    | ProjectDeleteCommand
)


_ADD_TASK_LINE_RE = re.compile(r"^\s*ADD_TASK:\s*(?P<payload>.+?)\s*$", re.IGNORECASE)
_TASK_UPDATE_PRIORITY_LINE_RE = re.compile(
    r"^\s*TASK_UPDATE_PRIORITY:\s*(?P<id>\d+)\s*\|\s*(?P<p>[0-5])\s*$",
    re.IGNORECASE,
)
_TASK_COMPLETE_LINE_RE = re.compile(r"^\s*TASK_COMPLETE:\s*(?P<id>\d+)\s*$", re.IGNORECASE)
_TASK_SET_DUE_LINE_RE = re.compile(
    r"^\s*TASK_SET_DUE:\s*(?P<id>\d+)\s*\|\s*(?P<due>[^|\n]+?)\s*$",
    re.IGNORECASE,
)
_TASK_SET_NEXT_ACTION_LINE_RE = re.compile(
    r"^\s*TASK_SET_NEXT_ACTION:\s*(?P<id>\d+)\s*\|\s*(?P<date>[^|\n]+?)\s*$",
    re.IGNORECASE,
)
_TASK_SNOOZE_LINE_RE = re.compile(
    r"^\s*TASK_SNOOZE:\s*(?P<id>\d+)\s*\|\s*(?P<days>\d+)\s*$",
    re.IGNORECASE,
)
_TASK_DELETE_LINE_RE = re.compile(r"^\s*TASK_DELETE:\s*(?P<id>\d+)\s*$", re.IGNORECASE)
_TASK_SET_PROJECT_LINE_RE = re.compile(
    r"^\s*TASK_SET_PROJECT:\s*(?P<id>\d+)\s*\|\s*(?P<pid>\d+|none|null|n/a|na)\s*$",
    re.IGNORECASE,
)

_ADD_PROJECT_LINE_RE = re.compile(
    r"^\s*ADD_PROJECT:\s*(?P<name>.+?)\s*\|\s*(?P<client>[^|]*)\s*\|\s*(?P<status>Active|Waiting|On Hold|Done|Cancelled)\s*$",
    re.IGNORECASE,
)
_PROJECT_UPDATE_STATUS_LINE_RE = re.compile(
    r"^\s*PROJECT_UPDATE_STATUS:\s*(?P<id>\d+)\s*\|\s*(?P<status>Active|Waiting|On Hold|Done|Cancelled)\s*$",
    re.IGNORECASE,
)
_PROJECT_SET_DEADLINE_LINE_RE = re.compile(
    r"^\s*PROJECT_SET_DEADLINE:\s*(?P<id>\d+)\s*\|\s*(?P<date>[^|\n]+?)\s*$",
    re.IGNORECASE,
)
_PROJECT_DELETE_LINE_RE = re.compile(r"^\s*PROJECT_DELETE:\s*(?P<id>\d+)\s*$", re.IGNORECASE)


def parse_add_task_line(line: str) -> tuple[bool, Optional[AddTaskCommand], str]:
    """
    Parse canonical ADD_TASK line (CoS/Mason contract):

    ADD_TASK: <desc> | <MM-DD-YYYY or none> | <Business|Personal> [| priority] [| next_action] [| project_id] [| recurrence]
    """
    m = _ADD_TASK_LINE_RE.match(line or "")
    if not m:
        return False, None, "not_add_task"
    payload = (m.group("payload") or "").strip()
    parts = _split_pipe_payload(payload)
    if len(parts) < 3:
        return True, None, "invalid_add_task_arity"

    desc = (parts[0] or "").strip()
    if not desc:
        return True, None, "invalid_add_task_desc"
    # Defend against model drift: description must not contain '|'.
    if "|" in desc:
        desc = desc.split("|", 1)[0].strip()
        if not desc:
            return True, None, "invalid_add_task_desc"

    due_ok, due_norm = normalize_mmddyyyy(parts[1])
    if not due_ok:
        return True, None, "invalid_add_task_due"

    cat = normalize_task_category(parts[2])
    if cat is None:
        return True, None, "invalid_add_task_category"

    priority = parse_task_priority(parts[3] if len(parts) > 3 else None)

    next_ok, next_norm = normalize_mmddyyyy(parts[4] if len(parts) > 4 else None)
    if not next_ok:
        return True, None, "invalid_add_task_next_action"

    project_id = parse_int_or_none(parts[5] if len(parts) > 5 else None)

    recurrence = (parts[6] if len(parts) > 6 else "").strip() or "None"
    if recurrence.lower() in {"none", "null", "n/a", "na"}:
        recurrence = "None"
    if recurrence not in {"None", "Daily", "Weekly", "Monthly"}:
        recurrence = "None"

    return (
        True,
        AddTaskCommand(
            description=desc,
            due_date=due_norm,
            category=cat,
            priority=priority,
            next_action_date=next_norm,
            project_id=project_id,
            recurrence=recurrence,
        ),
        "",
    )


def parse_action_line(line: str) -> AnyCommand | None:
    """
    Parse a single action line from Mason/Tasks-tab contract into a structured command.
    Returns None if the line is not a recognized action.
    """
    line = line or ""

    ok, cmd, _reason = parse_add_task_line(line)
    if ok and cmd is not None:
        return cmd

    m = _TASK_UPDATE_PRIORITY_LINE_RE.match(line)
    if m:
        return TaskUpdatePriorityCommand(task_id=int(m.group("id")), priority=int(m.group("p")))

    m = _TASK_COMPLETE_LINE_RE.match(line)
    if m:
        return TaskCompleteCommand(task_id=int(m.group("id")))

    m = _TASK_SET_DUE_LINE_RE.match(line)
    if m:
        ok_due, due_norm = normalize_mmddyyyy(m.group("due"))
        if not ok_due:
            return None
        return TaskSetDueCommand(task_id=int(m.group("id")), due_date=due_norm)

    m = _TASK_SET_NEXT_ACTION_LINE_RE.match(line)
    if m:
        ok_dt, norm = normalize_mmddyyyy(m.group("date"))
        if not ok_dt:
            return None
        return TaskSetNextActionCommand(task_id=int(m.group("id")), next_action_date=norm)

    m = _TASK_SNOOZE_LINE_RE.match(line)
    if m:
        return TaskSnoozeCommand(task_id=int(m.group("id")), days=max(1, int(m.group("days"))))

    m = _TASK_DELETE_LINE_RE.match(line)
    if m:
        return TaskDeleteCommand(task_id=int(m.group("id")))

    m = _TASK_SET_PROJECT_LINE_RE.match(line)
    if m:
        pid = parse_int_or_none(m.group("pid"))
        return TaskSetProjectCommand(task_id=int(m.group("id")), project_id=pid)

    m = _ADD_PROJECT_LINE_RE.match(line)
    if m:
        name = (m.group("name") or "").strip()
        client = (m.group("client") or "").strip() or None
        status = (m.group("status") or "").strip()
        if not name:
            return None
        if status not in {"Active", "Waiting", "On Hold", "Done", "Cancelled"}:
            return None
        return AddProjectCommand(name=name, client=client, status=status)  # type: ignore[arg-type]

    m = _PROJECT_UPDATE_STATUS_LINE_RE.match(line)
    if m:
        status = (m.group("status") or "").strip()
        if status not in {"Active", "Waiting", "On Hold", "Done", "Cancelled"}:
            return None
        return ProjectUpdateStatusCommand(project_id=int(m.group("id")), status=status)  # type: ignore[arg-type]

    m = _PROJECT_SET_DEADLINE_LINE_RE.match(line)
    if m:
        project_id = int(m.group("id"))
        raw = (m.group("date") or "").strip()
        if not raw or raw.lower() in {"none", "null", "n/a", "na"}:
            return ProjectSetDeadlineCommand(project_id=project_id, deadline=None)
        # Store as YYYY-MM-DD (project convention).
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            return ProjectSetDeadlineCommand(project_id=project_id, deadline=raw)
        ok_dt, mmdd = normalize_mmddyyyy(raw)
        if ok_dt and mmdd:
            dt = datetime.strptime(mmdd, "%m-%d-%Y").strftime("%Y-%m-%d")
            return ProjectSetDeadlineCommand(project_id=project_id, deadline=dt)
        return None

    m = _PROJECT_DELETE_LINE_RE.match(line)
    if m:
        return ProjectDeleteCommand(project_id=int(m.group("id")))

    return None


def extract_action_lines(text: str) -> list[str]:
    """
    Extract candidate action lines from a model response.
    This is intentionally conservative: only whole lines are considered.
    """
    out: list[str] = []
    for raw in (text or "").splitlines():
        line = (raw or "").strip()
        if not line:
            continue
        # Allow users/models to wrap commands in fences; ignore fence markers.
        if line.startswith("```"):
            continue
        out.append(line)
    return out


def parse_actions(text: str) -> list[AnyCommand]:
    cmds: list[AnyCommand] = []
    for line in extract_action_lines(text):
        cmd = parse_action_line(line)
        if cmd is not None:
            cmds.append(cmd)
    return cmds

