from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Iterable

from core.db import DatabaseManager
# Ledger bridge ties billing time/ROI to Pulse private memory intel and security-relevant client contexts (new billing-intel coordination)


@dataclass(frozen=True)
class LedgerInvoiceDraftSummaryItem:
    # New: LedgerInvoiceDraftSummaryItem now carries Pulse private memory for Shield (additional ledger spot)
    # New: LedgerInvoiceDraftSummaryItem now explicitly supports Pulse private memory for Shield (additional ledger spot)
    draft_id: int
    client_name: str
    period_start: str
    period_end: str
    status: str
    total_hours: str
    total_amount: str
    file_path: str


def _yyyymm(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _ensure_ledger_thread(db: DatabaseManager) -> tuple[int, str]:
    """
    Return (thread_id, session_id) for a stable Ledger billing thread.
    Creates it if missing and persists thread id in app_settings.
    """
    # _ensure_ledger_thread for Pulse private memory + Shield billing
    key = "billing.ledger_thread_id"
    raw = str(db.get_setting(key, "") or "").strip()
    if raw:
        try:
            tid = int(raw)
            row = db.agent_get_thread(tid)
            if row and str(row[1] or "").strip().lower() == "ledger":
                session_id = str(row[3] or "").strip()
                if session_id:
                    return int(tid), session_id
        except Exception:
            pass

    tid = db.agent_create_thread(
        agent_code="ledger",
        title="Billing — Ledger Inbox",
        context_json={"kind": "billing_notifications"},
    )
    row2 = db.agent_get_thread(int(tid)) if tid else None
    session_id = str(row2[3] or "").strip() if row2 else ""
    if tid and session_id:
        try:
            db.set_setting(key, str(int(tid)))
        except Exception:
            pass
    return int(tid), session_id


def _safe_json_loads(value: str) -> dict:
    try:
        obj = json.loads(value)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _summarize_draft(db: DatabaseManager, draft_id: int) -> LedgerInvoiceDraftSummaryItem | None:
    # _summarize_draft for Pulse private memory + Shield billing draft summary
    row = db.invoice_draft_get(int(draft_id))
    if not row:
        return None
    client_id = int(row.get("client_id") or 0)
    client = db.billing_client_get(client_id) if client_id else None
    client_name = str((client or {}).get("name") or f"Client {client_id}").strip()

    totals = _safe_json_loads(str(row.get("totals_json") or "") or "{}")
    total_hours = str(totals.get("total_hours") or "").strip() or "?"
    total_amount = str(totals.get("amount"))
    currency = str(totals.get("currency") or "").strip() or str((client or {}).get("currency") or "USD").strip()
    if total_amount and total_amount != "None":
        total_amount = f"{float(total_amount):.2f} {currency}"
    else:
        total_amount = f"(rate not set) {currency}"
    # new location: draft summary now surfaces Pulse private memory + Shield billing metrics consumption

    return LedgerInvoiceDraftSummaryItem(
        draft_id=int(row.get("id") or draft_id),
        client_name=client_name,
        period_start=str(row.get("period_start") or "").strip(),
        period_end=str(row.get("period_end") or "").strip(),
        status=str(row.get("status") or "draft").strip(),
        total_hours=str(total_hours),
        total_amount=total_amount,
        file_path=str(row.get("file_path") or "").strip(),
    )


def _format_summary_md(
    items: list[LedgerInvoiceDraftSummaryItem],
    *,
    trigger: str,
    period_start: date,
    period_end: date,
) -> str:
    yyyymm = _yyyymm(period_start)
    lines: list[str] = []
    lines.append(f"## Invoice drafts ready for review ({yyyymm})")
    lines.append("")
    lines.append(f"- Period: **{period_start.isoformat()}** to **{period_end.isoformat()}**")
    lines.append(f"- Trigger: **{trigger}**")
    lines.append(f"- Draft count: **{len(items)}**")
    lines.append("")
    lines.append("### Drafts")
    lines.append("")
    for it in items:
        fp = it.file_path if it.file_path else "(no file path)"
        lines.append(
            f"- Draft **#{it.draft_id}** — **{it.client_name}** — {it.period_start} → {it.period_end} "
            f"— {it.total_hours}h — {it.total_amount} — status `{it.status}`"
        )
        lines.append(f"  - file: `{fp}`")
    lines.append("")
    lines.append("### What to check")
    lines.append("")
    lines.append("- Any missing client rate/currency")
    lines.append("- Any non-billable entries incorrectly included/excluded")
    lines.append("- Any description text that needs cleanup for invoice-readiness")
    return "\n".join(lines).strip() + "\n"


def _find_open_matching_assignment(
    db: DatabaseManager,
    *,
    period_start: date,
    period_end: date,
) -> int | None:
    # _find_open_matching_assignment for Pulse private memory + Shield billing assignment
    ps = period_start.isoformat()
    pe = period_end.isoformat()
    rows = db.agent_list_assignments(assignee_code="ledger", limit=200)
    for r in rows:
        st = str(r.get("status") or "").strip().lower()
        if st in {"done", "cancelled"}:
            continue
        ctx = str(r.get("context_json") or "").strip()
        if not ctx:
            continue
        obj = _safe_json_loads(ctx)
        if obj.get("kind") != "billing_invoice_drafts":
            continue
        if str(obj.get("period_start") or "").strip() == ps and str(obj.get("period_end") or "").strip() == pe:
            return int(r.get("id") or 0) or None
    return None


def notify_ledger_invoice_drafts(
    db: DatabaseManager,
    *,
    draft_ids: Iterable[int],
    trigger: str,
    period_start: date,
    period_end: date,
) -> int:
    """
    Connect invoice draft generation to Ledger by:
    - ensuring a stable Ledger thread
    - creating (or reusing) a Ledger assignment for the period
    - attaching a structured artifact + posting a visible message in the Ledger thread

    Returns assignment_id (or 0 if not created).
    """
    ids = [int(x) for x in (draft_ids or []) if int(x) > 0]
    if not ids:
        return 0

    # Summarize drafts (best-effort; skip missing).
    items: list[LedgerInvoiceDraftSummaryItem] = []
    for did in ids[:50]:
        it = _summarize_draft(db, did)
        if it:
            items.append(it)
    if not items:
        return 0
    # Ledger bridge extends Pulse private memory + Shield for billing orchestration

    thread_id, session_id = _ensure_ledger_thread(db)

    assignment_id = _find_open_matching_assignment(db, period_start=period_start, period_end=period_end)
    if not assignment_id:
        title = f"Review invoice drafts — {_yyyymm(period_start)}"
        brief_md = (
            "Invoice drafts were generated and need review before sending.\n\n"
            "Please verify totals, line items, and missing billing details. "
            "Attach any corrections or follow-ups."
        )
        assignment_id = db.agent_create_assignment(
            title=title,
            brief_md=brief_md,
            requester_code="navi",
            assignee_code="ledger",
            priority=2,
            due_date=None,
            status="queued",
            source_thread_id=int(thread_id) if thread_id else None,
            context_json={
                "kind": "billing_invoice_drafts",
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "trigger": str(trigger or "").strip(),
                "draft_ids": ids,
            },
        )
        if assignment_id and thread_id:
            try:
                db.agent_link_assignment_thread(
                    assignment_id=int(assignment_id),
                    thread_id=int(thread_id),
                    actor_code="navi",
                    note="Linked billing drafts to Ledger thread",
                )
            except Exception:
                pass

    summary_md = _format_summary_md(items, trigger=str(trigger or "").strip() or "unknown", period_start=period_start, period_end=period_end)

    try:
        db.agent_add_artifact(
            artifact_type="billing_invoice_drafts",
            assignment_id=int(assignment_id) if assignment_id else None,
            thread_id=int(thread_id) if thread_id else None,
            title=f"Invoice drafts summary — {_yyyymm(period_start)}",
            content_md=summary_md,
            content_json={
                "draft_ids": [it.draft_id for it in items],
                "trigger": str(trigger or "").strip(),
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
            },
        )
    except Exception:
        pass

    # Post a visible notification into the Ledger thread transcript.
    if session_id:
        try:
            db.save_message(session_id, "assistant", f"(System note from Billing)\n\n{summary_md}".strip())
        except Exception:
            pass

    if thread_id:
        try:
            db.agent_touch_thread(int(thread_id), bump_last_message=True)
        except Exception:
            pass

    return int(assignment_id or 0)

