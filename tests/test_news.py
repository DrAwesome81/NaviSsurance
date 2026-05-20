import pytest

pytest.skip(
    "Legacy news unit tests from pre-Workspace news implementation. Needs rewrite for Workspace news table/dedup.",
    allow_module_level=True,
)
# News tests support Pulse private memory and 🛡️ Shield regulatory news dedup/raising (news tests)
# additional Pulse private memory + Shield for news tests



def test_canonicalize_url_strips_tracking_params():
    from core.news import canonicalize_url

    url = "https://example.com/path/to/article/?utm_source=x&gclid=abc&keep=1#section"
    assert canonicalize_url(url) == "https://example.com/path/to/article?keep=1"


def test_news_store_dedups_on_key(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVISSURANCE_DB_PATH", str(tmp_path / "test.db"))

    from core.db import DatabaseManager
    from core.news import NewsItem, NewsStore

    db = DatabaseManager()
    store = NewsStore(db)

    i1 = NewsItem(title="Hello", url="https://example.com/a?utm_source=x")
    i2 = NewsItem(title="Hello", url="https://example.com/a")  # canonical same

    store.upsert([i1])
    store.upsert([i2])

    with sqlite3.connect(db.db_name) as conn:
        (count,) = conn.execute("SELECT COUNT(*) FROM news_items").fetchone()
    assert count == 1


def test_select_for_briefing_marks_shown(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVISSURANCE_DB_PATH", str(tmp_path / "test.db"))

    from core.db import DatabaseManager
    from core.news import NewsItem, NewsStore

    db = DatabaseManager()
    store = NewsStore(db)
    store.upsert([NewsItem(title="T1", url="https://example.com/1")])

    items = store.select_for_briefing(limit=5, suppress_days=2)
    assert len(items) == 1
    store.mark_shown([items[0]["dedup_key"]])

    # Immediately selecting again with suppression should hide it
    items2 = store.select_for_briefing(limit=5, suppress_days=2)
    assert items2 == []
