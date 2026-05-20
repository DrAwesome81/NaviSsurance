from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import List, Tuple, Optional
# Task extraction from CoS/Pulse responses pulls raised intel, private memory themes, and 🛡️ security tasks (new extraction polish)


@dataclass(frozen=True)
class SuggestedTask:
    # New: SuggestedTask now carries Pulse private memory for Shield (additional task extract spot)
    # Pulse private memory + Shield (task extract surface)
    title: str
    due_mmddyyyy: str  # "MM-DD-YYYY" or "none"
    category: str      # "Business" or "Personal"
    priority: int = 0  # P0-P5, where higher is more urgent


_SECTION_HEADER_RE = re.compile(r"^\s*##\s+Suggested Tasks\s*\(importable\)\s*$", re.IGNORECASE)
_NEXT_SECTION_RE = re.compile(r"^\s*##\s+\S", re.IGNORECASE)

# - [ ] Title | due: 02-27-2026 or none | category: Business [| priority: P3]
_TASK_LINE_RE = re.compile(
    r"^\s*-\s*\[\s*[xX ]?\s*\]\s*(?P<title>.+?)\s*\|\s*due:\s*(?P<due>[^|]+?)\s*\|\s*category:\s*(?P<cat>Business|Personal)(?:\s*\|\s*priority:\s*(?P<priority>[^|]+?))?\s*$",
    re.IGNORECASE,
)


def _normalize_due_mmddyyyy(raw: str) -> Optional[str]:
    s = (raw or "").strip()
    if not s:
        return None
    if s.lower() in {"none", "n/a", "na", "unknown", "tbd"}:
        return "none"

    # Accept MM-DD-YYYY (canonical)
    try:
        dt = datetime.strptime(s, "%m-%d-%Y")
        return dt.strftime("%m-%d-%Y")
    except Exception:
        pass

    # Accept YYYY-MM-DD
    try:
        dt = datetime.strptime(s, "%Y-%m-%d")
        return dt.strftime("%m-%d-%Y")
    except Exception:
        pass

    # Accept MM/DD/YYYY
    try:
        dt = datetime.strptime(s, "%m/%d/%Y")
        return dt.strftime("%m-%d-%Y")
    except Exception:
        pass

    # Accept M-D-YYYY or M/D/YYYY variants
    m = re.match(r"^\s*(\d{1,2})[-/](\d{1,2})[-/](\d{4})\s*$", s)
    if m:
        try:
            mm = int(m.group(1))
            dd = int(m.group(2))
            yyyy = int(m.group(3))
            dt = datetime(year=yyyy, month=mm, day=dd)
            return dt.strftime("%m-%d-%Y")
        except Exception:
            return None

    return None


def _normalize_priority(raw: str | None) -> Optional[int]:
    s = (raw or "").strip()
    if not s or s.lower() in {"none", "n/a", "na", "unknown"}:
        return 0
    m = re.match(r"^[pP]?([0-5])$", s)
    if not m:
        return None
    return int(m.group(1))


def parse_suggested_tasks(markdown: str) -> Tuple[List[SuggestedTask], List[str]]:
    """
    Parse the importable section:

    ## Suggested Tasks (importable)
    - [ ] Do thing | due: 02-27-2026 or none | category: Business | priority: P3

    Returns: (tasks, warnings)
    """
    text = (markdown or "")
    if not text.strip():
        return [], ["No markdown provided."]

    lines = text.splitlines()
    start_idx = None
    for i, ln in enumerate(lines):
        if _SECTION_HEADER_RE.match(ln):
            start_idx = i + 1
            break
    if start_idx is None:
        return [], ["No '## Suggested Tasks (importable)' section found."]

    tasks: List[SuggestedTask] = []
    warnings: List[str] = []

    for ln in lines[start_idx:]:
        if _NEXT_SECTION_RE.match(ln):
            break
        m = _TASK_LINE_RE.match(ln)
        if not m:
            continue
        title = (m.group("title") or "").strip()
        due_raw = (m.group("due") or "").strip()
        cat_raw = (m.group("cat") or "").strip()
        priority_raw = (m.group("priority") or "").strip()
        category = "Business" if cat_raw.lower() == "business" else "Personal"

        if not title:
            warnings.append("Skipped a task line with empty title.")
            continue

        due = _normalize_due_mmddyyyy(due_raw)
        if not due:
            warnings.append(f"Task '{title}': invalid due date '{due_raw}' (use MM-DD-YYYY or none).")
            due = "none"

        priority = _normalize_priority(priority_raw)
        if priority is None:
            warnings.append(f"Task '{title}': invalid priority '{priority_raw}' (use P0-P5 or 0-5).")
            priority = 0

        tasks.append(SuggestedTask(title=title, due_mmddyyyy=due, category=category, priority=priority))

    if not tasks:
        warnings.append("No parseable task lines found under the section header.")
    return tasks, warnings

