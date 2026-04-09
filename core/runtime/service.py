from __future__ import annotations

import logging
import socket
import threading
from functools import lru_cache
from datetime import datetime, UTC

from core.app_preferences import (
    get_runtime_job_lease_s,
    get_runtime_poll_interval_s,
    is_runtime_enabled,
)
from core.db import DatabaseManager
from core.runtime.jobs import (
    enqueue_assignment_followup_scan,
    enqueue_billing_autorun,
    enqueue_daily_briefing_refresh,
    execute_runtime_job,
)

logger = logging.getLogger(__name__)

try:
    from apscheduler.schedulers.background import BackgroundScheduler
except Exception:  # pragma: no cover - optional dependency during install/bootstrap
    BackgroundScheduler = None


def runtime_scheduler_available() -> tuple[bool, str]:
    if BackgroundScheduler is None:
        return False, "APScheduler is not installed."
    return True, "available"


def runtime_scheduler_status(db: DatabaseManager | None = None) -> tuple[bool, str]:
    if not bool(is_runtime_enabled(db)):
        return False, "Disabled in Settings (runtime scheduler)."
    return runtime_scheduler_available()


class RuntimeService:
    def __init__(self, *, db: DatabaseManager | None = None):
        self.db = db or DatabaseManager()
        self.runner_id = f"{socket.gethostname()}:{threading.get_ident()}"
        self._lock = threading.Lock()
        self._scheduler = BackgroundScheduler(timezone="UTC") if BackgroundScheduler is not None else None
        self._started = False

    def start(self) -> bool:
        if self._started:
            return True
        ok, reason = runtime_scheduler_available()
        if not ok or self._scheduler is None:
            logger.warning("Runtime scheduler unavailable: %s", reason)
            return False
        self._scheduler.add_job(
            self.process_due_jobs,
            "interval",
            seconds=max(5, int(get_runtime_poll_interval_s(self.db))),
            id="runtime_process_due_jobs",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        self._scheduler.add_job(
            self.ensure_recurring_jobs,
            "interval",
            minutes=15,
            id="runtime_ensure_recurring_jobs",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        self._scheduler.start()
        self.ensure_recurring_jobs()
        self._started = True
        logger.info("Runtime service started.")
        return True

    def stop(self) -> None:
        if self._scheduler is not None and self._started:
            try:
                self._scheduler.shutdown(wait=False)
            except Exception:
                logger.exception("Runtime scheduler shutdown failed")
        self._started = False

    def ensure_recurring_jobs(self) -> None:
        try:
            enqueue_daily_briefing_refresh(self.db)
            enqueue_assignment_followup_scan(self.db)
            enqueue_billing_autorun(self.db)
        except Exception:
            logger.exception("Failed to enqueue recurring runtime jobs")

    def process_due_jobs(self) -> int:
        if not self._lock.acquire(blocking=False):
            return 0
        processed = 0
        try:
            while True:
                claimed = self.db.runtime_job_claim_due(
                    runner_id=self.runner_id,
                    lease_seconds=get_runtime_job_lease_s(self.db),
                )
                if not claimed:
                    break
                processed += 1
                job_id = int(claimed.get("id") or 0)
                run_id = int(claimed.get("run_id") or 0)
                try:
                    result = execute_runtime_job(
                        self.db,
                        job_type=str(claimed.get("job_type") or ""),
                        payload_json=str(claimed.get("payload_json") or ""),
                    )
                    self.db.runtime_job_complete(job_id=job_id, run_id=run_id, result_json=result)
                except Exception as exc:
                    retry_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                    self.db.runtime_job_fail(job_id=job_id, run_id=run_id, error_text=str(exc), retry_at=retry_at)
                    logger.exception("Runtime job %s failed", job_id)
        finally:
            self._lock.release()
        return processed


_runtime_service: RuntimeService | None = None


def get_runtime_service(*, db: DatabaseManager | None = None) -> RuntimeService:
    global _runtime_service
    if _runtime_service is None:
        _runtime_service = RuntimeService(db=db)
    elif db is not None:
        _runtime_service.db = db
    return _runtime_service
