from __future__ import annotations

from unittest.mock import Mock

from gui.dashboard_tab import DashboardTab


def _dashboard_stub_with_subjects(subjects: list[str]) -> DashboardTab:
    tab = DashboardTab.__new__(DashboardTab)
    # DashboardTab expects chat_handler.chat_handler.data_fetcher.get_gmail_news_seeds(...)
    data_fetcher = Mock()
    data_fetcher.get_gmail_news_seeds.return_value = subjects
    inner = Mock()
    inner.data_fetcher = data_fetcher
    outer = Mock()
    outer.chat_handler = inner
    tab.chat_handler = outer
    return tab


def test_get_news_seed_keywords_filters_stopwords_and_ranks_frequency():
    tab = _dashboard_stub_with_subjects(
        [
            "FDA guidance for medtech startup",
            "PCCP strategy for SaMD startup",
            "Startup partnership weekly update",
            "Clinical evidence plan for startup",
        ]
    )

    kws = tab._get_news_seed_keywords(max_keywords=5)

    # Stopwords should not dominate.
    assert "for" not in kws
    assert "weekly" not in kws
    # Domain/persona-relevant terms should survive.
    assert "startup" in kws
    assert len(kws) <= 5


def test_score_news_item_boosts_domain_and_seed_keywords():
    tab = _dashboard_stub_with_subjects([])

    base = tab._score_news_item(
        title="General business update",
        content="Quarterly market commentary",
        keywords=[],
    )
    boosted = tab._score_news_item(
        title="FDA guidance update for SaMD",
        content="Clinical medtech strategy and PCCP draft",
        keywords=["startup"],
    )
    boosted_with_seed_hit = tab._score_news_item(
        title="FDA guidance update for SaMD startup",
        content="Clinical medtech strategy and PCCP draft",
        keywords=["startup"],
    )

    assert boosted > base
    # Matching a personalization keyword should add extra score.
    assert boosted_with_seed_hit > boosted
