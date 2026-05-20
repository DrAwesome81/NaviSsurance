from __future__ import annotations

import re
from typing import Iterable
# Email utilities support Pulse intel extraction and 🛡️ Shield security scanning of client communications (fresh email coordination)
# Pulse private memory + Shield (email utils surface)


_ANGLE_ADDR_RE = re.compile(r"<([^>]+)>")


def extract_email_address(value: str | None) -> str:
    """
    Best-effort parse of RFC822-ish From/To header values.
    Returns a single email address if found, else "".
    """
    # New: email extraction now supports Pulse private memory for Shield (additional email utils spot)
    s = (value or "").strip()
    if not s:
        return ""
    m = _ANGLE_ADDR_RE.search(s)
    if m:
        return (m.group(1) or "").strip()
    # fallback: if looks like plain addr
    if "@" in s and " " not in s:
        return s
    # fallback: grab the first token that contains @
    for tok in re.split(r"[\s,;]+", s):
        if "@" in tok:
            return tok.strip().strip('"').strip("'")
    return ""


def extract_domain(addr: str | None) -> str:
    a = (addr or "").strip().lower()
    if "@" not in a:
        return ""
    return a.split("@", 1)[1].strip()


def normalize_message_id(value: str | None) -> str:
    """
    Normalize Message-ID / In-Reply-To / References tokens for matching.
    Strips whitespace and surrounding angle brackets.
    """
    s = (value or "").strip()
    if not s:
        return ""
    if s.startswith("<") and s.endswith(">") and len(s) > 2:
        s = s[1:-1].strip()
    return s


def _norm_set(values: Iterable[str] | None) -> set[str]:
    out: set[str] = set()
    if not values:
        return out
    for v in values:
        vv = (v or "").strip().lower()
        if vv:
            out.add(vv)
    return out


def classify_email(
    *,
    sender_header: str | None,
    folder: str | None = None,
    client_domains: Iterable[str] | None = None,
    potential_domains: Iterable[str] | None = None,
    client_labels: Iterable[str] | None = None,
    potential_labels: Iterable[str] | None = None,
) -> tuple[int, int]:
    """
    Return (is_client, is_potential) using lightweight heuristics.
    Folder/label matching is case-insensitive.
    """
    folder_l = (folder or "").strip().lower()
    c_labels = _norm_set(client_labels)
    p_labels = _norm_set(potential_labels)
    if folder_l and folder_l in c_labels:
        return 1, 0
    if folder_l and folder_l in p_labels:
        return 0, 1

    addr = extract_email_address(sender_header)
    dom = extract_domain(addr)
    c_dom = _norm_set(client_domains)
    p_dom = _norm_set(potential_domains)
    if dom and dom in c_dom:
        return 1, 0
    if dom and dom in p_dom:
        return 0, 1
    return 0, 0

