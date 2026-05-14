# Runtime, Jobs, And Local API — Operator Notes

Last updated: 2026-05-12

## What this is

The desktop app can start three optional **local** services (same machine, same SQLite DB as the GUI):

1. **Background runtime** — APScheduler ticks that claim and run rows from the `runtime_jobs` queue (`core/runtime/service.py`).
2. **Local HTTP API** — FastAPI app on loopback for health, tools, chat turn, and job enqueue (`api/app.py`).
3. **Telegram bot** (scaffolding) — Only relevant if explicitly enabled; not the primary product surface.

## Where toggles live: App preferences vs `config/.env`

**Secrets** (tokens, API keys) belong in `config/.env` only. Examples: `GROK_API_KEY`, `NAVI_TELEGRAM_BOT_TOKEN` (if you use Telegram).

**Non-secret runtime and integration switches** are stored in SQLite `app_settings` and edited from **Settings → App preferences** in the GUI. On first run after an upgrade, `core.app_preferences.migrate_legacy_env_preferences()` may copy values from legacy env vars into the DB if a key is still unset—so old `NAVI_*` entries in `.env` can “seed” the DB once.

| GUI / `app_settings` key (internal) | Purpose |
| ----------------------------------- | ------- |
| `navi_runtime_enabled` | Master switch for the background scheduler. |
| `navi_runtime_poll_interval_s` | Job poll interval (seconds, min 5). |
| `navi_runtime_job_lease_s` | Claim lease duration (seconds). |
| `navi_local_api_enabled` | Local FastAPI server on loopback. |
| `navi_local_api_host` / `navi_local_api_port` | Bind address and port. |
| `navi_local_api_log_level` | Uvicorn log level for the local API process. |
| `navi_telegram_bot_enabled` | Telegram scaffolding (still requires token in `.env`). |
| `navi_telegram_allowed_chat_ids` | Comma-separated allowlist (empty = allow all, when enabled). |

Restart the desktop app after changing these so the scheduler and HTTP server start/stop correctly.

## Legacy environment flags (optional seed for `app_settings`)

If the DB key above is **unset**, startup migration may copy from:

| Variable | Typical meaning |
| -------- | --------------- |
| `NAVI_RUNTIME_ENABLED` | Seed `navi_runtime_enabled`. |
| `NAVI_RUNTIME_POLL_INTERVAL_S` | Seed poll interval. |
| `NAVI_RUNTIME_JOB_LEASE_S` | Seed lease. |
| `NAVI_LOCAL_API_ENABLED` | Seed local API enabled. |
| `NAVI_LOCAL_API_HOST` / `NAVI_LOCAL_API_PORT` / `NAVI_LOCAL_API_LOG_LEVEL` | Seed bind and log level. |
| `NAVI_TELEGRAM_BOT_ENABLED` / `NAVI_TELEGRAM_ALLOWED_CHAT_IDS` | Seed Telegram prefs. |

Prefer the in-app Settings dialog for day-to-day changes so you are not maintaining two sources of truth.

## Recurring runtime jobs

Roughly every 15 minutes the runtime calls `ensure_recurring_jobs()`, which **enqueues** (idempotently, via `unique_key`):

- `daily_briefing_refresh` — precomputes briefing for the day.
- `assignment_followup_scan` — adds `runtime_nudge` events for overdue or stuck assignments.
- `billing_autorun` — monthly billing draft when settings say it is due (`core/runtime/jobs.py`).

Execution happens when `process_due_jobs()` claims due rows and dispatches to `execute_runtime_job()`.

## GUI vs runtime

When the shared runtime **scheduler has started**, billing auto-run **enqueue** is owned by the runtime; the main window only **drains** the queue and shows review prompts (`gui/interface.py`). If the scheduler failed to start but APScheduler is installed, the GUI falls back to enqueuing before `process_due_jobs()` so monthly billing can still run.

Other UI timers (dashboard refresh, briefing timeouts) stay on the Qt side by design; they are not duplicated on the job queue.

## Quick verification

1. In **Settings → App preferences**, leave **Enable background runtime scheduler** on (default after migration).
2. Restart the app. Confirm `logs/app.log` contains `Runtime service started` and a line with the poll interval.
3. Optional: enable **local API**, restart, then:

   `curl -s http://127.0.0.1:8765/health`

   Expect JSON with `"ok": true` and capability blocks for scheduler, local API host, browser tools, and Telegram.

## Production-style validation checklist

Use this when deciding what stays enabled for daily use.

1. **Runtime on, local API off** (recommended baseline): restart twice; confirm `Runtime service started` appears once per session and no traceback from `core.runtime`.
2. **Job queue**: after ~15 minutes (or temporarily lower poll interval in Settings for a test profile), confirm `runtime_jobs` receives rows and transitions (SQLite or `GET /jobs` if API enabled). Dashboard briefing cache should update when `daily_briefing_refresh` runs.
3. **Billing path**: if monthly autorun is configured, confirm either the review prompt or `billing.pending_review_*` settings; with runtime on, the GUI tick still calls `process_due_jobs()` even after you dismissed the monthly dialog (so briefing/follow-up jobs keep draining).
4. **Local API on**: hit `/health` and `/tools` from loopback only; confirm `browser_tools` reports unavailable with a clear reason if Playwright is not installed (expected on some machines).
5. **Shutdown**: quit the app cleanly; log should not show repeated scheduler errors (shutdown is best-effort).

## Automated tests

- `tests/test_runtime_service.py` — scheduler start/stop, `process_due_jobs`, failures.
- `tests/test_runtime_jobs.py` — DB enqueue, claim, retry.
- `tests/test_local_api.py` — HTTP routes with `TestClient`.

## Security

Treat the local API as **trusted local automation**: anything that can POST to it can invoke tools and enqueue jobs. Keep it on loopback, firewall off, and disabled unless you need it. See `SECURITY.md` and `docs/api.md`.

## See also

- `docs/api.md` — endpoint list and integration overview.
- `docs/staff_replacement_matrix.md` — why the runtime backbone matters for replacement-grade behavior.
