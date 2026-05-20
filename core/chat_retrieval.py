import json
import logging
import re
from typing import Callable

from core.local_llm import run_local_completion

logger = logging.getLogger(__name__)
# Pulse private memory + Shield (chat retrieval surface)

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)
_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-]{1,}")

_RECENT_TURN_BUFFER = 6
_MAX_TURNS_PER_CHUNK = 12
_MIN_TURNS_PER_CHUNK = 4


def _extract_json_object(raw: str) -> dict | None:
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
        pass
    match = _JSON_BLOCK_RE.search(text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _normalize_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if not text:
            continue
        out.append(text[:180])
    return out[:10]


def _preview_turns(turns: list[tuple]) -> str:
    lines: list[str] = []
    for _rowid, role, content, _timestamp in turns:
        snippet = " ".join(str(content or "").split())
        if len(snippet) > 240:
            snippet = snippet[:237].rstrip() + "..."
        lines.append(f"{str(role or '').upper()}: {snippet}")
    return "\n".join(lines)


def default_chunk_summarizer(turns: list[tuple], *, session_id: str) -> dict:
    transcript = _preview_turns(turns)
    prompt = [
        {
            "role": "system",
            "content": (
                "Summarize a conversation chunk for long-term retrieval. "
                "Return JSON only with keys summary, key_decisions, open_loops, tags. "
                "Keep the summary to 2-4 sentences. Tags should be short phrases."
            ),
        },
        {
            "role": "user",
            "content": (
                f"session_id: {session_id}\n"
                f"turn_count: {len(turns)}\n\n"
                f"conversation_chunk:\n{transcript}\n\n"
                'Return JSON like {"summary":"...","key_decisions":["..."],"open_loops":["..."],"tags":["..."]}.'
            ),
        },
    ]
    raw = run_local_completion(prompt, "conversation_chunk_summarize")
    data = _extract_json_object(raw) or {}
    summary = str(data.get("summary") or "").strip()
    if not summary:
        first_user = next((str(turn[2] or "").strip() for turn in turns if str(turn[1] or "").lower() == "user"), "")
        last_assistant = next((str(turn[2] or "").strip() for turn in reversed(turns) if str(turn[1] or "").lower() == "assistant"), "")
        summary = " ".join(part for part in (first_user[:120], last_assistant[:120]) if part).strip() or "Conversation chunk summary unavailable."
    return {
        "summary": summary[:500],
        "key_decisions": _normalize_list(data.get("key_decisions")),
        "open_loops": _normalize_list(data.get("open_loops")),
        "tags": _normalize_list(data.get("tags")),
    }


def ensure_session_chunk_summaries(
    db,
    session_id: str,
    *,
    summarizer: Callable[[list[tuple]], dict] | None = None,
    recent_turn_buffer: int = _RECENT_TURN_BUFFER,
    max_turns_per_chunk: int = _MAX_TURNS_PER_CHUNK,
    min_turns_per_chunk: int = _MIN_TURNS_PER_CHUNK,
) -> int:
    session = str(session_id or "").strip()
    if not session:
        return 0
    latest_end_rowid = 0
    try:
        latest_end_rowid = int(db.conversation_chunk_latest_end_rowid(session))
    except Exception:
        latest_end_rowid = 0
    turns = list(db.list_conversation_turn_rows(session, after_rowid=latest_end_rowid))
    if len(turns) <= int(recent_turn_buffer):
        return 0
    eligible_turns = turns[:-int(recent_turn_buffer)]
    if len(eligible_turns) < int(min_turns_per_chunk):
        return 0
    summarize = summarizer
    if summarize is None:
        summarize = lambda chunk_turns: default_chunk_summarizer(chunk_turns, session_id=session)
    created = 0
    for start in range(0, len(eligible_turns), int(max_turns_per_chunk)):
        chunk_turns = eligible_turns[start : start + int(max_turns_per_chunk)]
        if len(chunk_turns) < int(min_turns_per_chunk):
            break
        start_rowid = int(chunk_turns[0][0])
        end_rowid = int(chunk_turns[-1][0])
        roles = [str(turn[1] or "").strip().lower() for turn in chunk_turns]
        chunk_id = int(
            db.conversation_chunk_add(
                session_id=session,
                start_rowid=start_rowid,
                end_rowid=end_rowid,
                start_ts=str(chunk_turns[0][3] or "").strip() or None,
                end_ts=str(chunk_turns[-1][3] or "").strip() or None,
                turn_count=len(chunk_turns),
                roles_json=roles,
            )
        )
        if chunk_id <= 0:
            continue
        try:
            summary = summarize(chunk_turns)
        except Exception:
            logger.exception("Long-term retrieval chunk summarize failed for %s", session)
            continue
        db.conversation_chunk_summary_upsert(
            chunk_id=chunk_id,
            session_id=session,
            summary_text=str(summary.get("summary") or "").strip(),
            key_decisions_json=summary.get("key_decisions") or [],
            open_loops_json=summary.get("open_loops") or [],
            tags_json=summary.get("tags") or [],
        )
        created += 1
    return created


def _alias_expansion_terms(db, query: str) -> list[str]:
    base_query = str(query or "").strip()
    if not base_query:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def _add(value: str) -> None:
        text = " ".join(str(value or "").strip().split())
        if not text:
            return
        marker = text.casefold()
        if marker in seen:
            return
        seen.add(marker)
        out.append(text)

    _add(base_query)
    token_query = " ".join(_query_terms(base_query))
    if token_query and token_query.casefold() != base_query.casefold():
        _add(token_query)
    for term in _query_terms(base_query):
        _add(term)
    rows = []
    for alias_query in [base_query, token_query, *_query_terms(base_query)]:
        if not alias_query:
            continue
        try:
            rows = db.user_memory_alias_search(query=alias_query, approval_status="approved", limit=5)
        except Exception:
            rows = []
        if rows:
            break
    for row in rows:
        json_data = str(row[6] or "").strip()
        if not json_data:
            continue
        try:
            payload = json.loads(json_data)
        except Exception:
            continue
        alias = payload.get("alias") if isinstance(payload, dict) else None
        if not isinstance(alias, dict):
            continue
        for key in ("term", "canonical"):
            value = str(alias.get(key) or "").strip()
            _add(value)
        for item in alias.get("synonyms") or []:
            _add(str(item or "").strip())
    return out


def _query_terms(query: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for match in _WORD_RE.finditer(str(query or "")):
        term = match.group(0).strip()
        if len(term) < 3:
            continue
        lowered = term.casefold()
        if lowered in seen:
            continue
        seen.add(lowered)
        terms.append(term)
    return terms


def _select_relevant_turns(turns: list[tuple], query: str, *, limit: int) -> list[tuple]:
    if not turns:
        return []
    terms = [term.casefold() for term in _query_terms(query)]
    if not terms:
        return turns[-int(limit) :]
    hit_indexes = [
        idx
        for idx, turn in enumerate(turns)
        if any(term in str(turn[1] or "").casefold() or term in str(turn[0] or "").casefold() for term in terms)
    ]
    if hit_indexes:
        selected_indexes: list[int] = []
        seen_indexes: set[int] = set()
        for idx in hit_indexes:
            for candidate in (idx, idx + 1):
                if candidate < 0 or candidate >= len(turns) or candidate in seen_indexes:
                    continue
                seen_indexes.add(candidate)
                selected_indexes.append(candidate)
                if len(selected_indexes) >= int(limit):
                    break
            if len(selected_indexes) >= int(limit):
                break
        return [turns[idx] for idx in selected_indexes]
    return turns[-int(limit) :]


def build_long_term_retrieval_context(
    db,
    query: str,
    *,
    session_id: str | None,
    chunk_limit: int = 3,
    raw_turn_limit: int = 6,
) -> str:
    session = str(session_id or "").strip()
    q = str(query or "").strip()
    if not session or not q:
        return ""
    try:
        ensure_session_chunk_summaries(db, session)
    except Exception:
        logger.exception("Long-term retrieval lazy chunk build failed for %s", session)
    # Pulse private memory themes / raised intel (incl. 🛡️ security-relevant) complement long-term retrieval context for CoS/agents (new coordination note)
    # New: retrieval now explicitly consumes Pulse private memory for Shield (additional retrieval spot)
    search_queries = _alias_expansion_terms(db, q)
    summary_rows: list[tuple] = []
    seen_chunks: set[int] = set()
    for search_query in search_queries:
        try:
            rows = db.conversation_chunk_summary_search(query=search_query, session_id=session, limit=max(3, int(chunk_limit) * 2))
        except Exception:
            rows = []
        for row in rows:
            chunk_id = int(row[0] or 0)
            if chunk_id <= 0 or chunk_id in seen_chunks:
                continue
            seen_chunks.add(chunk_id)
            summary_rows.append(row)
            if len(summary_rows) >= int(chunk_limit):
                break
        if len(summary_rows) >= int(chunk_limit):
            break
    parts: list[str] = []
    if summary_rows:
        lines: list[str] = []
        raw_lines: list[str] = []
        raw_added = 0
        for chunk_id, _session_id, summary_text, key_decisions_json, open_loops_json, tags_json, _created_at in summary_rows[: int(chunk_limit)]:
            decisions = _normalize_list(json.loads(key_decisions_json)) if str(key_decisions_json or "").strip() else []
            loops = _normalize_list(json.loads(open_loops_json)) if str(open_loops_json or "").strip() else []
            tags = _normalize_list(json.loads(tags_json)) if str(tags_json or "").strip() else []
            line = f"- {str(summary_text or '').strip()}"
            if decisions:
                line += f" Decisions: {'; '.join(decisions[:3])}."
            if loops:
                line += f" Open loops: {'; '.join(loops[:3])}."
            if tags:
                line += f" Tags: {', '.join(tags[:5])}."
            lines.append(line)
            if raw_added < int(raw_turn_limit):
                turns = db.conversation_chunk_turns(int(chunk_id))
                chosen = _select_relevant_turns(turns, q, limit=max(1, int(raw_turn_limit) - raw_added))
                for role, content, timestamp in chosen:
                    snippet = " ".join(str(content or "").split())
                    if len(snippet) > 200:
                        snippet = snippet[:197].rstrip() + "..."
                    raw_lines.append(f"- [{timestamp}] {role}: {snippet}")
                    raw_added += 1
                    if raw_added >= int(raw_turn_limit):
                        break
        if lines:
            parts.append("Relevant older chat summaries (untrusted):\n" + "\n".join(lines))
        if raw_lines:
            parts.append("Grounding turns from matched summaries (untrusted):\n" + "\n".join(raw_lines))
    else:
        try:
            turns = db.list_conversation_turn_rows(session)
        except Exception:
            turns = []
        if turns:
            rows = _select_relevant_turns(turns, q, limit=int(raw_turn_limit))
            lines = []
            for rowid, role, content, timestamp in rows[: int(raw_turn_limit)]:
                _ = rowid
                snippet = " ".join(str(content or "").split())
                if len(snippet) > 200:
                    snippet = snippet[:197].rstrip() + "..."
                lines.append(f"- [{timestamp}] {role}: {snippet}")
            parts.append("Relevant older chat snippets (untrusted):\n" + "\n".join(lines))
    return "\n\n".join(parts)


def format_chat_history_tool_results(
    db,
    *,
    session_id: str,
    query: str,
    chunk_limit: int = 3,
    raw_turn_limit: int = 8,
) -> str:
    context = build_long_term_retrieval_context(
        db,
        query,
        session_id=session_id,
        chunk_limit=chunk_limit,
        raw_turn_limit=raw_turn_limit,
    )
    if not context:
        try:
            rows = db.search_chat_history(session_id, query, limit=int(raw_turn_limit))
        except Exception:
            rows = []
        if not rows:
            return "CHAT_HISTORY_RESULTS (untrusted):\n(no matches)"
        lines = []
        for role, content, timestamp in rows[: int(raw_turn_limit)]:
            snippet = " ".join(str(content or "").split())
            if len(snippet) > 240:
                snippet = snippet[:237].rstrip() + "..."
            lines.append(f"- [{timestamp}] {role}: {snippet}")
        return "CHAT_HISTORY_RESULTS (untrusted):\n" + "\n".join(lines)
    return "CHAT_HISTORY_RESULTS (untrusted):\n" + context
