from __future__ import annotations

from datetime import date, datetime

import pytest

from core.billing import invoice_service
from core.db import DatabaseManager


@pytest.fixture
def tmp_db(tmp_path):
    db = DatabaseManager(db_name=str(tmp_path / "billing.db"))
    return db


def test_generate_invoice_draft_writes_html_when_template_engine_is_html(tmp_db, tmp_path, monkeypatch):
    monkeypatch.setattr(invoice_service, "ARTIFACTS_DIR", str(tmp_path / "artifacts"))

    cid = tmp_db.billing_client_create(name="Acme", default_rate=100.0, currency="USD")
    tmp_db.time_entry_add(
        client_id=cid,
        start_ts=datetime(2026, 3, 1, 9, 0, 0).isoformat(timespec="seconds"),
        end_ts=datetime(2026, 3, 1, 10, 0, 0).isoformat(timespec="seconds"),
        minutes=60,
        description="Work",
        is_billable=1,
    )
    tid = tmp_db.invoice_template_create(
        name="HTML",
        template_body="<!doctype html><html><body>{{client_name}} {{line_items_html}}</body></html>",
        engine="placeholder_v1_html",
    )

    res = invoice_service.generate_invoice_draft(
        tmp_db,
        client_id=cid,
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 1),
        template_id=tid,
    )
    assert res.file_path is not None
    assert res.file_path.endswith(".html")
    with open(res.file_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "<html" in content.lower()
    assert "Acme" in content


def test_generate_invoice_draft_writes_md_when_template_engine_is_markdown(tmp_db, tmp_path, monkeypatch):
    monkeypatch.setattr(invoice_service, "ARTIFACTS_DIR", str(tmp_path / "artifacts"))

    cid = tmp_db.billing_client_create(name="Acme", default_rate=None, currency="USD")
    tid = tmp_db.invoice_template_create(
        name="MD",
        template_body="# Invoice\nClient {{client_name}}\n\n{{line_items_md}}",
        engine="placeholder_v1",
    )

    res = invoice_service.generate_invoice_draft(
        tmp_db,
        client_id=cid,
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 1),
        template_id=tid,
    )
    assert res.file_path is not None
    assert res.file_path.endswith(".md")

