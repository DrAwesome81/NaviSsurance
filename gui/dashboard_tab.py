from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextBrowser, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QCheckBox, QComboBox, QInputDialog, QMessageBox, QDateEdit, QHeaderView, QAbstractItemView, QSizePolicy
from PyQt6.QtCore import Qt, QTimer, QDate, QThread, pyqtSignal, QMetaObject, Q_ARG
from datetime import datetime, timedelta, timezone
from dateutil import parser
import sqlite3
import sys
import os
import time

# Import centralized database path
from config import DATABASE_PATH
from core.db import bump_task_due_date_mmddyyyy

# New: Dashboard pulls Pulse private memory for news and Shield alerts in CoS (additional dashboard coordination)
# Pulse private memory + Shield (dashboard tab surface)

class NewsWorker(QThread):
    """Worker thread for loading news without blocking the UI."""
    # New: NewsWorker now explicitly supports Pulse private memory for Shield in dashboard (additional dashboard spot)
    news_loaded = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, chat_handler):
        super().__init__()
        self.chat_handler = chat_handler
    
    def run(self):
        try:
            print(f"NewsWorker: Loading news... chat_handler type: {type(self.chat_handler)}")
            
            # Use a direct search query to avoid multiple API calls
            direct_search_query = "recent MedTech news AI machine learning IVD SaMD FDA regulations guidances medical devices EHR electronic health records clinical decision support generative AI"

            # Optional: seed relevance from Gmail label "News" subjects
            try:
                subjects = []
                if hasattr(self.chat_handler, "chat_handler") and hasattr(self.chat_handler.chat_handler, "data_fetcher"):
                    df = self.chat_handler.chat_handler.data_fetcher
                    if hasattr(df, "get_gmail_news_seeds"):
                        subjects = df.get_gmail_news_seeds(days=3, max_messages=15) or []
                if subjects:
                    # Light keyword extraction: take frequent tokens
                    import re
                    counts = {}
                    for s in subjects:
                        for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9\\-]{2,}", s or ""):
                            lw = w.lower()
                            if lw in {"the","and","for","with","your","from","this","that","news","update","weekly","daily"}:
                                continue
                            counts[lw] = counts.get(lw, 0) + 1
                    keywords = [w for w, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:6]]
                    if keywords:
                        direct_search_query = direct_search_query + " " + " ".join(keywords)
            except Exception:
                pass
            
            # IMPORTANT: Do not route news through ChatManager.get_response (local llama worker).
            # Instead use Grok web_search + Grok structuring to preserve URLs.
            from core.grok_client import MODEL_CHAT, MODEL_FAST, grok_available, grok_web_search, grok_completion

            ok, msg = grok_available()
            if not ok:
                self.error_occurred.emit(f"News unavailable: {msg}")
                return

            results = grok_web_search(direct_search_query, model=MODEL_FAST) or ""
            if not results.strip():
                self.error_occurred.emit("News unavailable: empty search results")
                return

            system = (
                "You are a news extraction assistant. "
                "Return ONLY a valid JSON array (no prose, no markdown). "
                "Each item MUST be an object with keys: title, content, url, source, published_date. "
                "The url MUST be the full article URL starting with https://. "
                "Only use URLs that appear in the provided results text; never invent URLs. "
                "If you cannot find a URL, set url to an empty string. "
                "Keep title plain text (no ####, no **). "
                "Limit to 8 items."
            )
            user = f"Extract up to 8 MedTech news items from these results:\n\n{results}"
            payload = grok_completion(system=system, user=user, model=MODEL_CHAT) or ""
            self.news_loaded.emit(payload.strip() or "[]")
                
        except Exception as e:
            print(f"NewsWorker: Error loading news: {e}")
            self.error_occurred.emit(f"Error loading news: {str(e)}")


class BriefingWorker(QThread):
    """Worker thread for loading daily briefing without blocking the UI."""
    briefing_loaded = pyqtSignal(str, object)  # Emits (briefing_text, chat_handler_obj)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, chat_handler):
        super().__init__()
        self.chat_handler = chat_handler
    
    def run(self):
        try:
            print(f"BriefingWorker: Loading briefing... chat_handler type: {type(self.chat_handler)}")
            
            # Get briefing from chat_handler - handle both ChatManager and ChatHandler
            briefing = None
            chat_handler_obj = None
            
            if hasattr(self.chat_handler, 'start_briefing'):
                # It's a ChatManager
                briefing = self.chat_handler.start_briefing()
                chat_handler_obj = self.chat_handler.chat_handler if hasattr(self.chat_handler, 'chat_handler') else None
            elif hasattr(self.chat_handler, 'chat_handler') and hasattr(self.chat_handler.chat_handler, 'start_briefing'):
                # Nested ChatManager
                briefing = self.chat_handler.chat_handler.start_briefing()
                chat_handler_obj = self.chat_handler.chat_handler.chat_handler if hasattr(self.chat_handler.chat_handler, 'chat_handler') else None
            elif hasattr(self.chat_handler, 'daily_briefing'):
                # It's a ChatHandler directly
                chat_handler_obj = self.chat_handler
                briefing = self.chat_handler.daily_briefing()
            
            if briefing:
                print(f"BriefingWorker: Got briefing ({len(briefing)} chars)")
                self.briefing_loaded.emit(briefing, chat_handler_obj)
            else:
                self.error_occurred.emit("Briefing already shown today or not available")
                
        except Exception as e:
            print(f"BriefingWorker: Error loading briefing: {e}")
            import traceback
            traceback.print_exc()
            self.error_occurred.emit(f"Error loading briefing: {str(e)}")

import re

class DashboardTab(QWidget):
    def __init__(self, chat_handler, todo_list, db, parent=None, defer_initial_loads: bool = False):
        super().__init__(parent)
        self.chat_handler = chat_handler
        self.todo_list = todo_list
        self.db = db
        self.defer_initial_loads = bool(defer_initial_loads)
        self.tasks_panel = None
        # Update TodoList's parent to point to this dashboard tab
        if self.todo_list:
            self.todo_list.parent = self
        # Ensure filter UI is prepared before building the task widget.
        # (create_task_widget may embed TasksTab or fall back to legacy table+filters.)
        try:
            self.setup_todo_filters()
        except Exception:
            pass
        self.setup_ui()

    def _setup_status_items(self) -> list[tuple[str, bool, str]]:
        """
        Return a small list of (label, ok, detail) items for the Setup/Connectivity banner.
        Best-effort only; this must never raise.
        """
        items: list[tuple[str, bool, str]] = []
        # Keys / integrations
        try:
            import os

            openai_ok = bool(str(os.getenv("OPENAI_API_KEY", "") or "").strip())
            items.append(("OpenAI web research", openai_ok, "Set OPENAI_API_KEY in config/.env"))

            assembly_ok = bool(str(os.getenv("ASSEMBLYAI_API_KEY", "") or "").strip())
            items.append(("AssemblyAI transcripts", assembly_ok, "Set ASSEMBLYAI_API_KEY in config/.env"))
        except Exception:
            pass

        # Grok availability
        try:
            from core.grok_client import grok_available

            ok, msg = grok_available()
            items.append(("Grok (xAI)", bool(ok), str(msg or "").strip() or "OK"))
        except Exception:
            # Fall back to env check
            try:
                import os

                grok_ok = bool(str(os.getenv("GROK_API_KEY", "") or "").strip())
                items.append(("Grok (xAI)", grok_ok, "Set GROK_API_KEY in config/.env"))
            except Exception:
                pass

        items.append(("🛡️ Shield + Pulse private memory", True, "Intelligence & Coordination pillar surface"))

        # Local dependencies (Meetings video extraction)
        try:
            import shutil

            ffmpeg_ok = shutil.which("ffmpeg") is not None
            items.append(("ffmpeg", ffmpeg_ok, "Install ffmpeg and ensure it is on PATH (Meetings video support)"))
        except Exception:
            pass

        # Briefing/email mode
        try:
            from core.app_preferences import is_briefing_and_email_disabled

            off = bool(is_briefing_and_email_disabled(self.db))
            items.append(
                (
                    "Briefing/email",
                    not off,
                    "Disabled in Settings" if off else "Enabled",
                )
            )
        except Exception:
            pass

        # Optional runtime / local API / browser tooling
        try:
            from core.runtime.service import runtime_scheduler_status

            ok, detail = runtime_scheduler_status()
            items.append(("Runtime scheduler", ok, detail))
        except Exception:
            pass
        try:
            from core.service.local_api import local_api_status

            ok, detail = local_api_status()
            items.append(("Local API", ok, detail))
        except Exception:
            pass
        try:
            from core.tools.browser import browser_tools_available

            ok, detail = browser_tools_available()
            items.append(("Browser tools", ok, detail))
        except Exception:
            pass

        return items

    def _render_setup_banner_html(self) -> str:
        items = self._setup_status_items()
        if not items:
            return ""
        parts: list[str] = []
        for label, ok, _detail in items:
            dot = "●"
            color = "#34a853" if ok else "#fbbc04"
            parts.append(f"<span style='color:{color}; font-weight:600;'>{dot}</span> {label}")
        return (
            "<div style='color:#9aa0a6; font-size:12px;'>"
            "<b style='color:#e8eaed;'>Setup:</b> "
            + " &nbsp; | &nbsp; ".join(parts)
            + "</div>"
        )

    def _show_setup_details(self) -> None:
        try:
            from PyQt6.QtWidgets import QMessageBox

            items = self._setup_status_items()
            lines = []
            for label, ok, detail in items:
                status = "OK" if ok else "Missing / limited"
                lines.append(f"- {label}: {status}\n  {detail}".rstrip())
            QMessageBox.information(self, "Setup / Connectivity", "\n\n".join(lines) if lines else "No setup information available.")
        except Exception:
            return

    def _today_utc_str(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _get_cached_briefing_html_for_today(self) -> str:
        try:
            cached_date = str(self.db.get_setting("daily_briefing_cache_date", "") or "").strip()
            if cached_date != self._today_utc_str():
                return ""
            return str(self.db.get_setting("daily_briefing_cache_html", "") or "").strip()
        except Exception:
            return ""

    def _set_cached_briefing_html_for_today(self, html: str) -> None:
        try:
            self.db.set_setting("daily_briefing_cache_date", self._today_utc_str())
            self.db.set_setting("daily_briefing_cache_html", str(html or ""))
        except Exception:
            pass

    def _get_cached_briefing_raw_for_today(self) -> str:
        """Fallback cache from ChatHandler when HTML cache is unavailable."""
        try:
            cached_date = str(self.db.get_setting("daily_briefing_raw_date", "") or "").strip()
            if cached_date != self._today_utc_str():
                return ""
            return str(self.db.get_setting("daily_briefing_raw_text", "") or "").strip()
        except Exception:
            return ""

    def _restore_briefing_from_raw_cache(self) -> bool:
        """Render raw briefing cache into HTML cache and display it."""
        raw_text = self._get_cached_briefing_raw_for_today()
        if not raw_text:
            return False
        html = self._render_briefing_to_html(raw_text, None, use_llm=False)
        self._set_cached_briefing_html_for_today(html)
        if hasattr(self, "briefing_display"):
            self.briefing_display.setHtml(html)
        return True

    def _get_cached_schedule_html(self) -> str:
        try:
            return str(self.db.get_setting("dashboard_schedule_cache_html", "") or "").strip()
        except Exception:
            return ""

    def _set_cached_schedule_html(self, html: str) -> None:
        try:
            self.db.set_setting("dashboard_schedule_cache_html", str(html or ""))
            self.db.set_setting("dashboard_schedule_cache_at", datetime.now(timezone.utc).isoformat())
        except Exception:
            pass

    def _linkify_briefing_urls(self, text: str) -> str:
        """Turn http(s) URLs in plain text into clickable HTML links."""
        import re
        from html import escape
        def repl(m):
            url = m.group(1)
            safe_href = escape(url, quote=True)
            display = escape(url)
            return f'<a href="{safe_href}" style="color: #8ab4f8;">{display}</a>'
        return re.sub(r'(https?://[^\s<>"\']+)', repl, text)

    def _render_briefing_to_html(self, briefing: str, chat_handler_obj, *, use_llm: bool = False) -> str:
        """Render daily briefing text into dashboard HTML (best-effort). URLs become clickable links."""
        if not use_llm:
            fallback = (briefing or "").replace("\n", "<br>")
            fallback = self._linkify_briefing_urls(fallback)
            return f"<div style='color: #e8eaed; padding: 10px; line-height: 1.5;'>{fallback}</div>"
        try:
            response_handler = getattr(chat_handler_obj, "response_handler", None)
            if response_handler is None:
                fallback = (briefing or "").replace("\n", "<br>")
                fallback = self._linkify_briefing_urls(fallback)
                return f"<div style='color: #e8eaed; padding: 10px; line-height: 1.5;'>{fallback}</div>"
            formatted_briefing = response_handler.chat_with_llama(
                [
                    {
                        "role": "user",
                        "content": (
                            "Turn this briefing into a concise, helpful rundown in Navi's tone (direct, professional, calm; no snark). "
                            "Use <br><br> between sections and keep it skimmable. "
                            "Suggest concrete next actions for urgent items. "
                            f"Briefing:\n\n{briefing}"
                        ),
                    }
                ],
                "briefing_session",
            )

            formatted_briefing = re.sub(r"\n+", "\n", formatted_briefing)
            formatted_briefing = re.sub(r"^#+\s*", "", formatted_briefing, flags=re.MULTILINE)
            lines = formatted_briefing.split("\n")
            formatted_lines = [line.strip() for line in lines if line.strip()]
            formatted_briefing = "\n".join(formatted_lines)
            formatted_briefing = formatted_briefing.replace("\n\n", "<br><br>").replace("\n", "<br>")
            formatted_briefing = re.sub(r"^<br><br>", "", formatted_briefing.strip())
            formatted_briefing = self._linkify_briefing_urls(formatted_briefing)
            return f"<div style='color: #e8eaed; padding: 10px; line-height: 1.5;'>{formatted_briefing}</div>"
        except Exception as e:
            print(f"Error formatting briefing: {e}")
            fallback = (briefing or "").replace("\n", "<br>")
            fallback = self._linkify_briefing_urls(fallback)
            return f"<div style='color: #e8eaed; padding: 10px; line-height: 1.5;'>{fallback}</div>"

    def run_initial_loads(self, *, skip_news: bool = False, skip_briefing: bool = False):
        """Run dashboard initial loads (used for normal startup and splash-preload startup)."""
        self._set_startup_refresh_indicator(True)
        self.load_schedule()
        try:
            # Keep the embedded tasks panel aligned with the Tasks tab.
            self.load_tasks_filtered()
        except Exception:
            pass
        if not skip_news:
            self.load_news()
        try:
            self.load_important_emails()
        except Exception:
            pass

        if skip_briefing:
            return
        try:
            from core.app_preferences import is_briefing_and_email_disabled

            briefing_off = bool(is_briefing_and_email_disabled(self.db))
        except Exception:
            briefing_off = False
        if not briefing_off:
            # Phase 5: auto-trigger morning plan on first open of the day (placeholder)
            QTimer.singleShot(2500, self._maybe_auto_generate_morning_plan)
        else:
            QTimer.singleShot(500, self._show_briefing_disabled)
        QTimer.singleShot(12000, lambda: self._set_startup_refresh_indicator(False))

    def show_startup_loading_state(self) -> None:
        """Show cached dashboard content immediately, then refresh asynchronously."""
        self._set_startup_refresh_indicator(True)
        try:
            cached_schedule = self._get_cached_schedule_html()
            if cached_schedule and hasattr(self, "schedule_display"):
                self.schedule_display.setHtml(cached_schedule)
        except Exception:
            pass
        try:
            if hasattr(self, "news_display"):
                self.display_stored_news()
        except Exception:
            pass
        try:
            cached_html = self._get_cached_briefing_html_for_today()
            if cached_html and hasattr(self, "briefing_display"):
                self.briefing_display.setHtml(cached_html)
            elif hasattr(self, "briefing_display"):
                self._restore_briefing_from_raw_cache()
        except Exception:
            pass

    def _set_startup_refresh_indicator(self, visible: bool) -> None:
        try:
            if not hasattr(self, "startup_refresh_label"):
                return
            self.startup_refresh_label.setVisible(bool(visible))
            if visible:
                self.startup_refresh_label.setText("Refreshing latest dashboard data in background...")
        except Exception:
            pass

    def preload_news_sync(self):
        """Blocking news prefetch for splash startup flow (best-effort)."""
        # Honor same staleness policy as async load_news.
        current_time = datetime.now(timezone.utc).timestamp()
        one_hour_ago = current_time - 3600
        try:
            last_news_update = self.db.get_last_news_update()
        except Exception:
            last_news_update = 0
        if last_news_update and last_news_update > one_hour_ago:
            try:
                self.display_stored_news()
            except Exception:
                pass
            return

        direct_search_query = (
            "recent MedTech news AI machine learning IVD SaMD FDA regulations guidances "
            "medical devices EHR electronic health records clinical decision support generative AI"
        )
        try:
            subjects = []
            if hasattr(self.chat_handler, "chat_handler") and hasattr(self.chat_handler.chat_handler, "data_fetcher"):
                df = self.chat_handler.chat_handler.data_fetcher
                if hasattr(df, "get_gmail_news_seeds"):
                    subjects = df.get_gmail_news_seeds(days=3, max_messages=15) or []
            if subjects:
                counts = {}
                for s in subjects:
                    for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9\\-]{2,}", s or ""):
                        lw = w.lower()
                        if lw in {"the", "and", "for", "with", "your", "from", "this", "that", "news", "update", "weekly", "daily"}:
                            continue
                        counts[lw] = counts.get(lw, 0) + 1
                keywords = [w for w, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:6]]
                if keywords:
                    direct_search_query = direct_search_query + " " + " ".join(keywords)
        except Exception:
            pass

        # For splash preload, avoid ChatManager.get_response to prevent local worker dependency.
        self.db.update_last_news_update()
        try:
            from core.grok_client import MODEL_CHAT, MODEL_FAST, grok_available, grok_web_search, grok_completion

            ok, msg = grok_available()
            if not ok:
                raise RuntimeError(msg)

            results = grok_web_search(direct_search_query, model=MODEL_FAST) or ""
            if not results.strip():
                raise RuntimeError("empty search results")

            system = (
                "You are a news extraction assistant. "
                "Return ONLY a valid JSON array (no prose, no markdown). "
                "Each item MUST be an object with keys: title, content, url, source, published_date. "
                "The url MUST be the full article URL starting with https://. "
                "Only use URLs that appear in the provided results text; never invent URLs. "
                "If you cannot find a URL, set url to an empty string. "
                "Keep title plain text (no ####, no **). "
                "Limit to 8 items."
            )
            user = f"Extract up to 8 MedTech news items from these results:\n\n{results}"
            payload = grok_completion(system=system, user=user, model=MODEL_CHAT) or "[]"
            self.process_and_store_news(str(payload))
            self.display_stored_news()
        except Exception:
            # Fail-open: fall back to whatever is already stored.
            try:
                self.display_stored_news()
            except Exception:
                pass

    def preload_briefing_sync(self, *, force_refresh: bool = False) -> bool:
        """
        Blocking briefing preload for splash startup flow.
        Returns True when briefing is available (cached or generated), False otherwise.
        """
        try:
            from core.app_preferences import is_briefing_and_email_disabled

            briefing_off = bool(is_briefing_and_email_disabled(self.db))
        except Exception:
            briefing_off = False
        if briefing_off:
            self._show_briefing_disabled()
            return False

        cached_html = "" if force_refresh else self._get_cached_briefing_html_for_today()
        if cached_html:
            if hasattr(self, "briefing_display"):
                self.briefing_display.setHtml(cached_html)
            return True
        if not force_refresh and self._restore_briefing_from_raw_cache():
            return True

        briefing = None
        chat_handler_obj = None
        if force_refresh:
            if hasattr(self.chat_handler, "chat_handler") and hasattr(self.chat_handler.chat_handler, "daily_briefing"):
                chat_handler_obj = self.chat_handler.chat_handler
                briefing = self.chat_handler.chat_handler.daily_briefing()
            elif hasattr(self.chat_handler, "daily_briefing"):
                chat_handler_obj = self.chat_handler
                briefing = self.chat_handler.daily_briefing()
        else:
            if hasattr(self.chat_handler, "start_briefing"):
                briefing = self.chat_handler.start_briefing()
                chat_handler_obj = self.chat_handler.chat_handler if hasattr(self.chat_handler, "chat_handler") else None
            elif hasattr(self.chat_handler, "chat_handler") and hasattr(self.chat_handler.chat_handler, "start_briefing"):
                briefing = self.chat_handler.chat_handler.start_briefing()
                chat_handler_obj = self.chat_handler.chat_handler.chat_handler if hasattr(self.chat_handler.chat_handler, "chat_handler") else None
            elif hasattr(self.chat_handler, "daily_briefing"):
                briefing = self.chat_handler.daily_briefing()
                chat_handler_obj = self.chat_handler

        if not briefing:
            cached_html = self._get_cached_briefing_html_for_today()
            if cached_html and hasattr(self, "briefing_display"):
                self.briefing_display.setHtml(cached_html)
                return True
            return False

        # During splash preload, avoid local worker formatting path.
        html = self._render_briefing_to_html(str(briefing), chat_handler_obj, use_llm=False)
        if hasattr(self, "briefing_display"):
            self.briefing_display.setHtml(html)
        self._set_cached_briefing_html_for_today(html)
        return True

    def setup_todo_filters(self):
        """Set up the todo list filter controls in the dashboard."""
        if not self.todo_list:
            return

        # Get the filter layout from TodoList
        filter_layout = QHBoxLayout()
        self.category_filter = QComboBox()
        self.category_filter.addItems(["All", "Business", "Personal"])
        self.category_filter.currentTextChanged.connect(self.load_tasks_filtered)
        filter_layout.addWidget(QLabel("Category:"))
        filter_layout.addWidget(self.category_filter)

        self.date_filter = QComboBox()
        self.date_filter.addItems(["All", "Today", "Overdue", "No Date", "Specific Date"])
        self.date_filter.currentTextChanged.connect(self.load_tasks_filtered)
        filter_layout.addWidget(QLabel("Due Date:"))
        filter_layout.addWidget(self.date_filter)

        self.date_range = QDateEdit()
        self.date_range.setCalendarPopup(True)
        self.date_range.setDate(QDate.currentDate())
        self.date_range.dateChanged.connect(self.load_tasks_filtered)
        filter_layout.addWidget(QLabel("Specific Date:"))
        filter_layout.addWidget(self.date_range)

        # Additional toggles (kept lightweight)
        self.show_completed_cb = QCheckBox("Show completed")
        self.show_completed_cb.stateChanged.connect(self.load_tasks_filtered)
        filter_layout.addWidget(self.show_completed_cb)

        self.show_snoozed_cb = QCheckBox("Show snoozed")
        self.show_snoozed_cb.stateChanged.connect(self.load_tasks_filtered)
        filter_layout.addWidget(self.show_snoozed_cb)
        filter_layout.addStretch()

        # Add the filter layout to the dashboard's left column layout
        # We'll store it for later use in setup_ui
        self.filter_layout = filter_layout

    def load_tasks_filtered(self):
        """Load tasks with current filter settings using batch optimization."""
        if self.tasks_panel is not None:
            try:
                self.tasks_panel.refresh_tasks()
            except Exception as e:
                print(f"Error refreshing embedded tasks panel: {e}")
            return
        if not getattr(self, "task_list", None):
            return

        try:
            category_filter = self.category_filter.currentText()
            date_filter = self.date_filter.currentText()
            specific_date = self.date_range.date().toString("MM-dd-yyyy") if date_filter == "Specific Date" else None

            print(f"DEBUG: Filter values - category: '{category_filter}', date_filter: '{date_filter}', specific_date: '{specific_date}'")

            tasks = []
            try:
                tasks = self.db.list_tasks_rich(
                    category=category_filter if category_filter != "All" else None,
                    date_filter=date_filter,
                    specific_date=specific_date,
                    include_completed=bool(self.show_completed_cb.isChecked()) if hasattr(self, "show_completed_cb") else False,
                    include_snoozed=bool(self.show_snoozed_cb.isChecked()) if hasattr(self, "show_snoozed_cb") else False,
                    limit=500,
                )
            except Exception:
                # Fallback (legacy)
                tasks = [
                    {
                        "id": tid,
                        "task_text": ttext,
                        "due_date": d,
                        "category": c,
                        "recurrence": r,
                        "completed": comp,
                        "priority": 0,
                        "tags_json": "[]",
                        "next_action_date": None,
                        "snoozed_until": None,
                    }
                    for (tid, ttext, d, c, r, comp) in self.db.get_tasks(
                        category=category_filter if category_filter != "All" else None,
                        date_filter=date_filter,
                        specific_date=specific_date,
                    )
                ]

            print(f"DEBUG: Retrieved {len(tasks)} tasks from database")

            # Dashboard policy: only show tasks due today or overdue, ordered by due date.
            today = datetime.now().date()
            due_window_tasks = []
            for t in tasks:
                due_raw = str(t.get("due_date") or "").strip()
                if not due_raw or due_raw.lower() == "unknown":
                    continue
                try:
                    due_dt = datetime.strptime(due_raw, "%m-%d-%Y").date()
                except Exception:
                    continue
                if due_dt <= today:
                    due_window_tasks.append((due_dt, t))

            due_window_tasks.sort(key=lambda item: item[0])
            tasks = [t for _, t in due_window_tasks]
            print(f"DEBUG: Dashboard due/overdue filter kept {len(tasks)} tasks")

            # Clear current tasks
            self.task_list.setRowCount(0)

            if tasks:
                print(f"DEBUG: Loading {len(tasks)} tasks with batch optimization...")
                
                # CRITICAL: Disable auto-repaint to prevent widget detachment during loading
                self.task_list.setUpdatesEnabled(False)
                
                try:
                    # BATCH OPTIMIZATION: Load all rows first, then style in one pass
                    # Step 1: Create all rows and widgets without styling
                    styling_data_list = []
                    for t in tasks:
                        task_id = int(t.get("id") or 0)
                        task_text = str(t.get("task_text") or "")
                        due_date = t.get("due_date")
                        category = str(t.get("category") or "Business")
                        recurrence = str(t.get("recurrence") or "None")
                        completed = int(t.get("completed") or 0)
                        priority = int(t.get("priority") or 0)
                        tags_json = str(t.get("tags_json") or "[]")
                        next_action_date = t.get("next_action_date")
                        snoozed_until = t.get("snoozed_until")
                        row_position = self.task_list.rowCount()
                        self.task_list.insertRow(row_position)
                        print(f"DEBUG: Creating row {row_position} for task {task_id}: {task_text[:30]}...")
                        
                        # Create and set widgets without styling
                        self._create_task_row_widgets(
                            row_position,
                            task_id,
                            task_text,
                            due_date,
                            category,
                            recurrence,
                            completed,
                            priority=priority,
                            tags_json=tags_json,
                            next_action_date=next_action_date,
                            snoozed_until=snoozed_until,
                        )
                        
                        # Store styling data for batch processing
                        styling_data_list.append((row_position, due_date, completed))
                    
                finally:
                    # CRITICAL: Re-enable auto-repaint after all operations complete
                    self.task_list.setUpdatesEnabled(True)
                    print("DEBUG: Re-enabled table updates")
                
                # Step 2: Apply styling to all rows AFTER updates are enabled
                for row_position, due_date, completed in styling_data_list:
                    self.apply_task_styling_css(row_position, due_date, completed)
                
                # Step 3: Final UI refresh
                print("DEBUG: Performing final UI refresh...")
                from PyQt6.QtWidgets import QApplication
                QApplication.processEvents()
                    
            print(f"DEBUG: Finished loading {len(tasks)} tasks")

        except Exception as e:
            print(f"Error loading filtered tasks: {e}")
            import traceback
            traceback.print_exc()

    def _create_task_row_widgets(
        self,
        row_position,
        task_id,
        task_text,
        due_date,
        category,
        recurrence,
        completed,
        *,
        priority: int = 0,
        tags_json: str = "[]",
        next_action_date: str | None = None,
        snoozed_until: str | None = None,
    ):
        """Create task row widgets without applying styling (for batch loading)."""
        try:
            # Create task widget with checkbox and label
            task_widget = QWidget()
            task_widget.setStyleSheet("QWidget { background-color: transparent; }")
            task_layout = QHBoxLayout(task_widget)
            task_layout.setContentsMargins(5, 5, 5, 5)
            task_layout.setSpacing(8)

            # Checkbox
            checkbox = QCheckBox()
            checkbox.setChecked(completed)
            checkbox.setStyleSheet("""
                QCheckBox {
                    background-color: transparent;
                    color: #e8eaed;
                    font-weight: 500;
                    padding: 2px;
                }
                QCheckBox::indicator {
                    width: 16px;
                    height: 16px;
                    background-color: #22252c;
                    border: 1px solid #2e2f32;
                    border-radius: 3px;
                }
                QCheckBox::indicator:checked {
                    background-color: #FD6262;
                    border: 1px solid #FD6262;
                }
            """)
            checkbox.stateChanged.connect(lambda state, tid=task_id: self.update_task_status(tid, state == Qt.CheckState.Checked.value))
            task_layout.addWidget(checkbox)

            # Task label
            pr = int(priority or 0)
            prefix = f"[P{pr}] " if pr > 0 else ""
            task_label = QLabel(f"  {prefix}{task_text}")  # Add spaces at the beginning for left alignment
            task_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            task_label.setStyleSheet("""
                QLabel {
                    color: #e8eaed;
                    font-size: 13px;
                    padding-left: 5px;
                    text-align: left;
                    margin: 0px;
                    background-color: transparent;
                    font-weight: normal;
                }
            """)
            task_layout.addWidget(task_label)
            # Tooltips for richer fields
            try:
                tip = []
                if pr:
                    tip.append(f"Priority: {pr}")
                if next_action_date:
                    tip.append(f"Next action: {next_action_date}")
                if snoozed_until:
                    tip.append(f"Snoozed until: {snoozed_until}")
                if tags_json and tags_json != "[]":
                    tip.append(f"Tags: {tags_json}")
                if tip:
                    task_label.setToolTip("\n".join(tip))
            except Exception:
                pass

            # CRITICAL: Set parent before adding to table to prevent widget detachment
            task_widget.setParent(self.task_list)
            self.task_list.setCellWidget(row_position, 0, task_widget)

            # Category item (column 1)
            category_item = QTableWidgetItem(category)
            category_item.setFlags(category_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.task_list.setItem(row_position, 1, category_item)

            # Due date item (column 2)
            due_date_display = due_date if due_date else "No due date"
            due_date_item = QTableWidgetItem(due_date_display)
            due_date_item.setFlags(due_date_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.task_list.setItem(row_position, 2, due_date_item)

            # Actions widget (column 3)
            actions_widget = QWidget()
            actions_widget.setStyleSheet("QWidget { background-color: transparent; }")
            actions_layout = QHBoxLayout(actions_widget)
            actions_layout.setContentsMargins(0, 0, 0, 0)
            actions_layout.setSpacing(5)

            # Edit button
            edit_btn = QPushButton("Edit")
            edit_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            edit_btn.setMinimumSize(50, 35)
            edit_btn.setMaximumSize(80, 45)
            edit_btn.setStyleSheet("""
                QPushButton {
                    background-color: #FD6262;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 6px 12px;
                    font-weight: 500;
                    font-size: 12px;
                    margin: 2px;
                    min-width: 60px;
                }
                QPushButton:hover {
                    background-color: #e85555;
                }
            """)
            edit_btn.clicked.connect(lambda checked, r=row_position, tid=task_id: self.edit_task(r, tid))
            actions_layout.addWidget(edit_btn)

            # Move due date forward by one day (clears hide-until snooze)
            snooze_btn = QPushButton("Due +1d")
            snooze_btn.setToolTip("Move the due date forward by one day (clears snooze hide).")
            snooze_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            snooze_btn.setMinimumSize(60, 35)
            snooze_btn.setMaximumSize(90, 45)
            snooze_btn.setStyleSheet("""
                QPushButton {
                    background-color: #3a3b3e;
                    color: #e8eaed;
                    border: 1px solid #2e2f32;
                    border-radius: 6px;
                    padding: 6px 12px;
                    font-weight: 500;
                    font-size: 12px;
                    margin: 2px;
                    min-width: 60px;
                }
                QPushButton:hover {
                    background-color: #4a4a4e;
                }
            """)

            def _snooze_one_day():
                try:
                    cur_due = due_date
                    new_due = bump_task_due_date_mmddyyyy(cur_due, days=1)
                    self.db.update_task_by_id(
                        int(task_id), due_date=new_due, snoozed_until=None
                    )
                    self.load_tasks_filtered()
                except Exception:
                    return

            snooze_btn.clicked.connect(_snooze_one_day)
            actions_layout.addWidget(snooze_btn)

            # Delete button
            delete_btn = QPushButton("Delete")
            delete_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            delete_btn.setMinimumSize(60, 35)
            delete_btn.setMaximumSize(90, 45)
            delete_btn.setStyleSheet("""
                QPushButton {
                    background-color: #3a3b3e;
                    color: #e8eaed;
                    border: 1px solid #2e2f32;
                    border-radius: 6px;
                    padding: 6px 12px;
                    font-weight: 500;
                    font-size: 12px;
                    margin: 2px;
                    min-width: 60px;
                }
                QPushButton:hover {
                    background-color: #4a4a4e;
                }
            """)
            delete_btn.clicked.connect(lambda checked, r=row_position, tid=task_id: self.delete_task(r, tid))
            actions_layout.addWidget(delete_btn)

            # CRITICAL: Set parent before adding to table to prevent widget detachment
            actions_widget.setParent(self.task_list)
            self.task_list.setCellWidget(row_position, 3, actions_widget)

            # Store task data for later use
            task_widget.task_data = {
                'id': task_id,
                'text': task_text,
                'due_date': due_date,
                'category': category,
                'recurrence': recurrence,
                'completed': completed,
                'priority': pr,
                'tags_json': tags_json,
                'next_action_date': next_action_date,
                'snoozed_until': snoozed_until,
            }

            print(f"DEBUG: Created widgets for row {row_position}, task: {task_text[:30]}...")

        except Exception as e:
            print(f"Error creating task row widgets: {e}")

    def add_task_to_table(self, task_id, task_text, due_date, category, recurrence, completed):
        """Add an existing task to the table (single task version)."""
        try:
            print(f"DEBUG: add_task_to_table called with task_id={task_id}, task_text='{task_text}', category='{category}'")
            row_position = self.task_list.rowCount()
            self.task_list.insertRow(row_position)

            # Create widgets without styling
            self._create_task_row_widgets(row_position, task_id, task_text, due_date, category, recurrence, completed)

            # Apply styling immediately for single task
            self.apply_task_styling_css(row_position, due_date, completed)

        except Exception as e:
            print(f"Error adding task to table: {e}")

    def add_task(self):
        """Add a new task from the input field."""
        if self.tasks_panel is not None:
            try:
                self.tasks_panel.add_task()
            except Exception as e:
                print(f"Error adding task via embedded tasks panel: {e}")
            return
        if not getattr(self, "task_list", None):
            return

        task_text = self.taskInput.text().strip()
        if not task_text:
            return

        # Get the selected due date
        due_date = self.dueDateInput.date().toString("MM-dd-yyyy")

        # Get the selected category and recurrence
        category = self.categoryInput.currentText()
        recurrence = self.recurrenceInput.currentText()

        try:
            # Use the database method to add the task
            task_id = self.db.add_task(
                session_id=f"dashboard_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                task_text=task_text,
                due_date=due_date,
                category=category,
                recurrence=recurrence,
                completed=0
            )

            # Add to table display
            print(f"DEBUG: About to call add_task_to_table with task_id={task_id}, task_text='{task_text}', due_date='{due_date}', category='{category}'")
            self.add_task_to_table(task_id, task_text, due_date, category, recurrence, 0)

            # Clear input fields
            self.taskInput.clear()

        except Exception as e:
            print(f"Error adding task: {e}")
            QMessageBox.critical(self, "Error", f"Failed to add task: {str(e)}")

    def setup_ui(self):
        # Set the overall dark theme for the dashboard (professional palette)
        self.setStyleSheet("""
            QWidget {
                background-color: #15171c;
                color: #e8eaed;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # Header
        dashboard_header = QLabel("Dashboard - Overview")
        dashboard_header.setStyleSheet("color: #e8eaed; font-weight: 600; font-size: 16px; padding: 10px; background-color: transparent; border: none;")
        dashboard_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(dashboard_header)

        self.startup_refresh_label = QLabel("Refreshing latest dashboard data in background...")
        self.startup_refresh_label.setStyleSheet(
            "color: #9aa0a6; font-size: 11px; padding: 2px 8px; background-color: transparent;"
        )
        self.startup_refresh_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.startup_refresh_label.setVisible(False)
        layout.addWidget(self.startup_refresh_label)

        # Setup/Connectivity banner (prevents silent demo failures when keys/deps are missing)
        try:
            banner_row = QHBoxLayout()
            self.setup_banner = QTextBrowser()
            self.setup_banner.setOpenExternalLinks(True)
            self.setup_banner.setFixedHeight(34)
            self.setup_banner.setStyleSheet(
                "QTextBrowser { background-color: #1c1e24; border: 1px solid #2e2f32; border-radius: 6px; padding: 6px; }"
            )
            self.setup_banner.setHtml(self._render_setup_banner_html())
            banner_row.addWidget(self.setup_banner, 1)
            details_btn = QPushButton("Details…")
            details_btn.setFixedHeight(30)
            details_btn.clicked.connect(self._show_setup_details)
            banner_row.addWidget(details_btn, 0)
            layout.addLayout(banner_row)
        except Exception:
            pass
        
        # Main horizontal layout: left column (schedule + briefing), right column (news + unreplied)
        main_layout = QHBoxLayout()
        main_layout.setSpacing(12)
        
        # Left column: Today's events + Task List + Daily briefing
        left_column = QVBoxLayout()
        left_column.setSpacing(12)
        schedule_widget = self.create_schedule_widget()
        left_column.addWidget(schedule_widget, 3)

        # Task list (embed TasksTab when available; otherwise legacy task widget)
        try:
            task_widget = self.create_task_widget()
            left_column.addWidget(task_widget, 4)
        except Exception:
            pass

        briefing_widget = self.create_briefing_widget()
        left_column.addWidget(briefing_widget, 6)
        
        # Right column: News (top ~70%), Unreplied emails (bottom ~30%)
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)
        news_widget = self.create_news_widget()
        right_layout.addWidget(news_widget, 7)  # 70% of right column height
        unreplied_widget = self.create_important_emails_widget()
        right_layout.addWidget(unreplied_widget, 3)  # 30% of right column height
        
        # Add columns to main layout
        main_layout.addLayout(left_column, 2)  # Left column takes 2/3 of space
        main_layout.addWidget(right_widget, 1)  # Right column takes 1/3 of space
        
        layout.addLayout(main_layout)
        
        # Setup auto-refresh timer for schedule (every 15 minutes)
        self.schedule_timer = QTimer()
        self.schedule_timer.timeout.connect(self.load_schedule)
        self.schedule_timer.start(900000)  # 15 minutes
        
        # Initial loads (can be deferred for splash-gated startup)
        if not self.defer_initial_loads:
            self.run_initial_loads()

    def create_task_widget(self):
        # Keep Dashboard and Tasks tab aligned by reusing the same task manager UI.
        try:
            from gui.tasks_tab import TasksTab

            widget = QWidget()
            layout = QVBoxLayout(widget)
            layout.setContentsMargins(8, 8, 8, 8)
            layout.setSpacing(8)

            task_header = QLabel("Task List")
            task_header.setStyleSheet(
                "color: #e8eaed; font-weight: 600; padding: 3px; "
                "background-color: transparent; border: none; font-size: 13px;"
            )
            task_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
            task_header.setMaximumHeight(25)
            layout.addWidget(task_header)

            self.tasks_panel = TasksTab(self, show_header=False, compact=True)
            layout.addWidget(self.tasks_panel, 1)
            return widget
        except Exception as e:
            print(f"Warning: could not embed TasksTab in Dashboard, using legacy task widget: {e}")
            self.tasks_panel = None

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # Header
        task_header = QLabel("Task List")
        task_header.setStyleSheet("color: #e8eaed; font-weight: 600; padding: 3px; background-color: transparent; border: none; font-size: 13px;")
        task_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        task_header.setMaximumHeight(25)
        layout.addWidget(task_header)
        
        # Task list - back to QTableWidget but with custom delegate for row coloring
        self.task_list = QTableWidget()
        self.task_list.setColumnCount(4)
        self.task_list.setHorizontalHeaderLabels(["Task", "Category", "Due Date", "Actions"])
        self.task_list.setAlternatingRowColors(False)  # We'll handle colors manually
        self.task_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.task_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # Professional dark table styling
        self.task_list.setStyleSheet("""
            QTableWidget {
                background-color: #1c1e24;
                color: #e8eaed;
                gridline-color: #2e2f32;
            }
            QHeaderView::section {
                background-color: #22252c;
                color: #e8eaed;
                padding: 8px;
                border: 1px solid #2e2f32;
                font-weight: 600;
                font-size: 13px;
                min-height: 30px;
            }
            QTableWidget::item {
                padding: 8px;
                border: none;
                color: #e8eaed;
                background-color: transparent;
            }
        """)
        
        # Configure columns
        header = self.task_list.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Task column stretches
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)  # Category fixed width
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)  # Due Date fixed width
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)  # Actions fixed width
        header.resizeSection(1, 100)  # Set Category column to 100px width
        header.resizeSection(2, 100)  # Set Due Date column to 100px width
        header.resizeSection(3, 200)  # Set Actions column to 200px width
        
        # Enable sorting
        self.task_list.setSortingEnabled(True)
        
        # QTableWidget handles clicks automatically
        
        # Enable context menu
        self.task_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.task_list.customContextMenuRequested.connect(self.show_task_context_menu)
        
        # Disable double-click to prevent errors with QTableWidgetItem
        # self.task_list.itemDoubleClicked.connect(self.edit_task)
        
        
        # Set default sorting by due date (column 1) in ascending order
        # self.task_list.sortByColumn(1, Qt.SortOrder.AscendingOrder)  # Disabled to prevent widget loss
        
        # Store task styling data
        self.task_styling = {}

        # Add filter controls if available
        if hasattr(self, 'filter_layout'):
            layout.addLayout(self.filter_layout)

        layout.addWidget(self.task_list)
        
        # Quick add task
        add_layout = QHBoxLayout()
        self.taskInput = QLineEdit()
        self.taskInput.setPlaceholderText("Quick task...")
        self.taskInput.setStyleSheet("background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; padding: 8px 12px; border-radius: 6px;")
        self.taskInput.returnPressed.connect(self.add_task)
        add_layout.addWidget(self.taskInput)
        
        # Add due date input
        self.dueDateInput = QDateEdit()
        self.dueDateInput.setCalendarPopup(True)
        self.dueDateInput.setDate(QDate.currentDate())
        self.dueDateInput.setStyleSheet("background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; padding: 8px; border-radius: 6px;")
        add_layout.addWidget(self.dueDateInput)

        # Add category input
        self.categoryInput = QComboBox()
        self.categoryInput.addItems(["Business", "Personal"])
        self.categoryInput.setStyleSheet("background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; padding: 8px; border-radius: 6px;")
        add_layout.addWidget(self.categoryInput)

        # Add recurrence input
        self.recurrenceInput = QComboBox()
        self.recurrenceInput.addItems(["None", "Daily", "Weekly"])
        self.recurrenceInput.setStyleSheet("background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; padding: 8px; border-radius: 6px;")
        add_layout.addWidget(self.recurrenceInput)
        
        add_btn = QPushButton("Add")
        add_btn.setStyleSheet("""
            QPushButton {
                background-color: #FD6262;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #e85555;
            }
        """)
        add_btn.clicked.connect(self.add_task)
        add_layout.addWidget(add_btn)
        
        layout.addLayout(add_layout)
        
        # Archive completed tasks button
        archive_btn = QPushButton("Archive Completed Tasks")
        archive_btn.setStyleSheet("""
            QPushButton {
                background-color: #FD6262;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #e85555;
            }
        """)
        archive_btn.clicked.connect(self.archive_completed_tasks)
        layout.addWidget(archive_btn)
        
        # Load initial tasks
        self.load_tasks_filtered()
        
        return widget


    def edit_task(self, row, column=None):
        """Edit a task (including priority/tags/next-action/snooze)."""
        if not getattr(self, "task_list", None):
            return
        try:
            task_widget = self.task_list.cellWidget(row, 0)
            if not task_widget or not hasattr(task_widget, "task_data"):
                return
            td = task_widget.task_data
            task_id = int(td.get("id") or 0)
            if task_id <= 0:
                return

            # Load current task row from DB if available (to include new fields).
            task_row = None
            try:
                rows = self.db.list_tasks_rich(include_completed=True, include_snoozed=True, limit=2000)
                for r in rows:
                    if int(r.get("id") or 0) == task_id:
                        task_row = r
                        break
            except Exception:
                task_row = {
                    "id": task_id,
                    "task_text": td.get("text") or "",
                    "due_date": td.get("due_date"),
                    "category": td.get("category") or "Business",
                    "priority": td.get("priority") or 0,
                    "tags_json": td.get("tags_json") or "[]",
                    "next_action_date": td.get("next_action_date"),
                    "snoozed_until": td.get("snoozed_until"),
                }

            from gui.task_edit_dialog import TaskEditDialog

            dlg = TaskEditDialog(parent=self, task=task_row or {})
            from PyQt6.QtWidgets import QDialog
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            vals = dlg.values()
            if not vals.get("task_text"):
                QMessageBox.warning(self, "Error", "Task text cannot be empty")
                return
            self.db.update_task_by_id(task_id, **vals)
            self.load_tasks_filtered()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to edit task: {str(e)}")

    def delete_task(self, row, column=None):
        """Delete a task."""
        if not getattr(self, "task_list", None):
            return
        try:
            # Get task data from the task widget
            task_widget = self.task_list.cellWidget(row, 0)
            if not task_widget or not hasattr(task_widget, 'task_data'):
                return
            
            task_data = task_widget.task_data
            task_text = task_data['text']  # Changed from 'task_text' to 'text'
            
            reply = QMessageBox.question(self, "Delete Task",
                                       f"Are you sure you want to delete '{task_text}'?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            
            if reply == QMessageBox.StandardButton.Yes:
                task_id = task_data['id']
                try:
                    if hasattr(self.db, "delete_task_by_id"):
                        self.db.delete_task_by_id(int(task_id))
                    else:
                        db_name = DATABASE_PATH
                        with sqlite3.connect(db_name) as conn:
                            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
                            conn.commit()
                except Exception:
                    db_name = DATABASE_PATH
                    with sqlite3.connect(db_name) as conn:
                        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
                        conn.commit()
                
                # Remove the row from the table
                self.task_list.removeRow(row)
                    
        except Exception as e:
            print(f"Error deleting task: {e}")
            QMessageBox.critical(self, "Error", f"Failed to delete task: {str(e)}")

    def show_task_context_menu(self, position):
        """Show context menu for task items."""
        if not getattr(self, "task_list", None):
            return
        item = self.task_list.itemAt(position)
        if item is None:
            return

        # Get row index (item may be in any column)
        row = item.row()
        task_widget = self.task_list.cellWidget(row, 0)
        if not task_widget or not hasattr(task_widget, "task_data"):
            return
        task_id = int(task_widget.task_data.get("id") or 0)
        if task_id <= 0:
            return
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction
        
        context_menu = QMenu(self)
        
        # Edit action
        edit_action = QAction("Edit Task", self)
        edit_action.triggered.connect(lambda: self.edit_task(row, 0))
        context_menu.addAction(edit_action)

        # Push due date forward (same as Due +1d / +3d on the row)
        due_raw = str(task_widget.task_data.get("due_date") or "").strip()

        snooze1_action = QAction("Due date +1 day", self)
        snooze1_action.triggered.connect(
            lambda: (
                self.db.update_task_by_id(
                    task_id,
                    due_date=bump_task_due_date_mmddyyyy(due_raw, days=1),
                    snoozed_until=None,
                ),
                self.load_tasks_filtered(),
            )
        )
        context_menu.addAction(snooze1_action)

        snooze3_action = QAction("Due date +3 days", self)
        snooze3_action.triggered.connect(
            lambda: (
                self.db.update_task_by_id(
                    task_id,
                    due_date=bump_task_due_date_mmddyyyy(due_raw, days=3),
                    snoozed_until=None,
                ),
                self.load_tasks_filtered(),
            )
        )
        context_menu.addAction(snooze3_action)

        unsnooze_action = QAction("Unsnooze", self)
        unsnooze_action.triggered.connect(lambda: (self.db.update_task_by_id(task_id, snoozed_until=None), self.load_tasks_filtered()))
        context_menu.addAction(unsnooze_action)
        
        # Delete action
        delete_action = QAction("Delete Task", self)
        delete_action.triggered.connect(lambda: self.delete_task(row, 0))
        context_menu.addAction(delete_action)
        
        # Show menu
        context_menu.exec(self.task_list.mapToGlobal(position))


    def archive_completed_tasks(self):
        """Archive completed tasks."""
        if not getattr(self, "task_list", None):
            return
        try:
            db_name = DATABASE_PATH
            with sqlite3.connect(db_name) as conn:
                # Get completed tasks with all fields
                cursor = conn.execute("SELECT task_text, due_date, category, recurrence, completed, session_id FROM tasks WHERE completed = 1")
                completed_tasks = cursor.fetchall()
                
                if completed_tasks:
                    # Archive each task using the database method
                    for task_text, due_date, category, recurrence, completed, session_id in completed_tasks:
                        # Use the database method to archive
                        self.db.archive_task(task_text, due_date, category, recurrence, completed)
                    
                    # Delete from active tasks
                    conn.execute("DELETE FROM tasks WHERE completed = 1")
                    conn.commit()
                    
                    print(f"Archived {len(completed_tasks)} completed tasks")
                    self.load_tasks_filtered()  # Refresh the display
                else:
                    print("No completed tasks to archive")
        except Exception as e:
            print(f"Error archiving tasks: {e}")

    def update_task_status(self, task_id, completed, row=None):
        """Update task completion status in database."""
        start_time = time.time()
        print(f"TIMING: update_task_status START for task_id {task_id}, completed {completed}, row {row} at {start_time:.6f}")
        
        # Skip if we're currently loading tasks to prevent widget conflicts
        if hasattr(self, '_loading_tasks') and self._loading_tasks:
            print(f"TIMING: Skipping update_task_status during loading at {time.time():.6f}")
            return
            
        try:
            try:
                if hasattr(self.db, "update_task_by_id"):
                    self.db.update_task_by_id(int(task_id), completed=1 if completed else 0)
                else:
                    db_name = DATABASE_PATH
                    with sqlite3.connect(db_name) as conn:
                        conn.execute("UPDATE tasks SET completed = ? WHERE id = ?", (completed, task_id))
                        conn.commit()
            except Exception:
                db_name = DATABASE_PATH
                with sqlite3.connect(db_name) as conn:
                    conn.execute("UPDATE tasks SET completed = ? WHERE id = ?", (completed, task_id))
                    conn.commit()
            
            # Find the row with this task and update styling
            print(f"TIMING: About to search for task_id {task_id} at {time.time():.6f}")
            for row in range(self.task_list.rowCount()):
                task_widget = self.task_list.cellWidget(row, 0)
                if task_widget and hasattr(task_widget, 'task_data') and task_widget.task_data['id'] == task_id:
                    due_date_item = self.task_list.item(row, 2)  # Column 2 is the due date column
                    if due_date_item:
                        due_date = due_date_item.text()
                        print(f"TIMING: About to call apply_task_styling_css from update_task_status for row {row} at {time.time():.6f}")
                        self.apply_task_styling_css(row, due_date, completed)
                        break
        except Exception as e:
            print(f"Error updating task status: {e}")

    def on_task_double_clicked(self, item):
        task_text = item.data(Qt.ItemDataRole.UserRole)
        if task_text:
            # Use the same database path as the main application
            db_name = DATABASE_PATH
                
            with sqlite3.connect(db_name) as conn:
                conn.execute("""
                    UPDATE tasks SET completed = 1 WHERE task = ?
                """, (task_text,))
                conn.commit()
            self.load_tasks_filtered()

    def create_briefing_widget(self):
        """Create the daily briefing widget."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Header with Morning Planning button
        header_layout = QHBoxLayout()
        briefing_header = QLabel("Morning Planning")
        briefing_header.setStyleSheet("color: #e8eaed; font-weight: 600; padding: 3px; background-color: transparent; border: none; font-size: 13px;")
        header_layout.addWidget(briefing_header)
        header_layout.addStretch()
        
        gen_btn = QPushButton("Generate Plan")
        gen_btn.clicked.connect(self.generate_morning_plan)
        header_layout.addWidget(gen_btn)
        layout.addLayout(header_layout)
        
        # Briefing display
        self.briefing_display = QTextBrowser()
        self.briefing_display.setStyleSheet("background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; border-radius: 6px; font-size: 13px;")
        self.briefing_display.setReadOnly(True)
        self.briefing_display.setPlaceholderText("Loading daily briefing...")
        self.briefing_display.setOpenExternalLinks(True)
        layout.addWidget(self.briefing_display)
        
        return widget

    def create_schedule_widget(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Header
        schedule_header = QLabel("Today's Schedule")
        schedule_header.setStyleSheet("color: #e8eaed; font-weight: 600; padding: 3px; background-color: transparent; border: none; font-size: 13px;")
        schedule_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        schedule_header.setMaximumHeight(25)
        layout.addWidget(schedule_header)
        
        # Schedule display
        self.schedule_display = QTextBrowser()
        self.schedule_display.setStyleSheet("background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; border-radius: 6px;")
        self.schedule_display.setReadOnly(True)
        self.schedule_display.setPlaceholderText("Loading schedule...")
        layout.addWidget(self.schedule_display)
        
        return widget

    def create_news_widget(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Header row: title + Refresh News
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        news_header = QLabel("News Feed")
        news_header.setStyleSheet("color: #e8eaed; font-weight: 600; padding: 3px; background-color: transparent; border: none; font-size: 13px;")
        news_header.setMaximumHeight(25)
        header_row.addWidget(news_header)
        header_row.addStretch()
        refresh_news_btn = QPushButton("Refresh News")
        refresh_news_btn.clicked.connect(self.refresh_news_feed)
        refresh_news_btn.setStyleSheet("font-size: 11px; padding: 2px 8px;")
        header_row.addWidget(refresh_news_btn)
        layout.addLayout(header_row)

        # Settings row
        settings_row = QHBoxLayout()
        settings_row.setContentsMargins(0, 0, 0, 0)
        settings_row.setSpacing(6)
        settings_label = QLabel("Hide repeats:")
        settings_label.setStyleSheet("color: #9aa0a6; font-size: 11px;")
        settings_row.addWidget(settings_label)

        self.news_suppress_combo = QComboBox()
        self.news_suppress_combo.addItems(["1 day", "2 days", "3 days", "7 days"])
        settings_row.addWidget(self.news_suppress_combo)

        max_label = QLabel("Max items:")
        max_label.setStyleSheet("color: #9aa0a6; font-size: 11px;")
        settings_row.addWidget(max_label)

        self.news_max_items_combo = QComboBox()
        self.news_max_items_combo.addItems(["5", "8", "10"])
        settings_row.addWidget(self.news_max_items_combo)
        settings_row.addStretch()
        layout.addLayout(settings_row)

        # Load persisted setting
        try:
            val = self.db.get_setting("news_suppress_days", "2")
            days = int(val) if val is not None else 2
        except Exception:
            days = 2
        self.news_suppress_days = days
        idx_map = {1: 0, 2: 1, 3: 2, 7: 3}
        self.news_suppress_combo.setCurrentIndex(idx_map.get(days, 1))

        # Load max items setting (default 8)
        try:
            val = self.db.get_setting("news_display_limit", "8")
            max_items = int(val) if val is not None else 8
        except Exception:
            max_items = 8
        if max_items not in (5, 8, 10):
            max_items = 8
        self.news_display_limit = max_items
        idx_map2 = {5: 0, 8: 1, 10: 2}
        self.news_max_items_combo.setCurrentIndex(idx_map2.get(max_items, 1))

        def _on_suppress_changed(_text):
            try:
                text = self.news_suppress_combo.currentText()
                d = int(text.split()[0])
                self.news_suppress_days = d
                self.db.set_setting("news_suppress_days", str(d))
                self.display_stored_news()
            except Exception:
                pass

        self.news_suppress_combo.currentTextChanged.connect(_on_suppress_changed)

        def _on_max_items_changed(_text):
            try:
                d = int(self.news_max_items_combo.currentText().strip())
                if d not in (5, 8, 10):
                    d = 8
                self.news_display_limit = d
                self.db.set_setting("news_display_limit", str(d))
                self.display_stored_news()
            except Exception:
                pass

        self.news_max_items_combo.currentTextChanged.connect(_on_max_items_changed)
        
        # News display
        self.news_display = QTextBrowser()
        self.news_display.setStyleSheet("background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; border-radius: 6px; font-size: 13px;")
        self.news_display.setReadOnly(True)
        self.news_display.setPlaceholderText("Loading news...")
        self.news_display.setOpenExternalLinks(True)
        layout.addWidget(self.news_display)
        
        # Auto-refresh timer (every hour)
        self.news_timer = QTimer()
        self.news_timer.timeout.connect(self.load_news)
        self.news_timer.start(3600000)  # 1 hour
        
        # Cleanup timer (every 24 hours)
        self.news_cleanup_timer = QTimer()
        self.news_cleanup_timer.timeout.connect(self.cleanup_old_news)
        self.news_cleanup_timer.start(86400000)  # 24 hours
        
        return widget

    def create_important_emails_widget(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        header_row = QHBoxLayout()
        header = QLabel("Important Emails")
        header.setStyleSheet("color: #e8eaed; font-weight: 600; padding: 3px; background-color: transparent; border: none; font-size: 13px;")
        header_row.addWidget(header)
        header_row.addStretch(1)

        rules_btn = QPushButton("Email rules…")
        rules_btn.setStyleSheet("background-color: #3a3b3e; color: #e8eaed; border: 1px solid #2e2f32; padding: 6px 10px; border-radius: 6px; font-size: 11px;")
        rules_btn.clicked.connect(self.open_email_rules)
        header_row.addWidget(rules_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.load_important_emails)
        header_row.addWidget(refresh_btn)

        layout.addLayout(header_row)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)

        self.unreplied_only_client = QCheckBox("Only client-related")
        self.unreplied_only_client.setChecked(True)
        self.unreplied_only_client.stateChanged.connect(self.load_important_emails)
        controls.addWidget(self.unreplied_only_client)

        controls.addStretch(1)
        layout.addLayout(controls)

        self.unreplied_table = QTableWidget(0, 7)
        self.unreplied_table.setHorizontalHeaderLabels(["From", "Subject", "Why Important", "Client", "Project", "Age", "Actions"])
        self.unreplied_table.verticalHeader().setVisible(False)
        self.unreplied_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.unreplied_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        hdr = self.unreplied_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.unreplied_table, 1)

        return widget

    def create_unreplied_emails_widget(self):
        return self.create_important_emails_widget()

    def open_email_rules(self):
        try:
            from gui.email_rules_dialog import EmailRulesDialog

            dlg = EmailRulesDialog(parent=self, db=self.db)
            res = dlg.exec()
            try:
                # If saved, reclassify recent emails so the view updates immediately.
                from PyQt6.QtWidgets import QDialog

                if res == QDialog.DialogCode.Accepted and hasattr(self.db, "reclassify_emails"):
                    self.db.reclassify_emails(days=30)
            except Exception:
                pass
            self.load_important_emails()
        except Exception as e:
            try:
                QMessageBox.warning(self, "Email Rules", f"Could not open rules:\n\n{type(e).__name__}: {e}")
            except Exception:
                pass

    def load_important_emails(self):
        try:
            self.unreplied_table.setRowCount(1)
            self.unreplied_table.setItem(0, 0, QTableWidgetItem("Refreshing important emails..."))
            only_cp = True
            try:
                only_cp = bool(self.unreplied_only_client.isChecked())
            except Exception:
                only_cp = True
            rows = self.db.list_important_emails(limit=30, days=30, include_triaged=False)
            if only_cp:
                rows = [
                    r for r in rows
                    if int(r.get("client_id") or 0) > 0
                    or int(r.get("is_client") or 0) == 1
                    or int(r.get("is_potential") or 0) == 1
                ]

            # Clear
            self.unreplied_table.setRowCount(0)
            if not rows:
                self.unreplied_table.setRowCount(1)
                self.unreplied_table.setItem(0, 0, QTableWidgetItem("No important emails"))
                return

            from datetime import datetime, UTC
            now = datetime.now(UTC).timestamp()

            for r in rows:
                email_id = str(r.get("id") or "")
                sender = str(r.get("sender") or "")
                subject = str(r.get("subject") or "")
                reasons = r.get("importance_reasons") or []
                why = "; ".join(str(x) for x in reasons[:2]) if reasons else "Flagged as important."
                client_name = str(r.get("client_name") or "")
                project_name = str(r.get("project_name") or "")
                ts = int(r.get("timestamp") or 0)
                age_h = 0
                try:
                    age_h = int(max(0, (now - ts) // 3600))
                except Exception:
                    age_h = 0

                row = self.unreplied_table.rowCount()
                self.unreplied_table.insertRow(row)
                it_from = QTableWidgetItem(sender)
                it_from.setData(Qt.ItemDataRole.UserRole, email_id)
                self.unreplied_table.setItem(row, 0, it_from)
                self.unreplied_table.setItem(row, 1, QTableWidgetItem(subject))
                why_item = QTableWidgetItem(why)
                why_item.setToolTip(why)
                self.unreplied_table.setItem(row, 2, why_item)
                self.unreplied_table.setItem(row, 3, QTableWidgetItem(client_name))
                self.unreplied_table.setItem(row, 4, QTableWidgetItem(project_name))
                self.unreplied_table.setItem(row, 5, QTableWidgetItem(f"{age_h}h"))

                actions = QWidget()
                outer = QVBoxLayout(actions)
                outer.setContentsMargins(0, 0, 0, 0)
                outer.setSpacing(4)
                row_one = QHBoxLayout()
                row_one.setContentsMargins(0, 0, 0, 0)
                row_one.setSpacing(4)
                row_two = QHBoxLayout()
                row_two.setContentsMargins(0, 0, 0, 0)
                row_two.setSpacing(4)

                archive_btn = QPushButton("Archive")
                archive_btn.clicked.connect(lambda _=False, mid=email_id: self._set_email_triage_status(mid, "archived"))
                row_one.addWidget(archive_btn)

                unimportant_btn = QPushButton("Unimportant")
                unimportant_btn.clicked.connect(lambda _=False, mid=email_id: self._set_email_triage_status(mid, "unimportant"))
                row_one.addWidget(unimportant_btn)

                junk_btn = QPushButton("Junk")
                junk_btn.clicked.connect(lambda _=False, mid=email_id: self._set_email_triage_status(mid, "junk"))
                row_one.addWidget(junk_btn)

                link_client_btn = QPushButton("Link Client")
                link_client_btn.clicked.connect(lambda _=False, mid=email_id: self._link_email_client(mid))
                row_two.addWidget(link_client_btn)

                link_project_btn = QPushButton("Link Project")
                link_project_btn.clicked.connect(lambda _=False, mid=email_id: self._link_email_project(mid))
                row_two.addWidget(link_project_btn)

                outer.addLayout(row_one)
                outer.addLayout(row_two)
                self.unreplied_table.setCellWidget(row, 6, actions)

            self.unreplied_table.resizeRowsToContents()
        except Exception as e:
            try:
                self.unreplied_table.setRowCount(1)
                self.unreplied_table.setItem(0, 0, QTableWidgetItem(f"Error loading emails: {e}"))
            except Exception:
                pass

    def load_unreplied_emails(self):
        self.load_important_emails()

    def _set_email_triage_status(self, email_id: str, status: str):
        try:
            self.db.update_email_triage(
                str(email_id),
                triage_status=str(status),
                triage_source="manual",
            )
        except Exception as e:
            QMessageBox.warning(self, "Emails", f"Could not update email triage:\n\n{type(e).__name__}: {e}")
            return
        self.load_important_emails()

    def _link_email_client(self, email_id: str):
        try:
            clients = self.db.clients_list(active_only=True)
        except Exception as e:
            QMessageBox.warning(self, "Emails", f"Could not load clients:\n\n{type(e).__name__}: {e}")
            return
        if not clients:
            QMessageBox.information(self, "Emails", "No clients are available to link yet.")
            return
        labels = [str(c.get("name") or "") for c in clients]
        choice, ok = QInputDialog.getItem(self, "Link Email to Client", "Client", labels, 0, False)
        if not ok or not choice:
            return
        chosen = next((c for c in clients if str(c.get("name") or "") == str(choice)), None)
        if not chosen:
            return
        try:
            self.db.link_email_to_client(str(email_id), int(chosen.get("id")))
        except Exception as e:
            QMessageBox.warning(self, "Emails", f"Could not link client:\n\n{type(e).__name__}: {e}")
            return
        self.load_important_emails()

    def _link_email_project(self, email_id: str):
        try:
            projects = self.db.cos_get_projects()
        except Exception as e:
            QMessageBox.warning(self, "Emails", f"Could not load projects:\n\n{type(e).__name__}: {e}")
            return
        if not projects:
            QMessageBox.information(self, "Emails", "No projects are available to link yet.")
            return
        project_choices = []
        project_map = {}
        for project in projects:
            try:
                pid = int(project[0])
                name = str(project[1] or "").strip() or f"Project {pid}"
            except Exception:
                continue
            label = f"{pid}: {name}"
            project_choices.append(label)
            project_map[label] = pid
        choice, ok = QInputDialog.getItem(self, "Link Email to Project", "Project", project_choices, 0, False)
        if not ok or not choice:
            return
        try:
            self.db.link_email_to_project(str(email_id), int(project_map[choice]))
        except Exception as e:
            QMessageBox.warning(self, "Emails", f"Could not link project:\n\n{type(e).__name__}: {e}")
            return
        self.load_important_emails()

    def _mark_email_replied(self, email_id: str):
        self._set_email_triage_status(email_id, "archived")

    def load_tasks(self):
        if not getattr(self, "task_list", None):
            return
        start_time = time.time()
        print(f"TIMING: load_tasks START at {start_time:.6f}")
        # Flag to prevent update_task_status from running during loading
        self._loading_tasks = True
        try:
            self.task_list.setRowCount(0)  # Clear all rows
            print(f"TIMING: setRowCount(0) at {time.time():.6f}")
            
            # Use the same database path as the main application
            db_name = DATABASE_PATH
            
            # Check if database file exists
            import os
            if not os.path.exists(db_name):
                self.task_list.setRowCount(1)
                item = QTableWidgetItem("Database file not found")
                self.task_list.setItem(0, 0, item)
                return
            
            with sqlite3.connect(db_name) as conn:
                # Check if tasks table exists and has data
                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks';")
                if cursor.fetchone():
                    # Get all tasks (both complete and incomplete) ordered by due date (nearest first), then by creation date
                    cursor = conn.execute("""
                        SELECT id, task_text, due_date, category, recurrence, completed, session_id FROM tasks
                        ORDER BY 
                            CASE 
                                WHEN due_date IS NULL THEN 1 
                                ELSE 0 
                            END,
                            due_date ASC,
                            created_at DESC
                    """)
                    tasks = cursor.fetchall()
                    
                    if tasks:
                        for task_id, task_text, due_date, category, recurrence, completed, session_id in tasks:
                            # Add new row to table
                            row_position = self.task_list.rowCount()
                            self.task_list.insertRow(row_position)
                            print(f"TIMING: Processing task {task_id} at row {row_position} at {time.time():.6f}: {task_text[:30]}...")
                            
                            # Create task widget with checkbox and text for first column
                            task_widget = QWidget()
                            task_widget.setStyleSheet("QWidget { background-color: transparent; }")
                            task_layout = QHBoxLayout(task_widget)
                            task_layout.setContentsMargins(8, 0, 0, 0)
                            task_layout.setSpacing(8)
                            
                            # Add checkbox to task widget
                            checkbox = QCheckBox()
                            print(f"TIMING: About to setChecked for row {row_position} at {time.time():.6f}")
                            # Temporarily disconnect the signal to prevent update_task_status from running during loading
                            checkbox.blockSignals(True)
                            checkbox.setChecked(completed == 1)
                            checkbox.blockSignals(False)
                            print(f"TIMING: setChecked completed for row {row_position} at {time.time():.6f}")
                            checkbox.setStyleSheet("""
                                QCheckBox {
                                    color: #e8eaed;
                                    background-color: transparent;
                                }
                                QCheckBox::indicator {
                                    width: 16px;
                                    height: 16px;
                                    background-color: #22252c;
                                    border: 1px solid #2e2f32;
                                    border-radius: 3px;
                                }
                                QCheckBox::indicator:checked {
                                    background-color: #FD6262;
                                    border: 1px solid #FD6262;
                                }
                            """)
                            checkbox.stateChanged.connect(lambda state, tid=task_id, r=row_position: self.update_task_status(tid, state == Qt.CheckState.Checked.value, r))
                            task_layout.addWidget(checkbox)
                            
                            # Add task text label
                            task_label = QLabel(f"   {task_text}")
                            task_label.setStyleSheet("color: #e8eaed; background-color: transparent; border: none; font-size: 13px;")
                            task_layout.addWidget(task_label)
                            task_layout.addStretch()
                            
                            # Set task widget in first column
                            self.task_list.setCellWidget(row_position, 0, task_widget)
                            
                            # Set due date in second column
                            due_date_display = due_date if due_date else "No due date"
                            due_date_item = QTableWidgetItem(due_date_display)
                            due_date_item.setFlags(due_date_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                            self.task_list.setItem(row_position, 1, due_date_item)
                            
                            # Create action buttons widget
                            print(f"DEBUG: Creating actions widget for row {row_position}")
                            actions_widget = QWidget()
                            actions_widget.setStyleSheet("QWidget { background-color: transparent; }")
                            actions_widget.setObjectName(f"actions_widget_row_{row_position}_task_{task_id}")
                            actions_layout = QHBoxLayout(actions_widget)
                            actions_layout.setContentsMargins(0, 0, 0, 0)  # Remove all margins
                            actions_layout.setSpacing(8)
                            actions_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                            
                            # Edit button
                            edit_btn = QPushButton("Edit")
                            edit_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                            edit_btn.setMinimumSize(70, 35)
                            edit_btn.setMaximumSize(90, 45)
                            edit_btn.setStyleSheet("""
                                QPushButton {
                                    background-color: #FD6262;
                                    color: white;
                                    border: none;
                                    border-radius: 6px;
                                    font-size: 12px;
                                    font-weight: 500;
                                }
                                QPushButton:hover {
                                    background-color: #e85555;
                                }
                            """)
                            # Capture the row position by value to avoid lambda closure issues
                            edit_btn.clicked.connect(lambda checked, r=row_position: self.edit_task(r, 0))
                            
                            # Delete button
                            delete_btn = QPushButton("Delete")
                            delete_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                            delete_btn.setMinimumSize(80, 35)
                            delete_btn.setMaximumSize(110, 45)
                            delete_btn.setStyleSheet("""
                                QPushButton {
                                    background-color: #3a3b3e;
                                    color: #e8eaed;
                                    border: 1px solid #2e2f32;
                                    border-radius: 6px;
                                    font-size: 12px;
                                    font-weight: 500;
                                }
                                QPushButton:hover {
                                    background-color: #4a4a4e;
                                }
                            """)
                            # Capture the row position by value to avoid lambda closure issues
                            delete_btn.clicked.connect(lambda checked, r=row_position: self.delete_task(r, 0))
                            
                            actions_layout.addWidget(edit_btn)
                            actions_layout.addWidget(delete_btn)
                            actions_layout.addStretch()
                            
                            # Set the actions widget in the third column
                            print(f"TIMING: About to set actions widget for row {row_position} at {time.time():.6f}")
                            # Ensure the widget has the table as its parent
                            actions_widget.setParent(self.task_list)
                            self.task_list.setCellWidget(row_position, 2, actions_widget)
                            print(f"TIMING: Set actions widget for row {row_position} at {time.time():.6f}, task: {task_text[:30]}...")
                            # Verify the widget was actually set
                            verify_widget = self.task_list.cellWidget(row_position, 2)
                            print(f"TIMING: Verification - widget exists after set: {verify_widget is not None} at {time.time():.6f}")
                            
                            # Store task data in the task widget for later use
                            task_widget.task_data = {
                                'id': task_id,
                                'task_text': task_text,
                                'due_date': due_date,
                                'category': category,
                                'recurrence': recurrence,
                                'completed': completed,
                                'session_id': session_id
                            }
                            
                            # Apply color coding after item is fully set up
                            print(f"TIMING: About to apply_task_styling_css for row {row_position} at {time.time():.6f}")
                            self.apply_task_styling_css(row_position, due_date, completed)
                            print(f"TIMING: apply_task_styling_css completed for row {row_position} at {time.time():.6f}")
                            
                            # Process events to ensure UI updates
                            from PyQt6.QtWidgets import QApplication
                            QApplication.processEvents()
                            
                            # Check if widget still exists after processEvents
                            verify_after_events = self.task_list.cellWidget(row_position, 2)
                            print(f"TIMING: Widget exists after processEvents for row {row_position}: {verify_after_events is not None} at {time.time():.6f}")
                            
                    else:
                        self.task_list.setRowCount(1)
                        item = QTableWidgetItem("No tasks found")
                        self.task_list.setItem(0, 0, item)
                else:
                    print("Tasks table does not exist!")
                    self.task_list.setRowCount(1)
                    item = QTableWidgetItem("Tasks table not found in database")
                    self.task_list.setItem(0, 0, item)
        except Exception as e:
            print(f"Error loading tasks: {e}")
            import traceback
            traceback.print_exc()
            self.task_list.setRowCount(1)
            item = QTableWidgetItem(f"Error loading tasks: {str(e)}")
            self.task_list.setItem(0, 0, item)
        
        # Sort by due date after all tasks are loaded
        print(f"TIMING: About to sort table at {time.time():.6f}")
        print(f"DEBUG: Before sorting - checking all widgets:")
        for row in range(self.task_list.rowCount()):
            task_widget = self.task_list.cellWidget(row, 0)
            actions_widget = self.task_list.cellWidget(row, 2)
            due_date_item = self.task_list.item(row, 1)
            due_date = due_date_item.text() if due_date_item else "No date"
            task_id = task_widget.task_data['id'] if task_widget and hasattr(task_widget, 'task_data') else "No ID"
            print(f"  Row {row}: task_widget={task_widget is not None}, actions_widget={actions_widget is not None}, due_date={due_date}, task_id={task_id}")

        # Sort the table
        self.task_list.sortByColumn(1, Qt.SortOrder.AscendingOrder)

        print(f"TIMING: After sorting - checking all widgets at {time.time():.6f}")
        for row in range(self.task_list.rowCount()):
            task_widget = self.task_list.cellWidget(row, 0)
            actions_widget = self.task_list.cellWidget(row, 2)
            due_date_item = self.task_list.item(row, 1)
            due_date = due_date_item.text() if due_date_item else "No date"
            task_id = task_widget.task_data['id'] if task_widget and hasattr(task_widget, 'task_data') else "No ID"
            print(f"  Row {row}: task_widget={task_widget is not None}, actions_widget={actions_widget is not None}, due_date={due_date}, task_id={task_id}")

        print(f"TIMING: Sorting complete at {time.time():.6f}")
        
        # Clear the loading flag
        self._loading_tasks = False
        
        # Debug: Check if all rows have their widgets
        self.debug_check_widgets()
    
    def debug_check_widgets(self):
        """Debug method to check if all rows have their widgets properly set."""
        start_time = time.time()
        print(f"TIMING: debug_check_widgets START at {start_time:.6f}")
        print(f"DEBUG: Checking widgets for {self.task_list.rowCount()} rows...")
        for row in range(self.task_list.rowCount()):
            task_widget = self.task_list.cellWidget(row, 0)
            actions_widget = self.task_list.cellWidget(row, 2)
            due_date_item = self.task_list.item(row, 1)

            task_id = task_widget.task_data['id'] if task_widget and hasattr(task_widget, 'task_data') else "No ID"
            due_date = due_date_item.text() if due_date_item else "No date"
            print(f"Row {row}: task_widget={task_widget is not None}, actions_widget={actions_widget is not None}, due_date_item={due_date_item is not None}, task_id={task_id}, due_date={due_date} at {time.time():.6f}")
    
    def is_overdue(self, due_date_str):
        """Check if a due date is overdue."""
        if not due_date_str or due_date_str == "No due date":
            return False
        try:
            from PyQt6.QtCore import QDate
            due_date = QDate.fromString(due_date_str, "MM-dd-yyyy")
            return due_date < QDate.currentDate()
        except:
            return False
    
    def apply_task_styling_css(self, row, due_date, completed):
        """Apply minimal styling to ensure proper row spacing."""
        # Just set row height for proper button and text spacing
        self.task_list.setRowHeight(row, 50)

    def apply_task_styling(self, item, due_date, completed):
        """Apply color coding to task items based on due date and completion status."""
        from PyQt6.QtGui import QColor, QBrush
        
        # Debug print to see if this function is being called
        # print(f"Applying styling: due_date={due_date}, completed={completed}")
        
        # Store color info in the item data for debugging
        color_info = ""
        
        if completed == 1:
            # Completed tasks - grayed out with white text
            color_info = "completed"
            for i in range(3):
                item.setBackground(i, QBrush(QColor(80, 80, 80)))  # Medium gray background
                item.setForeground(i, QBrush(QColor(200, 200, 200)))  # Light gray text
        elif due_date:
            try:
                # Parse the due date
                if due_date != "No due date":
                    due_date_obj = datetime.strptime(due_date, "%m-%d-%Y")
                    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                    due_date_start = due_date_obj.replace(hour=0, minute=0, second=0, microsecond=0)
                    
                    if due_date_start < today:
                        # Overdue - dark red background with white text
                        color_info = "overdue"
                        for i in range(3):
                            item.setBackground(i, QBrush(QColor(150, 50, 50)))  # Bright red background
                            item.setForeground(i, QBrush(QColor(255, 255, 255)))  # White text
                    elif due_date_start == today:
                        # Due today - orange background with WHITE text
                        color_info = "due_today"
                        for i in range(3):
                            item.setBackground(i, QBrush(QColor(255, 165, 0)))  # Bright orange background
                            item.setForeground(i, QBrush(QColor(255, 255, 255)))  # WHITE text for readability
                    else:
                        # Future date - default styling with white text
                        color_info = "future"
                        for i in range(3):
                            item.setBackground(i, QBrush(QColor(50, 50, 50)))  # Dark gray background
                            item.setForeground(i, QBrush(QColor(255, 255, 255)))  # White text
                else:
                    # No due date - default styling
                    color_info = "no_date"
                    for i in range(3):
                        item.setBackground(i, QBrush(QColor(50, 50, 50)))
                        item.setForeground(i, QBrush(QColor(255, 255, 255)))
            except ValueError:
                # Invalid date format - default styling
                color_info = "invalid_date"
                for i in range(3):
                    item.setBackground(i, QBrush(QColor(50, 50, 50)))
                    item.setForeground(i, QBrush(QColor(255, 255, 255)))
        else:
            # No due date - default styling
            color_info = "no_date_default"
            for i in range(3):
                item.setBackground(i, QBrush(QColor(50, 50, 50)))
                item.setForeground(i, QBrush(QColor(255, 255, 255)))
        
        # Store color info for debugging
        item.setData(1, Qt.ItemDataRole.UserRole + 1, color_info)

    def load_schedule(self):
        try:
            if hasattr(self, "schedule_display"):
                self.schedule_display.setHtml(
                    "<div style='color: #9aa0a6; text-align: center; padding: 16px;'>Refreshing schedule...</div>"
                )
            # Check if we have access to calendar data
            if hasattr(self.chat_handler, 'data_fetcher'):
                data_fetcher = self.chat_handler.data_fetcher
            elif hasattr(self.chat_handler, 'chat_handler') and hasattr(self.chat_handler.chat_handler, 'data_fetcher'):
                data_fetcher = self.chat_handler.chat_handler.data_fetcher
            else:
                raise AttributeError("No data_fetcher found in chat_handler")
            
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            tomorrow = today + timedelta(days=1)
            time_min = today.strftime('%Y-%m-%dT%H:%M:%SZ')
            time_max = tomorrow.strftime('%Y-%m-%dT%H:%M:%SZ')
            
            events = data_fetcher.get_calendar_events(time_min, time_max)
            
            if events:
                schedule_html = "<div style='font-family: Segoe UI, Arial, sans-serif; color: #e8eaed;'>"
                schedule_html += "<h3 style='color: #6b8cae; margin-bottom: 8px;'>Today's Events</h3><ul style='list-style-type: none; padding: 0;'>"
                for event in events:
                    start = event['start'].get('dateTime', event['start'].get('date'))
                    if isinstance(start, str):
                        try:
                            parsed = parser.parse(start)
                            if 'T' in start:
                                start_time = parsed.strftime('%I:%M %p')
                            else:
                                start_time = 'All Day - ' + parsed.strftime('%b %d')
                        except:
                            start_time = start  # Fallback
                    else:
                        start_time = 'Unknown time'
                    summary = event.get('summary', 'No title')
                    schedule_html += f"<li style='margin-bottom: 10px;'><b>{start_time}:</b> {summary}</li>"
                schedule_html += "</ul>"
                schedule_html += "</div>"
                self.schedule_display.setHtml(schedule_html)
                self._set_cached_schedule_html(schedule_html)
            else:
                empty_html = "<div style='color: #e8eaed;'>No events scheduled for today</div>"
                self.schedule_display.setHtml(empty_html)
                self._set_cached_schedule_html(empty_html)
        except Exception as e:
            self.schedule_display.setHtml(f"<div style='color: #e8eaed;'>Error loading schedule: {str(e)}</div>")

    def load_news(self):
        try:
            print(f"Loading news... chat_handler type: {type(self.chat_handler)}")
            
            # Check if news widget exists before using it
            if not hasattr(self, 'news_display'):
                print("News widget not yet created, skipping load_news")
                return

            # Always render cached items first so startup/manual refresh stays populated.
            try:
                self.display_stored_news()
            except Exception:
                pass
            
            # Check if news was updated within the last hour
            from datetime import datetime, timezone, timedelta
            last_news_update = self.db.get_last_news_update()
            current_time = datetime.now(timezone.utc).timestamp()
            one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).timestamp()
            
            
            # If no timestamp exists (first run), proceed with update
            if last_news_update == 0:
                print("First run detected - proceeding with news update.")
            elif last_news_update > one_hour_ago:
                print(f"News was last updated {int((current_time - last_news_update) / 60)} minutes ago. Skipping update.")
                # Just display existing news instead of loading new
                self.display_stored_news()
                return
            else:
                print(f"News is older than 1 hour ({int((current_time - last_news_update) / 60)} minutes ago). Proceeding with update.")
            
            # Update timestamp immediately when starting news fetch
            self.db.update_last_news_update()
            try:
                self._set_startup_refresh_indicator(True)
            except Exception:
                pass
            
            # Use QThread to make API call without blocking UI
            self.news_thread = NewsWorker(self.chat_handler)
            self.news_thread.news_loaded.connect(self.on_news_loaded)
            self.news_thread.error_occurred.connect(self.on_news_error)
            self.news_thread.start()
                
        except Exception as e:
            print(f"Error starting news thread: {e}")
            if hasattr(self, 'news_display'):
                self.news_display.setHtml(f"<div style='color: #e8eaed;'>Error loading news: {str(e)}</div>")
    
    def _show_briefing_disabled(self):
        """Show disabled message when briefing/email is turned off in Settings."""
        try:
            if hasattr(self, 'briefing_display'):
                self.briefing_display.setHtml(
                    "<div style='color: #9aa0a6; text-align: center; padding: 20px;'>Daily briefing and email checking are currently disabled.</div>"
                )
        except Exception as e:
            print(f"Error showing briefing disabled: {e}")

    def load_daily_briefing(self):
        """Load and display daily briefing if it hasn't been shown today (runs in background thread)."""
        try:
            from core.app_preferences import is_briefing_and_email_disabled

            if is_briefing_and_email_disabled(self.db):
                self._show_briefing_disabled()
                return
            cached_html = self._get_cached_briefing_html_for_today()
            if cached_html:
                self.briefing_display.setHtml(cached_html)
                return
            if self._restore_briefing_from_raw_cache():
                return
            # Check if briefing widget exists
            if not hasattr(self, 'briefing_display'):
                print("Briefing widget not yet created, skipping load_daily_briefing")
                return
            
            # Show loading message
            self.briefing_display.setHtml("<div style='color: #e8eaed; text-align: center; padding: 20px;'>Loading daily briefing... (this may take a moment)</div>")
            
            # Use QThread to make briefing generation non-blocking
            if not hasattr(self, 'briefing_thread') or not self.briefing_thread.isRunning():
                self.briefing_thread = BriefingWorker(self.chat_handler)
                self.briefing_thread.briefing_loaded.connect(self.on_briefing_loaded)
                self.briefing_thread.error_occurred.connect(self.on_briefing_error)
                self.briefing_thread.start()
                # Guard against indefinite worker hangs so UI doesn't stay on loading forever.
                QTimer.singleShot(45000, self._briefing_load_timeout_check)
                
        except Exception as e:
            print(f"Error starting briefing thread: {e}")
            import traceback
            traceback.print_exc()
            if hasattr(self, 'briefing_display'):
                self.briefing_display.setHtml(f"<div style='color: #e8eaed;'>Error loading briefing: {str(e)}</div>")

    def _maybe_auto_generate_morning_plan(self):
        """Phase 5: auto-generate morning plan on first open of the day if enabled."""
        try:
            from core.app_preferences import is_briefing_and_email_disabled
            if is_briefing_and_email_disabled(self.db):
                return
            # Simple date check using existing last_run mechanism or a new setting
            last = self.db.get_setting("morning_plan_last_date") or ""
            today = datetime.now().strftime("%Y-%m-%d")
            if last != today:
                self.db.set_setting("morning_plan_last_date", today)
                self.generate_morning_plan()
        except Exception:
            pass

    def generate_morning_plan(self):
        """Trigger Morning Planning flow (replaces legacy briefing generation)."""
        try:
            from core.morning_planning import run_morning_planning
            from gui.morning_plan_review_dialog import MorningPlanReviewDialog

            result = run_morning_planning(self.db)
            dlg = MorningPlanReviewDialog(result, self)
            if dlg.exec() == 1:  # accepted
                # Phase 6: basic commit (reuses existing CoS action parsing for ADD_CAL_BLOCK etc.)
                self.db.approve_daily_plan(result.get("plan_date", ""))
                # In full impl: parse result['raw_output'] with parse_action_line and execute
                if hasattr(self, 'briefing_display'):
                    self.briefing_display.setHtml("<div style='color:#e8eaed; padding:20px;'>Morning plan approved and committed.</div>")
        except Exception as e:
            print(f"Error generating morning plan: {e}")
            import traceback
            traceback.print_exc()

    def _briefing_load_timeout_check(self):
        """If briefing worker is still running after timeout, fail-open the UI message."""
        try:
            if not hasattr(self, "briefing_thread"):
                return
            if not self.briefing_thread or not self.briefing_thread.isRunning():
                return
            if not hasattr(self, "briefing_display"):
                return
            cached_html = self._get_cached_briefing_html_for_today()
            if cached_html:
                self.briefing_display.setHtml(cached_html)
            else:
                self.briefing_display.setHtml(
                    "<div style='color: #e8eaed; text-align: center; padding: 20px;'>"
                    "Daily briefing is taking longer than expected. You can continue using the app and click Refresh to retry."
                    "</div>"
                )
        except Exception:
            pass
    
    def on_briefing_loaded(self, briefing, chat_handler_obj):
        """Called when briefing is loaded successfully in the worker thread."""
        # Use thread-safe UI update
        QTimer.singleShot(0, lambda: self._on_briefing_loaded_safe(briefing, chat_handler_obj))
    
    def _on_briefing_loaded_safe(self, briefing, chat_handler_obj):
        """Thread-safe version of on_briefing_loaded."""
        try:
            if not hasattr(self, 'briefing_display'):
                return

            # Keep dashboard briefing independent of local llama worker stability.
            html = self._render_briefing_to_html(str(briefing or ""), chat_handler_obj, use_llm=False)
            self.briefing_display.setHtml(html)
            self._set_cached_briefing_html_for_today(html)
        except Exception as e:
            print(f"Error in briefing display: {e}")
            import traceback
            traceback.print_exc()
    
    def on_briefing_error(self, error_message):
        """Called when briefing loading fails in the worker thread."""
        # Use thread-safe UI update
        QTimer.singleShot(0, lambda: self._on_briefing_error_safe(error_message))
    
    def _on_briefing_error_safe(self, error_message):
        """Thread-safe version of on_briefing_error."""
        try:
            if not hasattr(self, 'briefing_display'):
                return
            
            if "already shown today" in error_message:
                cached_html = self._get_cached_briefing_html_for_today()
                if cached_html:
                    self.briefing_display.setHtml(cached_html)
                elif self._restore_briefing_from_raw_cache():
                    return
                else:
                    self.briefing_display.setHtml(
                        "<div style='color: #e8eaed; text-align: center; padding: 20px;'>"
                        "No cached copy was found for today's briefing. Regenerating now..."
                        "</div>"
                    )
                    QTimer.singleShot(0, self.refresh_daily_briefing)
            else:
                self.briefing_display.setHtml(f"<div style='color: #e8eaed;'>Error loading briefing: {error_message}</div>")
        except Exception as e:
            print(f"Error displaying briefing error: {e}")

    def refresh_daily_briefing(self):
        """Force refresh the daily briefing (bypasses date check, runs in background thread)."""
        try:
            from core.app_preferences import is_briefing_and_email_disabled

            if is_briefing_and_email_disabled(self.db):
                self._show_briefing_disabled()
                return
            # Check if briefing widget exists
            if not hasattr(self, 'briefing_display'):
                return
            
            # Show loading message
            self.briefing_display.setHtml("<div style='color: #e8eaed; text-align: center; padding: 20px;'>Generating new briefing... (this may take a moment)</div>")
            self.db.set_setting("daily_briefing_cache_date", "")
            self.db.set_setting("daily_briefing_cache_html", "")
            
            # Create a worker that forces new briefing (calls daily_briefing directly, not start_briefing)
            if not hasattr(self, 'briefing_refresh_thread') or not self.briefing_refresh_thread.isRunning():
                # Create a custom worker for forced refresh
                class RefreshBriefingWorker(QThread):
                    briefing_loaded = pyqtSignal(str, object)
                    error_occurred = pyqtSignal(str)
                    
                    def __init__(self, chat_handler):
                        super().__init__()
                        self.chat_handler = chat_handler
                    
                    def run(self):
                        try:
                            briefing = None
                            chat_handler_obj = None
                            
                            # Force new briefing by calling daily_briefing directly
                            if hasattr(self.chat_handler, 'chat_handler') and hasattr(self.chat_handler.chat_handler, 'daily_briefing'):
                                chat_handler_obj = self.chat_handler.chat_handler
                                briefing = self.chat_handler.chat_handler.daily_briefing()
                            elif hasattr(self.chat_handler, 'daily_briefing'):
                                chat_handler_obj = self.chat_handler
                                briefing = self.chat_handler.daily_briefing()
                            
                            if briefing:
                                self.briefing_loaded.emit(briefing, chat_handler_obj)
                            else:
                                self.error_occurred.emit("Unable to generate briefing")
                        except Exception as e:
                            self.error_occurred.emit(f"Error: {str(e)}")
                
                self.briefing_refresh_thread = RefreshBriefingWorker(self.chat_handler)
                self.briefing_refresh_thread.briefing_loaded.connect(self.on_briefing_loaded)
                self.briefing_refresh_thread.error_occurred.connect(self.on_briefing_error)
                self.briefing_refresh_thread.start()
                
        except Exception as e:
            print(f"Error starting briefing refresh thread: {e}")
            import traceback
            traceback.print_exc()
            if hasattr(self, 'briefing_display'):
                self.briefing_display.setHtml(f"<div style='color: #e8eaed;'>Error loading briefing: {str(e)}</div>")

    def on_news_loaded(self, news_query):
        """Called when news is loaded successfully in the worker thread."""
        # Use thread-safe UI update
        QTimer.singleShot(0, lambda: self._on_news_loaded_safe(news_query))
    
    def _on_news_loaded_safe(self, news_query):
        """Thread-safe version of on_news_loaded."""
        try:
            print(f"on_news_loaded: Got news response: {news_query[:100]}...")
            
            # Process and store the news
            self.process_and_store_news(news_query)
            
            # Display the stored news
            self.display_stored_news()
            self._set_startup_refresh_indicator(False)
            
        except Exception as e:
            print(f"Error processing loaded news: {e}")
            if hasattr(self, 'news_display'):
                self.news_display.setHtml(f"<div style='color: #e8eaed;'>Error processing news: {str(e)}</div>")
    
    def on_news_error(self, error_message):
        """Called when there's an error loading news in the worker thread."""
        # Use thread-safe UI update
        QTimer.singleShot(0, lambda: self._on_news_error_safe(error_message))
    
    def _on_news_error_safe(self, error_message):
        """Thread-safe version of on_news_error."""
        print(f"News error: {error_message}")
        self._set_startup_refresh_indicator(False)
        if hasattr(self, 'news_display'):
            # Check if it's a credit limit error
            if "credit" in error_message.lower() or "spending limit" in error_message.lower():
                self.news_display.setHtml(
                    "<div style='color: #e8eaed; text-align: center; padding: 20px;'>"
                    "<span style='color: #d4a84b;'>⚠️ Grok API credits exhausted</span><br>"
                    "Please add credits to your xAI account to continue fetching news.<br>"
                    "<small style='color: #9aa0a6;'>Showing cached news below...</small></div>"
                )
                # Still try to show cached news
                self.display_stored_news()
            else:
                self.news_display.setHtml(f"<div style='color: #e8eaed;'>{error_message}</div>")

    def parse_published_date(self, date_str):
        """Parse published date string into datetime object."""
        if not date_str:
            return None
            
        try:
            # Try to parse with dateutil first (handles many formats)
            from dateutil import parser
            return parser.parse(date_str, fuzzy=True)
        except:
            pass
            
        try:
            # Try common date formats
            from datetime import datetime
            formats = [
                '%Y-%m-%d',
                '%Y-%m-%d %H:%M:%S',
                '%B %d, %Y',
                '%b %d, %Y',
                '%d %B %Y',
                '%d %b %Y',
                '%Y-%m-%dT%H:%M:%S',
                '%Y-%m-%dT%H:%M:%SZ'
            ]
            
            for fmt in formats:
                try:
                    return datetime.strptime(date_str, fmt)
                except ValueError:
                    continue
        except:
            pass
            
        return None

    def is_likely_recent_by_heuristics(self, date_str):
        """Use heuristics to determine if a date string likely represents recent news."""
        if not date_str:
            return True  # No date means we keep it
            
        date_str_lower = date_str.lower()
        
        # Check for recent indicators
        recent_indicators = [
            'today', 'yesterday', 'this week', 'this month',
            'recent', 'latest', 'new', 'just', 'now'
        ]
        
        for indicator in recent_indicators:
            if indicator in date_str_lower:
                return True
        
        # Check for vague recent dates
        vague_recent = [
            'approximately', 'around', 'about', 'roughly'
        ]
        
        for vague in vague_recent:
            if vague in date_str_lower:
                # If it's vague but mentions recent time periods, include it
                if any(period in date_str_lower for period in ['week', 'day', 'ago', '2025']):
                    return True
        
        # Check for 2025 dates (current year)
        if '2025' in date_str:
            return True
            
        # Check for September 2025 (current month)
        if 'september' in date_str_lower and '2025' in date_str:
            return True
            
        # Check for August 2025 (previous month, still recent)
        if 'august' in date_str_lower and '2025' in date_str:
            return True
        
        # Exclude clearly old dates
        old_indicators = ['2023', '2024', '2022', '2021', '2020']
        for old in old_indicators:
            if old in date_str:
                return False
                
        # If we can't determine, err on the side of including it
        return True

    def format_display_date(self, date_str):
        """Format a date string for better display."""
        if not date_str:
            return "Unknown"
            
        # Try to parse the date first
        parsed_date = self.parse_published_date(date_str)
        if parsed_date:
            # If we can parse it, show a clean format
            return parsed_date.strftime('%B %d, %Y')
        
        # If we can't parse it, clean up the original string
        cleaned = date_str.strip()
        
        # Remove common prefixes that make dates look messy
        prefixes_to_remove = [
            'Published: ', 'Date: ', 'Posted: ', 'Updated: ',
            'approximately ', 'around ', 'about ', 'roughly '
        ]
        
        for prefix in prefixes_to_remove:
            if cleaned.lower().startswith(prefix.lower()):
                cleaned = cleaned[len(prefix):].strip()
        
        # Capitalize first letter
        if cleaned:
            cleaned = cleaned[0].upper() + cleaned[1:]
        
        return cleaned

    def sort_news_by_date(self, news_items):
        """Sort news items by published date (newest first)."""
        def get_sort_key(item):
            # Support both shapes:
            # - legacy: (title, content, url, source, published_date, created_at)
            # - dashboard (suppressed): (id, title, content, url, source, published_date, created_at)
            if len(item) == 7:
                _, title, content, url, source, published_date, created_at = item
            else:
                title, content, url, source, published_date, created_at = item
            
            if published_date:
                # Try to parse the published date
                parsed_date = self.parse_published_date(published_date)
                if parsed_date:
                    # Use parsed date for sorting (newest first = negative timestamp)
                    return -parsed_date.timestamp()
                else:
                    # If we can't parse, use heuristics to estimate recency
                    if self.is_likely_recent_by_heuristics(published_date):
                        # Recent items get higher priority (lower negative number)
                        return -999999999  # Very recent
                    else:
                        # Older items get lower priority
                        return -1
            else:
                # No published date, use created_at as fallback
                try:
                    from datetime import datetime
                    created_dt = datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S')
                    return -created_dt.timestamp()
                except:
                    # If we can't parse created_at either, put it at the end
                    return 0
        
        # Sort by the key (newest first)
        sorted_items = sorted(news_items, key=get_sort_key)
        
        # News items sorted by date (newest first)
        
        return sorted_items

    def is_valid_news_item(self, title, content):
        """Validate that a news item is properly formatted and not malformed."""
        if not title or not content:
            return False
            
        # Check for malformed titles
        malformed_patterns = [
            r'^```',  # Starts with ```
            r'^\* ',   # Starts with * (bullet point)
            r'^\[',    # Starts with [ (JSON array start)
            r'^\{',    # Starts with { (JSON object start)
            r'^null$', # Just "null"
            r'^undefined$', # Just "undefined"
        ]
        
        for pattern in malformed_patterns:
            if re.match(pattern, title.strip(), re.IGNORECASE):
                print(f"Rejecting malformed title: '{title[:50]}...' (matches pattern: {pattern})")
                return False
        
        # Check for very short titles (likely not real news)
        if len(title.strip()) < 10:
            print(f"Rejecting title too short: '{title[:50]}...'")
            return False
            
        # Check for very short content (likely not real news)
        if len(content.strip()) < 20:
            print(f"Rejecting content too short: '{content[:50]}...'")
            return False
            
        return True

    def process_and_store_news(self, news_results):
        # Processing news results
        
        stored_count = 0
        source_urls = []

        def _extract_candidate_urls(text: str) -> list[str]:
            found = []
            if not text:
                return found
            # Markdown links first: [label](https://...)
            for m in re.findall(r"\[[^\]]*\]\((https?://[^)\s]+)\)", text or "", flags=re.IGNORECASE):
                cleaned = str(m).strip().rstrip(".,;)]}\"'")
                if self.is_valid_news_url(cleaned):
                    found.append(cleaned)
            # Plain URLs.
            for m in re.findall(r"https?://[^\s<>\"]+", text or "", flags=re.IGNORECASE):
                cleaned = str(m).strip().rstrip(".,;)]}\"'")
                if self.is_valid_news_url(cleaned):
                    found.append(cleaned)
            # Preserve order, drop duplicates.
            deduped = []
            seen = set()
            for u in found:
                if u in seen:
                    continue
                seen.add(u)
                deduped.append(u)
            return deduped
        
        try:
            # First, try to parse as JSON
            import json
            
            # Clean the response to extract JSON
            response_clean = news_results.strip()
            source_urls.extend(_extract_candidate_urls(response_clean))
            
            # Look for JSON array in the response
            json_match = re.search(r'\[.*\]', response_clean, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                try:
                    news_items = json.loads(json_str)
                    print(f"Successfully parsed JSON with {len(news_items)} items")
                    
                    for item in news_items:
                        if isinstance(item, dict) and 'title' in item:
                            title = item.get('title', '').strip()
                            content = item.get('content', '').strip()
                            url = item.get('url', '').strip() or None
                            source = item.get('source', '').strip() or None
                            published_date = item.get('published_date', '').strip() or None
                            if not url:
                                local_urls = _extract_candidate_urls(content)
                                if local_urls:
                                    url = local_urls[0]
                            if not url and source_urls:
                                # Best-effort link preservation when model omits per-item URL.
                                url = source_urls.pop(0)
                            
                            # Validate the news item before storing
                            if self.is_valid_news_item(title, content):
                                print(f"Processing news item: '{title[:50]}...'")
                                
                                # Clean URL if provided
                                if url:
                                    # Remove extra text in parentheses from URLs
                                    url = re.sub(r'\s*\([^)]*\)', '', url).strip()
                                    # Validate URL after cleaning
                                    if not self.is_valid_news_url(url):
                                        print(f"Invalid URL detected after cleaning, removing: {url}")
                                        url = None
                                    else:
                                        # Canonicalize URLs early (strip tracking params/fragments) for better dedup.
                                        try:
                                            from core.news_dedup import canonicalize_url
                                            url = canonicalize_url(url) or url
                                        except Exception:
                                            pass
                                        print(f"Cleaned URL: {url}")
                                
                                if not self.db.check_news_exists(title, url):
                                    success = self.db.store_news_item(title, content, url, source, published_date)
                                    if success:
                                        stored_count += 1
                                        print(f"Stored news item: '{title[:50]}...'")
                                    else:
                                        print(f"Failed to store news item: '{title[:50]}...'")
                                else:
                                    print(f"News item already exists: '{title[:50]}...'")
                    
                    # News items stored successfully
                    return
                    
                except json.JSONDecodeError as e:
                    print(f"JSON parsing failed: {e}")
                    # Fall back to text parsing
                    
        except Exception as e:
            print(f"Error in JSON parsing: {e}")
            # Fall back to text parsing
            
        # Fallback: Parse as text (original method)
        # Falling back to text parsing
        cleaned_text = news_results or ""
        cleaned_text = re.sub(r"\n?\s*Sources:\s*.+$", "", cleaned_text, flags=re.IGNORECASE | re.DOTALL)
        news_items = cleaned_text.split('\n\n')
        
        for item in news_items:
            if item.strip():
                lines = item.strip().split('\n')
                if len(lines) >= 2:
                    title = lines[0].strip()
                    content = '\n'.join(lines[1:]).strip()
                    
                    url_match = re.search(r'https?://[^\s]+', content)
                    if url_match:
                        url = url_match.group(0)
                        content = re.sub(r'https?://[^\s]+', '', content).strip()
                    else:
                        url = None
                    if url:
                        try:
                            from core.news_dedup import canonicalize_url
                            url = canonicalize_url(url) or url
                        except Exception:
                            pass
                    
                    print(f"Processing news item: '{title[:50]}...'")
                    if not self.db.check_news_exists(title, url):
                        success = self.db.store_news_item(title, content, url)
                        if success:
                            stored_count += 1
                            print(f"Stored news item: '{title[:50]}...'")
                        else:
                            print(f"Failed to store news item: '{title[:50]}...'")
                    else:
                        print(f"News item already exists: '{title[:50]}...'")
        
        # News items stored successfully

    def _get_news_seed_keywords(self, max_keywords: int = 8) -> list[str]:
        """Best-effort personalization keywords for news relevance."""
        subjects = []
        try:
            if hasattr(self.chat_handler, "chat_handler") and hasattr(self.chat_handler.chat_handler, "data_fetcher"):
                df = self.chat_handler.chat_handler.data_fetcher
                if hasattr(df, "get_gmail_news_seeds"):
                    subjects = df.get_gmail_news_seeds(days=3, max_messages=20) or []
        except Exception:
            subjects = []

        import re
        stop = {
            "fda", "and", "the", "for", "with", "your", "from", "this", "that",
            "you", "are", "new", "update", "updates", "weekly", "daily",
            "newsletter", "news",
        }
        counts = {}
        for s in subjects:
            for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9\\-]{2,}", s or ""):
                lw = w.lower()
                if lw in stop:
                    continue
                counts[lw] = counts.get(lw, 0) + 1
        return [w for w, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:max_keywords]]

    def _score_news_item(self, title: str, content: str, keywords: list[str]) -> int:
        text = f"{title or ''} {content or ''}".lower()
        score = 0
        # Always-relevant domain boosts
        for kw in ("fda", "guidance", "draft", "ivd", "samd", "samd", "pccp", "clinical", "medtech", "medical device"):
            if kw in text:
                score += 1
        # Personalization boosts
        for kw in keywords:
            if kw and kw.lower() in text:
                score += 3
        return score

    def display_stored_news(self):
        try:
            
            # Check if news widget exists before using it
            if not hasattr(self, 'news_display'):
                # News widget not yet created, skipping display_stored_news
                return
            
            # Clean up old news items first
            self.db.cleanup_old_news(days=7)
            # Suppress repeats that have been shown recently
            suppress_days = getattr(self, "news_suppress_days", 2) or 2
            # Pull more candidates than we display so suppression + rerank still yields a full set.
            recent_news = self.db.get_news_for_dashboard(days=7, suppress_days=int(suppress_days), limit=200)
            # If daily briefing ran first, it may have marked top items as "shown" which can
            # suppress everything from the dashboard feed. Fail open: show unsuppressed feed.
            if (not recent_news) and int(suppress_days) > 0:
                try:
                    recent_news = self.db.get_news_for_dashboard(days=7, suppress_days=0, limit=200)
                except Exception:
                    recent_news = recent_news
            
            # Filter out items with old published dates (older than 7 days)
            from datetime import datetime, timedelta
            cutoff_date = datetime.now() - timedelta(days=7)
            filtered_news = []
            
            for item in recent_news:
                # DB returns id + fields
                news_id, title, content, url, source, published_date, created_at = item
                should_include = False
                
                if published_date:
                    # Try to parse the published date more intelligently
                    parsed_date = self.parse_published_date(published_date)
                    if parsed_date:
                        # If we successfully parsed a date, check if it's recent
                        if parsed_date >= cutoff_date:
                            should_include = True
                            # Including item with parsed date
                    else:
                        # If we can't parse the date, use heuristics
                        should_include = self.is_likely_recent_by_heuristics(published_date)
                else:
                    # If no published date, keep the item (it was recently created)
                    should_include = True
                
                if should_include:
                    filtered_news.append(item)
            
            recent_news = filtered_news
            # Retrieved news items from database
            
            if recent_news:
                # Sort news items by published date (newest first)
                display_news = self.sort_news_by_date(recent_news)

                # Stable re-rank by relevance (keeps date order within same score)
                seed_keywords = self._get_news_seed_keywords()
                display_news.sort(
                    key=lambda it: -self._score_news_item(
                        it[1] if len(it) == 7 else it[0],
                        it[2] if len(it) == 7 else it[1],
                        seed_keywords,
                    )
                )

                # Apply display limit (default 8; user-configurable)
                lim = int(getattr(self, "news_display_limit", 8) or 8)
                if lim < 1:
                    lim = 8
                display_news = display_news[:lim]
                
                news_text = "<div style='color: #e8eaed; font-family: Segoe UI, Arial, sans-serif;'>"
                news_text += "<h3 style='color: #6b8cae; margin-bottom: 15px;'>Latest News</h3>"
                
                shown_ids = []
                for news_id, title, content, url, source, published_date, created_at in display_news:
                    shown_ids.append(news_id)
                    if not url and content:
                        maybe = re.search(r"https?://[^\s<>\"]+", content or "", re.IGNORECASE)
                        if maybe:
                            cand = maybe.group(0).strip().rstrip(".,;)]}\"'")
                            if self.is_valid_news_url(cand):
                                url = cand
                    news_text += "<div style='margin-bottom: 15px; padding: 12px; background-color: #22252c; border: 1px solid #2e2f32; border-radius: 6px;'>"
                    news_text += f"<h4 style='color: #e8eaed; margin: 0 0 8px 0; font-size: 13px; line-height: 1.3;'>{title}</h4>"
                    if content:
                        # Truncate content if too long
                        display_content = content[:200] + "..." if len(content) > 200 else content
                        news_text += f"<p style='margin: 0 0 8px 0; line-height: 1.5; font-size: 12px; color: #9aa0a6;'>{display_content}</p>"
                    if url:
                        news_text += f'<p style="margin: 0 0 5px 0;"><a href="{url}" style="color: #6b8cae; text-decoration: underline; font-size: 12px;">🔗 Read full article</a></p>'
                    if source:
                        news_text += f"<small style='color: #5f6368; font-size: 11px;'>Source: {source}</small>"
                    if published_date:
                        # Try to format the date better
                        formatted_date = self.format_display_date(published_date)
                        news_text += f"<br><small style='color: #5f6368; font-size: 11px;'>Published: {formatted_date}</small>"
                    news_text += "</div>"
                
                news_text += "</div>"
                self.news_display.setHtml(news_text)
                # Mark items as shown so they won't repeat for the suppression window
                try:
                    self.db.mark_news_shown(shown_ids)
                except Exception:
                    pass
                # News display updated successfully
            else:
                self.news_display.setPlainText("No recent news available. Check back later.")
                # No recent news found in database
        except Exception as e:
            print(f"Error in display_stored_news: {e}")
            self.news_display.setPlainText(f"Error displaying news: {str(e)}")

    def refresh_news_feed(self):
        self.load_news()

    def cleanup_old_news(self):
        self.db.cleanup_old_news(days=7)
    
    def is_valid_news_url(self, url):
        """Validate that a URL is a proper web address."""
        if not url or not isinstance(url, str):
            return False
        
        # Check if it's a valid URL format
        if not url.startswith(('http://', 'https://')):
            return False
        
        # Basic URL format validation - must have domain and be reasonable length
        if '.' not in url or len(url) < 10:
            return False
        
        # That's it - if it's a proper URL, accept it
        return True
