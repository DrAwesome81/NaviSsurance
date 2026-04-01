from __future__ import annotations

from core.db import DatabaseManager


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
