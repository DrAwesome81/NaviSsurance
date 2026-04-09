from __future__ import annotations

import logging
import threading

from core.app_preferences import (
    get_local_api_host,
    get_local_api_log_level,
    get_local_api_port,
    is_local_api_enabled,
)
from core.db import DatabaseManager

logger = logging.getLogger(__name__)

try:
    import uvicorn
except Exception:  # pragma: no cover - optional dependency during bootstrap
    uvicorn = None


def local_api_available() -> tuple[bool, str]:
    if uvicorn is None:
        return False, "uvicorn is not installed."
    return True, "available"


def local_api_status(db: DatabaseManager | None = None) -> tuple[bool, str]:
    if not bool(is_local_api_enabled(db)):
        return False, "Disabled in Settings (local API)."
    return local_api_available()


class LocalApiService:
    def __init__(self, *, db: DatabaseManager | None = None):
        self._db = db or DatabaseManager()
        self._thread: threading.Thread | None = None
        self._server = None

    def start(self) -> bool:
        if self._thread is not None:
            return True
        ok, reason = local_api_status(self._db)
        if not ok or uvicorn is None:
            logger.warning("Local API unavailable: %s", reason)
            return False
        from api.app import app

        host = get_local_api_host(self._db)
        port = int(get_local_api_port(self._db))
        log_level = get_local_api_log_level(self._db)
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level=log_level,
        )
        self._server = uvicorn.Server(config)

        def _run():
            self._server.run()

        self._thread = threading.Thread(target=_run, name="navi-local-api", daemon=True)
        self._thread.start()
        logger.info("Local API started on %s:%s", host, port)
        return True

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        self._thread = None
        self._server = None


_local_api_service: LocalApiService | None = None


def get_local_api_service(*, db: DatabaseManager | None = None) -> LocalApiService:
    global _local_api_service
    if _local_api_service is None:
        _local_api_service = LocalApiService(db=db)
    elif db is not None:
        _local_api_service._db = db
    return _local_api_service
