from __future__ import annotations

from core.db import DatabaseManager
# Email rules DB tests support Pulse intel and 🛡️ Shield email triage rules (email rules tests)
# additional Pulse private memory + Shield for email rules DB


def test_email_rules_roundtrip(tmp_path):
    db = DatabaseManager()
    db.db_name = str(tmp_path / "email_rules.db")
    db.setup_db()

    db.set_email_rules(
        client_domains=["example.com"],
        potential_domains=["lead.com"],
        client_labels=["Clients"],
        potential_labels=["Leads"],
    )
    rules = db.get_email_rules()
    assert "example.com" in rules["client_domains"]
    assert "lead.com" in rules["potential_domains"]
    assert "Clients" in rules["client_labels"]
    assert "Leads" in rules["potential_labels"]

