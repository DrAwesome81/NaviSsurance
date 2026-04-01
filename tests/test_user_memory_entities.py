from __future__ import annotations

from core.db import DatabaseManager
from core.user_memory import build_user_memory_context, infer_entity_memory_refs


def test_user_memory_entity_links_and_context(tmp_path):
    db = DatabaseManager(str(tmp_path / "memory_entities.db"))
    client_id = db.client_create(name="Acme Diagnostics")
    assert client_id > 0

    mem_id = db.user_memory_add(
        kind="fact",
        content="Acme prefers weekly Friday status updates.",
        source="teach_navi",
        entity_refs=[{"entity_type": "client", "entity_key": str(client_id), "label": "Acme Diagnostics"}],
    )
    assert mem_id > 0

    refs = infer_entity_memory_refs(db, "Prepare the Acme Diagnostics update.")
    assert any(ref["entity_type"] == "client" and ref["entity_key"] == str(client_id) for ref in refs)

    rows = db.user_memory_search_by_entity(
        entity_type="client",
        entity_key=str(client_id),
        query="weekly updates",
        approval_status="approved",
        limit=5,
    )
    assert rows
    assert "weekly Friday status updates" in rows[0][2]

    ctx = build_user_memory_context(db, "What do we know about Acme Diagnostics?")
    assert "Acme prefers weekly Friday status updates." in ctx
