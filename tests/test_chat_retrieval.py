import os
import tempfile
from unittest.mock import patch

from core.chat_retrieval import build_long_term_retrieval_context, ensure_session_chunk_summaries
# Retrieval tests validate long-term context for CoS/Pulse private memory and 🛡️ security-relevant chat history (retrieval tests)
# additional Pulse private memory + Shield for chat retrieval tests



def _db_for_temp_path(path: str):
    import config as config_mod
    import core.db as core_db

    with patch.object(config_mod, "DATABASE_PATH", path):
        with patch.object(core_db, "DATABASE_PATH", path):
            return core_db.DatabaseManager()


def test_conversation_chunk_schema_and_helpers():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = _db_for_temp_path(path)
        assert db.current_schema_version >= 21

        session_id = "cos_42"
        for idx in range(18):
            role = "user" if idx % 2 == 0 else "assistant"
            content = (
                "Let's discuss Jeff Cunningham and the quote timeline."
                if idx == 0
                else "We agreed to send Jeff the quote tomorrow morning."
                if idx == 1
                else f"Turn {idx}"
            )
            db.save_message(session_id, role, content)

        created = ensure_session_chunk_summaries(
            db,
            session_id,
            summarizer=lambda turns: {
                "summary": "Jeff Cunningham quote timeline and follow-up.",
                "key_decisions": ["Send Jeff the quote tomorrow morning."],
                "open_loops": ["Confirm final pricing."],
                "tags": ["Jeff Cunningham", "quote timeline"],
            },
        )

        assert created >= 1
        hits = db.conversation_chunk_summary_search(query="Jeff Cunningham", session_id=session_id, limit=5)
        assert hits
        chunk_id = int(hits[0][0])
        raw_turns = db.conversation_chunk_turns(chunk_id)
        assert raw_turns
        assert any("tomorrow morning" in str(content).lower() for _role, content, _ts in raw_turns)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_build_long_term_retrieval_context_prefers_chunk_summaries():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = _db_for_temp_path(path)
        session_id = "cos_42"
        messages = [
            ("user", "Let's discuss Jeff Cunningham and the quote timeline."),
            ("assistant", "We agreed to send Jeff the quote tomorrow morning."),
            ("user", "We should also confirm pricing."),
            ("assistant", "Yes, pricing confirmation is still open."),
            ("user", "Another turn"),
            ("assistant", "Another reply"),
            ("user", "Another turn 2"),
            ("assistant", "Another reply 2"),
            ("user", "Another turn 3"),
            ("assistant", "Another reply 3"),
            ("user", "Recent buffer 1"),
            ("assistant", "Recent buffer 2"),
            ("user", "Recent buffer 3"),
            ("assistant", "Recent buffer 4"),
        ]
        for role, content in messages:
            db.save_message(session_id, role, content)

        ensure_session_chunk_summaries(
            db,
            session_id,
            summarizer=lambda turns: {
                "summary": "Jeff Cunningham quote timeline and pricing follow-up.",
                "key_decisions": ["Send Jeff the quote tomorrow morning."],
                "open_loops": ["Confirm pricing."],
                "tags": ["Jeff Cunningham", "pricing"],
            },
        )

        context = build_long_term_retrieval_context(
            db,
            "What did we decide about Jeff?",
            session_id=session_id,
            chunk_limit=2,
            raw_turn_limit=4,
        )

        assert "Relevant older chat summaries (untrusted)" in context
        assert "Grounding turns from matched summaries (untrusted)" in context
        assert "tomorrow morning" in context
        assert "Confirm pricing." in context
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_build_long_term_retrieval_context_expands_alias_queries():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = _db_for_temp_path(path)
        session_id = "main_session"
        db.user_memory_add(
            kind="alias",
            content="Q-sub means quality submission.",
            source="teach_navi",
            approval_status="approved",
            json_data={"alias": {"term": "Q-sub", "canonical": "quality submission", "synonyms": []}},
        )
        for idx in range(14):
            role = "user" if idx % 2 == 0 else "assistant"
            content = "We finished the quality submission outline." if idx == 1 else f"Turn {idx}"
            db.save_message(session_id, role, content)

        ensure_session_chunk_summaries(
            db,
            session_id,
            summarizer=lambda turns: {
                "summary": "Discussion about the quality submission outline.",
                "key_decisions": [],
                "open_loops": [],
                "tags": ["quality submission"],
            },
        )

        context = build_long_term_retrieval_context(
            db,
            "What did we say about the Q-sub?",
            session_id=session_id,
        )

        assert "quality submission" in context.lower()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_build_long_term_retrieval_context_falls_back_to_raw_snippets():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = _db_for_temp_path(path)
        session_id = "cos_99"
        db.save_message(session_id, "user", "Let's discuss Jeff Cunningham and the quote timeline.")
        db.save_message(session_id, "assistant", "We agreed to send Jeff the quote tomorrow morning.")
        db.save_message(session_id, "user", "Thanks.")

        context = build_long_term_retrieval_context(
            db,
            "Jeff Cunningham quote timeline",
            session_id=session_id,
            chunk_limit=2,
            raw_turn_limit=4,
        )

        assert "Relevant older chat snippets (untrusted)" in context
        assert "tomorrow morning" in context
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
