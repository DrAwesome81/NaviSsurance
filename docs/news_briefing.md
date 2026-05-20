# External News Feed (Dashboard) + Dedup / Suppression

Last updated: 2026-05-12

<!-- Pulse private memory visibility + Shield Security/Compliance surface awareness -->

## Goal
Show a **relevant external headlines** feed on the Dashboard that:
- pulls recent web headlines relevant to NaviSure’s work (FDA/MedTech/AI SaMD/IVD)
- optionally uses the Gmail **“News”** label as a personalization signal (seed topics)
- avoids duplicate stories (canonical URL + title-based dedup)
- avoids “Groundhog Day” repeats (don’t re-show items for \(N\) days)

## How it works (runtime)

### 1) Fetch: web search via the agent toolchain
The Dashboard spawns a `NewsWorker` thread which calls the agent with a single request shaped like:
- `WEB_SEARCH:<query>`

The query is a baseline MedTech/regulatory query, with optional extra keywords extracted from recent Gmail `"News"` label subjects (if Gmail is configured).

Code:
- `gui/dashboard_tab.py:NewsWorker.run()`
- `core/response_handler.py` (handles `WEB_SEARCH:`)

### 2) Parse + store
The Dashboard expects either:
- a JSON array of items (preferred), or
- a simple text fallback (paragraphs / title+body)

Before storing:
- URLs are validated, then **canonicalized early** (strip fragments + common tracking params) to reduce DB churn and improve dedup.

Code:
- `gui/dashboard_tab.py:DashboardTab.process_and_store_news()`
- `core/news_dedup.py:canonicalize_url()`

### 3) Dedup at the database layer
News is stored in `news_items`, with a separate `news_dedup` table maintaining stable dedup keys.

Dedup keys are computed two ways (both stored):
- **URL key** (preferred): canonicalized URL
- **Title key** (fallback): normalized title (+ date when available)

This allows “same story, different site” and “same story, tracking params” to collapse correctly.

Code:
- `core/db.py:DatabaseManager.store_news_item()`
- `core/news_dedup.py:make_dedup_key()`

### 4) Dashboard selection + “don’t repeat”
When rendering the feed, the Dashboard pulls from:
- `DatabaseManager.get_news_for_dashboard(days=7, suppress_days=N, limit=50)`

Then it immediately marks displayed items as shown:
- `DatabaseManager.mark_news_shown([news_id, ...])`

The suppression window \(N\) is configurable in the Dashboard UI (defaults to 2 days) and persisted in SQLite.

Code:
- `core/db.py:get_news_for_dashboard()` / `mark_news_shown()`
- `gui/dashboard_tab.py:DashboardTab.display_stored_news()`
- `core/db.py:get_setting()` / `set_setting()` (stores `news_suppress_days`)

### 5) Lightweight relevance ranking (no new infra)
After sorting by recency, the Dashboard applies a stable “relevance” rerank:
- boosts items matching MedTech/FDA/regulatory keywords
- boosts items matching keywords extracted from recent Gmail `"News"` subjects (if available)

This keeps the feed “fresh” while nudging it toward *your* current topics.

Code:
- `gui/dashboard_tab.py:DashboardTab._get_news_seed_keywords()` / `_score_news_item()`

## Daily Briefing integration
The daily briefing now includes:
- `[SECTION:News]`

It pulls from the same dedup/suppression-backed store as the Dashboard:
- selects items via `DatabaseManager.get_news_for_dashboard(...)`
- formats 3–5 bullet lines
- calls `mark_news_shown(...)` so the same stories won’t repeat immediately (including across Dashboard + briefing)

Code:
- `core/chat_handler.py:ChatHandler.daily_briefing()`

## Planned: migrate “search” to Grok (xAI) cleanly
The current mechanism relies on the agent’s `WEB_SEARCH:` tool path. Longer-term we should standardize on **Grok (xAI)** for search as well:
- keep the same output contract (JSON array of `{title, content/summary, url, source, published_date}`),
- keep canonicalization + DB dedup unchanged,
- ensure timeouts/retries and avoid logging raw tool outputs.

<!-- Pulse private memory + Shield surface in news briefing -->
