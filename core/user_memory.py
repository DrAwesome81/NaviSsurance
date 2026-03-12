import json
import logging
import re
from collections.abc import Callable

logger = logging.getLogger(__name__)

_TEACH_NAVI_RE = re.compile(r"^\s*teach\s+navi\s*:\s*(?P<body>.+?)\s*$", re.IGNORECASE | re.DOTALL)
_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_teach_navi_command(message: str) -> str | None:
    match = _TEACH_NAVI_RE.match(str(message or ""))
    if not match:
        return None
    body = (match.group("body") or "").strip()
    return body or None


def store_teach_navi_memory(db, message: str) -> str | None:
    body = parse_teach_navi_command(message)
    if not body:
        return None
    db.user_memory_add(
        kind="taught",
        content=body,
        source="teach_navi",
        confidence=1.0,
        json_data={"explicit": True},
    )
    preview = body if len(body) <= 120 else body[:117] + "..."
    return f"I'll remember that: {preview}"


def _dedupe_rows(rows: list[tuple], limit: int) -> list[tuple]:
    seen: set[int] = set()
    out: list[tuple] = []
    for row in rows:
        row_id = int(row[0])
        if row_id in seen:
            continue
        seen.add(row_id)
        out.append(row)
        if len(out) >= limit:
            break
    return out


def build_user_memory_context(db, query: str, *, limit: int = 5, recent_limit: int = 2) -> str:
    text = str(query or "").strip()
    if not text:
        return ""
    rows: list[tuple] = []
    try:
        rows.extend(db.user_memory_search(query=text, limit=limit))
    except Exception as exc:
        logger.debug("user_memory search failed: %s", exc)
    try:
        rows.extend(db.user_memory_recent(limit=recent_limit))
    except Exception as exc:
        logger.debug("user_memory recent failed: %s", exc)
    rows = _dedupe_rows(rows, limit)
    if not rows:
        return ""
    lines: list[str] = []
    for _mem_id, kind, content, source, confidence, _json_data, _created_at, _updated_at in rows:
        label = str(kind or "note").strip() or "note"
        src = str(source or "").strip()
        line = f"- ({label}"
        if src and src != label:
            line += f"; {src}"
        line += f") {str(content or '').strip()}"
        if float(confidence or 0) < 0.999:
            line += f" [confidence {float(confidence):.2f}]"
        lines.append(line)
    return "Relevant durable user memory:\n" + "\n".join(lines)


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


def extract_user_memory_items(
    *,
    user_message: str,
    assistant_message: str,
    llm_callable: Callable[[list[dict], str], str] | None,
) -> list[dict]:
    if llm_callable is None:
        return []
    user_text = str(user_message or "").strip()
    assistant_text = str(assistant_message or "").strip()
    if not user_text or not assistant_text:
        return []
    prompt = [
        {
            "role": "system",
            "content": (
                "Extract durable user memory from a chat turn. "
                "Return JSON only with keys facts, preferences, aliases. "
                "Only include durable facts the assistant should remember later. "
                "Do not include ephemeral requests, temporary plans, or anything uncertain."
            ),
        },
        {
            "role": "user",
            "content": (
                f"user_message: {user_text}\n"
                f"assistant_message: {assistant_text}\n\n"
                "Return JSON like "
                '{"facts":["..."],"preferences":["..."],"aliases":["..."]}.'
            ),
        },
    ]
    try:
        raw = llm_callable(prompt, "user_memory_extract")
    except Exception as exc:
        logger.debug("user_memory extraction call failed: %s", exc)
        return []
    data = _extract_json_object(raw)
    if not data:
        return []
    items: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for key, kind in (("facts", "fact"), ("preferences", "preference"), ("aliases", "alias")):
        values = data.get(key) or []
        if not isinstance(values, list):
            continue
        for value in values[:8]:
            content = str(value or "").strip()
            if not content or len(content) > 220:
                continue
            marker = (kind, content.casefold())
            if marker in seen:
                continue
            seen.add(marker)
            items.append(
                {
                    "kind": kind,
                    "content": content,
                    "source": "auto_chat",
                    "confidence": 0.65,
                    "json_data": data,
                }
            )
    return items[:10]


def auto_store_user_memory(
    db,
    *,
    user_message: str,
    assistant_message: str,
    llm_callable: Callable[[list[dict], str], str] | None,
) -> int:
    items = extract_user_memory_items(
        user_message=user_message,
        assistant_message=assistant_message,
        llm_callable=llm_callable,
    )
    if not items:
        return 0
    try:
        return int(db.user_memory_add_many(items=items))
    except Exception as exc:
        logger.debug("user_memory writeback failed: %s", exc)
        return 0
