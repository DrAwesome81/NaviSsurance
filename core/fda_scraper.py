from __future__ import annotations

from core.tools.browser import browser_workflow_tool


FDA_510K_SEARCH_URL = "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfPMN/pmn.cfm"


def run_fda_510k_search(
    *,
    product_code: str,
    start_date: str,
    end_date: str,
) -> dict:
    """
    Best-effort FDA 510(k) search automation using the shared Playwright browser tool.

    This replaces the old import-time Selenium script with a reusable workflow helper.
    """
    result = browser_workflow_tool(
        FDA_510K_SEARCH_URL,
        steps=[
            {"action": "fill", "selector": 'input[name="PRODUCTCODE"]', "value": str(product_code or "").strip()},
            {"action": "fill", "selector": 'input[name="STARTDATE"]', "value": str(start_date or "").strip()},
            {"action": "fill", "selector": 'input[name="ENDDATE"]', "value": str(end_date or "").strip()},
            {"action": "click", "selector": 'input[value="Search"]'},
            {"action": "wait", "ms": 2500},
        ],
        screenshot_name=f"fda-510k-{product_code}",
        timeout_ms=45_000,
    )
    return result.model_dump()