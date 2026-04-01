from __future__ import annotations

from core import agent_execution as execsvc


class _DbExecStub:
    def __init__(self, assignee_code: str):
        self.assignee_code = assignee_code
        self.db_name = ":memory:"
        self.assignment = {
            "id": 7,
            "title": "Regulatory synthesis",
            "brief_md": "Summarize the latest changes and prepare next steps.",
            "assignee_code": assignee_code,
        }
        self.artifacts: list[dict] = []
        self.summary_calls: list[dict] = []
        self.created_projects: list[dict] = []
        self.project_tasks = [(1, 1, "t1", "Web research", "web_researcher", "queued", "[]", "", "", "")]

    def agent_get_assignment(self, assignment_id: int):
        return dict(self.assignment) if int(assignment_id) == 7 else None

    def agent_list_artifacts(self, *, assignment_id=None, limit=100):
        return list(self.artifacts)[:limit]

    def agent_add_artifact(self, **kwargs):
        record = dict(kwargs)
        record["id"] = len(self.artifacts) + 1
        self.artifacts.append(record)
        return record["id"]

    def agent_set_assignment_result_summary(self, **kwargs):
        self.summary_calls.append(dict(kwargs))
        return True

    def create_project(self, name: str, mode: str, config_json: str = None):
        self.created_projects.append({"name": name, "mode": mode, "config_json": config_json})
        return 99

    def get_project_tasks(self, project_id: int):
        return list(self.project_tasks)

    def billing_clients_list(self, *, active_only=True):
        return [{"id": 1, "name": "Abbott"}, {"id": 2, "name": "Acme"}]

    def invoice_drafts_list(self, *, client_id=None, limit=200):
        return [
            {"id": 5, "client_id": 1, "status": "draft", "period_start": "2026-03-01", "period_end": "2026-03-31"},
        ]

    def list_tasks_rich(self, **kwargs):
        return [
            {"id": 11, "priority": 5, "task_text": "Send client deck", "due_date": "03-31-2026"},
            {"id": 12, "priority": 4, "task_text": "Prepare Q-sub outline", "due_date": ""},
        ]

    def list_leads(self, **kwargs):
        return [
            {"id": 21, "company": "Abbott", "name": "Jane Doe", "title": "VP Regulatory", "total_score": 94, "status": "new"},
            {"id": 22, "company": "Acme Dx", "name": "John Roe", "title": "CEO", "total_score": 88, "status": "nurturing"},
        ]


def test_bootstrap_assignment_execution_for_atlas(monkeypatch):
    db = _DbExecStub("atlas")

    class _FakeWorkflowEngine:
        def __init__(self, db):
            self.db = db

        def create_plan(self, project_id: int, goals: str, mode: str):
            return None

    monkeypatch.setattr("core.workflow_engine.WorkflowEngine", _FakeWorkflowEngine)

    out = execsvc.bootstrap_assignment_execution(db, assignment_id=7, thread_id=12)

    assert out["created"] is True
    assert db.created_projects[0]["mode"] == "web_only"
    assert any(a["artifact_type"] == "deep_research_project" for a in db.artifacts)
    assert any("Deep Research project" in c["summary_md"] for c in db.summary_calls)


def test_bootstrap_assignment_execution_for_quill():
    db = _DbExecStub("quill")
    db.artifacts.append(
        {
            "artifact_type": "uploaded_file",
            "title": "Input brief",
            "content_md": "",
            "content_json": "",
            "file_path": "C:/tmp/input.txt",
        }
    )

    out = execsvc.bootstrap_assignment_execution(db, assignment_id=7, thread_id=12)

    assert out["created"] is True
    artifact = next(a for a in db.artifacts if a["artifact_type"] == "workspace_draft_packet")
    assert "goal" in str(artifact["content_json"]).lower()
    assert "Input brief" in artifact["content_md"]


def test_bootstrap_assignment_execution_for_ledger():
    db = _DbExecStub("ledger")

    out = execsvc.bootstrap_assignment_execution(db, assignment_id=7, thread_id=12)

    assert out["created"] is True
    artifact = next(a for a in db.artifacts if a["artifact_type"] == "billing_execution_snapshot")
    assert "Recent drafts" in artifact["content_md"]
    assert any("Billing execution snapshot" in c["summary_md"] for c in db.summary_calls)


def test_bootstrap_assignment_execution_for_mason():
    db = _DbExecStub("mason")

    out = execsvc.bootstrap_assignment_execution(db, assignment_id=7, thread_id=12)

    assert out["created"] is True
    artifact = next(a for a in db.artifacts if a["artifact_type"] == "task_execution_snapshot")
    assert "Highest-priority open tasks" in artifact["content_md"]
    assert any("Task execution snapshot" in c["summary_md"] for c in db.summary_calls)


def test_bootstrap_assignment_execution_for_archive(monkeypatch):
    db = _DbExecStub("archive")
    monkeypatch.setattr("core.agent_execution.doc_search", lambda db_path, query, limit=8: [])
    monkeypatch.setattr("core.agent_execution.format_hits", lambda hits: "- (no matches)")

    out = execsvc.bootstrap_assignment_execution(db, assignment_id=7, thread_id=12)

    assert out["created"] is True
    artifact = next(a for a in db.artifacts if a["artifact_type"] == "knowledge_retrieval_snapshot")
    assert "Archive retrieval snapshot" in artifact["content_md"]
    assert any("Knowledge retrieval snapshot" in c["summary_md"] for c in db.summary_calls)


def test_bootstrap_assignment_execution_for_scout():
    db = _DbExecStub("scout")

    out = execsvc.bootstrap_assignment_execution(db, assignment_id=7, thread_id=12)

    assert out["created"] is True
    artifact = next(a for a in db.artifacts if a["artifact_type"] == "lead_execution_snapshot")
    assert "Highest-scoring recent leads" in artifact["content_md"]
    assert "Abbott" in artifact["content_md"]
