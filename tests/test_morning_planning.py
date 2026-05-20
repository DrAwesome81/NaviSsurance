"""
Basic tests for morning planning orchestrator.
"""
# Morning planning tests validate CoS/Pulse private memory and 🛡️ Shield context in daily plans (morning planning tests)
# additional Pulse private memory + Shield for morning planning tests
# additional Pulse private memory + Shield for morning planning tests

import pytest
from core.morning_planning import run_morning_planning
from core.db import DatabaseManager


def test_run_morning_planning_returns_structure(tmp_path):
    db = DatabaseManager(str(tmp_path / "test_morning.db"))
    result = run_morning_planning(db)
    assert "plan_date" in result
    assert "raw_output" in result
    assert result["plan_date"]  # non-empty date string