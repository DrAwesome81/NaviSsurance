from __future__ import annotations

import os

from core.workspace_orchestrator import (
    WorkspaceFile,
    WorkspaceTaskSpec,
    _parse_round_result,
    build_reference_pack,
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
