from __future__ import annotations

import os

from core.workspace_orchestrator import (
    DualLLMOrchestrator,
    WorkspaceFile,
    WorkspaceTaskSpec,
    _parse_round_result,
    build_reference_pack,
    format_reference_pack_summary,
)
from core.workspace_templates import TemplateFillTarget, WorkspaceTemplateSpec


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


def _template_payload():
    return WorkspaceTemplateSpec(
        key="external:test_template",
        display_name="Test Template",
        title="Test Template",
        source="external",
        machine_path="machine.docx",
        human_path="human.docx",
        sections=[],
        instructions=[],
        fields=["scope"],
        values=["scope"],
        fill_targets=[
            TemplateFillTarget(
                key="value::scope",
                token_kind="VALUE",
                token_name="scope",
                label="Scope",
                order=0,
            )
        ],
    ).to_payload()


def test_orchestrator_retries_when_template_payload_invalid():
    calls = {"grok": 0, "chatgpt": 0}

    def grok_call(task_spec, file_contents, feedback, round_num, previous_markdown):
        calls["grok"] += 1
        if round_num == 1:
            return {
                "explanation": "Initial draft",
                "markdown": "# Draft\n\nBody",
                "feedback": "",
                "is_complete": False,
                "template_blocks": {"value::scope": "Pilot release scope."},
                "document_metadata": {},
            }
        assert "Structured template payload is still invalid" in (feedback or "")
        return {
            "explanation": "Revised draft",
            "markdown": "# Draft\n\nBody",
            "feedback": "",
            "is_complete": True,
            "template_blocks": {"value::scope": "Pilot release scope."},
            "document_metadata": {
                "document_title": "Draft",
                "subtitle": "",
                "document_id": "DRAFT",
                "version": "0.1",
                "effective_date": "2026-03-19",
                "prepared_by": "NaviSsurance",
            },
        }

    def chatgpt_call(task_spec, grok_result, file_contents, round_num):
        calls["chatgpt"] += 1
        return {
            "explanation": "Review complete",
            "markdown": grok_result.get("markdown", ""),
            "feedback": "",
            "is_complete": round_num >= 2,
            "template_blocks": grok_result.get("template_blocks", {}),
            "document_metadata": grok_result.get("document_metadata", {}),
        }

    orchestrator = DualLLMOrchestrator(grok_call=grok_call, chatgpt_call=chatgpt_call)
    result = orchestrator.run_once(
        WorkspaceTaskSpec(
            goal="Draft a templated document",
            max_rounds=2,
            document_template=_template_payload(),
        ),
        file_contents={},
    )

    assert result["status"] == "completed"
    assert result["rounds"] == 2
    assert result["document_metadata"]["document_title"] == "Draft"
    assert "Structured template payload is still invalid" in result["collaboration_history"][0]["feedback"]
    assert calls["grok"] == 2
    assert calls["chatgpt"] == 2


def test_orchestrator_does_not_complete_invalid_template_payload_at_max_rounds():
    def grok_call(task_spec, file_contents, feedback, round_num, previous_markdown):
        return {
            "explanation": "Draft",
            "markdown": "# Draft\n\nBody",
            "feedback": "",
            "is_complete": True,
            "template_blocks": {"value::scope": "Pilot release scope."},
            "document_metadata": {},
        }

    def chatgpt_call(task_spec, grok_result, file_contents, round_num):
        return {
            "explanation": "Looks good",
            "markdown": grok_result.get("markdown", ""),
            "feedback": "",
            "is_complete": True,
            "template_blocks": grok_result.get("template_blocks", {}),
            "document_metadata": grok_result.get("document_metadata", {}),
        }

    orchestrator = DualLLMOrchestrator(grok_call=grok_call, chatgpt_call=chatgpt_call)
    result = orchestrator.run_once(
        WorkspaceTaskSpec(
            goal="Draft a templated document",
            max_rounds=1,
            document_template=_template_payload(),
        ),
        file_contents={},
    )

    assert result["status"] == "max_rounds_reached"
    assert result["rounds"] == 1
    assert result["document_metadata"] == {}
