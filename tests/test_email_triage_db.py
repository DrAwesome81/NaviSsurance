from __future__ import annotations

import json
import sqlite3

from core.db import DatabaseManager


def test_email_triage_queries_and_archiving_roundtrip(tmp_path):
    db = DatabaseManager(db_name=str(tmp_path / "email_triage.db"))
    db.init_email_calendar_tables()

    client_id = db.client_create(name="Acme Corp", domains=["acme.com"])
    project_id = db.cos_insert_project(
        name="Acme QMS",
        client="Acme Corp",
        client_id=client_id,
        status="Active",
    )

    with sqlite3.connect(db.db_name) as conn:
        conn.execute(
            """
            INSERT INTO emails (
                id, sender, subject, timestamp, content, source, replied, is_client, is_potential,
                triage_status, importance_score, needs_attention, importance_reason_json, triage_source,
                client_id, cos_project_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "email-1",
                "Jane <jane@acme.com>",
                "Please review the QMS package",
                1_700_000_000,
                "Need your approval by end of day.",
                "gmail",
                0,
                1,
                0,
                "important",
                52,
                1,
                json.dumps(["Matched client domain.", "Contained action-oriented language."]),
                "rule",
                client_id,
                project_id,
            ),
        )
        conn.commit()

    rows = db.list_important_emails(limit=10, days=3650, include_triaged=False)
    assert len(rows) == 1
    assert rows[0]["client_name"] == "Acme Corp"
    assert rows[0]["project_name"] == "Acme QMS"
    assert rows[0]["importance_reasons"] == [
        "Matched client domain.",
        "Contained action-oriented language.",
    ]

    updated = db.update_email_triage(
        "email-1",
        triage_status="archived",
        triage_source="manual",
    )
    assert updated is True
    assert db.list_important_emails(limit=10, days=3650, include_triaged=False) == []


def test_client_project_and_meeting_linkage_persist(tmp_path):
    db = DatabaseManager(db_name=str(tmp_path / "meeting_linkage.db"))
    db.init_email_calendar_tables()

    client_id = db.client_create(name="Beta Medical", aliases=["Beta"])
    project_id = db.cos_insert_project(
        name="Beta Launch",
        client="Beta Medical",
        client_id=client_id,
        status="Active",
    )
    meeting_id = db.create_meeting_record(
        meeting_date="2026-03-26",
        meeting_with="Beta Medical",
        notes="Kickoff",
        client_id=client_id,
        cos_project_id=project_id,
        status="pending",
    )

    raw_project = db.cos_get_project(project_id)
    assert raw_project[-1] == client_id

    with sqlite3.connect(db.db_name) as conn:
        meeting_row = conn.execute(
            "SELECT client_id, cos_project_id FROM meeting_records WHERE id = ?",
            (meeting_id,),
        ).fetchone()

    assert meeting_row == (client_id, project_id)
