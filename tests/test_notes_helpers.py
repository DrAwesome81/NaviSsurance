from __future__ import annotations

import os

import pytest

pytest.importorskip("PyQt6")

from gui.notes_tab import NoteTakingSystem, robust_json_parse


def test_robust_json_parse_extracts_json_block_with_noise():
    raw = 'prefix text {"formatted":"Cleaned note"} trailing text'
    data, ok = robust_json_parse(raw)
    assert ok is True
    assert isinstance(data, dict)
    assert data["formatted"] == "Cleaned note"


def test_robust_json_parse_cleans_trailing_commas():
    raw = '{"categories":{"Regulatory":[1,2,],},}'
    data, ok = robust_json_parse(raw)
    assert ok is True
    assert isinstance(data, dict)
    assert "categories" in data


def test_robust_json_parse_returns_plain_string_fallback():
    raw = "this is not json, but still useful"
    data, ok = robust_json_parse(raw)
    assert ok is True
    assert data == raw


@pytest.mark.parametrize(
    ("ts", "days", "expected"),
    [
        ("", 7, True),
        ("not-a-date", 30, True),
    ],
)
def test_note_ts_in_days_handles_invalid_and_empty(ts, days, expected):
    assert NoteTakingSystem._note_ts_in_days(ts, days) is expected


def test_note_ts_in_days_true_for_recent_timestamp():
    # Build timestamp from "now" to avoid flaky date boundary assumptions.
    from datetime import datetime

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    assert NoteTakingSystem._note_ts_in_days(ts, 1) is True


def test_note_ts_in_days_false_for_old_timestamp():
    from datetime import datetime, timedelta

    ts = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    assert NoteTakingSystem._note_ts_in_days(ts, 1) is False
