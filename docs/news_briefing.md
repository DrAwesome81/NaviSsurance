# External News in Daily Briefing

## Goal
Add a **relevant external headlines** section to the daily briefing that:
- pulls recent web headlines relevant to NaviSure’s work (FDA/MedTech/AI SaMD/IVD)
- uses the Gmail **“News”** label as a personalization signal (seed topics)
- avoids repeating the same headlines (dedup + “already shown” suppression)

## How it works (runtime)

### 1) Seeds from Gmail “News” label (optional)
If Gmail is configured, NaviSsurance reads recent subjects from the Gmail label `"News"` and uses them to extract keywords. These keywords are used to build one additional web query (e.g., “PCCP FDA draft guidance medical device regulatory news”).

Code: `core/data_fetch.py:get_gmail_news_seeds()`

### 2) Web search for headlines (structured JSON)
The app uses Anthropic web search to retrieve headlines and requires a **JSON array** response (title/url/source/published_at/summary).

Code: `core/news.py:NewsService._web_search_headlines()`

### 3) Dedup + cache in SQLite
Each headline is normalized and stored in SQLite:
- **Canonical URL** removes tracking parameters (`utm_*`, `gclid`, `fbclid`, etc.) and fragments.
- A stable **dedup_key** is computed (prefers canonical URL).
- `news_items` table stores `first_seen`, `last_seen`, and `last_shown`.

This allows the app to:
- avoid duplicates in a single run (same dedup key)
- suppress showing the same story repeatedly for a few days

Code: `core/news.py:NewsStore`

### 4) Briefing selection + “don’t repeat”
When building the daily briefing, the app selects up to 5 items:
- not shown in the last 2 days (configurable)
- not older than 7 days (configurable)

Selected items are immediately marked `last_shown = now`.

Code: `core/news.py:NewsStore.select_for_briefing()` / `mark_shown()`

### 5) Daily briefing integration
The daily briefing adds a new section:

- `[SECTION:News]`

with bullet lines containing title + source + link. The assistant then formats it.

Code: `core/chat_handler.py:daily_briefing()`

## Configuration & tuning knobs (current defaults)
- **Max headlines**: 5
- **Repeat suppression window**: 2 days
- **Max age window**: 7 days
- **Fetch interval**: 120 minutes (cache refresh throttle)
- **Queries**: 2–3 baseline domain queries + 0–1 Gmail-seeded query

These can be tuned in `core/news.py` (`build_news_queries`, `select_for_briefing`, `min_interval_minutes`).

## Failure modes
- **No Anthropic API key**: returns “News unavailable” (no crash).
- **Gmail not configured**: still works using baseline queries.
- **JSON parse failures from the model**: search results may be dropped; tighten the system prompt if this happens frequently.

## Privacy/safety notes
- Retrieved text is treated as **untrusted reference**.
- Do not log raw search responses containing sensitive content.
