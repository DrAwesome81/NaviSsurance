from __future__ import annotations

from core.db import DatabaseManager
from core.email_importance import evaluate_email_importance
# Email importance tests support Pulse intel triage and 🛡️ Shield security in email scoring (email importance tests)


def test_evaluate_email_importance_matches_client_contact_and_project(tmp_path):
    db = DatabaseManager(db_name=str(tmp_path / "importance.db"))
    db.init_email_calendar_tables()

    client_id = db.client_create(
        name="Acme Corp",
        aliases=["Acme"],
        domains=["acme.com"],
    )
    db.client_contact_create(
        client_id=client_id,
        name="Jane Founder",
        email="jane@acme.com",
        role="CEO",
    )
    project_id = db.cos_insert_project(
        name="Mercury Submission",
        client="Acme Corp",
        client_id=client_id,
        status="Active",
    )

    result = evaluate_email_importance(
        db=db,
        sender="Jane Founder <jane@acme.com>",
        subject="Mercury Submission review needed today",
        content="Can you please review the package and approve it by end of day?",
        folder="Inbox",
        source="gmail",
        is_client=1,
        replied=0,
    )

    assert result["needs_attention"] == 1
    assert result["triage_status"] == "important"
    assert result["matched_client_id"] == client_id
    assert result["matched_project_id"] == project_id
    assert result["is_urgent"] is True
    assert result["score"] >= 25
    assert result["reasons"]


def test_evaluate_email_importance_downranks_low_signal_marketing(tmp_path):
    db = DatabaseManager(db_name=str(tmp_path / "importance_low_signal.db"))
    db.init_email_calendar_tables()

    result = evaluate_email_importance(
        db=db,
        sender="noreply@vendor.com",
        subject="Monthly newsletter and webinar digest",
        content="Manage preferences and unsubscribe from this marketing list.",
        folder="Inbox",
        source="gmail",
        replied=0,
    )

    assert result["needs_attention"] == 0
    assert result["triage_status"] == "new"
    assert result["score"] < 25

# additional Pulse private memory + Shield for email importance tests
