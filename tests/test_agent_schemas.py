from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.agent_schemas import (
    AgentType,
    QAReport,
    RetrievalResult,
    TaskPlan,
    TaskPlanItem,
    UnifiedBrief,
    WebResearchBrief,
)


def test_task_plan_round_trip_json():
    plan = TaskPlan(
        project_id="42",
        tasks=[
            TaskPlanItem(
                task_id="t1",
                title="Internal research",
                description="Find internal evidence",
                agent_type=AgentType.INTERNAL_LIBRARIAN,
                dependencies=[],
                definition_of_done="brief stored",
                expected_artifacts=["internal_retrieval_brief"],
            )
        ],
    )
    restored = TaskPlan.model_validate_json(plan.model_dump_json())
    assert restored.project_id == "42"
    assert restored.tasks[0].agent_type == AgentType.INTERNAL_LIBRARIAN


def test_qa_report_quality_score_bounds_enforced():
    with pytest.raises(ValidationError):
        QAReport(checks_performed=[], quality_score=101, pass_fail=True)
    with pytest.raises(ValidationError):
        QAReport(checks_performed=[], quality_score=-1, pass_fail=False)


def test_unified_brief_accepts_internal_and_web_payloads():
    internal = {"query": "q", "results": [RetrievalResult(doc_id="d", title="T", excerpt="E").model_dump()]}
    web = {"query": "q2", "sources": [{"title": "S", "url": "https://e.com"}], "findings": [], "contradictions": []}
    unified = UnifiedBrief(project_id="9", internal_brief=internal, web_brief=web, notes="n")
    assert unified.internal_brief is not None
    assert unified.web_brief is not None
    assert unified.web_brief.sources[0].url == "https://e.com"


def test_web_research_brief_default_lists():
    brief = WebResearchBrief(query="regulatory update")
    assert brief.sources == []
    assert brief.findings == []
    assert brief.contradictions == []
