from __future__ import annotations

from core.channels.telegram_bot import telegram_bot_available
from core.runtime.service import get_runtime_service, runtime_scheduler_available, runtime_scheduler_status
from core.service.local_api import local_api_available, local_api_status
from core.tools.browser import browser_tools_available


def test_optional_availability_helpers_return_reason():
    for helper in (
        runtime_scheduler_available,
        runtime_scheduler_status,
        local_api_available,
        local_api_status,
        browser_tools_available,
        telegram_bot_available,
    ):
        ok, reason = helper()
        assert isinstance(ok, bool)
        assert isinstance(reason, str)
        assert reason


def test_runtime_service_singleton_db_can_be_rebound(tmp_path):
    from core.db import DatabaseManager

    db_one = DatabaseManager(str(tmp_path / "one.db"))
    db_two = DatabaseManager(str(tmp_path / "two.db"))

    svc = get_runtime_service(db=db_one)
    assert svc.db.db_name == db_one.db_name

    svc2 = get_runtime_service(db=db_two)
    assert svc2 is svc
    assert svc2.db.db_name == db_two.db_name


def test_runtime_and_local_api_status_report_disabled(monkeypatch):
    import core.runtime.service as runtime_service
    import core.service.local_api as local_api

    monkeypatch.setattr(runtime_service, "is_runtime_enabled", lambda db=None: False)
    monkeypatch.setattr(local_api, "is_local_api_enabled", lambda db=None: False)

    assert runtime_service.runtime_scheduler_status() == (False, "Disabled in Settings (runtime scheduler).")
    assert local_api.local_api_status() == (False, "Disabled in Settings (local API).")
