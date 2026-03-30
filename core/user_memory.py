import json
import logging
import re
from collections.abc import Callable

from core.local_llm import run_local_completion

logger = logging.getLogger(__name__)

_TEACH_NAVI_RE = re.compile(r"^\s*teach\s+navi\s*:\s*(?P<body>.+?)\s*$", re.IGNORECASE | re.DOTALL)
_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)
_ALIAS_PATTERNS = (
    re.compile(
        r"^\s*(?P<term>[^=\n]{1,80}?)\s+(?:means|stands\s+for|is\s+shorthand\s+for|is\s+short\s+for)\s+(?P<canonical>.+?)\s*$",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(r"^\s*(?P<term>[^=\n]{1,48}?)\s*=\s*(?P<canonical>.+?)\s*$", re.IGNORECASE | re.DOTALL),
)
_NON_ALIAS_TERMS = {
    "i",
    "i'm",
    "im",
    "me",
    "my",
    "mine",
    "we",
    "our",
    "ours",
    "you",
    "your",
    "please",
    "remember",
    "prefer",
}


def parse_teach_navi_command(message: str) -> str | None:
    match = _TEACH_NAVI_RE.match(str(message or ""))
    if not match:
        return None
    body = (match.group("body") or "").strip()
    return body or None


def _strip_terminal_punctuation(text: str) -> str:
    return str(text or "").strip().rstrip(" \t\r\n.;:!?")


def _looks_like_alias_term(term: str) -> bool:
    value = _strip_terminal_punctuation(term)
    if not value:
        return False
    if len(value) > 64 or any(ch in value for ch in ".!?"):
        return False
    words = [part for part in value.split() if part]
    if not words or len(words) > 6:
        return False
    if words[0].casefold() in _NON_ALIAS_TERMS:
        return False
    return True


def parse_alias_memory(text: str) -> dict | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    for pattern in _ALIAS_PATTERNS:
        match = pattern.match(raw)
        if not match:
            continue
        term = _strip_terminal_punctuation(match.group("term") or "")
        canonical = _strip_terminal_punctuation(match.group("canonical") or "")
        if not _looks_like_alias_term(term) or not canonical:
            continue
        return {
            "term": term,
            "canonical": canonical,
            "synonyms": [],
            "content": f"{term} means {canonical}.",
        }
    return None


def _parse_json_payload(value) -> dict | None:
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _preview_text(text: str, *, limit: int = 160) -> str:
    value = " ".join(str(text or "").strip().split())
    if len(value) <= int(limit):
        return value
    return value[: max(0, int(limit) - 3)].rstrip() + "..."


def default_user_memory_llm(messages: list[dict], session_id: str) -> str:
    """Default local extractor used when no response-handler helper is available."""
    return run_local_completion(messages, session_id)


def build_auto_memory_metadata(
    *,
    session_id: str | None = None,
    chat_id: int | None = None,
    route: str | None = None,
    user_message: str = "",
    assistant_message: str = "",
) -> dict:
    metadata: dict[str, object] = {
        "extraction_version": "passive_memory_v2",
        "source_session_id": str(session_id or "").strip() or None,
        "chat_id": int(chat_id) if chat_id is not None else None,
        "route": str(route or "").strip() or None,
        "user_message_preview": _preview_text(user_message),
        "assistant_message_preview": _preview_text(assistant_message),
    }
    return {key: value for key, value in metadata.items() if value not in (None, "")}


def _alias_payload_from_row(row: tuple) -> dict | None:
    json_payload = _parse_json_payload(row[6] if len(row) > 6 else None)
    alias_payload = json_payload.get("alias") if isinstance(json_payload, dict) else None
    if isinstance(alias_payload, dict):
        term = _strip_terminal_punctuation(alias_payload.get("term") or "")
        canonical = _strip_terminal_punctuation(alias_payload.get("canonical") or "")
        if term and canonical:
            synonyms = alias_payload.get("synonyms") or []
            if not isinstance(synonyms, list):
                synonyms = []
            return {
                "term": term,
                "canonical": canonical,
                "synonyms": [str(item).strip() for item in synonyms if str(item).strip()],
                "content": f"{term} means {canonical}.",
            }
    return parse_alias_memory(row[2] if len(row) > 2 else "")


def store_teach_navi_memory(db, message: str) -> str | None:
    body = parse_teach_navi_command(message)
    if not body:
        return None
    alias_payload = parse_alias_memory(body)
    if alias_payload:
        db.user_memory_add(
            kind="alias",
            content=alias_payload["content"],
            source="teach_navi",
            confidence=1.0,
            approval_status="approved",
            json_data={"explicit": True, "alias": alias_payload},
        )
        return f"I'll remember that alias: {alias_payload['term']} means {alias_payload['canonical']}."
    db.user_memory_add(
        kind="taught",
        content=body,
        source="teach_navi",
        confidence=1.0,
        approval_status="approved",
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


def _load_alias_rows(db, query: str, *, limit: int, recent_limit: int) -> list[tuple]:
    rows: list[tuple] = []
    alias_search = getattr(db, "user_memory_alias_search", None)
    alias_recent = getattr(db, "user_memory_alias_recent", None)
    try:
        if callable(alias_search):
            rows.extend(alias_search(query=query, approval_status="approved", limit=limit))
        else:
            rows.extend(db.user_memory_search(query=query, kind="alias", approval_status="approved", limit=limit))
    except Exception as exc:
        logger.debug("user_memory alias search failed: %s", exc)
    try:
        if callable(alias_recent):
            rows.extend(alias_recent(approval_status="approved", limit=recent_limit))
        else:
            rows.extend(db.user_memory_recent(kind="alias", approval_status="approved", limit=recent_limit))
    except Exception as exc:
        logger.debug("user_memory alias recent failed: %s", exc)
    rows = [row for row in rows if str(row[1] or "").strip() == "alias"]
    return _dedupe_rows(rows, limit)


def _format_generic_memory_lines(rows: list[tuple]) -> list[str]:
    lines: list[str] = []
    for _mem_id, kind, content, source, confidence, _approval_status, _json_data, _created_at, _updated_at in rows:
        label = str(kind or "note").strip() or "note"
        src = str(source or "").strip()
        line = f"- ({label}"
        if src and src != label:
            line += f"; {src}"
        line += f") {str(content or '').strip()}"
        if float(confidence or 0) < 0.999:
            line += f" [confidence {float(confidence):.2f}]"
        lines.append(line)
    return lines


def _format_alias_memory_lines(rows: list[tuple]) -> list[str]:
    lines: list[str] = []
    for row in rows:
        alias_payload = _alias_payload_from_row(row)
        content = str(row[2] or "").strip()
        source = str(row[3] or "").strip()
        confidence = float(row[4] or 0)
        if alias_payload:
            line = f"- {alias_payload['term']} means {alias_payload['canonical']}."
            synonyms = alias_payload.get("synonyms") or []
            if synonyms:
                line += f" Synonyms: {', '.join(str(item) for item in synonyms)}."
        else:
            line = f"- {content}"
        if source and source not in {"alias", "teach_navi"}:
            line += f" ({source})"
        if confidence < 0.999:
            line += f" [confidence {confidence:.2f}]"
        lines.append(line)
    return lines


def build_user_memory_context(db, query: str, *, limit: int = 5, recent_limit: int = 2) -> str:
    text = str(query or "").strip()
    if not text:
        return ""
    alias_rows = _load_alias_rows(db, text, limit=max(1, min(3, limit)), recent_limit=max(1, recent_limit))
    alias_ids = {int(row[0]) for row in alias_rows}
    rows: list[tuple] = []
    try:
        rows.extend(db.user_memory_search(query=text, approval_status="approved", limit=limit))
    except Exception as exc:
        logger.debug("user_memory search failed: %s", exc)
    try:
        rows.extend(db.user_memory_recent(approval_status="approved", limit=recent_limit))
    except Exception as exc:
        logger.debug("user_memory recent failed: %s", exc)
    rows = [row for row in _dedupe_rows(rows, limit) if int(row[0]) not in alias_ids]
    if not rows and not alias_rows:
        return ""
    sections: list[str] = []
    if alias_rows:
        sections.append("Approved aliases / glossary:\n" + "\n".join(_format_alias_memory_lines(alias_rows)))
    if rows:
        sections.append("Relevant durable user memory:\n" + "\n".join(_format_generic_memory_lines(rows)))
    return "\n\n".join(section for section in sections if section.strip())


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
    metadata: dict | None = None,
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
                "Only include stable facts, durable preferences, and repeatable glossary/alias terms the assistant should remember later. "
                "Do not include ephemeral requests, temporary plans, one-off scheduling details, or anything uncertain."
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
    base_metadata = dict(metadata or {})
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
            item_json = dict(base_metadata)
            if kind == "alias":
                alias_payload = parse_alias_memory(content)
                if alias_payload:
                    content = alias_payload["content"]
                    item_json["alias"] = alias_payload
                    item_json["normalized"] = True
            items.append(
                {
                    "kind": kind,
                    "content": content,
                    "source": "auto_chat",
                    "confidence": 0.65,
                    "approval_status": "pending",
                    "json_data": item_json,
                }
            )
    return items[:10]


def auto_store_user_memory(
    db,
    *,
    user_message: str,
    assistant_message: str,
    llm_callable: Callable[[list[dict], str], str] | None,
    session_id: str | None = None,
    chat_id: int | None = None,
    route: str | None = None,
) -> int:
    metadata = build_auto_memory_metadata(
        session_id=session_id,
        chat_id=chat_id,
        route=route,
        user_message=user_message,
        assistant_message=assistant_message,
    )
    items = extract_user_memory_items(
        user_message=user_message,
        assistant_message=assistant_message,
        llm_callable=llm_callable,
        metadata=metadata,
    )
    if not items:
        return 0
    try:
        return int(db.user_memory_add_many(items=items))
    except Exception as exc:
        logger.debug("user_memory writeback failed: %s", exc)
        return 0
