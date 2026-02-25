from __future__ import annotations

from gui.dashboard_tab import DashboardTab


def _dash() -> DashboardTab:
    return DashboardTab.__new__(DashboardTab)


def test_parse_published_date_supports_common_formats():
    d = _dash()
    assert d.parse_published_date("2026-02-24") is not None
    assert d.parse_published_date("February 24, 2026") is not None
    assert d.parse_published_date("2026-02-24T10:20:30Z") is not None
    assert d.parse_published_date("") is None


def test_recent_heuristics_include_recent_exclude_old():
    d = _dash()
    assert d.is_likely_recent_by_heuristics("today")
    assert d.is_likely_recent_by_heuristics("approximately 2 days ago")
    assert d.is_likely_recent_by_heuristics("2025-09-10")
    assert not d.is_likely_recent_by_heuristics("2023-01-05")


def test_sort_news_by_date_prefers_newer_items():
    d = _dash()
    items = [
        ("Old", "content", "https://a", "src", "2024-01-01", "2024-01-01 00:00:00"),
        ("New", "content", "https://b", "src", "2026-01-01", "2026-01-01 00:00:00"),
        ("NoPublished", "content", "https://c", "src", None, "2025-12-01 00:00:00"),
    ]
    out = d.sort_news_by_date(items)
    titles = [row[0] for row in out]
    assert titles[0] == "New"


def test_format_display_date_cleans_prefixes():
    d = _dash()
    # Parsed date path
    assert d.format_display_date("2026-02-24").startswith("February")
    # Prefix stripping fallback path
    txt = d.format_display_date("Published: approximately this week")
    assert "Published:" not in txt
