from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from calendar import monthrange

from core.billing.invoice_service import generate_invoice_draft, previous_month_period
from core.billing.ledger_bridge import notify_ledger_invoice_drafts
from core.db import DatabaseManager


@dataclass(frozen=True)
class AutoRunResult:
    ran: bool
    draft_ids: list[int]
    notes: str = ""


def _yyyymm(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def should_autorun(db: DatabaseManager, *, today: date | None = None) -> bool:
    d = today or date.today()
    enabled_raw = str(db.get_setting("billing.autorun_enabled", "true") or "").strip().lower()
    enabled = enabled_raw not in {"0", "false", "no", "off"}
    if not enabled:
        return False

    try:
        dom = int(str(db.get_setting("billing.autorun_day_of_month", "1") or "1").strip())
    except Exception:
        dom = 1
    dom = max(1, min(28, dom))
    if d.day != dom:
        return False

    last = str(db.get_setting("billing.last_autorun_yyyymm", "") or "").strip()
    return last != _yyyymm(d)


def next_autorun_date(db: DatabaseManager, *, today: date | None = None) -> date:
    d = today or date.today()
    enabled_raw = str(db.get_setting("billing.autorun_enabled", "true") or "").strip().lower()
    enabled = enabled_raw not in {"0", "false", "no", "off"}
    if not enabled:
        return d

    try:
        dom = int(str(db.get_setting("billing.autorun_day_of_month", "1") or "1").strip())
    except Exception:
        dom = 1
    dom = max(1, min(28, dom))

    last = str(db.get_setting("billing.last_autorun_yyyymm", "") or "").strip()
    current_key = _yyyymm(d)
    if last == current_key or d.day > dom:
        year = d.year + (1 if d.month == 12 else 0)
        month = 1 if d.month == 12 else d.month + 1
    else:
        year = d.year
        month = d.month
    day = min(dom, monthrange(year, month)[1])
    return date(year, month, day)


def run_monthly_autodraft(db: DatabaseManager, *, today: date | None = None) -> AutoRunResult:
    d = today or date.today()
    if not should_autorun(db, today=d):
        return AutoRunResult(ran=False, draft_ids=[], notes="Not due.")

    # Resolve template.
    template_id = None
    raw = str(db.get_setting("billing.default_template_id", "") or "").strip()
    if raw:
        try:
            template_id = int(raw)
        except Exception:
            template_id = None
    if not template_id:
        # Best-effort: pick most recent template.
        tmpls = db.invoice_templates_list()
        if tmpls:
            template_id = int(tmpls[0]["id"])

    if not template_id:
        db.set_setting("billing.last_autorun_yyyymm", _yyyymm(d))
        db.set_setting("billing.pending_review_notes", "No invoice template configured. Create a template first in Billing.")
        return AutoRunResult(
            ran=True,
            draft_ids=[],
            notes="No invoice template configured. Create a template first in Billing.",
        )

    period_start, period_end = previous_month_period(d)
    clients = db.billing_clients_list(active_only=True)
    draft_ids: list[int] = []
    for c in clients:
        try:
            res = generate_invoice_draft(
                db,
                client_id=int(c["id"]),
                period_start=period_start,
                period_end=period_end,
                template_id=int(template_id),
            )
            draft_ids.append(int(res.draft_id))
        except Exception:
            continue

    # Connect to Ledger: create/update a review assignment + post a thread update.
    try:
        if draft_ids:
            notify_ledger_invoice_drafts(
                db,
                draft_ids=draft_ids,
                trigger="monthly_autorun",
                period_start=period_start,
                period_end=period_end,
            )
    except Exception:
        # Billing draft generation should not fail due to notification plumbing.
        pass

    db.set_setting("billing.last_autorun_yyyymm", _yyyymm(d))
    db.set_setting("billing.pending_review_count", str(len(draft_ids)))
    db.set_setting("billing.pending_review_draft_ids_json", json.dumps(draft_ids))
    db.set_setting("billing.pending_review_notes", str("" if draft_ids else "No invoice drafts were generated."))
    return AutoRunResult(ran=True, draft_ids=draft_ids, notes="")

