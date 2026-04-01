from __future__ import annotations

import os
import re
from functools import lru_cache
from datetime import datetime, UTC

from config import ARTIFACTS_DIR
from core.agent_schemas import BrowserToolResult


def _slugify(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip("-")
    return text[:80] or "page"


def _excerpt(text: str, *, limit: int = 1500) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= int(limit):
        return value
    return value[: max(0, int(limit) - 3)].rstrip() + "..."


def _browser_output_dir() -> str:
    path = os.path.join(ARTIFACTS_DIR, "browser")
    os.makedirs(path, exist_ok=True)
    return path


def _playwright():
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - import path depends on local install
        raise RuntimeError("Playwright is not installed. Run `playwright install chromium` after dependency install.") from exc
    return sync_playwright


def browser_tools_available() -> tuple[bool, str]:
    try:
        return _browser_tools_available_cached()
    except Exception as exc:
        return False, str(exc)


@lru_cache(maxsize=1)
def _browser_tools_available_cached() -> tuple[bool, str]:
    sync_playwright = _playwright()
    try:
        with sync_playwright() as p:
            executable = str(p.chromium.executable_path or "").strip()
    except Exception as exc:
        return False, str(exc)
    if not executable:
        return False, "Playwright Chromium executable is not available."
    if not os.path.exists(executable):
        return False, f"Playwright Chromium executable is missing: {executable}"
    return True, "available"


def browser_fetch_tool(url: str, *, wait_until: str = "networkidle", timeout_ms: int = 30_000) -> BrowserToolResult:
    target = str(url or "").strip()
    if not target:
        raise ValueError("URL is required for browser_fetch.")
    sync_playwright = _playwright()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(target, wait_until=wait_until, timeout=int(timeout_ms))
        title = page.title()
        body_text = page.locator("body").inner_text(timeout=int(timeout_ms))
        final_url = page.url
        browser.close()
    return BrowserToolResult(
        url=final_url,
        title=title or None,
        text_excerpt=_excerpt(body_text),
        metadata={"wait_until": wait_until, "timeout_ms": int(timeout_ms)},
    )


def browser_snapshot_tool(
    url: str,
    *,
    screenshot_name: str | None = None,
    wait_until: str = "networkidle",
    timeout_ms: int = 30_000,
    full_page: bool = True,
) -> BrowserToolResult:
    target = str(url or "").strip()
    if not target:
        raise ValueError("URL is required for browser_snapshot.")
    sync_playwright = _playwright()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{stamp}_{_slugify(screenshot_name or target)}.png"
    output_path = os.path.join(_browser_output_dir(), filename)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(target, wait_until=wait_until, timeout=int(timeout_ms))
        title = page.title()
        body_text = page.locator("body").inner_text(timeout=int(timeout_ms))
        page.screenshot(path=output_path, full_page=bool(full_page))
        final_url = page.url
        browser.close()
    return BrowserToolResult(
        url=final_url,
        title=title or None,
        text_excerpt=_excerpt(body_text),
        screenshot_path=output_path,
        metadata={"wait_until": wait_until, "timeout_ms": int(timeout_ms), "full_page": bool(full_page)},
    )


def browser_workflow_tool(
    url: str,
    *,
    steps: list[dict],
    screenshot_name: str | None = None,
    timeout_ms: int = 30_000,
) -> BrowserToolResult:
    target = str(url or "").strip()
    if not target:
        raise ValueError("URL is required for browser_workflow.")
    if not isinstance(steps, list) or not steps:
        raise ValueError("Workflow steps are required for browser_workflow.")
    sync_playwright = _playwright()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{stamp}_{_slugify(screenshot_name or target)}.png"
    output_path = os.path.join(_browser_output_dir(), filename)
    executed: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(target, wait_until="domcontentloaded", timeout=int(timeout_ms))
        for idx, step in enumerate(steps, start=1):
            action = str((step or {}).get("action") or "").strip().lower()
            selector = str((step or {}).get("selector") or "").strip()
            value = (step or {}).get("value")
            if action == "click":
                page.locator(selector).click(timeout=int(timeout_ms))
            elif action == "fill":
                page.locator(selector).fill(str(value or ""), timeout=int(timeout_ms))
            elif action == "wait":
                ms = int((step or {}).get("ms") or 1000)
                page.wait_for_timeout(ms)
            elif action == "goto":
                page.goto(str(value or ""), wait_until="domcontentloaded", timeout=int(timeout_ms))
            elif action == "press":
                page.locator(selector).press(str(value or "Enter"), timeout=int(timeout_ms))
            else:
                raise ValueError(f"Unsupported browser workflow action: {action or '<empty>'}")
            executed.append(f"{idx}:{action}")
        title = page.title()
        body_text = page.locator("body").inner_text(timeout=int(timeout_ms))
        page.screenshot(path=output_path, full_page=True)
        final_url = page.url
        browser.close()
    return BrowserToolResult(
        url=final_url,
        title=title or None,
        text_excerpt=_excerpt(body_text),
        screenshot_path=output_path,
        metadata={"executed_steps": executed, "timeout_ms": int(timeout_ms)},
    )
