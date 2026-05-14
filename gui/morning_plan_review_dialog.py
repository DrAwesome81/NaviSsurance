"""
MorningPlanReviewDialog - review and approve the generated morning plan.
"""

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit, QLabel
from PyQt6.QtCore import Qt
from gui.morning_plan_view import MorningPlanView


class MorningPlanReviewDialog(QDialog):
    def __init__(self, plan_result: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Morning Plan Review")
        self.setMinimumSize(900, 620)
        self.plan_result = plan_result

        layout = QVBoxLayout(self)

        header = QLabel("Review Today's Proposed Plan")
        header.setStyleSheet("font-size: 16px; font-weight: 600; color: #e8eaed;")
        layout.addWidget(header)

        self.view = MorningPlanView()
        # In real use, populate with existing events + proposed blocks from plan_result
        layout.addWidget(self.view)

        # Simple triage text area
        triage = QTextEdit()
        triage.setPlainText(plan_result.get("raw_output", "")[:2000])
        triage.setReadOnly(True)
        layout.addWidget(triage)

        btn_row = QHBoxLayout()
        regen_btn = QPushButton("Regenerate")
        regen_btn.clicked.connect(self.reject)  # placeholder
        approve_btn = QPushButton("Approve Plan")
        approve_btn.clicked.connect(self.accept)
        btn_row.addWidget(regen_btn)
        btn_row.addStretch()
        btn_row.addWidget(approve_btn)
        layout.addLayout(btn_row)

    def get_approved_plan(self) -> dict:
        return self.plan_result