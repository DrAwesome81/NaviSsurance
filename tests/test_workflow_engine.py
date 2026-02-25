from __future__ import annotations

import json

import pytest

from core.agent_schemas import (
    ArtifactType,
    InternalRetrievalBrief,
    RetrievalResult,
    UnifiedBrief,
    WebResearchBrief,
    WebSource,
)
from core.workflow_engine import STATUS_AWAITING_RESEARCH_REVIEW, WorkflowEngine


class _DbWorkflowStub:
    def __init__(self):
        self.task_plan_json: str | None = None
        self.inserted_tasks: list[dict] = []
        self.artifacts: list[tuple[str, str]] = []
        self.status_updates: list[str] = []
        self.project_row = (1, "Demo", "internal_web", STATUS_AWAITING_RESEARCH_REVIEW, "", None)

    def insert_task_plan(self, project_id: int, plan_json: str):
        self.task_plan_json = plan_json

    def insert_project_task(
        self,
        *,
        project_id: int,
        plan_task_id: str,
        title: str,
        agent_type: str,
        dependencies_json: str,
        definition_of_done: str,
    ):
        self.inserted_tasks.append(
            {
                "project_id": project_id,
                "plan_task_id": plan_task_id,
                "title": title,
                "agent_type": agent_type,
                "dependencies_json": dependencies_json,
                "definition_of_done": definition_of_done,
            }
        )

    def get_artifacts_for_project(self, project_id: int):
        rows = []
        for idx, (art_type, content_json) in enumerate(self.artifacts, start=1):
            rows.append((idx, art_type, content_json, None, ""))
        return rows

    def insert_artifact(self, project_id: int, artifact_type: str, content_json: str, project_task_id=None, run_id=None):
        self.artifacts.append((artifact_type, content_json))

    def update_project_status(self, project_id: int, status: str):
        self.status_updates.append(status)

    def get_project(self, project_id: int):
        return self.project_row

    def get_house_style_guide(self):
        return None


def test_create_plan_internal_web_builds_expected_tasks():
    db = _DbWorkflowStub()
    engine = WorkflowEngine(db=db)

    engine.create_plan(project_id=1, goals="Prepare strategy memo", mode="internal_web")

    assert db.task_plan_json is not None
    assert len(db.inserted_tasks) == 4  # internal + web + writer + qa
    assert db.inserted_tasks[0]["agent_type"] == "internal_librarian"
    assert db.inserted_tasks[1]["agent_type"] == "web_researcher"
    assert db.inserted_tasks[2]["agent_type"] == "writer"
    assert db.inserted_tasks[3]["agent_type"] == "editor_qa"
    # writer depends on first two tasks
    writer_deps = json.loads(db.inserted_tasks[2]["dependencies_json"])
    assert writer_deps == ["t1", "t2"]


def test_brief_summary_for_prompt_includes_internal_and_web_sections():
    db = _DbWorkflowStub()
    engine = WorkflowEngine(db=db)

    unified = UnifiedBrief(
        project_id="1",
        internal_brief=InternalRetrievalBrief(
            query="quality",
            results=[RetrievalResult(doc_id="d1", title="Doc A", excerpt="Internal excerpt")],
            notes="internal note",
        ),
        web_brief=WebResearchBrief(
            query="fda",
            sources=[WebSource(title="Source A", url="https://example.com", publisher="Example")],
            findings=[{"claim": "Key web claim", "supporting_sources": [], "supporting_quotes": []}],
            notes="web note",
        ),
        notes="manager note",
    )

    txt = engine._brief_summary_for_prompt(unified)
    assert "## Internal document research" in txt
    assert "## Web research" in txt
    assert "Internal excerpt" in txt
    assert "Key web claim" in txt
    assert "manager note" in txt


def test_run_parallel_synthesis_stores_both_outputs_and_sets_review_status(monkeypatch):
    db = _DbWorkflowStub()
    unified = UnifiedBrief(project_id="1", internal_brief=None, web_brief=None, notes="n")
    db.artifacts.append((ArtifactType.UNIFIED_BRIEF.value, unified.model_dump_json()))

    monkeypatch.setattr("core.workflow_engine.call_grok_simple", lambda system, user: "grok synthesis")
    monkeypatch.setattr("core.workflow_engine.call_chatgpt_simple", lambda system, user: "chatgpt synthesis")

    engine = WorkflowEngine(db=db)
    engine.run_parallel_synthesis(project_id=1)

    types = [t for t, _ in db.artifacts]
    assert "synthesis_grok" in types
    assert "synthesis_chatgpt" in types
    assert db.status_updates[-1] == STATUS_AWAITING_RESEARCH_REVIEW


def test_continue_to_draft_requires_awaiting_research_review_status():
    db = _DbWorkflowStub()
    db.project_row = (1, "Demo", "internal_web", "running", "", None)
    engine = WorkflowEngine(db=db)

    with pytest.raises(ValueError):
        engine.continue_to_draft(project_id=1, user_feedback=None)
