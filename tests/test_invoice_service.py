from __future__ import annotations

from datetime import date, datetime

from core.billing import invoice_service
from core.db import DatabaseManager


def test_generate_invoice_draft_writes_file_and_is_idempotent(tmp_path, monkeypatch):
    db_path = tmp_path / "billing.db"
    db = DatabaseManager(db_name=str(db_path))

    # Keep artifacts in tmp.
    monkeypatch.setattr(invoice_service, "ARTIFACTS_DIR", str(tmp_path / "artifacts"))

    client_id = db.billing_client_create(name="Acme", default_rate=200.0, currency="USD")
    template_id = db.invoice_template_create(
        name="T1",
        template_body="Client {{client_name}} hours {{total_hours}} amount {{total_amount}}\n\n{{line_items_md}}",
    )

    ps = date(2026, 1, 1)
    pe = date(2026, 1, 31)

    db.time_entry_add(
        client_id=client_id,
        start_ts=datetime(2026, 1, 10, 9, 0, 0).isoformat(),
        end_ts=datetime(2026, 1, 10, 10, 0, 0).isoformat(),
        minutes=60,
        description="Work A",
        is_billable=1,
    )
    db.time_entry_add(
        client_id=client_id,
        start_ts=datetime(2026, 1, 11, 9, 0, 0).isoformat(),
        end_ts=datetime(2026, 1, 11, 9, 30, 0).isoformat(),
        minutes=30,
        description="Work B",
        is_billable=1,
    )

    res1 = invoice_service.generate_invoice_draft(db, client_id=client_id, period_start=ps, period_end=pe, template_id=template_id)
    assert res1.draft_id > 0
    assert res1.file_path is not None
    assert "Acme" in res1.rendered_body_md
    assert res1.reused_existing is False
    assert res1.totals["total_minutes"] == 90
    assert abs(res1.totals["total_hours"] - 1.5) < 1e-6
    assert res1.totals["amount"] == 300.0

    # File written
    assert res1.file_path
    assert (tmp_path / "artifacts" / "invoice_drafts" / str(res1.draft_id)).exists()

    drafts_after_1 = db.invoice_drafts_list(client_id=client_id)
    assert len(drafts_after_1) == 1

    # Idempotent: same period returns same draft.
    res2 = invoice_service.generate_invoice_draft(db, client_id=client_id, period_start=ps, period_end=pe, template_id=template_id)
    assert res2.draft_id == res1.draft_id
    assert res2.reused_existing is True
    drafts_after_2 = db.invoice_drafts_list(client_id=client_id)
    assert len(drafts_after_2) == 1

