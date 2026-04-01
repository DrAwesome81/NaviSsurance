# NaviSsurance APIs And Integrations

Last updated: 2026-04-01

## Overview
NaviSsurance now has two different API layers:

1. **Third-party APIs and SDKs** used for research, transcription, search, calendar, and storage
2. **A local HTTP API** exposed by the app itself when enabled

This distinction matters because `core/api.py` is Dropbox-related code, while the app’s local REST surface lives in `api/app.py`.

## Local Runtime API

### Purpose
The local API creates a non-GUI entry point into the same SQLite-backed system used by the desktop app. It is intended for:
- local integrations
- runtime jobs
- future external automation surfaces

### Code
- `api/app.py`
- `core/service/local_api.py`

### Enablement
The local API is optional and controlled via `config.py` environment flags:
- `NAVI_LOCAL_API_ENABLED`
- `NAVI_LOCAL_API_HOST`
- `NAVI_LOCAL_API_PORT`
- `NAVI_LOCAL_API_LOG_LEVEL`

### Current endpoints
- `GET /health`
- `GET /tools`
- `POST /chat/main-turn`
- `GET /jobs`
- `POST /jobs`
- `POST /tools/{tool_name}`

### Notes
- The local API uses the same SQLite database and orchestration logic as the desktop app.
- It is designed as a local-only service surface, not a public multi-user web product.
- It is not intended to replace the built-in desktop chat as the main user interaction surface.

## Local Model Runtime

### Purpose
The local model is used for narrower structured and formatting-heavy tasks, especially where local execution is preferred for privacy, speed, or cost.

### Current configuration source
- `config.py`
- `docs/llm_routing.md`
- `docs/local_model_validation.md`

### Current model path
- `Qwen3-14B-Q5_K_M.gguf`

### Related config
- `LOCAL_LLM_MODEL_PATH`
- `LOCAL_LLM_CTX_SIZE`
- `LOCAL_LLM_GPU_LAYERS`
- `LOCAL_LLM_TIMEOUT_S`

### Notes
- This replaces older documentation that described the local path primarily as Llama 3.1-8B.
- The app still contains legacy local-model pathways and worker-style patterns, but the current documented local target is the Qwen3-based runtime configured in `config.py`.

## xAI Grok

### Purpose
Used for:
- Chief of Staff and planning flows
- compliance analysis
- lead generation
- shared remote completions
- app-level web-aware flows

### Authentication
- `GROK_API_KEY` (or compatible xAI key setup)

### Code
- `core/grok_client.py`
- callers include `core/chief_of_staff_service.py`, `core/response_handler.py`, `gui/dashboard_tab.py`, `gui/leads_tab.py`, and others

### Notes
- Default model selection is centralized in `core/grok_client.py`.
- CoS and remote planning flows should be treated as Grok-backed unless explicitly rerouted.

## OpenAI Responses API

### Purpose
Used primarily by Deep Research for hosted web search and synthesis.

### Authentication
- `OPENAI_API_KEY`

### Code
- `core/tools/web_research.py`
- `core/llm_collab.py`
- `core/workflow_engine.py`
- `gui/deep_research_tab.py`

### Current behavior
- Deep Research uses the Responses API hosted `web_search` tool when available.
- It falls back to non-browsing ChatGPT behavior if hosted web search is unavailable.

## AssemblyAI

### Purpose
- meeting transcription

### Authentication
- `ASSEMBLYAI_API_KEY`

### Code
- `gui/meetings_tab.py`
- related meeting/transcription flows in the GUI and DB-backed meeting records

## Google Calendar API

### Purpose
- dashboard schedule display
- calendar context in Chief of Staff
- optional explicit calendar block creation when configured

### Authentication
- OAuth token files and Google client credentials

### Code
- `core/data_fetch.py`
- `core/cos_calendar.py`

### Notes
- Calendar use should degrade gracefully when credentials are unavailable.

## Dropbox

### Purpose
- document storage and indexing
- RAG source material
- older storage integrations still present in the repo

### Code
- `core/api.py`
- `build_rag_index.py`
- Dropbox-related indexing and retrieval helpers elsewhere in the repo

### Important distinction
`core/api.py` is Dropbox integration code. It is not the app’s local FastAPI service.

## Browser Automation

### Purpose
- browser-backed evidence capture
- automated page fetch and workflow steps
- future lead, research, and portal interaction support

### Code
- `core/tools/browser.py`
- `core/fda_scraper.py`

### Dependency
- `playwright`
- browser install step: `playwright install chromium`

## Telegram Integration

Telegram support exists only as optional scaffolding:
- `core/channels/telegram_bot.py`

Current product direction:
- built-in desktop chat is the intended user chat surface
- remote chat integrations are not part of the active roadmap
- Telegram should remain disabled unless explicitly revisited for a future use case

## Shared Tool Surface

The app now has a central tool registry:
- `core/tool_registry.py`

This is the canonical place for:
- shared tool names
- caller permissions
- side-effect classification
- approval metadata
- common invocation patterns

Current registered tool families include:
- internal retrieval
- web research
- browser tools
- CoS doc search
- CoS memory search
- CoS chat-history search

## Security Notes
- Keys and tokens should remain in local config and environment files, not hardcoded source.
- The local API increases the operational attack surface and should remain disabled unless actively needed.
- Browser automation may capture screenshots and artifacts under local artifact paths.

See also:
- `docs/security.md`
- `SECURITY.md`

