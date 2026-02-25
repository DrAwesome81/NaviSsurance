from __future__ import annotations

from gui.dashboard_tab import DashboardTab


class _NewsDbStub:
    def __init__(self):
        self._seen: set[tuple[str, str | None]] = set()
        self.saved: list[tuple[str, str, str | None, str | None, str | None]] = []

    def check_news_exists(self, title, url):
        return (str(title), url) in self._seen

    def store_news_item(self, title, content, url=None, source=None, published_date=None):
        key = (str(title), url)
        self._seen.add(key)
        self.saved.append((str(title), str(content), url, source, published_date))
        return True


def _dash_with_stub() -> DashboardTab:
    d = DashboardTab.__new__(DashboardTab)
    d.db = _NewsDbStub()
    return d


def test_is_valid_news_item_rejects_malformed_short_entries():
    d = _dash_with_stub()
    assert not d.is_valid_news_item("```bad", "valid enough content here")
    assert not d.is_valid_news_item("tiny", "valid enough content here")
    assert not d.is_valid_news_item("Valid title long enough", "short")
    assert d.is_valid_news_item("Valid title long enough", "This is sufficiently long content for validation.")


def test_is_valid_news_url_basic_rules():
    d = _dash_with_stub()
    assert d.is_valid_news_url("https://example.com/article")
    assert d.is_valid_news_url("http://example.org/path")
    assert not d.is_valid_news_url("example.com/article")
    assert not d.is_valid_news_url("https://x")


def test_process_and_store_news_parses_json_and_skips_duplicates():
    d = _dash_with_stub()
    payload = """
[
  {"title":"FDA issues AI guidance update","content":"Detailed policy update for medtech teams.","url":"https://example.com/a","source":"Example","published_date":"2026-02-24"},
  {"title":"FDA issues AI guidance update","content":"Duplicate title/url should skip.","url":"https://example.com/a","source":"Example","published_date":"2026-02-24"},
  {"title":"Bad","content":"Too short content","url":"https://example.com/b","source":"Example","published_date":"2026-02-24"}
]
""".strip()
    d.process_and_store_news(payload)

    # First valid item saved, duplicate skipped, malformed skipped.
    assert len(d.db.saved) == 1
    title, content, url, source, published_date = d.db.saved[0]
    assert "FDA issues AI guidance update" in title
    assert "policy update" in content
    assert source == "Example"
    assert published_date == "2026-02-24"


def test_process_and_store_news_cleans_invalid_url_to_none():
    d = _dash_with_stub()
    payload = """
[
  {"title":"Regulatory milestone reached by startup","content":"Long enough content to be valid for storage.","url":"not-a-url (source)","source":"Wire","published_date":"2026-02-20"}
]
""".strip()
    d.process_and_store_news(payload)
    assert len(d.db.saved) == 1
    _, _, url, _, _ = d.db.saved[0]
    assert url is None
