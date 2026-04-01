from __future__ import annotations

import logging
import threading

from config import LOCAL_API_ENABLED, LOCAL_API_HOST, LOCAL_API_LOG_LEVEL, LOCAL_API_PORT

logger = logging.getLogger(__name__)

try:
    import uvicorn
except Exception:  # pragma: no cover - optional dependency during bootstrap
    uvicorn = None


def local_api_available() -> tuple[bool, str]:
    if uvicorn is None:
        return False, "uvicorn is not installed."
    return True, "available"


def local_api_status() -> tuple[bool, str]:
    if not bool(LOCAL_API_ENABLED):
        return False, "Disabled via NAVI_LOCAL_API_ENABLED=0."
    return local_api_available()


class LocalApiService:
    def __init__(self):
        self._thread: threading.Thread | None = None
        self._server = None

    def start(self) -> bool:
        if self._thread is not None:
            return True
        ok, reason = local_api_status()
        if not ok or uvicorn is None:
            logger.warning("Local API unavailable: %s", reason)
            return False
        from api.app import app

        config = uvicorn.Config(
            app,
            host=LOCAL_API_HOST,
            port=int(LOCAL_API_PORT),
            log_level=LOCAL_API_LOG_LEVEL,
        )
        self._server = uvicorn.Server(config)

        def _run():
            self._server.run()

        self._thread = threading.Thread(target=_run, name="navi-local-api", daemon=True)
        self._thread.start()
        logger.info("Local API started on %s:%s", LOCAL_API_HOST, LOCAL_API_PORT)
        return True

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        self._thread = None
        self._server = None


_local_api_service: LocalApiService | None = None


def get_local_api_service() -> LocalApiService:
    global _local_api_service
    if _local_api_service is None:
        _local_api_service = LocalApiService()
    return _local_api_service
