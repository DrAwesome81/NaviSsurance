from __future__ import annotations

import sqlite3

from core.db import DatabaseManager


def test_upsert_lead_sanitizes_linkedin_url(tmp_path):
    db = DatabaseManager()
    db.db_name = str(tmp_path / "leads.db")
    db.setup_db()

    lead_id = db.upsert_lead(
        {
            "name": "Jane Doe",
            "company": "Acme",
            "title": "VP",
            "rationale": "test",
            "message": "hi",
            "linkedin_url": "linkedin.com/in/jane-doe",
            "company_url": "acme.com",
            "sources": ["https://example.com/a"],
            "signals": [],
        }
    )
    assert lead_id > 0

    leads = db.list_leads(limit=10)
    row = next(l for l in leads if int(l["id"]) == int(lead_id))
    assert row["linkedin_url"].startswith("https://")
    assert "linkedin.com/in/" in row["linkedin_url"]
    assert row["company_url"].startswith("https://")


def test_list_leads_repairs_triple_slash_urls(tmp_path):
    db = DatabaseManager()
    db.db_name = str(tmp_path / "leads2.db")
    db.setup_db()

    # Insert a legacy-ish malformed URL directly.
    with sqlite3.connect(db.db_name) as conn:
        conn.execute(
            """
            INSERT INTO leads (lead_key, company_key, name, company, title, linkedin_url, company_url, rationale, message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "li:https:///linkedin.com/in/x",
                "acme",
                "X",
                "Acme",
                "CTO",
                "https:///linkedin.com/in/x",
                "https:///acme.com",
                "r",
                "m",
            ),
        )
        conn.commit()

    leads = db.list_leads(limit=10)
    assert leads[0]["linkedin_url"].startswith("https://")
    assert "https:///" not in leads[0]["linkedin_url"]

