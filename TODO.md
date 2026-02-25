# NaviSsurance Remaining To-Do

## Remaining Work

- [ ] Add pointer to `user_manual.md` in `docs/overview.md`
- [ ] Apply deterministic count/verification pattern to:
  - `BULK_UPDATE_ASSIGNMENT_PRIORITY`
  - `BULK_UPDATE_ASSIGNMENT_DUE`
  - `BULK_REASSIGN_ASSIGNMENTS`
- [ ] Persist daily briefing state across restart/session (show existing briefing for the day)
- [ ] Assignment tab bulk due date: switch to date picker UI (keep optional manual ISO fallback)
- [ ] Broader UI sizing pass (increase control heights/widths where clipping still occurs)
- [ ] Auto-refresh task list after manual task creation in any remaining non-covered paths
- [ ] Optional performance pass:
  - reduce duplicate LLM calls
  - add context windowing/summarization
  - tune token caps
  - add per-request timing logs
- [ ] Final closeout artifact: "done vs intentionally manual" matrix in docs

## Intentionally Manual / Not Targeted for Deterministic Automation

- [ ] True cross-session UX verification requiring real restart/runtime state
- [ ] Live external integrations (email providers, model/network behavior)
- [ ] Heavier async multi-service orchestration flows that are brittle in CI-style tests
