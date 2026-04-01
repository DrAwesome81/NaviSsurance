from __future__ import annotations

from pathlib import Path

import pytest

import core.tools.browser as browser_tools


class _FakeLocator:
    def __init__(self, page):
        self.page = page

    def inner_text(self, timeout=None):
        self.page.recorded.append(("inner_text", timeout))
        return self.page.body_text

    def click(self, timeout=None):
        self.page.recorded.append(("click", timeout))

    def fill(self, value, timeout=None):
        self.page.recorded.append(("fill", value, timeout))

    def press(self, value, timeout=None):
        self.page.recorded.append(("press", value, timeout))


class _FakePage:
    def __init__(self, *, title="Example title", body_text="Visible body text"):
        self._title = title
        self.body_text = body_text
        self.url = ""
        self.recorded: list[tuple] = []

    def goto(self, url, wait_until=None, timeout=None):
        self.url = str(url)
        self.recorded.append(("goto", str(url), wait_until, timeout))

    def title(self):
        return self._title

    def locator(self, selector):
        self.recorded.append(("locator", selector))
        return _FakeLocator(self)

    def screenshot(self, path=None, full_page=True):
        self.recorded.append(("screenshot", str(path), bool(full_page)))
        Path(path).write_bytes(b"png")

    def wait_for_timeout(self, ms):
        self.recorded.append(("wait", int(ms)))


class _FakeBrowser:
    def __init__(self, page):
        self.page = page
        self.closed = False

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self, page):
        self.page = page
        self.executable_path = "fake-chromium"

    def launch(self, headless=True):
        self.page.recorded.append(("launch", bool(headless)))
        return _FakeBrowser(self.page)


class _FakePlaywrightContext:
    def __init__(self, page):
        self.chromium = _FakeChromium(page)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _fake_sync_playwright(page):
    return lambda: _FakePlaywrightContext(page)


def test_browser_fetch_tool_returns_structured_result(monkeypatch):
    page = _FakePage(body_text="Some visible text from the page")
    monkeypatch.setattr(browser_tools, "_playwright", lambda: _fake_sync_playwright(page))

    result = browser_tools.browser_fetch_tool("https://example.com")

    assert result.url == "https://example.com"
    assert result.title == "Example title"
    assert result.text_excerpt == "Some visible text from the page"
    assert result.screenshot_path is None
    assert result.metadata["wait_until"] == "networkidle"


def test_browser_snapshot_tool_writes_screenshot_and_metadata(monkeypatch, tmp_path):
    page = _FakePage(body_text="Snapshot body text")
    monkeypatch.setattr(browser_tools, "_playwright", lambda: _fake_sync_playwright(page))
    monkeypatch.setattr(browser_tools, "_browser_output_dir", lambda: str(tmp_path))

    result = browser_tools.browser_snapshot_tool(
        "https://example.com/report",
        screenshot_name="monthly report",
        full_page=False,
    )

    assert result.url == "https://example.com/report"
    assert result.title == "Example title"
    assert result.text_excerpt == "Snapshot body text"
    assert result.screenshot_path is not None
    assert result.screenshot_path.endswith(".png")
    assert Path(result.screenshot_path).exists()
    assert result.metadata["full_page"] is False


def test_browser_workflow_tool_records_executed_steps(monkeypatch, tmp_path):
    page = _FakePage(body_text="Workflow output")
    monkeypatch.setattr(browser_tools, "_playwright", lambda: _fake_sync_playwright(page))
    monkeypatch.setattr(browser_tools, "_browser_output_dir", lambda: str(tmp_path))

    result = browser_tools.browser_workflow_tool(
        "https://example.com/start",
        steps=[
            {"action": "click", "selector": "#start"},
            {"action": "fill", "selector": "#query", "value": "PCCP"},
            {"action": "press", "selector": "#query", "value": "Enter"},
            {"action": "wait", "ms": 250},
            {"action": "goto", "value": "https://example.com/final"},
        ],
        screenshot_name="workflow",
    )

    assert result.url == "https://example.com/final"
    assert result.text_excerpt == "Workflow output"
    assert result.screenshot_path is not None
    assert result.metadata["executed_steps"] == [
        "1:click",
        "2:fill",
        "3:press",
        "4:wait",
        "5:goto",
    ]


def test_browser_tools_reject_missing_url():
    with pytest.raises(ValueError, match="URL is required"):
        browser_tools.browser_fetch_tool("")

    with pytest.raises(ValueError, match="URL is required"):
        browser_tools.browser_snapshot_tool("")

    with pytest.raises(ValueError, match="URL is required"):
        browser_tools.browser_workflow_tool("", steps=[{"action": "wait", "ms": 1}])


def test_browser_workflow_requires_steps():
    with pytest.raises(ValueError, match="Workflow steps are required"):
        browser_tools.browser_workflow_tool("https://example.com", steps=[])


def test_browser_workflow_rejects_unknown_action(monkeypatch, tmp_path):
    page = _FakePage()
    monkeypatch.setattr(browser_tools, "_playwright", lambda: _fake_sync_playwright(page))
    monkeypatch.setattr(browser_tools, "_browser_output_dir", lambda: str(tmp_path))

    with pytest.raises(ValueError, match="Unsupported browser workflow action"):
        browser_tools.browser_workflow_tool(
            "https://example.com",
            steps=[{"action": "dance", "selector": "#nope"}],
        )
