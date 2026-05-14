# LLM Routing Map

Last updated: 2026-05-12

## Current target split

### Local `Qwen3-14B Q5_K_M` via `llama.cpp`
- `Notes` document merge and reorganize flows (`notes_session`, `notes_*`)
- Dashboard briefing cleanup (`briefing_session`)
- Legacy Navi task detection (`task_detection`)
- Legacy Navi task query answering (`task_query`)
- Legacy document generation fallback (`doc_gen`)
- Any remaining non-CoS `ResponseHandler` sessions that do not require web tools or CoS orchestration

### Remote `Grok`
- Dashboard main chat (`main_session`) through Chief of Staff
- Chief of Staff chats and planning sessions (`cos_*`)
- Agent consoles:
  - `Library` / Archive
  - `Intel` / Pulse
  - `Security` / Shield
  - `Leads` / Scout
  - `Billing` / Ledger
  - `Tasks` / Mason
- Compliance primary analysis path
- News / live web search

### Other remote path
- Web research tool flow uses OpenAI-hosted web search in `core/tools/web_research.py`

### Shared runtime/tooling layer
- Shared tool registration and metadata live in `core/tool_registry.py`
- Browser-backed tools live in `core/tools/browser.py`
- Optional local service exposure lives in `api/app.py` + `core/service/local_api.py`

## Why this split
- Keep tool-using, web-aware, multi-step planning chat on remote models.
- Keep narrow formatting and extraction tasks on the faster local path.
- Keep Notes local because it is structured, repetitive, and background-tolerant.
- Avoid moving CoS onto the local stack until there is a deliberate product decision to trade tool depth for speed.

## Current architectural note
- Routing decisions still happen primarily inside `core/main_chat_router.py`, `core/chief_of_staff_service.py`, and `core/response_handler.py`.
- The local API and runtime layers expose existing orchestration and tools; they do not replace the app’s routing logic.
