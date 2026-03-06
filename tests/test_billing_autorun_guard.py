from __future__ import annotations

from datetime import date

from core.billing import autorun
from core.billing import invoice_service
from core.db import DatabaseManager


def test_should_autorun_guard_and_last_autorun_yyyymm(tmp_path, monkeypatch):
    db = DatabaseManager(db_name=str(tmp_path / "billing.db"))
    monkeypatch.setattr(invoice_service, "ARTIFACTS_DIR", str(tmp_path / "artifacts"))

    client_id = db.billing_client_create(name="Acme", default_rate=100.0)
    template_id = db.invoice_template_create(name="T1", template_body="Hi {{client_name}} {{total_hours}} {{total_amount}}")
    db.set_setting("billing.default_template_id", str(template_id))

    today = date(2026, 2, 15)
    db.set_setting("billing.autorun_enabled", "true")
    db.set_setting("billing.autorun_day_of_month", str(today.day))
    db.set_setting("billing.last_autorun_yyyymm", "")

    assert autorun.should_autorun(db, today=today) is True
    out = autorun.run_monthly_autodraft(db, today=today)
    assert out.ran is True
    assert autorun.should_autorun(db, today=today) is False

    # Disabling prevents autorun
    db.set_setting("billing.autorun_enabled", "false")
    assert autorun.should_autorun(db, today=today) is False

