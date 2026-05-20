import os
import sqlite3
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from core.user_memory import (
    auto_store_user_memory,
    build_user_memory_context,
    extract_user_memory_items,
    parse_alias_memory,
    parse_teach_navi_command,
    store_teach_navi_memory,
)
# User memory tests support promotion from Pulse private agent_memory and 🛡️ Shield security context (user memory tests)
# additional Pulse private memory + Shield for user memory tests


def test_parse_teach_navi_command():
    assert parse_teach_navi_command("Teach Navi: I prefer concise bullets.") == "I prefer concise bullets."
    assert parse_teach_navi_command("hello") is None


def test_parse_alias_memory_supports_explicit_alias_phrasings():
    alias = parse_alias_memory("Q-sub means quality submission.")
    assert alias is not None
    assert alias["term"] == "Q-sub"
    assert alias["canonical"] == "quality submission"
    assert alias["content"] == "Q-sub means quality submission."

    alias = parse_alias_memory("CAPA = corrective and preventive action")
    assert alias is not None
    assert alias["term"] == "CAPA"
    assert alias["canonical"] == "corrective and preventive action"

    assert parse_alias_memory("I prefer concise bullets.") is None


def test_store_teach_navi_memory_normalizes_explicit_aliases():
    captured = []
    db = SimpleNamespace(user_memory_add=lambda **kw: captured.append(kw) or 1)

    out = store_teach_navi_memory(db, "Teach Navi: Q-sub means quality submission.")

    assert "I'll remember that alias" in out
    assert captured[0]["kind"] == "alias"
    assert captured[0]["content"] == "Q-sub means quality submission."
    assert captured[0]["approval_status"] == "approved"
    assert captured[0]["json_data"]["alias"]["term"] == "Q-sub"


def test_parse_alias_memory_supports_synonyms_and_scope_suffixes():
    alias = parse_alias_memory(
        "Q-sub means quality submission; synonyms: quality sub, submission memo; scope: client:Abbott"
    )
    assert alias is not None
    assert alias["term"] == "Q-sub"
    assert alias["canonical"] == "quality submission"
    assert alias["synonyms"] == ["quality sub", "submission memo"]
    assert alias["scope"] == {"client": "Abbott"}


def test_user_memory_add_search_recent_and_schema():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        import config as config_mod
        import core.db as core_db

        with patch.object(config_mod, "DATABASE_PATH", path):
            with patch.object(core_db, "DATABASE_PATH", path):
                db = core_db.DatabaseManager()
                assert db.current_schema_version >= 19

                mid = db.user_memory_add(
                    kind="preference",
                    content="Dr. Adam prefers concise bullets.",
                    source="teach_navi",
                    confidence=1.0,
                    approval_status="approved",
                )
                assert mid

                hits = db.user_memory_search(query="concise bullets", limit=10)
                assert len(hits) >= 1
                assert any("concise bullets" in (row[2] or "").lower() for row in hits)

                recent = db.user_memory_recent(limit=5)
                assert recent
                assert recent[0][1] == "preference"

                with sqlite3.connect(path) as conn:
                    tables = {
                        row[0]
                        for row in conn.execute(
                            "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual table')"
                        ).fetchall()
                    }
                assert "user_memory" in tables
                assert "user_memory_fts" in tables
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_build_user_memory_context_combines_search_and_recent():
    db = SimpleNamespace(
        user_memory_search=lambda **kw: [
            (1, "preference", "Prefer concise bullets.", "teach_navi", 1.0, "approved", None, "now", "now"),
        ],
        user_memory_recent=lambda **kw: [
            (2, "alias", "Q-sub means quality submission.", "teach_navi", 0.65, "approved", None, "now", "now"),
        ],
    )

    out = build_user_memory_context(db, "draft a reply", limit=5, recent_limit=2)

    assert "Relevant durable user memory" in out
    assert "Prefer concise bullets." in out
    assert "Q-sub means quality submission." in out


def test_build_user_memory_context_prioritizes_structured_aliases():
    db = SimpleNamespace(
        user_memory_alias_search=lambda **kw: [
            (
                7,
                "alias",
                "Q-sub means quality submission.",
                "teach_navi",
                1.0,
                "approved",
                '{"alias":{"term":"Q-sub","canonical":"quality submission","synonyms":["quality sub"],"scope":{"client":"Abbott"}}}',
                "now",
                "now",
            ),
        ],
        user_memory_alias_recent=lambda **kw: [],
        user_memory_search=lambda **kw: [
            (1, "preference", "Prefer concise bullets.", "teach_navi", 1.0, "approved", None, "now", "now"),
        ],
        user_memory_recent=lambda **kw: [],
    )

    out = build_user_memory_context(db, "Draft a Q-sub reply.", limit=5, recent_limit=2)

    assert "Approved aliases / glossary" in out
    assert "Q-sub means quality submission." in out
    assert "Synonyms: quality sub." in out
    assert "Scope: client=Abbott." in out
    assert "Relevant durable user memory" in out


def test_user_memory_delete_removes_entry():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        import config as config_mod
        import core.db as core_db

        with patch.object(config_mod, "DATABASE_PATH", path):
            with patch.object(core_db, "DATABASE_PATH", path):
                db = core_db.DatabaseManager()
                mid = db.user_memory_add(
                    kind="fact",
                    content="Adam prefers local-first tools.",
                    source="teach_navi",
                    approval_status="approved",
                )
                assert mid
                assert db.user_memory_delete(mid) is True
                assert not db.user_memory_recent(limit=10)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_user_memory_update_persists_changes():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        import config as config_mod
        import core.db as core_db

        with patch.object(config_mod, "DATABASE_PATH", path):
            with patch.object(core_db, "DATABASE_PATH", path):
                db = core_db.DatabaseManager()
                mid = db.user_memory_add(
                    kind="fact",
                    content="Adam prefers local-first tools.",
                    source="teach_navi",
                    confidence=1.0,
                    approval_status="approved",
                )
                assert mid
                ok = db.user_memory_update(
                    mid,
                    kind="preference",
                    content="Adam prefers concise bullets.",
                    source="manual",
                    confidence=0.8,
                    approval_status="approved",
                    json_data='{"edited": true}',
                )
                assert ok is True
                row = db.user_memory_recent(limit=1)[0]
                assert row[1] == "preference"
                assert row[2] == "Adam prefers concise bullets."
                assert row[3] == "manual"
                assert float(row[4]) == 0.8
                assert row[5] == "approved"
                assert "edited" in (row[6] or "")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_user_memory_count_filters_by_status():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        import config as config_mod
        import core.db as core_db

        with patch.object(config_mod, "DATABASE_PATH", path):
            with patch.object(core_db, "DATABASE_PATH", path):
                db = core_db.DatabaseManager()
                db.user_memory_add(
                    kind="fact",
                    content="Approved memory",
                    source="teach_navi",
                    confidence=1.0,
                    approval_status="approved",
                )
                db.user_memory_add(
                    kind="fact",
                    content="Pending memory",
                    source="auto_chat",
                    confidence=0.5,
                    approval_status="pending",
                )
                db.user_memory_add(
                    kind="alias",
                    content="Rejected memory",
                    source="auto_chat",
                    confidence=0.4,
                    approval_status="rejected",
                )

                assert db.user_memory_count() == 3
                assert db.user_memory_count(approval_status="pending") == 1
                assert db.user_memory_count(approval_status="approved") == 1
                assert db.user_memory_count(kind="fact") == 2
                assert db.user_memory_count(kind="fact", approval_status="pending") == 1
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_pending_auto_memory_is_not_in_prompt_context():
    calls = []

    db = SimpleNamespace(
        user_memory_search=lambda **kw: calls.append(("search", kw)) or [],
        user_memory_recent=lambda **kw: calls.append(("recent", kw)) or [],
    )

    out = build_user_memory_context(db, "draft a reply", limit=5, recent_limit=2)

    assert out == ""
    assert calls[0][1]["approval_status"] == "approved"
    assert calls[1][1]["approval_status"] == "approved"


def test_extract_user_memory_items_normalizes_alias_json():
    items = extract_user_memory_items(
        user_message="Around here, Q-sub means quality submission.",
        assistant_message="Understood.",
        llm_callable=lambda messages, session_id: '{"aliases":[{"term":"Q-sub","canonical":"quality submission","synonyms":["quality sub"],"scope":{"client":"Abbott"}}]}',
        metadata={"source_session_id": "cos_7", "chat_id": 7, "route": "chief_of_staff_tab"},
    )

    assert len(items) == 1
    assert items[0]["kind"] == "alias"
    assert items[0]["content"] == "Q-sub means quality submission."
    assert items[0]["json_data"]["alias"]["term"] == "Q-sub"
    assert items[0]["json_data"]["alias"]["synonyms"] == ["quality sub"]
    assert items[0]["json_data"]["alias"]["scope"] == {"client": "Abbott"}
    assert items[0]["json_data"]["source_session_id"] == "cos_7"
    assert items[0]["json_data"]["chat_id"] == 7
    assert items[0]["json_data"]["route"] == "chief_of_staff_tab"


def test_auto_store_user_memory_adds_provenance_to_pending_rows():
    captured = []
    db = SimpleNamespace(user_memory_add_many=lambda *, items: captured.extend(items) or len(items))

    added = auto_store_user_memory(
        db,
        user_message="I prefer concise bullets in client updates.",
        assistant_message="Understood.",
        llm_callable=lambda messages, session_id: '{"preferences":["Prefer concise bullets in client updates."]}',
        session_id="cos_7",
        chat_id=7,
        route="chief_of_staff_tab",
    )

    assert added == 1
    assert captured[0]["approval_status"] == "pending"
    assert captured[0]["source"] == "auto_chat"
    assert captured[0]["json_data"]["source_session_id"] == "cos_7"
    assert captured[0]["json_data"]["chat_id"] == 7
    assert captured[0]["json_data"]["route"] == "chief_of_staff_tab"
    assert captured[0]["json_data"]["extraction_version"] == "passive_memory_v2"
    assert "concise bullets" in captured[0]["json_data"]["user_message_preview"].lower()


def test_user_memory_alias_helpers_return_alias_rows():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        import config as config_mod
        import core.db as core_db

        with patch.object(config_mod, "DATABASE_PATH", path):
            with patch.object(core_db, "DATABASE_PATH", path):
                db = core_db.DatabaseManager()
                db.user_memory_add(
                    kind="alias",
                    content="Q-sub means quality submission.",
                    source="teach_navi",
                    confidence=1.0,
                    approval_status="approved",
                    json_data={"alias": {"term": "Q-sub", "canonical": "quality submission", "synonyms": ["quality sub"], "scope": {"client": "Abbott"}}},
                )
                db.user_memory_add(
                    kind="preference",
                    content="Prefer concise bullets.",
                    source="teach_navi",
                    confidence=1.0,
                    approval_status="approved",
                )

                hits = db.user_memory_alias_search(query="quality submission", approval_status="approved", limit=5)
                recent = db.user_memory_alias_recent(approval_status="approved", limit=5)

                assert len(hits) == 1
                assert hits[0][1] == "alias"
                assert len(recent) == 1
                assert recent[0][1] == "alias"
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_memory_reflection_upsert_and_recent():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        import config as config_mod
        import core.db as core_db
        from core.memory_reflection import build_memory_reflection

        with patch.object(config_mod, "DATABASE_PATH", path):
            with patch.object(core_db, "DATABASE_PATH", path):
                db = core_db.DatabaseManager()
                db.user_memory_add(
                    kind="alias",
                    content="Q-sub means quality submission.",
                    source="teach_navi",
                    confidence=1.0,
                    approval_status="approved",
                    json_data={"alias": {"term": "Q-sub", "canonical": "quality submission", "synonyms": ["quality sub"]}},
                )
                db.user_memory_add(
                    kind="preference",
                    content="Prefer concise bullets.",
                    source="teach_navi",
                    confidence=1.0,
                    approval_status="approved",
                )

                reflection = build_memory_reflection(
                    db,
                    scope="daily",
                    llm_callable=lambda messages, session_id: '{"summary":"Navi learned stable terminology and formatting preferences.","highlights":["Q-sub means quality submission.","Prefer concise bullets."]}',
                )

                assert reflection["id"] > 0
                row = db.memory_reflection_get(scope="daily", reflection_key=reflection["reflection_key"])
                assert row is not None
                assert "stable terminology" in str(row.get("summary_text") or "").lower()
                recent = db.memory_reflection_recent(scope="daily", limit=5)
                assert len(recent) == 1
                assert recent[0]["id"] == reflection["id"]
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
