from __future__ import annotations

import re

from core.email_utils import extract_domain, extract_email_address

_WORD_BOUNDARY = r"(?<![a-z0-9]){needle}(?![a-z0-9])"

_URGENT_PATTERNS = (
    "urgent",
    "asap",
    "time sensitive",
    "deadline",
    "today",
    "tomorrow",
    "eod",
    "by end of day",
    "immediately",
)

_ACTION_PATTERNS = (
    "please review",
    "please approve",
    "please send",
    "please confirm",
    "action required",
    "follow up",
    "can you",
    "could you",
    "need your",
    "needs your",
    "schedule",
    "meeting",
    "call",
    "invoice",
    "proposal",
    "sow",
    "msa",
    "contract",
    "quote",
)

_LOW_SIGNAL_PATTERNS = (
    "newsletter",
    "unsubscribe",
    "manage preferences",
    "view in browser",
    "webinar",
    "promotion",
    "sale",
    "discount",
    "press release",
    "digest",
    "marketing",
)

_STAKEHOLDER_PATTERNS = (
    "ceo",
    "cto",
    "founder",
    "co-founder",
    "regulatory",
    "quality",
    "clinical",
    "legal",
    "finance",
    "vp",
)


def _contains_phrase(haystack: str, needle: str) -> bool:
    value = (needle or "").strip().lower()
    if not value:
        return False
    if " " in value:
        return value in haystack
    return re.search(_WORD_BOUNDARY.format(needle=re.escape(value)), haystack) is not None


def _normalize_text(*parts: str | None) -> str:
    return " ".join(str(p or "").strip() for p in parts if str(p or "").strip()).lower()


def evaluate_email_importance(
    *,
    db,
    sender: str | None,
    subject: str | None,
    content: str | None,
    folder: str | None = None,
    account: str | None = None,
    source: str | None = None,
    is_client: int = 0,
    is_potential: int = 0,
    replied: int = 0,
) -> dict:
    """Return deterministic triage metadata for one email."""
    sender_value = str(sender or "").strip()
    subject_value = str(subject or "").strip()
    content_value = str(content or "").strip()
    folder_value = str(folder or "").strip()
    account_value = str(account or "").strip()
    source_value = str(source or "").strip()
    sender_addr = extract_email_address(sender_value)
    sender_domain = extract_domain(sender_addr)
    text = _normalize_text(sender_value, subject_value, content_value, folder_value, account_value, source_value)

    score = 0
    reasons: list[str] = []
    matched_client_id: int | None = None
    matched_project_id: int | None = None
    is_urgent = False

    clients = []
    contacts = []
    projects = []
    try:
        clients = db.clients_list(active_only=True) if hasattr(db, "clients_list") else []
    except Exception:
        clients = []
    try:
        contacts = db.client_contacts_list() if hasattr(db, "client_contacts_list") else []
    except Exception:
        contacts = []
    try:
        projects = db.cos_get_projects() if hasattr(db, "cos_get_projects") else []
    except Exception:
        projects = []

    contact_match = None
    if sender_addr:
        for contact in contacts:
            email_value = str(contact.get("email") or "").strip().lower()
            if email_value and sender_addr.lower() == email_value:
                contact_match = contact
                break

    if contact_match:
        matched_client_id = int(contact_match.get("client_id"))
        score += 45
        reasons.append("Matched a known client contact.")

    for client in clients:
        client_id = int(client.get("id"))
        client_name = str(client.get("name") or "").strip()
        aliases = [client_name] + [str(v).strip() for v in (client.get("aliases_json") or [])]
        domains = [str(v).strip().lower() for v in (client.get("domain_rules_json") or [])]

        if matched_client_id is None and sender_domain and sender_domain in domains:
            matched_client_id = client_id
            score += 35
            reasons.append(f"Matched client domain: {sender_domain}.")
        if matched_client_id is None:
            for alias in aliases:
                if len(alias) >= 4 and _contains_phrase(text, alias):
                    matched_client_id = client_id
                    score += 18
                    reasons.append(f"Mentioned client name or alias: {alias}.")
                    break

    if int(is_client or 0) == 1:
        score += 12
        reasons.append("Classified as a client email.")
    elif int(is_potential or 0) == 1:
        score += 8
        reasons.append("Classified as a lead or potential client email.")

    for project in projects:
        try:
            project_id = int(project[0])
            project_name = str(project[1] or "").strip()
        except Exception:
            continue
        if len(project_name) >= 4 and _contains_phrase(text, project_name):
            matched_project_id = project_id
            score += 22
            reasons.append(f"Mentioned project: {project_name}.")
            break

    urgent_hits = [kw for kw in _URGENT_PATTERNS if _contains_phrase(text, kw)]
    if urgent_hits:
        score += 18
        is_urgent = True
        reasons.append("Contained urgent or time-sensitive language.")

    action_hits = [kw for kw in _ACTION_PATTERNS if _contains_phrase(text, kw)]
    if action_hits:
        score += 12
        reasons.append("Contained action-oriented language.")

    stakeholder_hits = [kw for kw in _STAKEHOLDER_PATTERNS if _contains_phrase(text, kw)]
    if stakeholder_hits:
        score += 8
        reasons.append("Referenced a business-critical stakeholder or function.")

    low_signal_hits = [kw for kw in _LOW_SIGNAL_PATTERNS if _contains_phrase(text, kw)]
    if low_signal_hits:
        score -= 20
        reasons.append("Looks like low-signal marketing or newsletter content.")

    if sender_value.lower().startswith(("no-reply", "noreply")) or sender_addr.lower().startswith(("no-reply@", "noreply@")):
        score -= 12
        reasons.append("Sender appears automated.")

    if int(replied or 0) == 0:
        score += 2

    score = max(0, min(100, score))
    needs_attention = 1 if score >= 25 else 0
    triage_status = "important" if needs_attention else "new"

    return {
        "score": score,
        "needs_attention": needs_attention,
        "triage_status": triage_status,
        "reasons": reasons,
        "matched_client_id": matched_client_id,
        "matched_project_id": matched_project_id,
        "is_urgent": is_urgent,
        "triage_source": "rule",
    }
