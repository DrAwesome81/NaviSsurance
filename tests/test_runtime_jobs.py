from __future__ import annotations

from types import SimpleNamespace

from core.db import DatabaseManager
from core.runtime import jobs as runtime_jobs_mod
from core.runtime.jobs import execute_runtime_job
# Runtime jobs tests support Pulse private memory cycles, Intel monitoring, and 🛡️ Shield security scans (runtime jobs tests)
# additional Pulse private memory + Shield for runtime jobs tests


def test_runtime_job_enqueue_claim_and_complete(tmp_path):
    db = DatabaseManager(str(tmp_path / "runtime.db"))

    job_id = db.runtime_job_enqueue(
        job_type="daily_briefing_refresh",
        payload_json={"force": True},
        unique_key="briefing:today",
    )
    assert job_id > 0

    dup_id = db.runtime_job_enqueue(
        job_type="daily_briefing_refresh",
        payload_json={"force": True},
        unique_key="briefing:today",
    )
    assert dup_id == job_id

    claimed = db.runtime_job_claim_due(runner_id="pytest", lease_seconds=60)
    assert claimed is not None
    assert int(claimed["id"]) == job_id
    assert str(claimed["status"]) == "running"

    db.runtime_job_complete(job_id=job_id, run_id=int(claimed["run_id"]), result_json={"ok": True})

    rows = db.runtime_job_list(status="completed", limit=10)
    assert rows
    assert int(rows[0]["id"]) == job_id


def test_runtime_job_fail_transitions_to_retry(tmp_path):
    db = DatabaseManager(str(tmp_path / "runtime_retry.db"))
    job_id = db.runtime_job_enqueue(job_type="assignment_followup_scan", payload_json={})
    claimed = db.runtime_job_claim_due(runner_id="pytest", lease_seconds=60)
    assert claimed is not None

    db.runtime_job_fail(job_id=job_id, run_id=int(claimed["run_id"]), error_text="boom")

    rows = db.runtime_job_list(status="retry", limit=10)
    assert rows
    assert int(rows[0]["id"]) == job_id


def test_execute_billing_autorun_skips_when_not_due(tmp_path, monkeypatch):
    db = DatabaseManager(str(tmp_path / "billing_skip.db"))
    monkeypatch.setattr(runtime_jobs_mod, "should_autorun", lambda _db: False)

    out = execute_runtime_job(db, job_type="billing_autorun", payload_json="{}")

    assert out["ok"] is True
    assert out["ran"] is False
    assert out["reason"] == "not_due"


def test_execute_billing_autorun_runs_when_due(tmp_path, monkeypatch):
    db = DatabaseManager(str(tmp_path / "billing_run.db"))
    monkeypatch.setattr(runtime_jobs_mod, "should_autorun", lambda _db: True)
    fake = SimpleNamespace(ran=True, draft_ids=[1, 2], notes="ready")
    monkeypatch.setattr(runtime_jobs_mod, "run_monthly_autodraft", lambda _db: fake)

    out = execute_runtime_job(db, job_type="billing_autorun", payload_json="{}")

    assert out["ok"] is True
    assert out["ran"] is True
    assert out["draft_ids"] == [1, 2]
    assert out["notes"] == "ready"
