import pytest

from core.task_extract import SuggestedTask, parse_suggested_tasks


def test_parse_suggested_tasks_missing_section():
    tasks, warnings = parse_suggested_tasks("# Title\n\nNo tasks here.")
    assert tasks == []
    assert any("section" in w.lower() for w in warnings)


def test_parse_suggested_tasks_canonical_lines():
    md = """
# Plan

## Suggested Tasks (importable)
- [ ] Draft software architecture spec | due: 03-15-2026 | category: Business
- [ ] Finalize design inputs | due: none | category: Business

## Notes
something
""".strip()
    tasks, warnings = parse_suggested_tasks(md)
    assert warnings == [] or all(isinstance(w, str) for w in warnings)
    assert tasks == [
        SuggestedTask(title="Draft software architecture spec", due_mmddyyyy="03-15-2026", category="Business"),
        SuggestedTask(title="Finalize design inputs", due_mmddyyyy="none", category="Business"),
    ]


@pytest.mark.parametrize(
    "due_raw,expected",
    [
        ("2026-03-02", "03-02-2026"),
        ("03/02/2026", "03-02-2026"),
        ("3/2/2026", "03-02-2026"),
        ("3-2-2026", "03-02-2026"),
        ("none", "none"),
        ("tbd", "none"),
    ],
)
def test_parse_suggested_tasks_due_normalization(due_raw, expected):
    md = f"""
## Suggested Tasks (importable)
- [ ] Do thing | due: {due_raw} | category: Business
""".strip()
    tasks, warnings = parse_suggested_tasks(md)
    assert len(tasks) == 1
    assert tasks[0].due_mmddyyyy == expected


def test_parse_suggested_tasks_invalid_due_becomes_none_with_warning():
    md = """
## Suggested Tasks (importable)
- [ ] Do thing | due: tomorrow | category: Business
""".strip()
    tasks, warnings = parse_suggested_tasks(md)
    assert len(tasks) == 1
    assert tasks[0].due_mmddyyyy == "none"
    assert any("invalid due date" in w.lower() for w in warnings)


def test_parse_suggested_tasks_category_case_insensitive():
    md = """
## Suggested Tasks (importable)
- [ ] Personal item | due: none | category: personal
""".strip()
    tasks, warnings = parse_suggested_tasks(md)
    assert len(tasks) == 1
    assert tasks[0].category == "Personal"

