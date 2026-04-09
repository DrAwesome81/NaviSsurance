import json
import logging
import os
import re
from collections.abc import Callable

from core.local_llm import run_local_completion

logger = logging.getLogger(__name__)
_SEMANTIC_MODEL = None

_TEACH_NAVI_RE = re.compile(r"^\s*teach\s+navi\s*:\s*(?P<body>.+?)\s*$", re.IGNORECASE | re.DOTALL)
_TEACH_TARGET_RE = re.compile(
    r"^\s*teach\s+(?P<target>[a-z0-9][a-z0-9 _-]{0,63})\s*:\s*(?P<body>.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
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


def _coerce_scope_payload(value) -> dict:
    if isinstance(value, dict):
        out = {
            str(k).strip(): str(v).strip()
            for k, v in value.items()
            if str(k).strip() and str(v).strip()
        }
        return out
    text = str(value or "").strip()
    if not text:
        return {}
    if ":" in text:
        key, raw_value = text.split(":", 1)
        key = str(key or "").strip().lower()
        raw_value = str(raw_value or "").strip()
        if key and raw_value:
            return {key: raw_value}
    return {"label": text}


def _coerce_synonyms(value) -> list[str]:
    if isinstance(value, list):
        raw_values = value
    else:
        text = str(value or "").strip()
        if not text:
            return []
        raw_values = re.split(r"[;,/]|(?:\s+or\s+)", text)
    out: list[str] = []
    seen: set[str] = set()
    for item in raw_values:
        synonym = _strip_terminal_punctuation(item)
        if not synonym:
            continue
        marker = synonym.casefold()
        if marker in seen:
            continue
        seen.add(marker)
        out.append(synonym)
    return out[:8]


def _json_list(value) -> list:
    if isinstance(value, list):
        return value
    text = str(value or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _entity_ref(entity_type: str, entity_key: str, label: str) -> dict:
    return {
        "entity_type": str(entity_type or "").strip().lower(),
        "entity_key": str(entity_key or "").strip(),
        "label": str(label or "").strip(),
    }


def infer_entity_memory_refs(db, text: str, *, client_limit: int = 200, project_limit: int = 250) -> list[dict]:
    query = str(text or "").strip().casefold()
    if not query:
        return []
    refs: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def _add(entity_type: str, entity_key: str, label: str) -> None:
        marker = (str(entity_type or "").strip().lower(), str(entity_key or "").strip())
        if not marker[0] or not marker[1] or marker in seen:
            return
        seen.add(marker)
        refs.append(_entity_ref(marker[0], marker[1], label))

    try:
        for row in db.list_clients(active_only=False, limit=client_limit):
            names = [str(row.get("name") or "").strip()]
            names.extend(str(item or "").strip() for item in _json_list(row.get("aliases_json")))
            matches = [candidate for candidate in names if candidate and candidate.casefold() in query]
            if matches:
                _add("client", str(row.get("id") or ""), matches[0])
    except Exception as exc:
        logger.debug("client entity inference failed: %s", exc)

    try:
        for row in db.list_cos_projects(active_only=False, limit=project_limit):
            names = [
                str(row.get("name") or "").strip(),
                str(row.get("client") or "").strip(),
            ]
            matches = [candidate for candidate in names if candidate and candidate.casefold() in query]
            if matches:
                _add("project", str(row.get("id") or ""), matches[0])
    except Exception as exc:
        logger.debug("project entity inference failed: %s", exc)

    return refs[:8]


def _semantic_model():
    global _SEMANTIC_MODEL
    if _SEMANTIC_MODEL is not None:
        return _SEMANTIC_MODEL
    try:
        from sentence_transformers import SentenceTransformer
    except Exception:
        return None
    model_name = str(os.getenv("MEMORY_EMBEDDINGS_MODEL", "all-MiniLM-L6-v2")).strip() or "all-MiniLM-L6-v2"
    try:
        _SEMANTIC_MODEL = SentenceTransformer(model_name)
    except Exception:
        _SEMANTIC_MODEL = None
    return _SEMANTIC_MODEL


def _cosine_similarity(a, b) -> float:
    if a is None or b is None:
        return 0.0
    if len(a) == 0 or len(b) == 0:
        return 0.0
    dot = sum(float(x) * float(y) for x, y in zip(a, b))
    norm_a = sum(float(x) * float(x) for x in a) ** 0.5
    norm_b = sum(float(y) * float(y) for y in b) ** 0.5
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _semantic_rerank_rows(query: str, rows: list[tuple], *, limit: int) -> list[tuple]:
    model = _semantic_model()
    if model is None or not rows:
        return rows[: int(limit)]
    try:
        query_emb = model.encode([str(query or "").strip()], convert_to_numpy=True)[0]
        row_embs = model.encode([str(row[2] or "").strip() for row in rows], convert_to_numpy=True)
    except Exception as exc:
        logger.debug("semantic rerank failed: %s", exc)
        return rows[: int(limit)]
    scored: list[tuple[float, tuple]] = []
    for row, emb in zip(rows, row_embs):
        scored.append((_cosine_similarity(query_emb, emb), row))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [row for _score, row in scored[: int(limit)]]


def _normalize_alias_payload(value, *, default_term: str = "", default_canonical: str = "") -> dict | None:
    if isinstance(value, dict):
        term = _strip_terminal_punctuation(value.get("term") or default_term)
        canonical = _strip_terminal_punctuation(value.get("canonical") or default_canonical)
        if not _looks_like_alias_term(term) or not canonical:
            return None
        synonyms = _coerce_synonyms(value.get("synonyms"))
        synonyms = [item for item in synonyms if item.casefold() not in {term.casefold(), canonical.casefold()}]
        scope = _coerce_scope_payload(value.get("scope"))
        payload = {
            "term": term,
            "canonical": canonical,
            "synonyms": synonyms,
            "scope": scope,
            "content": f"{term} means {canonical}.",
        }
        return payload
    parsed = parse_alias_memory(str(value or "").strip())
    if parsed:
        return parsed
    return None


def parse_teach_navi_command(message: str) -> str | None:
    match = _TEACH_NAVI_RE.match(str(message or ""))
    if not match:
        return None
    body = (match.group("body") or "").strip()
    return body or None


def parse_teach_target_command(message: str) -> tuple[str, str] | None:
    match = _TEACH_TARGET_RE.match(str(message or ""))
    if not match:
        return None
    target = str(match.group("target") or "").strip()
    body = str(match.group("body") or "").strip()
    if not target or not body:
        return None
    return target, body


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
    scope_payload: dict = {}
    synonyms: list[str] = []
    base = raw
    if ";" in raw or "|" in raw:
        parts = [segment.strip() for segment in re.split(r"[;|]", raw) if str(segment).strip()]
        retained: list[str] = []
        for segment in parts:
            lowered = segment.casefold()
            if lowered.startswith("synonyms:") or lowered.startswith("synonym:"):
                synonyms = _coerce_synonyms(segment.split(":", 1)[1] if ":" in segment else "")
                continue
            if lowered.startswith("scope:"):
                scope_payload = _coerce_scope_payload(segment.split(":", 1)[1] if ":" in segment else "")
                continue
            retained.append(segment)
        if retained:
            base = retained[0]
    for pattern in _ALIAS_PATTERNS:
        match = pattern.match(base)
        if not match:
            continue
        term = _strip_terminal_punctuation(match.group("term") or "")
        canonical = _strip_terminal_punctuation(match.group("canonical") or "")
        if not _looks_like_alias_term(term) or not canonical:
            continue
        return {
            "term": term,
            "canonical": canonical,
            "synonyms": [item for item in synonyms if item.casefold() not in {term.casefold(), canonical.casefold()}],
            "scope": scope_payload,
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
    entity_refs: list[dict] | None = None,
) -> dict:
    metadata: dict[str, object] = {
        "extraction_version": "passive_memory_v2",
        "source_session_id": str(session_id or "").strip() or None,
        "chat_id": int(chat_id) if chat_id is not None else None,
        "route": str(route or "").strip() or None,
        "user_message_preview": _preview_text(user_message),
        "assistant_message_preview": _preview_text(assistant_message),
        "entity_refs": entity_refs or [],
    }
    return {key: value for key, value in metadata.items() if value not in (None, "")}


def _alias_payload_from_row(row: tuple) -> dict | None:
    json_payload = _parse_json_payload(row[6] if len(row) > 6 else None)
    alias_payload = json_payload.get("alias") if isinstance(json_payload, dict) else None
    if isinstance(alias_payload, dict):
        normalized = _normalize_alias_payload(alias_payload)
        if normalized:
            return normalized
    return parse_alias_memory(row[2] if len(row) > 2 else "")


def _emit_teach_memory_toast(scope_label: str) -> None:
    try:
        from core.chief_of_staff_service import emit_cos_toast

        label = (scope_label or "Navi").strip() or "Navi"
        emit_cos_toast(f"✓ Saved to {label} memory")
    except Exception:
        pass


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
        _emit_teach_memory_toast("Navi")
        return f"I'll remember that alias: {alias_payload['term']} means {alias_payload['canonical']}."
    db.user_memory_add(
        kind="taught",
        content=body,
        source="teach_navi",
        confidence=1.0,
        approval_status="approved",
        json_data={"explicit": True},
    )
    _emit_teach_memory_toast("Navi")
    preview = body if len(body) <= 120 else body[:117] + "..."
    return f"I'll remember that: {preview}"


def store_teach_memory(db, message: str) -> str | None:
    parsed = parse_teach_target_command(message)
    if not parsed:
        return None
    target, body = parsed
    if str(target).strip().lower() == "navi":
        return store_teach_navi_memory(db, message)
    agent = None
    try:
        agent = db.agent_resolve_by_name(target)
    except Exception:
        agent = None
    if not agent:
        return None
    agent_code = str(agent.get("code") or "").strip().lower()
    display_name = str(agent.get("display_name") or agent_code or target).strip() or str(target).strip()
    alias_payload = parse_alias_memory(body)
    if alias_payload:
        db.agent_memory_add(
            agent_code=agent_code,
            kind="alias",
            content=alias_payload["content"],
            source="teach_agent",
            confidence=1.0,
            approval_status="approved",
            json_data={"explicit": True, "alias": alias_payload, "target_agent": agent_code},
        )
        _emit_teach_memory_toast(display_name)
        return f"I'll remember that for {display_name}: {alias_payload['term']} means {alias_payload['canonical']}."
    db.agent_memory_add(
        agent_code=agent_code,
        kind="taught",
        content=body,
        source="teach_agent",
        confidence=1.0,
        approval_status="approved",
        json_data={"explicit": True, "target_agent": agent_code},
    )
    _emit_teach_memory_toast(display_name)
    preview = body if len(body) <= 120 else body[:117] + "..."
    return f"I'll remember that for {display_name}: {preview}"


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
            scope = alias_payload.get("scope") or {}
            if isinstance(scope, dict) and scope:
                line += " Scope: " + ", ".join(f"{k}={v}" for k, v in scope.items()) + "."
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
    rows = [row for row in _dedupe_rows(rows, max(limit, 12)) if int(row[0]) not in alias_ids]
    rows = _semantic_rerank_rows(text, rows, limit=limit)
    entity_refs = infer_entity_memory_refs(db, text)
    entity_sections: list[str] = []
    for ref in entity_refs[:4]:
        try:
            entity_rows = db.user_memory_search_by_entity(
                entity_type=ref.get("entity_type") or "",
                entity_key=ref.get("entity_key") or "",
                query=text,
                approval_status="approved",
                limit=3,
            )
        except Exception as exc:
            logger.debug("entity memory lookup failed: %s", exc)
            entity_rows = []
        if not entity_rows:
            continue
        lines = _format_generic_memory_lines(_semantic_rerank_rows(text, entity_rows, limit=3))
        entity_sections.append(f"Relevant {ref.get('entity_type')} memory for {ref.get('label')}:\n" + "\n".join(lines))
    if not rows and not alias_rows:
        return "\n\n".join(section for section in entity_sections if section.strip())
    sections: list[str] = []
    if alias_rows:
        sections.append("Approved aliases / glossary:\n" + "\n".join(_format_alias_memory_lines(alias_rows)))
    if rows:
        sections.append("Relevant durable user memory:\n" + "\n".join(_format_generic_memory_lines(rows)))
    sections.extend(entity_sections)
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
    entity_refs: list[dict] | None = None,
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
                '{"facts":["..."],"preferences":["..."],"aliases":[{"term":"...","canonical":"...","synonyms":["..."],"scope":{"client":"..."}}]}. '
                "Aliases may also be simple strings if structure is unclear."
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
            item_json = dict(base_metadata)
            if kind == "alias":
                alias_payload = _normalize_alias_payload(value)
                if alias_payload:
                    content = alias_payload["content"]
                    item_json["alias"] = alias_payload
                    item_json["normalized"] = True
                else:
                    content = str(value or "").strip()
            else:
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
                    "approval_status": "pending",
                    "json_data": item_json,
                    "entity_refs": list(entity_refs or []),
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
    entity_refs = infer_entity_memory_refs(db, user_message)
    metadata = build_auto_memory_metadata(
        session_id=session_id,
        chat_id=chat_id,
        route=route,
        user_message=user_message,
        assistant_message=assistant_message,
        entity_refs=entity_refs,
    )
    items = extract_user_memory_items(
        user_message=user_message,
        assistant_message=assistant_message,
        llm_callable=llm_callable,
        metadata=metadata,
        entity_refs=entity_refs,
    )
    if not items:
        return 0
    try:
        return int(db.user_memory_add_many(items=items))
    except Exception as exc:
        logger.debug("user_memory writeback failed: %s", exc)
        return 0
