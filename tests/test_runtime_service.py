from __future__ import annotations

import sqlite3

from core.db import DatabaseManager
import core.runtime.service as runtime_service
# Runtime service tests support Pulse private memory jobs, Intel monitoring, and 🛡️ Shield security scheduling (runtime service tests)
# additional Pulse private memory + Shield for runtime service tests



class _FakeScheduler:
    def __init__(self, timezone=None):
        self.timezone = timezone
        self.jobs: list[dict] = []
        self.started = False
        self.shutdown_calls: list[bool] = []

    def add_job(self, func, trigger, **kwargs):
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})

    def start(self):
        self.started = True

    def shutdown(self, wait=False):
        self.shutdown_calls.append(bool(wait))


def test_runtime_scheduler_status_disabled_when_runtime_flag_off(monkeypatch):
    monkeypatch.setattr(runtime_service, "is_runtime_enabled", lambda db=None: False)
    ok, reason = runtime_service.runtime_scheduler_status()
    assert ok is False
    assert "Settings" in reason


def test_runtime_service_start_returns_false_when_scheduler_unavailable(tmp_path, monkeypatch):
    db = DatabaseManager(str(tmp_path / "runtime_unavailable.db"))
    monkeypatch.setattr(runtime_service, "runtime_scheduler_available", lambda: (False, "missing"))

    service = runtime_service.RuntimeService(db=db)

    assert service.start() is False
    assert service._started is False


def test_runtime_service_start_registers_jobs_and_starts_scheduler(tmp_path, monkeypatch):
    db = DatabaseManager(str(tmp_path / "runtime_start.db"))
    monkeypatch.setattr(runtime_service, "BackgroundScheduler", _FakeScheduler)
    monkeypatch.setattr(runtime_service, "runtime_scheduler_available", lambda: (True, "available"))

    service = runtime_service.RuntimeService(db=db)
    calls = {"ensure": 0}
    service.ensure_recurring_jobs = lambda: calls.__setitem__("ensure", calls["ensure"] + 1)

    started = service.start()

    assert started is True
    assert service._started is True
    assert isinstance(service._scheduler, _FakeScheduler)
    assert service._scheduler.started is True
    assert {job["id"] for job in service._scheduler.jobs} == {
        "runtime_process_due_jobs",
        "runtime_ensure_recurring_jobs",
    }
    assert calls["ensure"] == 1

    service.stop()
    assert service._started is False
    assert service._scheduler.shutdown_calls == [False]


def test_runtime_service_ensure_recurring_jobs_calls_enqueue_helpers(tmp_path, monkeypatch):
    db = DatabaseManager(str(tmp_path / "runtime_recurring.db"))
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(runtime_service, "enqueue_daily_briefing_refresh", lambda runtime_db: seen.append(("briefing", runtime_db.db_name)))
    monkeypatch.setattr(runtime_service, "enqueue_assignment_followup_scan", lambda runtime_db: seen.append(("followup", runtime_db.db_name)))
    monkeypatch.setattr(runtime_service, "enqueue_billing_autorun", lambda runtime_db: seen.append(("billing", runtime_db.db_name)))

    service = runtime_service.RuntimeService(db=db)
    service.ensure_recurring_jobs()

    assert seen == [
        ("briefing", db.db_name),
        ("followup", db.db_name),
        ("billing", db.db_name),
    ]


def test_runtime_service_process_due_jobs_completes_jobs(tmp_path, monkeypatch):
    db = DatabaseManager(str(tmp_path / "runtime_process.db"))
    db.runtime_job_enqueue(job_type="daily_briefing_refresh", payload_json={"force": True})
    monkeypatch.setattr(runtime_service, "execute_runtime_job", lambda db, job_type, payload_json: {"ok": True, "job_type": job_type})

    service = runtime_service.RuntimeService(db=db)
    processed = service.process_due_jobs()

    assert processed == 1
    completed = db.runtime_job_list(status="completed", limit=10)
    assert len(completed) == 1
    assert completed[0]["job_type"] == "daily_briefing_refresh"

    with sqlite3.connect(db.db_name) as conn:
        row = conn.execute(
            "SELECT status, result_json FROM runtime_job_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row == ("completed", '{"ok": true, "job_type": "daily_briefing_refresh"}')


def test_runtime_service_process_due_jobs_marks_failures(tmp_path, monkeypatch):
    db = DatabaseManager(str(tmp_path / "runtime_fail.db"))
    db.runtime_job_enqueue(
        job_type="assignment_followup_scan",
        payload_json={},
        max_attempts=1,
    )
    monkeypatch.setattr(runtime_service, "execute_runtime_job", lambda db, job_type, payload_json: (_ for _ in ()).throw(RuntimeError("boom")))

    service = runtime_service.RuntimeService(db=db)
    processed = service.process_due_jobs()

    assert processed == 1
    failed = db.runtime_job_list(status="failed", limit=10)
    assert len(failed) == 1
    assert failed[0]["last_error"] == "boom"

    with sqlite3.connect(db.db_name) as conn:
        row = conn.execute(
            "SELECT status, error_text FROM runtime_job_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row == ("failed", "boom")
