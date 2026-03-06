from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from config import ARTIFACTS_DIR
from core.billing.template_render import render_template
from core.db import DatabaseManager


@dataclass(frozen=True)
class InvoiceDraftResult:
    draft_id: int
    file_path: str | None
    rendered_body_md: str
    totals: dict
    reused_existing: bool = False


def _safe_filename(s: str) -> str:
    t = (s or "").strip()
    t = re.sub(r"\s+", "_", t)
    t = re.sub(r"[^a-zA-Z0-9_\\-\\.]", "", t)
    return t[:80] or "client"


def _period_bounds(period_start: date, period_end: date) -> tuple[str, str]:
    """
    Return inclusive start (ISO) and exclusive end (ISO) timestamps in UTC-ish strings.
    """
    start_iso = datetime(period_start.year, period_start.month, period_start.day).isoformat()
    end_exclusive = datetime(period_end.year, period_end.month, period_end.day) + timedelta(days=1)
    end_iso = end_exclusive.isoformat()
    return start_iso, end_iso


def generate_invoice_draft(
    db: DatabaseManager,
    *,
    client_id: int,
    period_start: date,
    period_end: date,
    template_id: int,
    force_new: bool = False,
) -> InvoiceDraftResult:
    """
    Generate (or reuse) an invoice draft for a client and period.
    Writes a markdown artifact and stores metadata in SQLite.
    """
    if period_end < period_start:
        raise ValueError("period_end must be >= period_start")

    client = db.billing_client_get(int(client_id))
    if not client:
        raise ValueError(f"Client {client_id} not found")

    tmpl = db.invoice_template_get(int(template_id))
    if not tmpl:
        raise ValueError(f"Template {template_id} not found")
    tmpl_engine = str((tmpl or {}).get("engine") or "placeholder_v1").strip().lower()
    is_html = "html" in tmpl_engine

    period_start_s = period_start.isoformat()
    period_end_s = period_end.isoformat()

    # Idempotency: avoid duplicate drafts for the same client+period (unless voided),
    # unless the caller requests a forced regeneration.
    existing_id: int | None = None
    if not force_new:
        try:
            import sqlite3

            with sqlite3.connect(db.db_name) as conn:
                row = conn.execute(
                    """
                    SELECT id FROM invoice_drafts
                    WHERE client_id = ? AND period_start = ? AND period_end = ? AND status != 'void'
                    ORDER BY id DESC LIMIT 1
                    """,
                    (int(client_id), period_start_s, period_end_s),
                ).fetchone()
                if row:
                    existing_id = int(row[0])
        except Exception:
            existing_id = None

    if existing_id is not None:
        existing = db.invoice_draft_get(existing_id)
        if existing:
            return InvoiceDraftResult(
                draft_id=int(existing["id"]),
                file_path=existing.get("file_path"),
                rendered_body_md=str(existing.get("rendered_body_md") or ""),
                totals=json.loads(existing.get("totals_json") or "{}"),
                reused_existing=True,
            )

    start_iso, end_iso = _period_bounds(period_start, period_end)
    entries = db.time_entries_list(client_id=int(client_id), start_ts=start_iso, end_ts=end_iso, limit=5000)
    billable_entries = [e for e in entries if int(e.get("is_billable") or 0) == 1]

    # Line items (group by date)
    by_day: dict[str, list[dict]] = {}
    for e in sorted(billable_entries, key=lambda x: str(x.get("start_ts") or "")):
        day = str(e.get("start_ts") or "")[:10] or "unknown-date"
        by_day.setdefault(day, []).append(e)

    line_parts: list[str] = []
    line_parts_html: list[str] = []
    total_minutes = 0
    for day, items in by_day.items():
        line_parts.append(f"### {day}")
        # Compact HTML for fixed-layout invoice templates (avoid big margins / lists).
        line_parts_html.append(f"<div style=\"margin: 6px 0 2px 0; font-weight: 600;\">{day}</div>")
        for it in items:
            mins = int(it.get("minutes") or 0)
            total_minutes += mins
            hours = mins / 60.0
            desc = str(it.get("description") or "").strip()
            desc_part = f" — {desc}" if desc else ""
            line_parts.append(f"- {hours:.2f}h{desc_part}")
            # Basic HTML escaping
            desc_html = (
                str(desc).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                if desc
                else ""
            )
            desc_part_html = f" — {desc_html}" if desc_html else ""
            line_parts_html.append(f"<div style=\"margin: 0 0 1px 0;\">{hours:.2f}h{desc_part_html}</div>")
        line_parts.append("")
        line_parts_html.append("<div style=\"height: 6px;\"></div>")

    total_hours = total_minutes / 60.0
    rate = client.get("default_rate")
    amount = None
    if rate is not None:
        try:
            amount = float(rate) * float(total_hours)
        except Exception:
            amount = None

    currency = str(client.get("currency") or "USD").strip() or "USD"
    total_amount_s = f"{amount:.2f} {currency}" if amount is not None else f"(rate not set) {currency}"

    totals = {
        "total_minutes": int(total_minutes),
        "total_hours": float(round(total_hours, 4)),
        "default_rate": rate,
        "amount": amount,
        "currency": currency,
        "entry_count": int(len(billable_entries)),
    }

    # Create the draft row first so we can use its id as an invoice number.
    # (Templates can render {{invoice_number}} deterministically.)
    draft_id = db.invoice_draft_create(
        client_id=int(client_id),
        period_start=period_start_s,
        period_end=period_end_s,
        totals_json=json.dumps(totals, ensure_ascii=False),
        rendered_body_md="",
        file_path=None,
        status="draft",
    )

    # Friendly formatted date strings for templates.
    period_start_mmddyyyy = period_start.strftime("%m/%d/%Y")
    period_end_mmddyyyy = period_end.strftime("%m/%d/%Y")

    total_amount_number = f"{amount:.2f}" if amount is not None else ""
    if amount is not None:
        amt_commas = format(float(amount), ",.2f")
        if currency.upper() == "USD":
            total_amount_display = f"${amt_commas}"
        else:
            total_amount_display = f"{amt_commas} {currency}"
    else:
        total_amount_display = total_amount_s

    context = {
        "client_name": str(client.get("name") or "").strip(),
        "billing_email": str(client.get("billing_email") or "").strip(),
        "invoice_number": f"PM{int(draft_id):04d}",
        "due_date": "Due upon receipt",
        "period_start": period_start_s,
        "period_end": period_end_s,
        "period_start_mmddyyyy": period_start_mmddyyyy,
        "period_end_mmddyyyy": period_end_mmddyyyy,
        "period_range": f"{period_start_mmddyyyy} - {period_end_mmddyyyy}",
        "line_items_md": "\n".join(line_parts).strip() or "(No billable time entries found.)",
        "line_items_html": "\n".join(line_parts_html).strip() or "<p>(No billable time entries found.)</p>",
        "total_hours": f"{total_hours:.2f}",
        "total_minutes": str(int(total_minutes)),
        "currency": currency,
        "total_amount": total_amount_s,
        "total_amount_number": total_amount_number,
        "total_amount_display": total_amount_display,
        "default_rate": (str(rate) if rate is not None else ""),
    }

    rendered = render_template(str(tmpl.get("template_body") or ""), context)
    # Persist the rendered body (best-effort).
    try:
        import sqlite3

        with sqlite3.connect(db.db_name) as conn:
            conn.execute(
                "UPDATE invoice_drafts SET rendered_body_md = ?, totals_json = ? WHERE id = ?",
                (str(rendered or ""), json.dumps(totals, ensure_ascii=False), int(draft_id)),
            )
            conn.commit()
    except Exception:
        pass

    # Persist artifact markdown to disk.
    file_path: str | None = None
    try:
        base = os.path.join(str(ARTIFACTS_DIR), "invoice_drafts", str(draft_id))
        os.makedirs(base, exist_ok=True)
        yyyymm = period_start_s[:7].replace("-", "")
        ext = "html" if is_html else "md"
        fname = f"invoice_{_safe_filename(context['client_name'])}_{yyyymm}.{ext}"
        file_path = os.path.join(base, fname)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(rendered or "")

        # Best-effort: update row with file_path.
        try:
            import sqlite3

            with sqlite3.connect(db.db_name) as conn:
                conn.execute("UPDATE invoice_drafts SET file_path = ? WHERE id = ?", (file_path, int(draft_id)))
                conn.commit()
        except Exception:
            pass
    except Exception:
        file_path = None

    return InvoiceDraftResult(
        draft_id=int(draft_id),
        file_path=file_path,
        rendered_body_md=rendered,
        totals=totals,
    )


def previous_month_period(today: date | None = None) -> tuple[date, date]:
    d = today or date.today()
    first_this_month = date(d.year, d.month, 1)
    last_prev_month = first_this_month - timedelta(days=1)
    first_prev_month = date(last_prev_month.year, last_prev_month.month, 1)
    return first_prev_month, last_prev_month

