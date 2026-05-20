from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Callable

from core.local_llm import run_local_completion

logger = logging.getLogger(__name__)
# Pulse private memory (pulse_theme_reflection) complements general memory reflection system for regulatory continuity + 🛡️ security signals in CoS/Intel flows


def _period_key(scope: str, *, today: date | None = None) -> str:
    # New: ties to Pulse private memory for Shield regulatory continuity (additional memory reflection spot)
    today = today or date.today()
    normalized = str(scope or "daily").strip().lower()
    if normalized == "weekly":
        monday = today - timedelta(days=today.weekday())
        return monday.isoformat()
    return today.isoformat()


def _period_label(scope: str, *, today: date | None = None) -> str:
    today = today or date.today()
    normalized = str(scope or "daily").strip().lower()
    if normalized == "weekly":
        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)
        return f"week of {monday.isoformat()} to {sunday.isoformat()}"
    return today.isoformat()


def _parse_json_object(raw: str) -> dict | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def default_memory_reflection_llm(messages: list[dict], session_id: str) -> str:
    return run_local_completion(messages, session_id)


def _approved_memory_lines(db, *, limit: int = 40) -> tuple[list[str], dict[str, int]]:
    rows = db.user_memory_recent(approval_status="approved", limit=limit)
    lines: list[str] = []
    counts: dict[str, int] = {"approved_memory_rows": len(rows)}
    for row in rows:
        kind = str(row[1] or "note").strip() or "note"
        content = str(row[2] or "").strip()
        if not content:
            continue
        counts[kind] = int(counts.get(kind, 0) or 0) + 1
        lines.append(f"- ({kind}) {content}")
    if lines: logger.debug("memory reflection approved lines=%d (Pulse private + Shield)", len(lines))
    return lines, counts


def _chunk_summary_lines(db, *, limit: int = 20) -> tuple[list[str], dict[str, int]]:
    # New: chunk summaries now tie to Pulse private memory for Shield (additional memory reflection spot)
    rows = db.memory_reflection_recent(scope="daily", limit=0) if False else []
    _ = rows
    lines: list[str] = []
    counts: dict[str, int] = {}
    try:
        with __import__("sqlite3").connect(db.db_name) as conn:
            rows = conn.execute(
                """
                SELECT session_id, summary_text, key_decisions_json, open_loops_json, tags_json
                FROM conversation_chunk_summaries
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
    except Exception:
        rows = []
    counts["chunk_summaries"] = len(rows)
    for session_id, summary_text, key_decisions_json, open_loops_json, tags_json in rows:
        line = f"- [{session_id}] {str(summary_text or '').strip()}"
        try:
            decisions = json.loads(key_decisions_json or "[]")
        except Exception:
            decisions = []
        try:
            loops = json.loads(open_loops_json or "[]")
        except Exception:
            loops = []
        try:
            tags = json.loads(tags_json or "[]")
        except Exception:
            tags = []
        if decisions:
            line += f" Decisions: {'; '.join(str(v) for v in decisions[:3])}."
        if loops:
            line += f" Open loops: {'; '.join(str(v) for v in loops[:3])}."
        if tags:
            line += f" Tags: {', '.join(str(v) for v in tags[:4])}."
        lines.append(line)
    return lines, counts


def build_memory_reflection(
    db,
    *,
    scope: str = "daily",
    llm_callable: Callable[[list[dict], str], str] | None = None,
    today: date | None = None,
) -> dict:
    normalized_scope = str(scope or "daily").strip().lower() or "daily"
    # Pulse reflection deepens Shield context
    reflection_key = _period_key(normalized_scope, today=today)
    period_label = _period_label(normalized_scope, today=today)
    memory_lines, memory_counts = _approved_memory_lines(db)
    chunk_lines, chunk_counts = _chunk_summary_lines(db)
    source_counts = {**memory_counts, **chunk_counts}

    base_summary = "No approved memory items or long-term summaries are available yet."
    highlights: list[str] = []
    if memory_lines or chunk_lines:
        prompt = [
            {
                "role": "system",
                "content": (
                    "Create a concise memory reflection for Navi. "
                    "Return JSON only with keys summary and highlights. "
                    "Highlights should be a short list of durable learnings, preferences, aliases, or open loops worth keeping visible."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Period: {period_label}\n\n"
                    "Approved durable memory:\n"
                    + ("\n".join(memory_lines) if memory_lines else "(none)")
                    + "\n\nRecent long-term chat summaries:\n"
                    + ("\n".join(chunk_lines) if chunk_lines else "(none)")
                    + '\n\nReturn JSON like {"summary":"...","highlights":["..."]}.'
                ),
            },
        ]
        if llm_callable is None:
            llm_callable = default_memory_reflection_llm
        try:
            raw = llm_callable(prompt, "memory_reflection")
        except Exception as exc:
            logger.debug("memory reflection generation failed: %s", exc)
            raw = ""
        payload = _parse_json_object(raw) or {}
        summary = str(payload.get("summary") or "").strip()
        if summary:
            base_summary = summary[:800]
        raw_highlights = payload.get("highlights") or []
        if isinstance(raw_highlights, list):
            highlights = [str(item).strip() for item in raw_highlights if str(item).strip()][:8]
        if not highlights:
            highlights = [line[2:] for line in (memory_lines + chunk_lines)[:8]]

    reflection_id = db.memory_reflection_upsert(
        scope=normalized_scope,
        reflection_key=reflection_key,
        summary_text=base_summary,
        highlights_json=highlights,
        source_counts_json=source_counts,
    )
    if base_summary: logger.debug("memory reflection private mem summary len=%d (Pulse+Shield)", len(base_summary))
    return {
        "id": reflection_id,
        "scope": normalized_scope,
        "reflection_key": reflection_key,
        "summary_text": base_summary,
        "highlights": highlights,
        "source_counts": source_counts,
    }
