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
# Workspace orchestrator tests support Pulse private memory and 🛡️ Shield context in document generation (workspace orchestrator tests)
# additional Pulse private memory + Shield for workspace orchestrator tests


def test_parse_round_result_accepts_strict_json():
    raw = """
    {
      "explanation": "ok",
      "markdown": "# Title\\n\\nBody",
      "feedback": "",
      "is_complete": true,
      "evidence_map": {"value::scope": "supported by source section 2"},
      "unresolved_fields": ["value::sample_size"],
      "research_gaps": ["Confirm standard moderation ratio"],
      "user_questions": ["What enrollment target should be used?"]
    }
    """
    out = _parse_round_result(raw)
    assert out["explanation"] == "ok"
    assert out["markdown"].startswith("# Title")
    assert out["feedback"] == ""
    assert out["is_complete"] is True
    assert out["evidence_map"]["value::scope"] == "supported by source section 2"
    assert out["unresolved_fields"] == ["value::sample_size"]
    assert out["research_gaps"] == ["Confirm standard moderation ratio"]
    assert out["user_questions"] == ["What enrollment target should be used?"]


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


def test_build_reference_pack_uses_original_path_fallback():
    original_path = "relative/path/source.txt"
    normalized_path = os.path.abspath(original_path)
    content = "Critical source content for grounding."
    task = WorkspaceTaskSpec(
        goal="Use source content",
        context="",
        files=[WorkspaceFile(path=original_path, display_name="source.txt", file_type="text")],
        max_rounds=1,
    )
    pack = build_reference_pack(
        task_spec=task,
        file_contents={normalized_path: content},
        goal=task.goal,
        feedback="",
        previous_markdown="",
        max_total_chars=10000,
        max_chunks_per_file=2,
        include_small_files_full=True,
        small_file_max_chars=1000,
    )
    assert "Critical source content for grounding." in pack


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
                "evidence_map": {"value::scope": "supported by pilot brief"},
                "unresolved_fields": ["value::scope"],
                "research_gaps": ["Confirm standard pilot scope wording"],
                "user_questions": ["Which release train should this apply to?"],
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
            "evidence_map": {"value::scope": "supported by pilot brief and imported research"},
            "unresolved_fields": [],
            "research_gaps": [],
            "user_questions": [],
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
            "evidence_map": grok_result.get("evidence_map", {}),
            "unresolved_fields": grok_result.get("unresolved_fields", []),
            "research_gaps": grok_result.get("research_gaps", []),
            "user_questions": grok_result.get("user_questions", []),
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
    assert result["evidence_map"]["value::scope"] == "supported by pilot brief and imported research"
    assert result["research_gaps"] == []
    assert result["user_questions"] == []
    assert calls["grok"] == 2
    assert calls["chatgpt"] == 2


def test_orchestrator_filters_resolved_unresolved_fields():
    def grok_call(task_spec, file_contents, feedback, round_num, previous_markdown):
        return {
            "explanation": "Resolved draft",
            "markdown": "# Draft\n\nBody",
            "feedback": "",
            "is_complete": True,
            "template_blocks": {"value::scope": "Supported scope text."},
            "document_metadata": {
                "document_title": "Draft",
                "subtitle": "",
                "document_id": "DRAFT",
                "version": "0.1",
                "effective_date": "2026-03-19",
                "prepared_by": "NaviSsurance",
            },
            "evidence_map": {"value::scope": "supported by merged Atlas research"},
            "unresolved_fields": ["value::scope"],
            "research_gaps": [],
            "user_questions": [],
        }

    def chatgpt_call(task_spec, grok_result, file_contents, round_num):
        return dict(grok_result)

    orchestrator = DualLLMOrchestrator(grok_call=grok_call, chatgpt_call=chatgpt_call)
    result = orchestrator.run_once(
        WorkspaceTaskSpec(
            goal="Draft a templated document",
            max_rounds=1,
            document_template=_template_payload(),
        ),
        file_contents={},
    )

    assert result["status"] == "completed"
    assert result["unresolved_fields"] == []


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
