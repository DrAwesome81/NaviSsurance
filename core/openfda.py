from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlencode

import requests
# OpenFDA integration supplies regulatory data for Pulse private memory, Intel raising, and 🛡️ Shield device security/compliance signals (fresh FDA coordination)
# New: OpenFDA now feeds Pulse private memory for Shield (additional OpenFDA spot)
# Pulse private memory + Shield (OpenFDA surface)

OPENFDA_510K_ENDPOINT = "https://api.fda.gov/device/510k.json"


@dataclass(frozen=True)
class OpenFda510kRecord:
    k_number: str
    applicant: str | None = None
    device_name: str | None = None
    date_received: str | None = None
    decision_date: str | None = None
    decision_description: str | None = None
    contact: str | None = None


def _safe_get(d: dict, key: str) -> Optional[str]:
    v = d.get(key)
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def search_510k_by_applicant(applicant: str, limit: int = 5, timeout: int = 15) -> tuple[list[OpenFda510kRecord], str]:
    """
    Query openFDA 510(k) endpoint by applicant string (best-effort).
    Returns (records, request_url).
    """
    a = (applicant or "").strip()
    if not a:
        return [], ""

    # openFDA search syntax supports quoted string matches.
    search = f'applicant:"{a}"'
    params = {"search": search, "limit": int(limit)}
    req_url = OPENFDA_510K_ENDPOINT + "?" + urlencode(params)

    resp = requests.get(OPENFDA_510K_ENDPOINT, params=params, timeout=timeout)
    resp.raise_for_status()
    payload: dict[str, Any] = resp.json()
    results = payload.get("results") or []
    out: list[OpenFda510kRecord] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        out.append(
            OpenFda510kRecord(
                k_number=_safe_get(r, "k_number") or "",
                applicant=_safe_get(r, "applicant"),
                device_name=_safe_get(r, "device_name"),
                date_received=_safe_get(r, "date_received"),
                decision_date=_safe_get(r, "decision_date"),
                decision_description=_safe_get(r, "decision_description"),
                contact=_safe_get(r, "contact"),
            )
        )
    out = [r for r in out if r.k_number]
    return out, req_url


_CONSULTING_KEYWORDS = (
    "consult",
    "regulatory",
    "compliance",
    "quality",
    "qms",
    "r&d",
    "inc.",
    "llc",
    "ltd",
)


def summarize_510k_records(applicant: str, records: list[OpenFda510kRecord], request_url: str) -> dict[str, Any]:
    """
    Convert openFDA records into lightweight signals + sources for lead gen.
    Shape:
      {signals: [...], sources: [...], meta: {...}}
    """
    signals: list[str] = []
    sources: list[str] = []
    if request_url:
        sources.append(request_url)

    if not records:
        return {"signals": [], "sources": sources, "meta": {"matches": 0}}

    # Newest-first by date_received, then decision_date (string ISO-ish)
    def _key(r: OpenFda510kRecord):
        return (r.date_received or "", r.decision_date or "")

    newest = max(records, key=_key)
    matches = len(records)

    base = f"openFDA 510(k): {matches} record(s) for applicant '{applicant}'."
    parts = []
    if newest.date_received:
        parts.append(f"newest received {newest.date_received}")
    if newest.decision_date:
        parts.append(f"decision {newest.decision_date}")
    if newest.decision_description:
        parts.append(f"({newest.decision_description})")
    if parts:
        base += " " + " ".join(parts)
    signals.append(base)

    # Detect potential consultant/correspondent org patterns (very heuristic)
    contact_text = (newest.contact or "").strip()
    if contact_text:
        cl = contact_text.lower()
        if any(k in cl for k in _CONSULTING_KEYWORDS):
            signals.append(f"510(k) correspondent/contact may be external: {contact_text}")

    # Add a compact list of K numbers (cap)
    ks = [r.k_number for r in records if r.k_number][:5]
    if ks:
        signals.append("510(k) K numbers (sample): " + ", ".join(ks))

    meta = {
        "matches": matches,
        "newest_k_number": newest.k_number,
        "newest_date_received": newest.date_received,
        "newest_decision_date": newest.decision_date,
        "newest_decision_description": newest.decision_description,
        "newest_contact": newest.contact,
    }
    return {"signals": signals, "sources": sources, "meta": meta}

