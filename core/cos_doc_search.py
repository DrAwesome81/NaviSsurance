from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class DocHit:
    source: str
    snippet: str
    score: int = 0


def _normalize_q(q: str) -> str:
    return (q or "").strip()


def _snippet(text: str, q: str, max_len: int = 260) -> str:
    t = text or ""
    qq = q.strip()
    if not t:
        return ""
    low = t.lower()
    i = low.find(qq.lower()) if qq else -1
    if i < 0:
        return (t[: max_len - 3] + "...") if len(t) > max_len else t
    start = max(0, i - 80)
    end = min(len(t), i + 180)
    s = t[start:end]
    if start > 0:
        s = "..." + s
    if end < len(t):
        s = s + "..."
    return s


def search_notes(db_path: str, query: str, limit: int = 5) -> list[DocHit]:
    q = _normalize_q(query)
    if not q:
        return []
    like = f"%{q}%"
    hits: list[DocHit] = []
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, category, formatted_note, timestamp
                FROM notes
                WHERE formatted_note LIKE ? OR category LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (like, like, int(limit)),
            ).fetchall()
        for note_id, category, formatted_note, ts in rows:
            src = f"note:{note_id} ({category or 'uncategorized'})"
            hits.append(DocHit(source=src, snippet=_snippet(formatted_note or "", q), score=1))
    except Exception:
        return []
    return hits


def search_local_markdown(root_dir: str, query: str, limit: int = 8) -> list[DocHit]:
    q = _normalize_q(query)
    if not q or not os.path.isdir(root_dir):
        return []
    hits: list[DocHit] = []
    patt = re.compile(re.escape(q), re.IGNORECASE)
    for base, _, files in os.walk(root_dir):
        for fn in files:
            if not fn.lower().endswith((".md", ".txt")):
                continue
            path = os.path.join(base, fn)
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                if not patt.search(text):
                    continue
                score = len(patt.findall(text))
                hits.append(DocHit(source=os.path.relpath(path), snippet=_snippet(text, q), score=score))
            except Exception:
                continue
    hits.sort(key=lambda h: (-h.score, h.source))
    return hits[: int(limit)]


def rag_search(query: str, k: int = 5) -> list[DocHit]:
    """
    Optional semantic search over the local Chroma RAG index.
    Disabled unless COS_ENABLE_RAG_SEARCH=1 and chroma_index exists.
    """
    q = _normalize_q(query)
    if not q:
        return []
    if os.getenv("COS_ENABLE_RAG_SEARCH") != "1":
        return []
    chroma_path = os.getenv("CHROMA_PATH") or "chroma_index"
    if not os.path.isdir(chroma_path):
        return []

    model_name = os.getenv("RAG_EMBEDDINGS_MODEL") or "BAAI/bge-large-en-v1.5"
    try:
        from langchain_community.vectorstores import Chroma
        from langchain_huggingface import HuggingFaceEmbeddings
    except Exception:
        return []

    try:
        embeddings = HuggingFaceEmbeddings(model_name=model_name)
        vs = Chroma(persist_directory=chroma_path, embedding_function=embeddings)
        docs = vs.similarity_search(q, k=int(k))
        out: list[DocHit] = []
        for d in docs:
            src = (d.metadata or {}).get("source") or "rag"
            out.append(DocHit(source=f"rag:{src}", snippet=_snippet(d.page_content or "", q), score=1))
        return out
    except Exception:
        return []


def doc_search(db_path: str, query: str, limit: int = 10) -> list[DocHit]:
    """
    Hybrid doc search:
    - notes in SQLite
    - local markdown in docs/
    - optional semantic search via Chroma (if enabled)
    """
    q = _normalize_q(query)
    if not q:
        return []
    hits: list[DocHit] = []
    hits.extend(search_notes(db_path, q, limit=5))
    hits.extend(search_local_markdown("docs", q, limit=8))
    hits.extend(rag_search(q, k=5))

    # Dedup by source+snippet head
    seen = set()
    uniq: list[DocHit] = []
    for h in hits:
        key = (h.source, h.snippet[:80])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(h)
    uniq.sort(key=lambda h: (-h.score, h.source))
    return uniq[: int(limit)]


def format_hits(hits: list[DocHit]) -> str:
    if not hits:
        return "(no matches)"
    lines = []
    for h in hits[:10]:
        lines.append(f"- {h.source}: {h.snippet}")
    return "\n".join(lines)

