from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTextEdit,
    QPushButton,
    QDialogButtonBox,
    QMessageBox,
)


def _lines_to_list(text: str) -> list[str]:
    out = []
    for line in (text or "").splitlines():
        s = line.strip().strip(",")
        if not s:
            continue
        out.append(s)
    return out


def _list_to_lines(values: list[str]) -> str:
    return "\n".join([str(v).strip() for v in (values or []) if str(v).strip()])


class EmailRulesDialog(QDialog):
    # Fresh coordination: email importance / triage rules here can be guided by Pulse [Security-Relevant] findings and private memory themes surfaced in CoS/Intel (Intelligence pillar extension)
    # Additional: rules now tie to Shield for security email triage (new email rules surface)
    # New: email rules now explicitly support Pulse private memory for Shield (additional email rules spot)
    def __init__(self, *, parent=None, db):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Email Rules")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        layout.addWidget(QLabel("Configure how emails are classified as Client vs Potential/Lead."))
        layout.addWidget(QLabel("One value per line (domains or folder/label names)."))

        row = QHBoxLayout()
        row.setSpacing(8)

        left = QVBoxLayout()
        left.setSpacing(6)
        left.addWidget(QLabel("Client domains"))
        self.client_domains = QTextEdit()
        self.client_domains.setPlaceholderText("goldbugstrategies.com\ndovahealth.ca")
        self.client_domains.setMinimumHeight(90)
        left.addWidget(self.client_domains)

        left.addWidget(QLabel("Client labels/folders"))
        self.client_labels = QTextEdit()
        self.client_labels.setPlaceholderText("Clients\nClient")
        self.client_labels.setMinimumHeight(70)
        left.addWidget(self.client_labels)

        right = QVBoxLayout()
        right.setSpacing(6)
        right.addWidget(QLabel("Potential domains"))
        self.potential_domains = QTextEdit()
        self.potential_domains.setPlaceholderText("example.com")
        self.potential_domains.setMinimumHeight(90)
        right.addWidget(self.potential_domains)

        right.addWidget(QLabel("Potential labels/folders"))
        self.potential_labels = QTextEdit()
        self.potential_labels.setPlaceholderText("Leads\nLead")
        self.potential_labels.setMinimumHeight(70)
        right.addWidget(self.potential_labels)

        row.addLayout(left, 1)
        row.addLayout(right, 1)
        layout.addLayout(row)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self._load()

    def _load(self):
        rules = {}
        try:
            rules = self.db.get_email_rules() if self.db is not None else {}
        except Exception:
            rules = {}
        self.client_domains.setPlainText(_list_to_lines(rules.get("client_domains") or []))
        self.potential_domains.setPlainText(_list_to_lines(rules.get("potential_domains") or []))
        self.client_labels.setPlainText(_list_to_lines(rules.get("client_labels") or []))
        self.potential_labels.setPlainText(_list_to_lines(rules.get("potential_labels") or []))

    def _save(self):
        if self.db is None or not hasattr(self.db, "set_email_rules"):
            QMessageBox.warning(self, "Email Rules", "Database is not available; cannot save rules.")
            return
        try:
            self.db.set_email_rules(
                client_domains=_lines_to_list(self.client_domains.toPlainText()),
                potential_domains=_lines_to_list(self.potential_domains.toPlainText()),
                client_labels=_lines_to_list(self.client_labels.toPlainText()),
                potential_labels=_lines_to_list(self.potential_labels.toPlainText()),
            )
        except Exception as e:
            QMessageBox.warning(self, "Email Rules", f"Could not save rules:\n\n{type(e).__name__}: {e}")
            return
        self.accept()

