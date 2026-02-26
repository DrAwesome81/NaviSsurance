from __future__ import annotations

import os

from core.workspace_orchestrator import (
    WorkspaceFile,
    WorkspaceTaskSpec,
    _parse_round_result,
    build_reference_pack,
    format_reference_pack_summary,
)


def test_parse_round_result_accepts_strict_json():
    raw = """
    {
      "explanation": "ok",
      "markdown": "# Title\\n\\nBody",
      "feedback": "",
      "is_complete": true
    }
    """
    out = _parse_round_result(raw)
    assert out["explanation"] == "ok"
    assert out["markdown"].startswith("# Title")
    assert out["feedback"] == ""
    assert out["is_complete"] is True


def test_parse_round_result_accepts_json_code_fence():
    raw = """```json
    {"explanation":"x","markdown":"# Doc","feedback":"do y","is_complete":false}
    ```"""
    out = _parse_round_result(raw)
    assert out["explanation"] == "x"
    assert out["markdown"] == "# Doc"
    assert out["feedback"] == "do y"
    assert out["is_complete"] is False


def test_build_reference_pack_selects_relevant_excerpts():
    path = os.path.abspath("/tmp/workspace_orchestrator_ref.txt")
    content = (
        "Intro text.\n\n"
        "Section 5: Performance endpoints\n"
        "Primary endpoint: sensitivity and specificity.\n"
        "More details...\n"
    )
    task = WorkspaceTaskSpec(
        goal="Draft endpoints section for sensitivity and specificity",
        context="",
        files=[WorkspaceFile(path=path, display_name="ref.txt", file_type="text")],
        max_rounds=1,
    )
    pack = build_reference_pack(
        task_spec=task,
        file_contents={path: content},
        goal=task.goal,
        feedback="Focus on endpoint definitions",
        previous_markdown="",
        max_total_chars=20000,
        max_chunks_per_file=3,
        include_small_files_full=False,
        small_file_max_chars=100,
    )
    assert "### File: ref.txt" in pack
    assert "sensitivity" in pack.lower()
    assert "specificity" in pack.lower()


def test_build_reference_pack_returns_coverage_stats():
    p1 = os.path.abspath("/tmp/workspace_stats_a.txt")
    p2 = os.path.abspath("/tmp/workspace_stats_b.txt")
    content_a = "A" * 4000 + "\nSection endpoint data\n" + "B" * 2000
    task = WorkspaceTaskSpec(
        goal="Draft endpoint section",
        context="",
        files=[
            WorkspaceFile(path=p1, display_name="a.txt", file_type="text"),
            WorkspaceFile(path=p2, display_name="b.txt", file_type="text"),
        ],
        max_rounds=1,
    )
    pack, stats = build_reference_pack(
        task_spec=task,
        file_contents={p1: content_a, p2: ""},
        goal=task.goal,
        feedback="include endpoint data",
        previous_markdown="",
        max_total_chars=1200,
        max_chunks_per_file=1,
        include_small_files_full=False,
        small_file_max_chars=100,
        return_stats=True,
    )
    assert isinstance(pack, str)
    assert isinstance(stats, dict)
    assert stats["selected_files_count"] == 2
    assert stats["files_with_content"] == 1
    assert stats["files_omitted"] >= 1
    assert stats["pack_chars"] == len(pack)


def test_format_reference_pack_summary_human_readable():
    summary = format_reference_pack_summary(
        {
            "selected_files_count": 3,
            "files_fully_included": 1,
            "files_partially_included": 1,
            "files_omitted": 1,
            "pack_chars": 12345,
        }
    )
    assert "used 2/3 files" in summary
    assert "full 1, partial 1, omitted 1" in summary
    assert "12345 chars" in summary
