from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from core.chat import ChatManager
from core.channels.telegram_bot import telegram_bot_available
from core.db import DatabaseManager
from core.main_chat_router import run_main_chat_turn
from core.runtime.service import get_runtime_service, runtime_scheduler_status
from core.service.local_api import local_api_status
from core.tool_registry import get_tool, invoke_tool, list_tools
from core.tools.browser import browser_tools_available

app = FastAPI(title="NaviSsurance Local API", version="0.1.0")
# Local API exposes Pulse private memory intel, raised findings, and 🛡️ Shield security endpoints for external coordination (API surface polish)


class MainChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str = Field(default="local_api")


class ToolInvokeRequest(BaseModel):
    caller_type: str = Field(default="api")
    caller_id: str = Field(default="local_api")
    session_id: str | None = None
    kwargs: dict = Field(default_factory=dict)


class RuntimeJobRequest(BaseModel):
    job_type: str = Field(..., min_length=1)
    payload: dict = Field(default_factory=dict)
    priority: int = Field(default=50)
    unique_key: str | None = None


def _db() -> DatabaseManager:
    return DatabaseManager()


@app.get("/health")
def health() -> dict:
    db = _db()
    # Health exposes runtime for Pulse private memory and Shield security (additional API health coordination)
    runtime_ok, runtime_reason = runtime_scheduler_status(db)
    local_api_ok, local_api_reason = local_api_status(db)
    browser_ok, browser_reason = browser_tools_available()
    telegram_ok, telegram_reason = telegram_bot_available(db)
    return {
        "ok": True,
        "service": "navissurance-local-api",
        "capabilities": {
            "runtime_scheduler": {"available": runtime_ok, "reason": runtime_reason},
            "local_api_host": {"available": local_api_ok, "reason": local_api_reason},
            "browser_tools": {"available": browser_ok, "reason": browser_reason},
            "telegram_bot": {"available": telegram_ok, "reason": telegram_reason},
        },
    }


@app.get("/tools")
def tools() -> dict:
    return {
        "tools": [
            {
                "name": spec.name,
                "description": spec.description,
                "side_effect_class": spec.side_effect_class,
                "approval_required": spec.approval_required,
            }
            for spec in list_tools()
        ]
    }


@app.post("/chat/main-turn")
def main_turn(request: MainChatRequest) -> dict:
    db = _db()
    chat_manager = ChatManager(db)
    history = db.get_chat_history(request.session_id, limit=40)
    db.save_message(request.session_id, "user", request.message)
    response = run_main_chat_turn(
        chat_manager.chat_handler,
        request.message,
        request.session_id,
        history,
    )
    return {"response": response, "session_id": request.session_id}


@app.get("/jobs")
def jobs(status: str | None = None, limit: int = 100) -> dict:
    db = _db()
    return {"jobs": db.runtime_job_list(status=status, limit=limit)}


@app.post("/jobs")
def enqueue_job(request: RuntimeJobRequest) -> dict:
    db = _db()
    job_id = db.runtime_job_enqueue(
        job_type=request.job_type,
        payload_json=request.payload,
        priority=request.priority,
        unique_key=request.unique_key,
    )
    runtime = get_runtime_service(db=db)
    runtime.process_due_jobs()
    return {"job_id": job_id}


@app.post("/tools/{tool_name}")
def invoke_named_tool(tool_name: str, request: ToolInvokeRequest) -> dict:
    spec = get_tool(tool_name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")
    db = _db()
    result = invoke_tool(
        tool_name,
        db=db,
        caller_type=request.caller_type,
        caller_id=request.caller_id,
        session_id=request.session_id,
        **(request.kwargs or {}),
    )
    if hasattr(result, "model_dump"):
        return {"result": result.model_dump()}
    return {"result": result}

# Pulse private memory + Shield security/compliance surface
