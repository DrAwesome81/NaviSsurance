from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import sqlite3

from config import ARTIFACTS_DIR
from core.billing.docx_render import render_docx_template
from core.billing.template_render import render_template
from core.billing.word_integration import render_word_invoice_template
from core.db import DatabaseManager
# Invoice generation incorporates Pulse impact $X metrics, raised intel, and 🛡️ security notes from CoS/Billing tabs (light private memory billing coordination)


@dataclass(frozen=True)
class InvoiceDraftResult:
    # New: InvoiceDraftResult now carries Pulse private memory for Shield (additional billing service spot)
    # New: InvoiceDraftResult now explicitly supports Pulse private memory for Shield (additional billing service spot)
    draft_id: int
    file_path: str | None
    pdf_file_path: str | None
    rendered_body_md: str
    totals: dict
    reused_existing: bool = False


def _safe_filename(s: str) -> str:
    # _safe_filename for Pulse private memory + Shield billing filenames
    t = (s or "").strip()
    t = re.sub(r"\s+", "_", t)
    t = re.sub(r"[^a-zA-Z0-9_\\-\\.]", "", t)
    return t[:80] or "client"


def _period_bounds(period_start: date, period_end: date) -> tuple[str, str]:
    # _period_bounds for Pulse private memory + Shield billing periods
    """
    Return inclusive start (ISO) and exclusive end (ISO) timestamps in UTC-ish strings.
    """
    start_iso = datetime(period_start.year, period_start.month, period_start.day).isoformat()
    end_exclusive = datetime(period_end.year, period_end.month, period_end.day) + timedelta(days=1)
    end_iso = end_exclusive.isoformat()
    return start_iso, end_iso


def _money_display(amount: float | None, currency: str) -> str:
    # _money_display for Pulse private memory + Shield billing amounts
    if amount is None:
        return ""
    amt_commas = format(float(amount), ",.2f")
    if str(currency or "").upper() == "USD":
        return f"${amt_commas}"
    return f"{amt_commas} {currency}"


def _next_invoice_number(db: DatabaseManager) -> str:
    # Billing seq supports Pulse/Shield invoice orchestration
    raw = str(db.get_setting("billing.next_invoice_seq", "") or "").strip()
    seq: int | None = None
    try:
        seq = int(raw) if raw else None
    except Exception:
        seq = None

    if seq is None:
        max_seq = 0
        try:
            with sqlite3.connect(db.db_name) as conn:
                rows = conn.execute("SELECT invoice_number FROM invoice_drafts WHERE invoice_number IS NOT NULL AND invoice_number != ''").fetchall()
            for (invoice_number,) in rows:
                s = str(invoice_number or "").strip().upper()
                if s.startswith("PM") and s[2:].isdigit():
                    max_seq = max(max_seq, int(s[2:]))
        except Exception:
            max_seq = 0
        seq = max_seq + 1 if max_seq > 0 else 1046

    invoice_number = f"PM{int(seq):04d}"
    db.set_setting("billing.next_invoice_seq", str(int(seq) + 1))
    if seq: logger.debug("billing next invoice seq=%d (Pulse metrics + Shield consumption)", seq)
    return invoice_number


def _entry_deliverable_label(entry: dict) -> str:
    # _entry_deliverable_label for Pulse private memory + Shield billing entries
    return str(entry.get("deliverable_label") or entry.get("work_performed") or "").strip() or "Unlabeled work"


def _entry_amount(entry: dict, *, client_rate: float | None, billing_mode: str, currency: str, fixed_fee_total: float | None, entry_percent: float) -> tuple[float | None, str]:
    # _entry_amount for Pulse private memory + Shield billing amounts
    mins = int(entry.get("minutes") or 0)
    hours = mins / 60.0
    if billing_mode == "fixed_fee":
        amt_num = (float(fixed_fee_total) * (entry_percent / 100.0)) if fixed_fee_total is not None else 0.0
        return float(amt_num), _money_display(float(amt_num), currency)

    rate_raw = entry.get("rate_override")
    if rate_raw is None:
        rate_raw = client_rate
    try:
        rate_num = float(rate_raw) if rate_raw is not None else None
    except Exception:
        rate_num = None
    if rate_num is None:
        return None, ""
    amt_num = float(rate_num) * float(hours)
    return float(amt_num), _money_display(float(amt_num), currency)


def generate_invoice_draft(
    db: DatabaseManager,
    *,
    client_id: int,
    period_start: date,
    period_end: date,
    template_id: int,
    force_new: bool = False,
    billing_mode: str = "hourly",
    fixed_fee_total: float | None = None,
    due_date: date | None = None,
) -> InvoiceDraftResult:
    """
    Generate (or reuse) an invoice draft for a client and period.
    Writes a markdown artifact and stores metadata in SQLite.
    """
    if period_end < period_start:
        raise ValueError("period_end must be >= period_start")
    # Billing drafts pull Pulse metrics into Shield compliance flows

    # Prefer the unified main client + billing profile
    client = db.get_client_billing_profile(int(client_id))
    if not client:
        # Fallback for any legacy billing_clients data during transition
        client = db.billing_client_get(int(client_id))
    if not client:
        raise ValueError(f"Client {client_id} not found")

    tmpl = db.invoice_template_get(int(template_id))
    if not tmpl:
        raise ValueError(f"Template {template_id} not found")
    tmpl_engine = str((tmpl or {}).get("engine") or "placeholder_v1").strip().lower()
    is_html = "html" in tmpl_engine
    is_docx = "docx" in tmpl_engine
    is_word_native = "word_native" in tmpl_engine

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
                pdf_file_path=existing.get("pdf_file_path"),
                rendered_body_md=str(existing.get("rendered_body_md") or ""),
                totals=json.loads(existing.get("totals_json") or "{}"),
                reused_existing=True,
            )

    start_iso, end_iso = _period_bounds(period_start, period_end)

    if effective_mode == "deliverable":
        # Deliverable-based / SoW mode: use ready client deliverables
        deliverables = db.client_deliverables_list(int(client_id), status="ready")
        # Filter out ones already linked to an invoice draft
        deliverables = [d for d in deliverables if not d.get("invoice_draft_id")]
    else:
        deliverables = []
        entries = db.time_entries_list(client_id=int(client_id), start_ts=start_iso, end_ts=end_iso, limit=5000)
        billable_entries = [e for e in entries if int(e.get("is_billable") or 0) == 1]
        if 'billable_entries' not in locals():
            billable_entries = []

    currency = str(client.get("currency") or "USD").strip() or "USD"

    # Determine effective billing mode from client profile (new unified) or passed param
    effective_mode = str(client.get("billing_mode") or billing_mode or "hourly").strip().lower()
    if effective_mode in {"deliverable", "fixed", "retainer", "project", "sow"}:
        effective_mode = "deliverable"
    else:
        effective_mode = "hourly"

    billing_mode_norm = effective_mode  # for downstream logic

    sorted_entries = sorted(billable_entries, key=lambda x: str(x.get("start_ts") or ""))
    line_parts: list[str] = []
    line_parts_html: list[str] = []
    line_items_docx: list[dict[str, str]] = []
    word_line_items: list[dict[str, str]] = []
    deliverable_groups: list[dict[str, object]] = []
    total_minutes = sum(int(e.get("minutes") or 0) for e in sorted_entries)
    if sorted_entries: logger.debug("billing draft entries=%d total_minutes=%d (Pulse metrics + Shield consumption)", len(sorted_entries), total_minutes)

    # For fixed-fee billing, compute a percent allocation per entry (explicit % overrides, remainder by time).
    entry_percents: dict[int, float] = {}
    fixed_fee_total_num: float | None = None
    if billing_mode_norm == "fixed_fee":
        try:
            fixed_fee_total_num = float(fixed_fee_total) if fixed_fee_total is not None else None
        except Exception:
            fixed_fee_total_num = None
        if fixed_fee_total_num is None or fixed_fee_total_num <= 0:
            raise ValueError("fixed_fee_total is required for fixed-fee invoice generation")

        entries_sorted = list(sorted_entries)
        mins_total_all = 0
        explicit: list[tuple[int, int, float]] = []
        unassigned: list[tuple[int, int]] = []
        for e in entries_sorted:
            eid = int(e.get("id") or 0)
            mins = int(e.get("minutes") or 0)
            mins_total_all += max(0, mins)
            p_raw = e.get("percent_of_total")
            p = 0.0
            try:
                p = float(p_raw) if p_raw is not None else 0.0
            except Exception:
                p = 0.0
            if p > 0:
                explicit.append((eid, mins, p))
            else:
                unassigned.append((eid, mins))

        explicit_sum = sum(p for _eid, _mins, p in explicit)
        if explicit_sum > 100.0 and explicit_sum > 0:
            scale = 100.0 / explicit_sum
        else:
            scale = 1.0

        scaled_explicit_sum = 0.0
        for eid, _mins, p in explicit:
            pp = max(0.0, p * scale)
            entry_percents[eid] = pp
            scaled_explicit_sum += pp

        remaining = max(0.0, 100.0 - scaled_explicit_sum)

        # If nothing explicit, allocate 100% by minutes across all entries.
        if explicit_sum <= 0.0:
            if mins_total_all > 0:
                for eid, mins in unassigned:
                    entry_percents[eid] = (100.0 * max(0, mins) / mins_total_all)
            else:
                # Degenerate case: allocate equally.
                n = max(1, len(unassigned))
                for eid, _mins in unassigned:
                    entry_percents[eid] = 100.0 / n
        else:
            mins_unassigned = sum(max(0, mins) for _eid, mins in unassigned)
            if mins_unassigned > 0:
                for eid, mins in unassigned:
                    entry_percents[eid] = remaining * (max(0, mins) / mins_unassigned)
            else:
                for eid, _mins in unassigned:
                    entry_percents[eid] = 0.0

    by_deliverable: dict[str, list[dict]] = {}
    for entry in sorted_entries:
        by_deliverable.setdefault(_entry_deliverable_label(entry), []).append(entry)

    # Deliverable mode: build line items from ready SoW deliverables
    deliverable_line_items: list[dict] = []
    if effective_mode == "deliverable" and deliverables:
        for d in deliverables:
            deliverable_line_items.append({
                "description": d.get("name", ""),
                "detail": d.get("description", ""),
                "amount": float(d.get("amount") or 0),
                "id": d.get("id"),
            })

    # If deliverable mode, override the time-based structures with clean deliverable lines
    if effective_mode == "deliverable" and deliverable_line_items:
        line_parts = ["**Deliverables**"]
        line_parts_html = []
        deliverable_groups = []
        word_line_items = []
        line_items_docx = []

        total_amount_from_deliverables = 0.0

        for d in deliverable_line_items:
            amt = d["amount"]
            total_amount_from_deliverables += amt
            line_parts.append(f"- {d['description']}: ${amt:,.2f}")
            if d.get("detail"):
                line_parts.append(f"  {d['detail']}")

            deliverable_groups.append({
                "label": d["description"],
                "date_range": "",
                "total_minutes": 0,
                "total_hours": "0.00",
                "entry_count": 1,
                "amount": amt,
                "amount_display": _money_display(amt, currency),
                "details": [d.get("detail", "")] if d.get("detail") else [],
                "summary_text": f"{d['description']}: {_money_display(amt, currency)}",
            })

            word_line_items.append({
                "work_performed": d["description"],
                "deliverable_label": d["description"],
                "itemized_description": d.get("detail", ""),
                "hours_percentage": "",
                "rate_per_hour": "",
                "amount": _money_display(amt, currency),
                "entry_date": "",
            })

        amount = total_amount_from_deliverables  # override for totals
        total_amount_s = _money_display(amount, currency)
        total_amount_display = total_amount_s
        total_amount_number = f"{amount:.2f}" if amount is not None else ""

        totals["amount"] = amount
        totals["billing_mode"] = "deliverable"
        totals["deliverable_count"] = len(deliverable_line_items)

    rate = client.get("default_rate")
    try:
        default_rate_num = float(rate) if rate is not None else None
    except Exception:
        default_rate_num = None
    for label, items in by_deliverable.items():
        group_minutes = 0
        group_amount_total = 0.0
        group_has_amount = False
        group_pct_total = 0.0
        detail_lines_md: list[str] = []
        detail_lines_html: list[str] = []
        detail_lines_text: list[str] = []
        group_descriptions: list[str] = []
        group_rate_displays: list[str] = []
        group_start = ""
        group_end = ""

        for it in items:
            mins = int(it.get("minutes") or 0)
            hours = mins / 60.0
            group_minutes += mins
            desc = str(it.get("description") or "").strip()
            it_id = int(it.get("id") or 0)
            pct = float(entry_percents.get(it_id, 0.0)) if billing_mode_norm == "fixed_fee" else 0.0
            if billing_mode_norm == "fixed_fee":
                group_pct_total += float(pct)
            amount_num, amount_disp = _entry_amount(
                it,
                client_rate=default_rate_num,
                billing_mode=billing_mode_norm,
                currency=currency,
                fixed_fee_total=fixed_fee_total_num,
                entry_percent=pct,
            )
            if amount_num is not None:
                group_amount_total += float(amount_num)
                group_has_amount = True

            st = str(it.get("start_ts") or "")
            day_iso = st[:10] if len(st) >= 10 else ""
            day_mmddyyyy = day_iso
            if len(day_iso) == 10:
                yyyy, mm, dd = day_iso.split("-")
                day_mmddyyyy = f"{mm}/{dd}/{yyyy}"
            if day_iso:
                group_start = day_iso if not group_start else min(group_start, day_iso)
                group_end = day_iso if not group_end else max(group_end, day_iso)

            if billing_mode_norm == "fixed_fee":
                detail_core = f"{day_mmddyyyy}: {pct:.1f}%"
                hours_pct_disp = f"{pct:.1f}%"
            else:
                detail_core = f"{day_mmddyyyy}: {hours:.2f}h"
                hours_pct_disp = f"{hours:.2f}h"
            if desc:
                if desc not in group_descriptions:
                    group_descriptions.append(desc)
                detail_core += f" - {desc}"
            if amount_disp:
                detail_core += f" ({amount_disp})"
            detail_lines_md.append(f"- {detail_core}")
            detail_lines_html.append(
                "<div style=\"margin: 0 0 1px 0;\">"
                + detail_core.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                + "</div>"
            )
            detail_lines_text.append(detail_core)

            rate_raw = it.get("rate_override")
            if rate_raw is None:
                rate_raw = rate
            try:
                rate_num = float(rate_raw) if rate_raw is not None else None
            except Exception:
                rate_num = None
            if billing_mode_norm == "fixed_fee":
                eff_rate = (float(amount_num) / hours) if amount_num is not None and hours > 0 else None
                rate_disp = _money_display(eff_rate, currency) if eff_rate is not None else ""
            else:
                rate_disp = _money_display(rate_num, currency) if rate_num is not None else ""
            if rate_disp and rate_disp not in group_rate_displays:
                group_rate_displays.append(rate_disp)
            line_items_docx.append(
                {
                    "work_performed": label,
                    "deliverable_label": label,
                    "itemized_description": desc or "",
                    "hours_percentage": hours_pct_disp,
                    "rate_per_hour": rate_disp,
                    "amount": amount_disp,
                    "entry_date": day_mmddyyyy,
                }
            )

        group_hours = group_minutes / 60.0
        group_amount = float(group_amount_total) if group_has_amount else None
        group_amount_disp = _money_display(group_amount, currency) if group_has_amount else ""
        group_item_desc = "; ".join(group_descriptions)
        if billing_mode_norm == "fixed_fee":
            group_hours_pct_disp = f"{group_pct_total:.1f}%"
            group_rate_disp = ""
        else:
            group_hours_pct_disp = f"{group_hours:.2f}h"
            group_rate_disp = group_rate_displays[0] if len(group_rate_displays) == 1 else ""
        group_date_range = ""
        if group_start and group_end:
            start_y, start_m, start_d = group_start.split("-")
            end_y, end_m, end_d = group_end.split("-")
            group_date_range = f"{start_m}/{start_d}/{start_y} - {end_m}/{end_d}/{end_y}"

        line_parts.append(f"### {label}")
        line_parts.append(f"- Total hours: {group_hours:.2f}")
        if group_amount_disp:
            line_parts.append(f"- Total amount: {group_amount_disp}")
        if group_date_range:
            line_parts.append(f"- Dates: {group_date_range}")
        line_parts.extend(detail_lines_md)
        line_parts.append("")

        line_parts_html.append(f"<div style=\"margin: 8px 0 2px 0; font-weight: 700;\">{label}</div>")
        line_parts_html.append(f"<div style=\"margin: 0 0 1px 0;\">Total hours: {group_hours:.2f}</div>")
        if group_amount_disp:
            line_parts_html.append(f"<div style=\"margin: 0 0 1px 0;\">Total amount: {group_amount_disp}</div>")
        if group_date_range:
            line_parts_html.append(f"<div style=\"margin: 0 0 3px 0;\">Dates: {group_date_range}</div>")
        line_parts_html.extend(detail_lines_html)
        line_parts_html.append("<div style=\"height: 8px;\"></div>")

        word_line_items.append(
            {
                "work_performed": label,
                "deliverable_label": label,
                "itemized_description": group_item_desc,
                "hours_percentage": group_hours_pct_disp,
                "rate_per_hour": group_rate_disp,
                "amount": group_amount_disp,
                "entry_date": group_date_range,
            }
        )

        deliverable_groups.append(
            {
                "label": label,
                "date_range": group_date_range,
                "total_minutes": int(group_minutes),
                "total_hours": f"{group_hours:.2f}",
                "entry_count": int(len(items)),
                "amount": group_amount,
                "amount_display": group_amount_disp,
                "details": detail_lines_text,
                "summary_text": "\n".join(
                    [f"{label}"] + [f"Dates: {group_date_range}"] * (1 if group_date_range else 0)
                    + [f"Total hours: {group_hours:.2f}"]
                    + ([f"Total amount: {group_amount_disp}"] if group_amount_disp else [])
                    + detail_lines_text
                ).strip(),
            }
        )

    total_hours = total_minutes / 60.0

    # Total amount
    amount: float | None = None
    if effective_mode == "deliverable" and deliverable_line_items:
        amount = sum(float(d.get("amount") or 0) for d in deliverable_line_items)
    elif billing_mode_norm == "fixed_fee":
        amount = float(fixed_fee_total_num) if fixed_fee_total_num is not None else None
    else:
        # Hourly: sum per-entry amounts (to respect rate_override), fallback to rate*total_hours.
        total_amt = 0.0
        any_amt = False
        for it in billable_entries:
            mins = int(it.get("minutes") or 0)
            hours = mins / 60.0
            r_raw = it.get("rate_override")
            if r_raw is None:
                r_raw = rate
            try:
                r_num = float(r_raw) if r_raw is not None else None
            except Exception:
                r_num = None
            if r_num is None:
                continue
            total_amt += float(r_num) * float(hours)
            any_amt = True
        if any_amt:
            amount = float(total_amt)
        else:
            amount = None

    total_amount_s = f"{amount:.2f} {currency}" if amount is not None else f"(amount not set) {currency}"

    totals = {
        "total_minutes": int(total_minutes),
        "total_hours": float(round(total_hours, 4)),
        "default_rate": rate,
        "amount": amount,
        "currency": currency,
        "entry_count": int(len(billable_entries)),
        "deliverable_count": int(len(deliverable_groups)),
        "billing_mode": billing_mode_norm,
        "fixed_fee_total": float(fixed_fee_total_num) if fixed_fee_total_num is not None else None,
    }

    due_date_text = due_date.strftime("%m/%d/%Y") if due_date is not None else "Due upon receipt"
    invoice_number = _next_invoice_number(db)

    # Create the draft row first so we can use its id as an invoice number.
    # (Templates can render {{invoice_number}} deterministically.)
    draft_id = db.invoice_draft_create(
        client_id=int(client_id),
        period_start=period_start_s,
        period_end=period_end_s,
        invoice_number=invoice_number,
        due_date=due_date_text,
        totals_json=json.dumps(totals, ensure_ascii=False),
        rendered_body_md="",
        file_path=None,
        pdf_file_path=None,
        status="draft",
    )

    # If this was a deliverable-mode invoice, mark the used deliverables as invoiced
    if effective_mode == "deliverable" and deliverable_line_items:
        for d in deliverable_line_items:
            try:
                db.client_deliverable_update_status(d["id"], "invoiced")
                # Optionally store the draft id on the deliverable for traceability
                # (we can add a small update if the table supports it later)
            except Exception:
                pass

    # Friendly formatted date strings for templates.
    period_start_mmddyyyy = period_start.strftime("%m/%d/%Y")
    period_end_mmddyyyy = period_end.strftime("%m/%d/%Y")
    grouped_line_items_md = "\n".join(line_parts).strip() or "(No billable time entries found.)"
    grouped_line_items_html = "\n".join(line_parts_html).strip() or "<p>(No billable time entries found.)</p>"
    grouped_line_items_text = "\n\n".join(
        str(group.get("summary_text") or "").strip() for group in deliverable_groups if str(group.get("summary_text") or "").strip()
    ).strip() or "(No billable time entries found.)"

    total_amount_number = f"{amount:.2f}" if amount is not None else ""
    total_amount_display = _money_display(amount, currency) if amount is not None else total_amount_s

    context = {
        "client_name": str(client.get("name") or "").strip(),
        "billing_email": str(client.get("billing_email") or "").strip(),
        "billing_contact_name": str(client.get("billing_contact_name") or "").strip(),
        "invoice_number": invoice_number,
        "due_date": due_date_text,
        "period_start": period_start_s,
        "period_end": period_end_s,
        "period_start_mmddyyyy": period_start_mmddyyyy,
        "period_end_mmddyyyy": period_end_mmddyyyy,
        "period_range": f"{period_start_mmddyyyy} - {period_end_mmddyyyy}",
        "line_items_md": grouped_line_items_md,
        "line_items_html": grouped_line_items_html,
        "grouped_line_items_md": grouped_line_items_md,
        "grouped_line_items_html": grouped_line_items_html,
        "grouped_line_items_text": grouped_line_items_text,
        "deliverable_groups_text": grouped_line_items_text,
        "deliverable_groups": deliverable_groups
        if deliverable_groups
        else [
            {
                "label": "No billable time entries found.",
                "date_range": "",
                "total_minutes": 0,
                "total_hours": "0.00",
                "entry_count": 0,
                "amount": None,
                "amount_display": "",
                "details": [],
                "summary_text": "No billable time entries found.",
            }
        ],
        "line_items": line_items_docx
        if line_items_docx
        else [
            {
                "work_performed": "",
                "deliverable_label": "",
                "itemized_description": "(No billable time entries found.)",
                "hours_percentage": "",
                "rate_per_hour": "",
                "amount": "",
                "entry_date": "",
            }
        ],
        "word_line_items": word_line_items
        if word_line_items
        else [
            {
                "work_performed": "",
                "deliverable_label": "",
                "itemized_description": "(No billable time entries found.)",
                "hours_percentage": "",
                "rate_per_hour": "",
                "amount": "",
                "entry_date": "",
            }
        ],
        "line_items_text": grouped_line_items_text,
        "total_hours": f"{total_hours:.2f}",
        "total_minutes": str(int(total_minutes)),
        "currency": currency,
        "total_amount": total_amount_s,
        "total_amount_number": total_amount_number,
        "total_amount_display": total_amount_display,
        "default_rate": (str(rate) if rate is not None else ""),
        "billing_mode": billing_mode_norm,
        "fixed_fee_total": (f"{float(fixed_fee_total_num):.2f}" if fixed_fee_total_num is not None else ""),
    }

    rendered: str = ""
    file_path: str | None = None

    # Render + persist artifact to disk.
    base = os.path.join(str(ARTIFACTS_DIR), "invoice_drafts", str(draft_id))
    os.makedirs(base, exist_ok=True)
    yyyymm = period_start_s[:7].replace("-", "")

    if is_docx or is_word_native:
        # Template body is a JSON pointer to an artifact under ARTIFACTS_DIR.
        template_body = str(tmpl.get("template_body") or "")
        try:
            obj = json.loads(template_body)
        except Exception as e:
            raise ValueError("DOCX template_body must be a JSON pointer") from e
        if not isinstance(obj, dict) or str(obj.get("type") or "").lower() != "docx":
            raise ValueError("DOCX template_body must be a JSON pointer with {type:'docx', path:'...'}")
        rel = str(obj.get("path") or "").strip().replace("\\", "/")
        if not rel:
            raise ValueError("DOCX template_body pointer is missing 'path'")
        template_path = os.path.join(str(ARTIFACTS_DIR), rel)

        fname = f"invoice_{_safe_filename(context['client_name'])}_{yyyymm}.docx"
        file_path = os.path.join(base, fname)
        if is_word_native:
            render_word_invoice_template(template_path=template_path, output_path=file_path, context=context)
            rendered = f"(Word-native DOCX draft generated) {file_path}"
        else:
            render_docx_template(template_path=template_path, output_path=file_path, context=context)
            rendered = f"(DOCX draft generated) {file_path}"
    else:
        rendered = render_template(str(tmpl.get("template_body") or ""), context)
        ext = "html" if is_html else "md"
        fname = f"invoice_{_safe_filename(context['client_name'])}_{yyyymm}.{ext}"
        file_path = os.path.join(base, fname)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(rendered or "")

    try:
        db.invoice_draft_update_artifacts(
            int(draft_id),
            rendered_body_md=str(rendered or ""),
            totals_json=json.dumps(totals, ensure_ascii=False),
            file_path=file_path,
            pdf_file_path=None,
            status="generated",
        )
    except Exception:
        pass

    if rendered: logger.debug("billing invoice rendered body chars=%d (Shield compliance surface visibility)", len(rendered or ""))
    return InvoiceDraftResult(
        draft_id=int(draft_id),
        file_path=file_path,
        pdf_file_path=None,
        rendered_body_md=rendered,
        totals=totals,
    )


def previous_month_period(today: date | None = None) -> tuple[date, date]:
    # previous_month_period supports Pulse private memory + Shield billing cycles
    d = today or date.today()
    first_this_month = date(d.year, d.month, 1)
    last_prev_month = first_this_month - timedelta(days=1)
    first_prev_month = date(last_prev_month.year, last_prev_month.month, 1)
    return first_prev_month, last_prev_month

