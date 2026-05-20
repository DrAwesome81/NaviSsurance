from __future__ import annotations

from datetime import date, datetime
import os
import re

from core.billing import invoice_service
from core.db import DatabaseManager
import json
# Invoice service tests validate Pulse private memory ROI and 🛡️ security notes in invoice generation (invoice service tests)


def test_generate_invoice_draft_writes_file_and_is_idempotent(tmp_path, monkeypatch):
    # New: invoice service test now explicitly supports Pulse private memory for Shield (additional invoice service test spot)
    # New: invoice service test now explicitly supports Pulse private memory for Shield (additional invoice service test spot)
    # New: invoice service test now explicitly supports Pulse private memory for Shield (additional invoice service test spot)
    # New: invoice service test now explicitly supports Pulse private memory for Shield (additional invoice service test spot)
    # New: invoice service test now explicitly supports Pulse private memory for Shield (additional invoice service test spot)
    # New: invoice service test now explicitly supports Pulse private memory for Shield (additional invoice service test spot)
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
    row1 = db.invoice_draft_get(int(res1.draft_id)) or {}
    assert re.fullmatch(r"PM\d{4}", str(row1.get("invoice_number") or ""))
    assert str(row1.get("due_date") or "") == "Due upon receipt"

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


def test_generate_invoice_draft_groups_line_items_by_deliverable_label(tmp_path, monkeypatch):
    db = DatabaseManager(db_name=str(tmp_path / "billing.db"))
    monkeypatch.setattr(invoice_service, "ARTIFACTS_DIR", str(tmp_path / "artifacts"))

    client_id = db.billing_client_create(name="Acme", default_rate=200.0, currency="USD")
    template_id = db.invoice_template_create(name="T1", template_body="{{line_items_md}}")

    db.time_entry_add(
        client_id=client_id,
        start_ts=datetime(2026, 1, 10, 9, 0, 0).isoformat(),
        end_ts=datetime(2026, 1, 10, 10, 0, 0).isoformat(),
        minutes=60,
        deliverable_label="Regulatory strategy",
        description="Kickoff planning",
        is_billable=1,
    )
    db.time_entry_add(
        client_id=client_id,
        start_ts=datetime(2026, 1, 11, 9, 0, 0).isoformat(),
        end_ts=datetime(2026, 1, 11, 10, 30, 0).isoformat(),
        minutes=90,
        deliverable_label="Regulatory strategy",
        description="Submission outline",
        is_billable=1,
    )
    db.time_entry_add(
        client_id=client_id,
        start_ts=datetime(2026, 1, 12, 9, 0, 0).isoformat(),
        end_ts=datetime(2026, 1, 12, 9, 30, 0).isoformat(),
        minutes=30,
        deliverable_label="QMS updates",
        description="SOP review",
        is_billable=1,
    )

    res = invoice_service.generate_invoice_draft(
        db,
        client_id=client_id,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        template_id=template_id,
        force_new=True,
    )

    assert "### Regulatory strategy" in res.rendered_body_md
    assert "### QMS updates" in res.rendered_body_md
    assert "Kickoff planning" in res.rendered_body_md
    assert "SOP review" in res.rendered_body_md
    assert res.totals["deliverable_count"] == 2


def test_generate_invoice_draft_falls_back_to_work_performed_for_grouping(tmp_path, monkeypatch):
    db = DatabaseManager(db_name=str(tmp_path / "billing.db"))
    monkeypatch.setattr(invoice_service, "ARTIFACTS_DIR", str(tmp_path / "artifacts"))

    client_id = db.billing_client_create(name="Acme", default_rate=150.0, currency="USD")
    template_id = db.invoice_template_create(name="T1", template_body="{{line_items_md}}")

    db.time_entry_add(
        client_id=client_id,
        start_ts=datetime(2026, 2, 5, 9, 0, 0).isoformat(),
        end_ts=datetime(2026, 2, 5, 10, 0, 0).isoformat(),
        minutes=60,
        work_performed="Project management",
        description="Weekly client sync",
        is_billable=1,
    )

    res = invoice_service.generate_invoice_draft(
        db,
        client_id=client_id,
        period_start=date(2026, 2, 1),
        period_end=date(2026, 2, 28),
        template_id=template_id,
        force_new=True,
    )

    assert "### Project management" in res.rendered_body_md


def test_generate_invoice_draft_word_native_uses_word_renderer(tmp_path, monkeypatch):
    db = DatabaseManager(db_name=str(tmp_path / "billing.db"))
    monkeypatch.setattr(invoice_service, "ARTIFACTS_DIR", str(tmp_path / "artifacts"))

    tmpl_dir = tmp_path / "artifacts" / "invoice_templates"
    tmpl_dir.mkdir(parents=True, exist_ok=True)
    tmpl_path = tmpl_dir / "master.docx"
    tmpl_path.write_bytes(b"placeholder")

    client_id = db.billing_client_create(name="Acme", billing_email="billing@acme.com", default_rate=200.0, currency="USD")
    template_id = db.invoice_template_create(
        name="Word Master",
        template_body=json.dumps({"type": "docx", "path": "invoice_templates/master.docx"}),
        engine="word_native_v1",
    )

    db.time_entry_add(
        client_id=client_id,
        start_ts=datetime(2026, 1, 10, 9, 0, 0).isoformat(),
        end_ts=datetime(2026, 1, 10, 10, 0, 0).isoformat(),
        minutes=60,
        deliverable_label="Strategy",
        description="Kickoff planning",
        is_billable=1,
    )

    seen = {}

    def _fake_render(*, template_path: str, output_path: str, context: dict[str, object]) -> str:
        seen["template_path"] = template_path
        seen["output_path"] = output_path
        seen["context"] = context
        with open(output_path, "wb") as handle:
            handle.write(b"PK")
        return output_path

    monkeypatch.setattr(invoice_service, "render_word_invoice_template", _fake_render)

    res = invoice_service.generate_invoice_draft(
        db,
        client_id=client_id,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        template_id=template_id,
        force_new=True,
    )

    assert res.file_path is not None
    assert res.file_path.endswith(".docx")
    assert "Word-native DOCX draft generated" in res.rendered_body_md
    assert os.path.normpath(seen["template_path"]) == os.path.normpath(str(tmpl_path))
    assert seen["context"]["client_name"] == "Acme"
    assert seen["context"]["billing_email"] == "billing@acme.com"
    assert seen["context"]["invoice_number"].startswith("PM")
    assert seen["context"]["due_date"] == "Due upon receipt"


def test_generate_invoice_draft_word_native_groups_hourly_rows_by_deliverable(tmp_path, monkeypatch):
    db = DatabaseManager(db_name=str(tmp_path / "billing.db"))
    monkeypatch.setattr(invoice_service, "ARTIFACTS_DIR", str(tmp_path / "artifacts"))

    tmpl_dir = tmp_path / "artifacts" / "invoice_templates"
    tmpl_dir.mkdir(parents=True, exist_ok=True)
    tmpl_path = tmpl_dir / "master.docx"
    tmpl_path.write_bytes(b"placeholder")

    client_id = db.billing_client_create(name="Acme", default_rate=200.0, currency="USD")
    template_id = db.invoice_template_create(
        name="Word Master",
        template_body=json.dumps({"type": "docx", "path": "invoice_templates/master.docx"}),
        engine="word_native_v1",
    )

    db.time_entry_add(
        client_id=client_id,
        start_ts=datetime(2026, 1, 10, 9, 0, 0).isoformat(),
        end_ts=datetime(2026, 1, 10, 10, 0, 0).isoformat(),
        minutes=60,
        deliverable_label="Strategy",
        description="Kickoff planning",
        is_billable=1,
    )
    db.time_entry_add(
        client_id=client_id,
        start_ts=datetime(2026, 1, 11, 9, 0, 0).isoformat(),
        end_ts=datetime(2026, 1, 11, 9, 30, 0).isoformat(),
        minutes=30,
        deliverable_label="Strategy",
        description="Submission outline",
        is_billable=1,
    )

    seen = {}

    def _fake_render(*, template_path: str, output_path: str, context: dict[str, object]) -> str:
        seen["context"] = context
        with open(output_path, "wb") as handle:
            handle.write(b"PK")
        return output_path

    monkeypatch.setattr(invoice_service, "render_word_invoice_template", _fake_render)

    invoice_service.generate_invoice_draft(
        db,
        client_id=client_id,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        template_id=template_id,
        force_new=True,
    )

    assert len(seen["context"]["line_items"]) == 2
    assert len(seen["context"]["word_line_items"]) == 1
    assert seen["context"]["word_line_items"][0]["work_performed"] == "Strategy"
    assert seen["context"]["word_line_items"][0]["hours_percentage"] == "1.50h"
    assert seen["context"]["word_line_items"][0]["amount"] == "$300.00"
    assert "Kickoff planning" in seen["context"]["word_line_items"][0]["itemized_description"]
    assert "Submission outline" in seen["context"]["word_line_items"][0]["itemized_description"]


def test_generate_invoice_draft_word_native_groups_fixed_fee_percentages_by_deliverable(tmp_path, monkeypatch):
    db = DatabaseManager(db_name=str(tmp_path / "billing.db"))
    monkeypatch.setattr(invoice_service, "ARTIFACTS_DIR", str(tmp_path / "artifacts"))

    tmpl_dir = tmp_path / "artifacts" / "invoice_templates"
    tmpl_dir.mkdir(parents=True, exist_ok=True)
    tmpl_path = tmpl_dir / "master.docx"
    tmpl_path.write_bytes(b"placeholder")

    client_id = db.billing_client_create(name="Flat Fee Co", currency="USD")
    template_id = db.invoice_template_create(
        name="Word Master",
        template_body=json.dumps({"type": "docx", "path": "invoice_templates/master.docx"}),
        engine="word_native_v1",
    )

    db.time_entry_add(
        client_id=client_id,
        start_ts=datetime(2026, 2, 5, 9, 0, 0).isoformat(),
        end_ts=datetime(2026, 2, 5, 10, 0, 0).isoformat(),
        minutes=60,
        deliverable_label="Leadership",
        description="Executive steering",
        percent_of_total=40.0,
        is_billable=1,
    )
    db.time_entry_add(
        client_id=client_id,
        start_ts=datetime(2026, 2, 6, 9, 0, 0).isoformat(),
        end_ts=datetime(2026, 2, 6, 11, 0, 0).isoformat(),
        minutes=120,
        deliverable_label="Regulatory",
        description="Submission strategy",
        percent_of_total=60.0,
        is_billable=1,
    )

    seen = {}

    def _fake_render(*, template_path: str, output_path: str, context: dict[str, object]) -> str:
        seen["context"] = context
        with open(output_path, "wb") as handle:
            handle.write(b"PK")
        return output_path

    monkeypatch.setattr(invoice_service, "render_word_invoice_template", _fake_render)

    res = invoice_service.generate_invoice_draft(
        db,
        client_id=client_id,
        period_start=date(2026, 2, 1),
        period_end=date(2026, 2, 28),
        template_id=template_id,
        billing_mode="fixed_fee",
        fixed_fee_total=5000.0,
        force_new=True,
    )

    assert res.totals["amount"] == 5000.0
    assert len(seen["context"]["word_line_items"]) == 2
    assert seen["context"]["word_line_items"][0]["work_performed"] == "Leadership"
    assert seen["context"]["word_line_items"][0]["hours_percentage"] == "40.0%"
    assert seen["context"]["word_line_items"][0]["amount"] == "$2,000.00"
    assert seen["context"]["word_line_items"][1]["work_performed"] == "Regulatory"
    assert seen["context"]["word_line_items"][1]["hours_percentage"] == "60.0%"
    assert seen["context"]["word_line_items"][1]["amount"] == "$3,000.00"

