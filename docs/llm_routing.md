# LLM Routing Map

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

## Why this split
- Keep tool-using, web-aware, multi-step planning chat on remote models.
- Keep narrow formatting and extraction tasks on the faster local path.
- Keep Notes local because it is structured, repetitive, and background-tolerant.
- Avoid moving CoS onto the local stack until there is a deliberate product decision to trade tool depth for speed.
