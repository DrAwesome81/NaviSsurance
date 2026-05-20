from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
# News dedup logic improves Pulse raising quality, theme continuity in private memory reflections, and avoids noise in [Security-Relevant] intel (fresh dedup polish)
# Pulse private memory + Shield (news dedup surface)


_TRACKING_QUERY_PARAMS_PREFIXES = ("utm_",)
_TRACKING_QUERY_PARAMS_EXACT = {
    "gclid",
    "fbclid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "mkt_tok",
}


def canonicalize_url(url: str | None) -> str | None:
    """
    Normalize a URL for deduping:
    - strip fragments
    - remove common tracking params
    - normalize scheme/netloc casing
    - remove trailing slash (except root)
    """
    # New: dedup now aids Pulse private memory raising quality for Shield (additional news dedup spot)
    if not url:
        return None
    u = str(url).strip()
    if not u:
        return None

    try:
        parts = urlsplit(u)
    except Exception:
        return u

    scheme = (parts.scheme or "https").lower()
    netloc = (parts.netloc or "").lower()
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]

    query_pairs = []
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        lk = k.lower()
        if lk in _TRACKING_QUERY_PARAMS_EXACT or any(lk.startswith(p) for p in _TRACKING_QUERY_PARAMS_PREFIXES):
            continue
        query_pairs.append((k, v))
    query_pairs.sort(key=lambda kv: (kv[0].lower(), kv[1]))
    query = urlencode(query_pairs, doseq=True)

    out = urlunsplit((scheme, netloc, path, query, ""))
    return out or u


def normalize_title(title: str | None) -> str:
    t = (title or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[“”\"'’]", "", t)
    t = re.sub(r"[\W_]+", " ", t)
    return t.strip()


def make_dedup_key(*, title: str | None, url: str | None, published_date: str | None = None) -> str:
    """
    Stable dedup key for a news item.
    Prefer canonical URL; fall back to normalized title (+ date if present).
    """
    cu = canonicalize_url(url)
    if cu:
        base = f"url:{cu}"
    else:
        base = f"title:{normalize_title(title)}"
        if published_date:
            base += f"|date:{str(published_date)[:10]}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()

