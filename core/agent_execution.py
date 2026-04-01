from __future__ import annotations

import json
import logging
import os

from core.cos_doc_search import doc_search, format_hits
from core.db import DatabaseManager

logger = logging.getLogger(__name__)


def _artifact_exists(db: DatabaseManager, *, assignment_id: int, artifact_type: str) -> bool:
    try:
        rows = db.agent_list_artifacts(assignment_id=int(assignment_id), limit=200)
    except Exception:
        return False
    return any(str(row.get("artifact_type") or "").strip() == str(artifact_type).strip() for row in rows)


def _assignment_artifact_rows(db: DatabaseManager, assignment_id: int, *, limit: int = 20) -> list[dict]:
    try:
        return db.agent_list_artifacts(assignment_id=int(assignment_id), limit=int(limit))
    except Exception:
        return []


def _inline_reference_lines(rows: list[dict], *, limit: int = 6) -> list[str]:
    lines: list[str] = []
    for row in rows[: int(limit)]:
        title = str(row.get("title") or row.get("artifact_type") or "Artifact").strip()
        file_path = str(row.get("file_path") or "").strip()
        content_md = str(row.get("content_md") or "").strip()
        if content_md:
            snippet = " ".join(content_md.split())
            if len(snippet) > 180:
                snippet = snippet[:177].rstrip() + "..."
            lines.append(f"- {title}: {snippet}")
            continue
        if file_path:
            lines.append(f"- {title}: file `{file_path}`")
    return lines


def _run_atlas_bootstrap(db: DatabaseManager, assignment: dict, *, thread_id: int | None = None) -> dict:
    from core.workflow_engine import WorkflowEngine

    assignment_id = int(assignment.get("id") or 0)
    title = str(assignment.get("title") or "Research assignment").strip()
    brief = str(assignment.get("brief_md") or "").strip()
    if _artifact_exists(db, assignment_id=assignment_id, artifact_type="deep_research_project"):
        return {"created": False, "artifact_type": "deep_research_project"}
    config_json = json.dumps(
        {
            "source_assignment_id": assignment_id,
            "assignee_code": "atlas",
            "title": title,
        },
        ensure_ascii=False,
    )
    project_id = int(db.create_project(name=f"A-{assignment_id:04d} {title}"[:120], mode="web_only", config_json=config_json))
    engine = WorkflowEngine(db=db)
    engine.create_plan(project_id=project_id, goals=brief or title, mode="web_only")
    tasks = db.get_project_tasks(project_id)
    content_md = (
        f"## Atlas execution bootstrap\n\n"
        f"- Assignment: `A-{assignment_id:04d}`\n"
        f"- Created Deep Research project: `{project_id}`\n"
        f"- Mode: `web_only`\n"
        f"- Planned task count: `{len(tasks)}`\n\n"
        "This assignment is now linked to a concrete Deep Research workflow scaffold."
    )
    artifact_id = db.agent_add_artifact(
        artifact_type="deep_research_project",
        assignment_id=assignment_id,
        thread_id=int(thread_id) if thread_id is not None else None,
        title=f"Deep Research project scaffold A-{assignment_id:04d}",
        content_md=content_md,
        content_json={"project_id": project_id, "task_count": len(tasks), "mode": "web_only"},
    )
    db.agent_set_assignment_result_summary(
        assignment_id=assignment_id,
        summary_md=f"Deep Research project `{project_id}` scaffolded for this assignment.",
        actor_code="navi",
        note="Atlas execution bootstrap",
    )
    return {"created": True, "artifact_type": "deep_research_project", "project_id": project_id, "artifact_id": artifact_id}


def _run_quill_bootstrap(db: DatabaseManager, assignment: dict, *, thread_id: int | None = None) -> dict:
    from core.workspace_orchestrator import WorkspaceFile, WorkspaceTaskSpec

    assignment_id = int(assignment.get("id") or 0)
    title = str(assignment.get("title") or "Draft assignment").strip()
    brief = str(assignment.get("brief_md") or "").strip()
    if _artifact_exists(db, assignment_id=assignment_id, artifact_type="workspace_draft_packet"):
        return {"created": False, "artifact_type": "workspace_draft_packet"}
    artifact_rows = _assignment_artifact_rows(db, assignment_id)
    files: list[WorkspaceFile] = []
    for row in artifact_rows:
        file_path = str(row.get("file_path") or "").strip()
        if not file_path:
            continue
        files.append(
            WorkspaceFile(
                path=file_path,
                display_name=os.path.basename(file_path) or file_path,
                file_type=os.path.splitext(file_path)[1].lstrip(".").lower() or "unknown",
            )
        )
    task_spec = WorkspaceTaskSpec(
        goal=title,
        context=brief,
        files=files,
        style="regulatory",
        audience="internal team",
    )
    references = _inline_reference_lines(artifact_rows)
    content_md = (
        f"## Quill draft packet\n\n"
        f"- Assignment: `A-{assignment_id:04d}`\n"
        f"- Goal: {title}\n"
        f"- Source file count: `{len(files)}`\n\n"
        "### Brief\n"
        f"{brief or '(none)'}\n\n"
        "### Attached references\n"
        + ("\n".join(references) if references else "- (no attached references)")
    )
    artifact_id = db.agent_add_artifact(
        artifact_type="workspace_draft_packet",
        assignment_id=assignment_id,
        thread_id=int(thread_id) if thread_id is not None else None,
        title=f"Workspace draft packet A-{assignment_id:04d}",
        content_md=content_md,
        content_json={
            "goal": task_spec.goal,
            "context": task_spec.context,
            "style": task_spec.style,
            "audience": task_spec.audience,
            "files": [
                {"path": wf.path, "display_name": wf.display_name, "file_type": wf.file_type}
                for wf in task_spec.files
            ],
        },
    )
    db.agent_set_assignment_result_summary(
        assignment_id=assignment_id,
        summary_md="Workspace draft packet prepared with assignment brief and attached references.",
        actor_code="navi",
        note="Quill execution bootstrap",
    )
    return {"created": True, "artifact_type": "workspace_draft_packet", "artifact_id": artifact_id}


def _run_ledger_bootstrap(db: DatabaseManager, assignment: dict, *, thread_id: int | None = None) -> dict:
    assignment_id = int(assignment.get("id") or 0)
    if _artifact_exists(db, assignment_id=assignment_id, artifact_type="billing_execution_snapshot"):
        return {"created": False, "artifact_type": "billing_execution_snapshot"}
    drafts = db.invoice_drafts_list(limit=10)
    clients = db.billing_clients_list(active_only=True)
    lines = [
        "## Ledger execution snapshot",
        "",
        f"- Assignment: `A-{assignment_id:04d}`",
        f"- Active billing clients: `{len(clients)}`",
        f"- Recent invoice drafts: `{len(drafts)}`",
        "",
        "### Recent drafts",
    ]
    if drafts:
        for row in drafts[:5]:
            lines.append(
                f"- Draft `{row.get('id')}` — client `{row.get('client_id')}` — status `{row.get('status')}` — period {row.get('period_start')} to {row.get('period_end')}"
            )
    else:
        lines.append("- (no invoice drafts found)")
    artifact_id = db.agent_add_artifact(
        artifact_type="billing_execution_snapshot",
        assignment_id=assignment_id,
        thread_id=int(thread_id) if thread_id is not None else None,
        title=f"Billing execution snapshot A-{assignment_id:04d}",
        content_md="\n".join(lines).strip(),
        content_json={"draft_count": len(drafts), "active_client_count": len(clients)},
    )
    db.agent_set_assignment_result_summary(
        assignment_id=assignment_id,
        summary_md="Billing execution snapshot prepared from current invoice drafts and billing clients.",
        actor_code="navi",
        note="Ledger execution bootstrap",
    )
    return {"created": True, "artifact_type": "billing_execution_snapshot", "artifact_id": artifact_id}


def _run_mason_bootstrap(db: DatabaseManager, assignment: dict, *, thread_id: int | None = None) -> dict:
    assignment_id = int(assignment.get("id") or 0)
    if _artifact_exists(db, assignment_id=assignment_id, artifact_type="task_execution_snapshot"):
        return {"created": False, "artifact_type": "task_execution_snapshot"}
    rows = db.list_tasks_rich(
        category=None,
        date_filter="All",
        specific_date=None,
        include_completed=False,
        include_snoozed=False,
        search=None,
        cos_project_id=None,
        sort_by="priority",
        limit=20,
    )
    lines = [
        "## Mason execution snapshot",
        "",
        f"- Assignment: `A-{assignment_id:04d}`",
        f"- Open task count sampled: `{len(rows)}`",
        "",
        "### Highest-priority open tasks",
    ]
    if rows:
        for row in rows[:8]:
            lines.append(
                f"- Task `{row.get('id')}` — P{int(row.get('priority') or 0)} — {row.get('task_text')} — due {row.get('due_date') or 'none'}"
            )
    else:
        lines.append("- (no open tasks found)")
    artifact_id = db.agent_add_artifact(
        artifact_type="task_execution_snapshot",
        assignment_id=assignment_id,
        thread_id=int(thread_id) if thread_id is not None else None,
        title=f"Task execution snapshot A-{assignment_id:04d}",
        content_md="\n".join(lines).strip(),
        content_json={"sampled_open_tasks": len(rows)},
    )
    db.agent_set_assignment_result_summary(
        assignment_id=assignment_id,
        summary_md="Task execution snapshot prepared from the current open task list.",
        actor_code="navi",
        note="Mason execution bootstrap",
    )
    return {"created": True, "artifact_type": "task_execution_snapshot", "artifact_id": artifact_id}


def _run_archive_bootstrap(db: DatabaseManager, assignment: dict, *, thread_id: int | None = None) -> dict:
    assignment_id = int(assignment.get("id") or 0)
    title = str(assignment.get("title") or "Knowledge request").strip()
    brief = str(assignment.get("brief_md") or "").strip()
    if _artifact_exists(db, assignment_id=assignment_id, artifact_type="knowledge_retrieval_snapshot"):
        return {"created": False, "artifact_type": "knowledge_retrieval_snapshot"}
    query = brief or title
    hits = doc_search(db.db_name, query, limit=8)
    content_md = (
        f"## Archive retrieval snapshot\n\n"
        f"- Assignment: `A-{assignment_id:04d}`\n"
        f"- Query: {query}\n"
        f"- Hit count: `{len(hits)}`\n\n"
        f"{format_hits(hits)}"
    )
    artifact_id = db.agent_add_artifact(
        artifact_type="knowledge_retrieval_snapshot",
        assignment_id=assignment_id,
        thread_id=int(thread_id) if thread_id is not None else None,
        title=f"Knowledge retrieval snapshot A-{assignment_id:04d}",
        content_md=content_md,
        content_json={"query": query, "hit_count": len(hits)},
    )
    db.agent_set_assignment_result_summary(
        assignment_id=assignment_id,
        summary_md=f"Knowledge retrieval snapshot prepared with {len(hits)} doc-search hits.",
        actor_code="navi",
        note="Archive execution bootstrap",
    )
    return {"created": True, "artifact_type": "knowledge_retrieval_snapshot", "artifact_id": artifact_id}


def _run_scout_bootstrap(db: DatabaseManager, assignment: dict, *, thread_id: int | None = None) -> dict:
    assignment_id = int(assignment.get("id") or 0)
    if _artifact_exists(db, assignment_id=assignment_id, artifact_type="lead_execution_snapshot"):
        return {"created": False, "artifact_type": "lead_execution_snapshot"}
    leads = db.list_leads(status=None, contacted=None, min_score=0, limit=12)
    lines = [
        "## Scout lead snapshot",
        "",
        f"- Assignment: `A-{assignment_id:04d}`",
        f"- Lead sample count: `{len(leads)}`",
        "",
        "### Highest-scoring recent leads",
    ]
    if leads:
        leads_sorted = sorted(leads, key=lambda row: int(row.get("total_score") or 0), reverse=True)
        for row in leads_sorted[:8]:
            lines.append(
                f"- Lead `{row.get('id')}` — **{row.get('company') or row.get('name') or 'Unknown'}** — "
                f"{row.get('title') or 'Unknown title'} — score `{int(row.get('total_score') or 0)}` — status `{row.get('status')}`"
            )
    else:
        lines.append("- (no leads found)")
    artifact_id = db.agent_add_artifact(
        artifact_type="lead_execution_snapshot",
        assignment_id=assignment_id,
        thread_id=int(thread_id) if thread_id is not None else None,
        title=f"Lead execution snapshot A-{assignment_id:04d}",
        content_md="\n".join(lines).strip(),
        content_json={"lead_count": len(leads)},
    )
    db.agent_set_assignment_result_summary(
        assignment_id=assignment_id,
        summary_md=f"Lead execution snapshot prepared from {len(leads)} recent leads.",
        actor_code="navi",
        note="Scout execution bootstrap",
    )
    return {"created": True, "artifact_type": "lead_execution_snapshot", "artifact_id": artifact_id}


def bootstrap_assignment_execution(db: DatabaseManager, *, assignment_id: int, thread_id: int | None = None) -> dict:
    assignment = db.agent_get_assignment(int(assignment_id))
    if not assignment:
        return {"created": False, "reason": "assignment_missing"}
    code = str(assignment.get("assignee_code") or "").strip().lower()
    if code == "atlas":
        return _run_atlas_bootstrap(db, assignment, thread_id=thread_id)
    if code == "quill":
        return _run_quill_bootstrap(db, assignment, thread_id=thread_id)
    if code == "ledger":
        return _run_ledger_bootstrap(db, assignment, thread_id=thread_id)
    if code == "mason":
        return _run_mason_bootstrap(db, assignment, thread_id=thread_id)
    if code == "archive":
        return _run_archive_bootstrap(db, assignment, thread_id=thread_id)
    if code == "scout":
        return _run_scout_bootstrap(db, assignment, thread_id=thread_id)
    return {"created": False, "reason": "unsupported_agent", "agent_code": code}
