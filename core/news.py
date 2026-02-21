from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, UTC
from typing import Iterable, Optional
from urllib.parse import parse_qsl, urlsplit, urlunsplit, urlencode

from anthropic import Anthropic

from core.db import DatabaseManager


_TRACKING_QUERY_PARAMS_PREFIXES = ("utm_",)
_TRACKING_QUERY_PARAMS_EXACT = {
    "gclid",
    "fbclid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "mkt_tok",
}


def canonicalize_url(url: str) -> str:
    """
    Normalize a URL for deduping:
    - strip fragments
    - remove common tracking params
    - normalize scheme/netloc casing
    - remove trailing slash (except root)
    """
    if not url:
        return ""
    u = url.strip()
    try:
        parts = urlsplit(u)
    except Exception:
        return u

    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]

    # Filter tracking query params, preserve the rest (sorted for stability)
    query_pairs = []
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        lk = k.lower()
        if lk in _TRACKING_QUERY_PARAMS_EXACT or any(lk.startswith(p) for p in _TRACKING_QUERY_PARAMS_PREFIXES):
            continue
        query_pairs.append((k, v))
    query_pairs.sort(key=lambda kv: (kv[0].lower(), kv[1]))
    query = urlencode(query_pairs, doseq=True)

    return urlunsplit((scheme, netloc, path, query, ""))  # no fragment


def _normalize_title(title: str) -> str:
    t = (title or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[“”\"'’]", "", t)
    t = re.sub(r"[\W_]+", " ", t)
    return t.strip()


def dedup_key(url: str, title: str, published_at: Optional[str] = None) -> str:
    """
    Stable dedup key for a news item.
    Prefer canonical URL; fall back to normalized title (+ date if present).
    """
    cu = canonicalize_url(url)
    if cu:
        base = f"url:{cu}"
    else:
        base = f"title:{_normalize_title(title)}"
        if published_at:
            base += f"|date:{published_at[:10]}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class NewsItem:
    title: str
    url: str
    source: str | None = None
    published_at: str | None = None  # ISO if available
    summary: str | None = None
    query: str | None = None

    @property
    def canonical_url(self) -> str:
        return canonicalize_url(self.url)

    @property
    def key(self) -> str:
        return dedup_key(self.url, self.title, self.published_at)


class NewsStore:
    """
    Lightweight persistence for external news headlines with dedup + 'last shown' tracking.
    """

    def __init__(self, db: DatabaseManager):
        self.db = db
        self._init_tables()

    def _init_tables(self) -> None:
        with sqlite3.connect(self.db.db_name) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS news_items (
                    dedup_key TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    canonical_url TEXT,
                    url TEXT,
                    source TEXT,
                    published_at TEXT,
                    summary TEXT,
                    query TEXT,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    last_shown TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_news_items_last_shown
                ON news_items(last_shown)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_news_items_last_seen
                ON news_items(last_seen)
                """
            )
            conn.commit()

    def get_metadata(self, key: str) -> Optional[str]:
        with sqlite3.connect(self.db.db_name) as conn:
            row = conn.execute("SELECT value FROM index_metadata WHERE key = ?", (key,)).fetchone()
            return row[0] if row else None

    def set_metadata(self, key: str, value: str) -> None:
        with sqlite3.connect(self.db.db_name) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO index_metadata (key, value) VALUES (?, ?)",
                (key, value),
            )
            conn.commit()

    def upsert(self, items: Iterable[NewsItem]) -> int:
        now = datetime.now(UTC).isoformat()
        rows = []
        for it in items:
            rows.append(
                (
                    it.key,
                    it.title,
                    it.canonical_url,
                    it.url,
                    it.source,
                    it.published_at,
                    it.summary,
                    it.query,
                    now,
                    now,
                )
            )

        if not rows:
            return 0

        with sqlite3.connect(self.db.db_name) as conn:
            conn.executemany(
                """
                INSERT INTO news_items (
                    dedup_key, title, canonical_url, url, source, published_at, summary, query, first_seen, last_seen
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dedup_key) DO UPDATE SET
                    title=excluded.title,
                    canonical_url=excluded.canonical_url,
                    url=excluded.url,
                    source=COALESCE(excluded.source, news_items.source),
                    published_at=COALESCE(excluded.published_at, news_items.published_at),
                    summary=COALESCE(excluded.summary, news_items.summary),
                    query=COALESCE(excluded.query, news_items.query),
                    last_seen=excluded.last_seen
                """,
                rows,
            )
            conn.commit()
        return len(rows)

    def select_for_briefing(self, limit: int = 5, suppress_days: int = 2, max_age_days: int = 7) -> list[dict]:
        """
        Return items not shown recently, limited and biased toward recent.
        """
        with sqlite3.connect(self.db.db_name) as conn:
            rows = conn.execute(
                """
                SELECT dedup_key, title, COALESCE(canonical_url, url) AS link, source, published_at, summary
                FROM news_items
                WHERE (last_shown IS NULL OR last_shown < datetime('now', ?))
                  AND first_seen >= datetime('now', ?)
                ORDER BY
                    COALESCE(published_at, last_seen) DESC
                LIMIT ?
                """,
                (f"-{suppress_days} days", f"-{max_age_days} days", limit),
            ).fetchall()

        return [
            {
                "dedup_key": r[0],
                "title": r[1],
                "link": r[2],
                "source": r[3],
                "published_at": r[4],
                "summary": r[5],
            }
            for r in rows
        ]

    def mark_shown(self, dedup_keys: Iterable[str]) -> None:
        keys = [k for k in dedup_keys if k]
        if not keys:
            return
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.db.db_name) as conn:
            conn.executemany(
                "UPDATE news_items SET last_shown = ? WHERE dedup_key = ?",
                [(now, k) for k in keys],
            )
            conn.commit()


def _extract_keywords(subjects: list[str], max_keywords: int = 6) -> list[str]:
    stop = {
        "fda",
        "and",
        "the",
        "for",
        "with",
        "your",
        "from",
        "this",
        "that",
        "you",
        "are",
        "new",
        "update",
        "updates",
        "weekly",
        "daily",
        "newsletter",
        "news",
    }
    counts: dict[str, int] = {}
    for s in subjects:
        for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]{2,}", s or ""):
            lw = w.lower()
            if lw in stop:
                continue
            counts[lw] = counts.get(lw, 0) + 1
    return [w for w, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:max_keywords]]


def build_news_queries(seed_subjects: list[str]) -> list[str]:
    base_queries = [
        "FDA medical device guidance update",
        "AI SaMD regulatory news FDA PCCP",
        "IVD LDT FDA policy update",
    ]
    keywords = _extract_keywords(seed_subjects)
    if keywords:
        base_queries.insert(0, " ".join(keywords[:6]) + " medical device regulatory news")
    # Dedup queries while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for q in base_queries:
        qq = q.strip()
        if not qq or qq.lower() in seen:
            continue
        seen.add(qq.lower())
        out.append(qq)
    return out[:3]


class NewsService:
    """
    Fetch external headlines (via web search), seed relevance with Gmail 'News' label subjects,
    dedup + cache in SQLite, and return a stable list for daily briefing.
    """

    def __init__(self, db: DatabaseManager, data_fetcher):
        self.db = db
        self.data_fetcher = data_fetcher
        self.store = NewsStore(db)

        api_key = os.getenv("ANTHROPIC_API_KEY")
        self._client = Anthropic(api_key=api_key) if api_key else None

    def _web_search_headlines(self, query: str) -> list[NewsItem]:
        if not self._client:
            return []
        system = (
            "You are a news researcher for a medical device regulatory consultant. "
            "Search the web for the most relevant, recent headlines for the query. "
            "Return ONLY a JSON array of 5-10 items. Each item must have: "
            "{title, url, source, published_at, summary}. "
            "published_at should be ISO 8601 date or datetime if known; otherwise null. "
            "summary must be one sentence. Do not include duplicates; prefer canonical URLs."
        )
        resp = self._client.messages.create(
            model="claude-3-7-sonnet-latest",
            max_tokens=1600,
            system=system,
            messages=[{"role": "user", "content": query}],
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
        )

        text_parts = []
        for block in (resp.content or []):
            if hasattr(block, "text") and block.text:
                text_parts.append(block.text)
        text = "\n".join(text_parts).strip()
        if not text:
            return []

        # Extract JSON array from response
        start = text.find("[")
        end = text.rfind("]") + 1
        if start < 0 or end <= start:
            return []
        json_str = text[start:end]
        try:
            data = json.loads(json_str)
        except Exception:
            return []
        if not isinstance(data, list):
            return []

        items: list[NewsItem] = []
        for obj in data:
            if not isinstance(obj, dict):
                continue
            title = str(obj.get("title") or "").strip()
            url = str(obj.get("url") or "").strip()
            if not title or not url:
                continue
            items.append(
                NewsItem(
                    title=title,
                    url=url,
                    source=(str(obj.get("source")) if obj.get("source") else None),
                    published_at=(str(obj.get("published_at")) if obj.get("published_at") else None),
                    summary=(str(obj.get("summary")) if obj.get("summary") else None),
                    query=query,
                )
            )
        return items

    def _should_fetch_now(self, min_interval_minutes: int = 120) -> bool:
        key = "news:last_fetch"
        last = self.store.get_metadata(key)
        if not last:
            return True
        try:
            last_dt = datetime.fromisoformat(last)
        except Exception:
            return True
        return datetime.now(UTC) - last_dt >= timedelta(minutes=min_interval_minutes)

    def _mark_fetched_now(self) -> None:
        self.store.set_metadata("news:last_fetch", datetime.now(UTC).isoformat())

    def refresh_cache(self) -> None:
        if not self._should_fetch_now():
            return

        seed_subjects: list[str] = []
        try:
            if hasattr(self.data_fetcher, "get_gmail_news_seeds"):
                seed_subjects = self.data_fetcher.get_gmail_news_seeds(days=3, max_messages=20) or []
        except Exception:
            seed_subjects = []

        queries = build_news_queries(seed_subjects)
        all_items: list[NewsItem] = []
        for q in queries:
            try:
                all_items.extend(self._web_search_headlines(q))
            except Exception:
                continue

        # Dedup in-memory before writing
        uniq: dict[str, NewsItem] = {}
        for it in all_items:
            uniq[it.key] = it
        self.store.upsert(uniq.values())
        self._mark_fetched_now()

    def get_briefing_items(self, limit: int = 5) -> list[dict]:
        self.refresh_cache()
        items = self.store.select_for_briefing(limit=limit)
        self.store.mark_shown([i["dedup_key"] for i in items])
        return items

