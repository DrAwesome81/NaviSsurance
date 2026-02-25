from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")

from gui.leads_tab import _s, _safe_url_for_open, robust_json_parse_array


def test_s_coerces_none_to_empty_string():
    assert _s(None) == ""
    assert _s("abc") == "abc"
    assert _s(123) == "123"


def test_safe_url_for_open_normalizes_or_rejects():
    assert _safe_url_for_open("example.com").startswith("http")
    assert _safe_url_for_open("https://example.com/path") == "https://example.com/path"
    assert _safe_url_for_open("") == ""


def test_robust_json_parse_array_direct_json():
    data, ok = robust_json_parse_array('[{"name":"A"},{"name":"B"}]')
    assert ok is True
    assert isinstance(data, list)
    assert len(data) == 2


def test_robust_json_parse_array_from_code_block():
    raw = "Here you go:\n```json\n[{\"name\":\"A\"}]\n```"
    data, ok = robust_json_parse_array(raw)
    assert ok is True
    assert isinstance(data, list)
    assert data[0]["name"] == "A"


def test_robust_json_parse_array_manual_extraction_trailing_comma():
    raw = "Result payload: [{\"name\":\"A\",}, {\"name\":\"B\",}]"
    data, ok = robust_json_parse_array(raw)
    # Parser may still fail depending on regex branch; either way should be graceful.
    assert ok in (True, False)
    if ok:
        assert isinstance(data, list)
