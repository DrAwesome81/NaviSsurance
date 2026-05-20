# Pre-pilot smoke test checklist (fast)

Last updated: 2026-05-12

<!-- Pulse private memory visibility + Shield Security/Compliance surface awareness -->

Use this checklist before a paid pilot kickoff, a CEO demo, or any “screen share” call.

## A) 60-second setup check (no code)
- Confirm you are on the intended branch and have pulled latest changes.
- Launch the app once locally and confirm the **Dashboard “Setup” banner** appears (yellow items are OK; just know what you’re not demoing).

### Optional keys (only required if demoing those features)
- **Deep Research (live web)**: `OPENAI_API_KEY`
- **News/Briefing (live)**: `GROK_API_KEY` (and briefing/email not disabled)
- **Meetings transcript**: `ASSEMBLYAI_API_KEY`
- **Meetings video support**: `ffmpeg` installed and on PATH

## B) 5-minute manual UI smoke (demo-critical loop)
### 1) Deep Research → artifacts
- Open `Deep Research`
- Start a run with a short objective (or open the last run)
- Confirm you can view artifacts and/or a final brief without UI errors

### 2) Workspace → draft → Suggested Tasks (importable)
- Open `Workspace`
- Pick a **Template** (e.g. “CEO Strategy Memo (v1)”)
- Use either (a) no files or (b) 1–2 small marked files
- Click `Generate Draft` and confirm:
  - Grok pane updates
  - ChatGPT pane updates (or shows empty gracefully if key missing)
  - Markdown Document populates
- Click `Extract Suggested Tasks…`
  - Confirm at least 5 tasks are detected and the import dialog opens

### 3) Tasks → visibility + basic actions
- Open `Tasks`
- Confirm imported tasks are present
- Mark one complete and undo
- Change priority or snooze one task

### 4) Billing → draft generation
- Open `Billing`
- Create/select a client
- Add 1 manual time entry
- Generate a draft (previous month or a small custom range)
- Confirm preview renders and “Save As…” works

## C) Fast automated tests (no GUI, no network)
Run these before demos when possible:

```bash
python -m pytest ^
  tests/test_workflow_engine.py ^
  tests/test_response_handler_helpers.py ^
  tests/test_llm_collab.py ^
  tests/test_tools_web_research.py ^
  tests/test_task_extract.py ^
  tests/test_billing_template_render.py ^
  tests/test_invoice_service.py ^
  tests/test_billing_autorun_guard.py
```

Notes:
- GUI tests (`tests/test_tasks_tab.py`, `tests/test_projects_tab.py`) are intentionally excluded from the fast gate because they require PyQt and environment setup.
- These tests are designed to avoid real network/model calls; they validate contracts and failure modes.

<!-- Pulse private memory + Shield surface in pre-pilot smoke -->

