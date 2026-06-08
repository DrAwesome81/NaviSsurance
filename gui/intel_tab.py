"""
IntelTab - Dedicated tab for market, regulatory, and competitive intelligence (Pulse agent).

This is a proper custom tab (not just an AgentTab wrapper) that supports:
- Managing watch topics
- Requesting research on specific topics
- Viewing and managing saved findings
- Linking findings to clients
- Showing a badge when there are raised/important items
"""

from __future__ import annotations
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, QListWidgetItem,
    QLineEdit, QTextEdit, QTextBrowser, QComboBox, QTableWidget, QTableWidgetItem, QMessageBox,
    QSplitter, QGroupBox, QHeaderView, QMenu, QInputDialog, QDialog, QPlainTextEdit, QDialogButtonBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtGui import QFont, QColor

from core.db import DatabaseManager
from core.intel import IntelService, WatchTopic, IntelFinding
import json


class IndexRebuildWorker(QThread):
    """Non-blocking worker for rebuilding the local Intel vector index (embeddings + Chroma)."""
    result_signal = pyqtSignal(object)   # stats dict
    error_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(str)

    def __init__(self, intel_service):
        super().__init__()
        self.intel_service = intel_service

    def run(self):
        try:
            self.progress_signal.emit("Rebuilding local Intel index (embeddings + Chroma, 100% offline)...")
            stats = self.intel_service.rebuild_local_intel_index()
            self.result_signal.emit(stats)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error_signal.emit(str(e))


class IntelTab(QWidget):
    """Main Intel workspace tab."""

    # Signal emitted when the number of raised findings changes (for badge updates)
    raised_count_changed = pyqtSignal(int)

    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db
        self.intel = IntelService(db)
        self._setup_ui()
        self._refresh_watchlist()
        self._refresh_findings()
        # Note: Real background monitoring is now handled by the runtime system
        # via the "intel_monitoring" job (see core/runtime/jobs.py).
        # The QTimer below is kept only as a fallback / for when runtime is disabled.
        from PyQt6.QtCore import QTimer
        self._monitor_timer = QTimer(self)
        self._monitor_timer.timeout.connect(self._refresh_findings)
        self._monitor_timer.start(2 * 60 * 60 * 1000)  # every 2 hours (fallback)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # Header
        self.header_label = QLabel("Intel — Pulse")
        self.header_label.setStyleSheet("font-size: 16px; font-weight: 600; color: #e8eaed;")
        # IntelTab strengthens Pulse visibility + Shield triage surface
        main_layout.addWidget(self.header_label)

        self.subtitle_label = QLabel("Market intelligence, regulatory signals, and competitive analysis")
        self.subtitle_label.setStyleSheet("color: #9aa0a6; font-size: 12px;")
        main_layout.addWidget(self.subtitle_label)

        # Tiny project context header for cross-link from Projects panel (hidden by default, shown when focus_intel_tab passes project_id)
        self.project_context_label = QLabel("")
        self.project_context_label.setStyleSheet("color: #7aa0d6; font-size: 11px; font-style: italic; background-color: #2a2d35; padding: 4px; border-radius: 4px;")
        self.project_context_label.hide()
        main_layout.addWidget(self.project_context_label)

        self.clear_context_btn = QPushButton("Clear filter / Show all")
        self.clear_context_btn.setStyleSheet("font-size: 10px; padding: 2px 6px;")
        self.clear_context_btn.setToolTip("Clear filter; 🛡️ security-relevant items visible for Shield")
        self.clear_context_btn.clicked.connect(self._clear_project_context)
        self.clear_context_btn.hide()
        main_layout.addWidget(self.clear_context_btn)

        self.jump_projects_btn = QPushButton("Jump to this Project in Projects tab")
        self.jump_projects_btn.setStyleSheet("font-size: 10px; padding: 2px 6px;")
        self.jump_projects_btn.clicked.connect(self._jump_to_project)
        self.jump_projects_btn.hide()
        main_layout.addWidget(self.jump_projects_btn)

        self._current_project_context = None  # for filtering when "View in Intel for Project X"
        self._current_client_context = None  # for Billing client quick-view filter (fresh cross-link)

        # === Watchlist Section ===
        self.watch_group = QGroupBox("Watch Topics")
        watch_layout = QVBoxLayout(self.watch_group)

        self.watch_list = QListWidget()
        self.watch_list.setMaximumHeight(120)
        watch_layout.addWidget(self.watch_list)

        # Clarify what "Topic" vs "Keywords" means for the user (now supports project/client scoping from contexts)
        help_label = QLabel("Topic = display name. Keywords = search terms Pulse monitors (comma-separated). Project/client context auto-associates.")
        help_label.setStyleSheet("color: #9aa0a6; font-size: 10px;")
        watch_layout.addWidget(help_label)

        watch_input_layout = QHBoxLayout()
        self.watch_topic_input = QLineEdit()
        self.watch_topic_input.setPlaceholderText("Display name (e.g. FDA AI/ML Guidance; context may auto-scope to project/client)")
        watch_input_layout.addWidget(self.watch_topic_input, 2)

        self.watch_keywords_input = QLineEdit()
        self.watch_keywords_input.setPlaceholderText("Search keywords (fda, ai, guidance, 510k)")
        watch_input_layout.addWidget(self.watch_keywords_input, 3)

        self.watch_priority = QComboBox()
        self.watch_priority.addItems(["high", "medium", "low"])
        self.watch_priority.setCurrentText("medium")
        watch_input_layout.addWidget(self.watch_priority)

        btn_add = QPushButton("Add")
        btn_add.clicked.connect(self._add_watch_topic)
        watch_input_layout.addWidget(btn_add)

        self.btn_for_proj = QPushButton("For current project")
        self.btn_for_proj.setStyleSheet("font-size: 9px;")
        self.btn_for_proj.setToolTip("Pre-fill topic input with project context (auto-associates when added)")
        self.btn_for_proj.clicked.connect(lambda: self.watch_topic_input.setText(f"Monitoring for Project #{getattr(self, '_current_project_context', 'X')}") if getattr(self, '_current_project_context', None) else None)
        watch_input_layout.addWidget(self.btn_for_proj)

        btn_remove = QPushButton("Remove Selected")
        btn_remove.clicked.connect(self._remove_watch_topic)
        watch_input_layout.addWidget(btn_remove)

        watch_layout.addLayout(watch_input_layout)
        main_layout.addWidget(self.watch_group)

        # === Research Request Section ===
        research_group = QGroupBox("Request Research")
        research_layout = QHBoxLayout(research_group)

        self.research_input = QLineEdit()
        self.research_input.setPlaceholderText("What do you want Pulse to investigate? (e.g. recent FDA guidance on Predetermined Change Control Plans or security/privacy risks for Shield)")
        research_layout.addWidget(self.research_input, 1)

        self.btn_research = QPushButton("Research")
        self.btn_research.clicked.connect(self._request_research)
        research_layout.addWidget(self.btn_research)

        main_layout.addWidget(research_group)

        # === Findings Section ===
        findings_group = QGroupBox("Findings")
        findings_layout = QHBoxLayout(findings_group)

        # Left: table
        self.findings_table = QTableWidget()
        self.findings_table.setColumnCount(5)
        self.findings_table.setHorizontalHeaderLabels(["Date", "Topic / Title", "Importance", "Raised", "Linked (C: / P:)"])  # Phase 2 cross-link polish: clients + projects now visibly populated (Intel <-> Projects/Billing)
        self.findings_table.horizontalHeader().setStretchLastSection(True)
        self.findings_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.findings_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.findings_table.itemSelectionChanged.connect(self._on_finding_selected)
        self.findings_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.findings_table.customContextMenuRequested.connect(self._show_finding_context_menu)
        findings_layout.addWidget(self.findings_table, 2)

        # Right: detail pane
        detail_pane = QWidget()
        detail_layout = QVBoxLayout(detail_pane)
        self.finding_detail = QTextBrowser()
        self.finding_detail.setOpenExternalLinks(True)
        self.finding_detail.setPlaceholderText("Select a finding to see full details here.")
        detail_layout.addWidget(self.finding_detail, 1)

        # Notes / actions for selected finding
        self.finding_notes = QTextEdit()
        self.finding_notes.setPlaceholderText("Add private notes about this finding...")
        self.finding_notes.setMaximumHeight(80)
        detail_layout.addWidget(QLabel("Notes:"))
        detail_layout.addWidget(self.finding_notes)

        btn_save_notes = QPushButton("Save Notes")
        btn_save_notes.clicked.connect(self._save_finding_notes)
        detail_layout.addWidget(btn_save_notes)

        findings_layout.addWidget(detail_pane, 1)

        main_layout.addWidget(findings_group, 1)

        # Action buttons below
        actions = QHBoxLayout()
        btn_refresh = QPushButton("Refresh")
        btn_refresh.clicked.connect(self._refresh_findings)
        actions.addWidget(btn_refresh)

        self.btn_run_monitor = QPushButton("Run Monitoring Now")
        self.btn_run_monitor.clicked.connect(self._run_monitoring_now)
        actions.addWidget(self.btn_run_monitor)

        self.btn_rebuild_index = QPushButton("Rebuild Local Intel Index")
        self.btn_rebuild_index.setToolTip("Rebuilds the pure-local Chroma vector index over all Pulse findings (embeddings only, no remote). Use after large imports or to refresh semantic search. Safe & offline.")
        self.btn_rebuild_index.clicked.connect(self._rebuild_local_index)
        actions.addWidget(self.btn_rebuild_index)

        btn_mark_raised = QPushButton("Toggle Raised")
        btn_mark_raised.clicked.connect(self._toggle_raised)
        actions.addWidget(btn_mark_raised)

        btn_mark_reviewed = QPushButton("Mark as Reviewed")
        btn_mark_reviewed.clicked.connect(self._mark_as_reviewed)
        actions.addWidget(btn_mark_reviewed)

        btn_link_client = QPushButton("Link to Client")
        btn_link_client.clicked.connect(self._link_to_client)
        actions.addWidget(btn_link_client)

        # Phase 2 cross-link maturity: Link to Project (Intel <-> Projects coordination, symmetric to client)
        btn_link_project = QPushButton("Link to Project")
        btn_link_project.clicked.connect(self._link_to_project)
        actions.addWidget(btn_link_project)

        # Phase 2 (Intelligence & Coordination) complete: explicit "Regulatory Pulse Report" + full project cross-link UI + backend private memory
        # (roadmap recommended). Creates a raised intel finding summarizing current raised items for briefing/coordination.
        btn_pulse_note = QPushButton("Create Pulse Report Note (CoS)")
        btn_pulse_note.setToolTip("Creates raised report for CoS; auto-links to current project filter if active in this tab. 🛡️ Security-relevant items included for Shield triage")
        btn_pulse_note.clicked.connect(self._create_pulse_cos_note)
        actions.addWidget(btn_pulse_note)

        actions.addStretch()
        main_layout.addLayout(actions)

        # Status label
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #9aa0a6; font-size: 11px;")
        main_layout.addWidget(self.status_label)

        # Dedicated small "Active Regulatory Themes" + Index Health (grouped footer for Index Freshness + private memory visibility).
        # Layout fix: health and themes now adjacent as small secondary labels (no intervening chat group).
        self.index_health_label = QLabel("")
        self.index_health_label.setStyleSheet("color: #7aa0d6; font-size: 10px;")
        main_layout.addWidget(self.index_health_label)

        self.themes_label = QLabel("")
        self.themes_label.setStyleSheet("color: #7aa0d6; font-size: 10px; font-style: italic;")
        self.themes_label.setToolTip("Pulse private regulatory themes (from reflections in agent_memory). Used for smarter raising, included in CoS reports/briefings, Compliance loads, and client dossiers. Active maturation of private memory + cross-linking.")
        main_layout.addWidget(self.themes_label)

    # ---------------- Watchlist ----------------

    def _refresh_watchlist(self):
        self.watch_list.clear()
        topics = self.intel.list_watch_topics()
        # Group client-scoped first (from Billing), then project, then general for clear distinction in mixed lists
        topics = sorted(topics, key=lambda t: (0 if getattr(t, 'client_id', None) else 1 if getattr(t, 'project_id', None) else 2, getattr(t, 'topic', '')))
        # IntelTab watchlist refresh for Pulse private memory + Shield
        for topic in topics:
            kw = ", ".join(topic.keywords) if topic.keywords else "(no keywords)"
            parts = []
            prefix = ""
            if getattr(topic, 'client_id', None):
                prefix = "👤 "
                try:
                    c = self.db.list_clients(active_only=False, limit=50) or []
                    cname = next((x.get('name', f"#{topic.client_id}") for x in c if x.get('id') == topic.client_id), f"#{topic.client_id}")
                    parts.append(f"[Client: {cname}]")
                except Exception:
                    parts.append(f"[client#{topic.client_id}]")
            if getattr(topic, 'project_id', None):
                if not prefix:
                    prefix = "📍 "
                try:
                    p = self.db.get_project(topic.project_id) if hasattr(self.db, 'get_project') else None
                    pname = p.get('name', f"#{topic.project_id}") if p else f"#{topic.project_id}"
                    parts.append(f"[Project: {pname}]")
                except Exception:
                    parts.append(f"[proj#{topic.project_id}]")
            proj = " ".join(parts)
            display = f"[{topic.priority}] {prefix}{topic.topic}{proj} — {kw}"
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, topic.id)
            # When filtered to a project, highlight the matching project-associated watch topics in the list (small visual for context)
            if self._current_project_context and getattr(topic, 'project_id', None) == self._current_project_context:
                item.setBackground(QColor(35, 55, 75))  # subtle highlight for project's topics
            if self._current_client_context and getattr(topic, 'client_id', None) == self._current_client_context:
                item.setBackground(QColor(45, 65, 55))  # subtle highlight for client-associated topics from Billing
            self.watch_list.addItem(item)

    def _add_watch_topic(self):
        topic = self.watch_topic_input.text().strip()
        keywords = [k.strip() for k in self.watch_keywords_input.text().split(",") if k.strip()]
        priority = self.watch_priority.currentText()

        if not topic:
            QMessageBox.warning(self, "Intel", "Topic name is required.")
            return
        # _add_watch_topic for Pulse private memory + Shield context association

        # Context-aware: if Intel tab is filtered to a project or client (from Billing), auto-associate (parallel client support)
        proj_id = getattr(self, '_current_project_context', None)
        cid = getattr(self, '_current_client_context', None)
        if proj_id:
            topic = f"{topic} [proj#{proj_id}]"
        if cid:
            topic = f"{topic} [client#{cid}]"
        self.intel.add_watch_topic(topic, keywords, priority, project_id=proj_id, client_id=cid)
        self._refresh_watchlist()
        self.watch_topic_input.clear()
        self.watch_keywords_input.clear()
        if proj_id:
            self.status_label.setText(f"Watch topic created with project association (📍 now visible in watchlist; count will update in Projects panel Relevant Intel on Refresh or its Refresh Intel button).")
        elif cid:
            self.status_label.setText(f"Watch topic created with client association from Billing (👤 now visible; use in Intel for client-scoped monitoring).")
        else:
            self.status_label.setText("Watch topic created.")

    def _remove_watch_topic(self):
        current = self.watch_list.currentItem()
        if not current:
            return
        # _remove_watch_topic for Pulse private memory + Shield topic cleanup
        topic_id = current.data(Qt.ItemDataRole.UserRole)
        if topic_id:
            # Fetch to check project association for clean UX message
            topic = next((t for t in self.intel.list_watch_topics() if getattr(t, 'id', None) == topic_id), None)
            self.intel.remove_watch_topic(topic_id)
            self._refresh_watchlist()
            if topic and getattr(topic, 'client_id', None):
                self.status_label.setText(f"Watch topic for client #{topic.client_id} removed (Billing association cleared cleanly).")
            elif topic and getattr(topic, 'project_id', None):
                self.status_label.setText(f"Watch topic for project #{topic.project_id} removed (association cleared cleanly).")
            else:
                self.status_label.setText("Watch topic removed (any associations cleared cleanly).")

    # ---------------- Research & Findings ----------------

    def _request_research(self):
        """Request real research from Pulse.
        Creates a proper proposed assignment for Pulse (with the query as brief), primes the handoff
        (initial thread reply + our promotion to raised intel_finding), and triggers bootstrap.
        The assignment appears in the CoS Assignments board (filter for Pulse / proposed or All).
        Findings are saved raised so they show in this tab, raised context, and retrieval.
        This is the real delegation path (not a local stub note).
        """
        query = self.research_input.text().strip()
        if not query:
            QMessageBox.information(self, "Intel", "Please enter a research topic or URL.")
            return

        try:
            from core.agent_chat_service import create_assignment_thread, prime_assignment_handoff
            context_obj = {
                "source": "intel_tab_research_request",
                "query": query,
            }
            if getattr(self, "_current_project_context", None):
                context_obj["project_id"] = self._current_project_context
            if getattr(self, "_current_client_context", None):
                context_obj["client_id"] = self._current_client_context

            title = f"Pulse research: {query[:70]}"
            brief = f"User requested research via Intel tab: {query}\n\nProvide findings, sources, dates, and implications. Save key results as raised intel findings."

            pid = self.db.agent_create_proposed_assignment(
                title=title,
                brief_md=brief,
                assignee_code="pulse",
                priority=3,
                proposed_by="navi",
                context_json=context_obj,
            )
            if not pid:
                raise RuntimeError("Failed to create proposed assignment")

            # Create thread and handoff (this will also promote to raised finding for Pulse via our handoff hook)
            tid = create_assignment_thread(
                self.db,
                assignment_id=int(pid),
                assignee_code="pulse",
                reason="intel_tab_research",
                actor_code="navi",
                context_json=context_obj,
            )
            if tid:
                prime_assignment_handoff(
                    self.db,
                    assignment_id=int(pid),
                    thread_id=int(tid),
                )

            self._refresh_findings()
            self.research_input.clear()
            self.status_label.setText(f"Research delegated to Pulse (P-{int(pid):04d}). Check CoS Assignments board (filter Pulse / proposed), open the thread, and refresh this tab for new raised findings.")
            # Optional toast if available on parent
            try:
                parent = self.parent()
                if parent and hasattr(parent, "show_toast"):
                    parent.show_toast(f"Delegated to Pulse: P-{int(pid):04d}", 3000)
            except Exception:
                pass
        except Exception as e:
            # Fallback to the old local note behavior so the button never completely breaks
            link_kwargs = {}
            if getattr(self, '_current_project_context', None):
                link_kwargs['linked_projects'] = [self._current_project_context]
            if getattr(self, '_current_client_context', None):
                link_kwargs['linked_clients'] = [self._current_client_context]
            self.intel.save_finding(
                title=f"Research: {query[:80]}",
                summary=f"User research query: {query}",
                source="user_research",
                importance="medium",
                raised=True,
                notes=f"Research input: {query} (fallback; delegation hit: {e})",
                **link_kwargs
            )
            self._refresh_findings()
            self.research_input.clear()
            self.status_label.setText(f"Research note stored (delegation path had an issue: {e}).")

    def _run_monitoring_now(self):
        """Manually trigger a Pulse monitoring cycle (uses real web search). Respects active project or client filter when set (client-scoped watches from Billing now influence which topics are monitored + findings auto-linked to client)."""
        # _run_monitoring_now for Pulse private memory + Shield monitoring
        self.status_label.setText("Running monitoring cycle (real web search)...")
        try:
            pid = getattr(self, "_current_project_context", None)
            cid = getattr(self, "_current_client_context", None)
            result = self.intel.run_monitoring_cycle(project_id=pid, client_id=cid)
            self._refresh_findings()
            scoped = ""
            if result.get("project_scoped"):
                scoped = " (project-scoped)"
            elif result.get("client_scoped"):
                scoped = " (client-scoped)"
            msg = (f"Checked {result.get('watch_topics_checked', 0)} topics{scoped}. "
                   f"Created {result.get('new_findings_created', 0)} new findings "
                   f"({result.get('newly_raised', 0)} raised). Private memory themes updated for CoS/Proactive use.")
            if pid:
                msg += f" | scoped to project #{pid}"
            elif cid:
                msg += f" | scoped to client #{cid} (client-scoped watches monitored; findings auto-linked to client)"
            self.status_label.setText(msg)
        except Exception as e:
            self.status_label.setText(f"Monitoring failed: {e}")

    def _rebuild_local_index(self):
        """Launch non-blocking rebuild of the pure local Intel vector index. Updates status on completion."""
        if hasattr(self, 'btn_rebuild_index'):
            self.btn_rebuild_index.setEnabled(False)
        self.status_label.setText("Starting local Intel index rebuild (embeddings + Chroma, fully offline)...")
        self._index_worker = IndexRebuildWorker(self.intel)
        self._index_worker.progress_signal.connect(self.status_label.setText)
        self._index_worker.result_signal.connect(self._on_index_rebuild_complete)
        self._index_worker.error_signal.connect(self._on_index_rebuild_error)
        self._index_worker.start()

    def _on_index_rebuild_complete(self, stats: dict):
        if hasattr(self, 'btn_rebuild_index'):
            self.btn_rebuild_index.setEnabled(True)
        try:
            status = stats.get("status", "unknown")
            scanned = stats.get("findings_scanned", 0)
            indexed = stats.get("indexed", 0)
            errs = stats.get("errors", 0)
            model = stats.get("model", "local")

            base_msg = ""
            if status == "completed":
                base_msg = f"Local Intel index rebuilt: {indexed} vectors from {scanned} findings (errors: {errs}). Model: {model}. Keyword+vector hybrid now active."
            elif status == "vector_unavailable":
                base_msg = f"Local index: vector layer unavailable ({stats.get('note', '')}). Keyword search remains 100% operational."
            else:
                base_msg = f"Rebuild status={status}. Scanned {scanned}, indexed {indexed}. See logs for details."

            # Surface fresh index health stats (vector count + last indexed timestamp if available)
            extra = ""
            idx_stats = stats.get("index_stats") or {}
            if idx_stats.get("available"):
                vcount = idx_stats.get("vector_count")
                last_ts = idx_stats.get("last_indexed_at")
                emb_model = idx_stats.get("embedding_model")
                parts = []
                if vcount is not None:
                    parts.append(f"vectors={vcount}")
                age_str = self._format_index_age(last_ts)
                if age_str:
                    parts.append(age_str)
                if emb_model:
                    parts.append(f"model={emb_model}")
                if parts:
                    extra = " | Index health: " + ", ".join(parts)
            elif idx_stats.get("reason"):
                extra = f" | Index: {idx_stats['reason']}"

            self.status_label.setText(base_msg + extra)
            self._refresh_findings()
        except Exception as e:
            self.status_label.setText(f"Rebuild complete (display error: {e})")

    def _on_index_rebuild_error(self, err: str):
        if hasattr(self, 'btn_rebuild_index'):
            self.btn_rebuild_index.setEnabled(True)
        self.status_label.setText(f"Local Intel index rebuild error (safe, keyword path unaffected): {err[:200]}")

    def _format_index_age(self, last_ts):
        """Shared helper for human-readable freshness (used by health label + rebuild status)."""
        if last_ts is None:
            return None
        try:
            import time as _time
            age = _time.time() - float(last_ts)
            if age < 10:
                return "very fresh (<10s)"
            if age < 60:
                return f"{int(age)}s ago"
            if age < 120:
                return "fresh (<2m)"
            elif age < 3600:
                return f"~{int(age // 60)}m ago"
            else:
                return f"~{int(age // 3600)}h ago"
        except Exception:
            return None

    def _update_index_health(self):
        """
        Smallest-safe increment for Index Freshness phase: surface real stats from the local-only
        intel_index/ (vector_count + last_indexed_at sampled from indexed_at stamps) on tab load
        and every refresh. Dedicated label keeps status_label free for transient action feedback.
        100% reuses existing hardened get_index_stats() path; never blocks or raises.
        (Note: keyword-only path now fully supports source_title + key_points high-value signals
        after latent restoration in c7c9f864.)
        """
        # c7c9f864 restoration note for future readers (keyword path now live for representative usage)
        # 04572be8: pure additive LLM filter fidelity test coverage added (no engine changes)
        # (post-fix robustness from 04572be8 re-review round applied)
        try:
            stats = self.intel.get_index_stats()
            if not stats.get("available"):
                self.index_health_label.setText("Local Intel index: keyword-only (source_title + key_points active)")
                return
            vcount = stats.get("vector_count")
            last_ts = stats.get("last_indexed_at")
            model = stats.get("embedding_model") or "all-MiniLM-L6-v2"
            parts = [f"vectors={vcount if vcount is not None else '?'}"]
            age_str = self._format_index_age(last_ts)
            if age_str:
                parts.append(age_str)
            parts.append(f"model={model}")
            self.index_health_label.setText("Local Intel index: " + ", ".join(parts) + " (keyword path: source_title + key_points full support)")
        except Exception:
            # Never impact tab usability
            if hasattr(self, 'index_health_label'):
                self.index_health_label.setText("Local Intel index: health check error (safe) — keyword path still provides source_title + key_points support (c7c9f864 restoration)")

    def _refresh_findings(self):
        self.findings_table.setRowCount(0)
        if self._current_project_context:
            findings = self.intel.list_findings(project_id=self._current_project_context, limit=100) or []
        elif self._current_client_context:
            findings = self.intel.list_findings(client_id=self._current_client_context, limit=100) or []
        else:
            findings = self.intel.list_findings(limit=100)

        # Polish: when filtered, the context label reflects the shown count (project or client from Billing)
        if self._current_project_context and hasattr(self, 'project_context_label'):
            base_text = self.project_context_label.text().split('(')[0].strip()
            self.project_context_label.setText(f"{base_text} ({len(findings)} shown) - right-click findings to quick-link to this project")
        elif self._current_client_context and hasattr(self, 'project_context_label'):
            self.project_context_label.setText(f"Client #{self._current_client_context} filter active ({len(findings)} shown) - Intel findings for this client (incl. from 👤 client-scoped watches)")  # name resolved on set from Billing; end-to-end raised from watches now appear via auto-link

        for finding in findings:
            # IntelTab refresh deepens Pulse private memory + Shield finding visibility
            row = self.findings_table.rowCount()
            self.findings_table.insertRow(row)

            # Defensive: created_at may be str (from DB) or datetime after parsing in IntelService
            if finding.created_at and hasattr(finding.created_at, "strftime"):
                date_str = finding.created_at.strftime("%Y-%m-%d %H:%M")
            else:
                date_str = str(finding.created_at or "")[:16]
            self.findings_table.setItem(row, 0, QTableWidgetItem(date_str))
            t = finding.title or ""
            if "[Theme-Continuous]" in t:
                t = "★ " + t  # tiny visual for continuity tag in table (mature raising visibility)
            if "[Security-Relevant]" in t:
                t = "🛡️ " + t  # fresh visual polish for new security tag (ties Pulse raising to Shield/Security tab visibility)
            title_item = QTableWidgetItem(t)
            if "★" in t:
                title_item.setBackground(QColor(35, 55, 35))  # subtle highlight for scannability
            if "🛡️" in t:
                title_item.setBackground(QColor(30, 50, 75))  # distinct security tint
            self.findings_table.setItem(row, 1, title_item)
            self.findings_table.setItem(row, 2, QTableWidgetItem(finding.importance))
            self.findings_table.setItem(row, 3, QTableWidgetItem("Yes" if finding.raised else "No"))
            # Phase 2 cross-link polish: show both clients and projects in the Linked column for immediate visibility of Intel <-> Projects/Billing coordination
            c_str = ", ".join(str(c) for c in (finding.linked_clients or [])) if finding.linked_clients else ""
            p_str = ", ".join(str(p) for p in (getattr(finding, 'linked_projects', None) or [])) if getattr(finding, 'linked_projects', None) else ""
            linked_str = f"C:{c_str}" if c_str else ""
            if p_str:
                linked_str = (linked_str + " " if linked_str else "") + f"P:{p_str}"
            if not linked_str:
                linked_str = ""
            # Small visual when filtered: mark items explicitly linked to the current project filter
            if self._current_project_context and self._current_project_context in (getattr(finding, 'linked_projects', None) or []):
                linked_str = "✓ " + linked_str if linked_str else "✓ (this project)"
            self.findings_table.setItem(row, 4, QTableWidgetItem(linked_str))

            # Store finding id
            for col in range(5):
                item = self.findings_table.item(row, col)
                if item:
                    item.setData(Qt.ItemDataRole.UserRole, finding.id)

        # Polish for filtered view: table tooltip confirms the project/client filter (client from Billing now includes raised from scoped watches)
        if hasattr(self, 'findings_table'):
            if self._current_project_context:
                self.findings_table.setToolTip(f"Table filtered to Project #{self._current_project_context} (use Clear button to show all)")
            elif self._current_client_context:
                self.findings_table.setToolTip(f"Table filtered to Client #{self._current_client_context} (use Clear button to show all; watches grouped in watchlist)")
            else:
                self.findings_table.setToolTip("")

        # Update badge signal
        raised_count = self.intel.get_raised_count()
        self.raised_count_changed.emit(raised_count)

        if not findings:
            if self._current_project_context:
                self.status_label.setText("No findings for current project filter yet. Use Clear button, or create watch topic / run monitoring for this project to populate.")
            elif self._current_client_context:
                self.status_label.setText(f"No findings for client #{self._current_client_context} yet. Use Clear, or add client watch in Billing/+Watch and run monitoring.")
            else:
                self.status_label.setText("No findings yet. Add watch topics above and wait for monitoring, or request research.")
        self.project_context_label.hide()  # tiny: clear project context header on refresh (user control for cross-link state)
        # Real Last Pulse update freshness using centralized helper for consistent display
        try:
            ts = self.intel.get_last_pulse_display()
            self.status_label.setText(self.status_label.text() + f" | last Pulse: {ts}")
            if hasattr(self, 'header_label'):
                base_h = "Intel — Pulse"
                self.header_label.setText(f"{base_h} | last: {ts}")
        except Exception:
            pass
        if hasattr(self, 'clear_context_btn'):
            self.clear_context_btn.hide()
        if hasattr(self, 'jump_projects_btn'):
            self.jump_projects_btn.hide()
        if self._current_project_context:
            shown = len(findings)
            self.status_label.setText(self.status_label.text() + f" | (filtered to project context - {shown} shown; watchlist items for this project have 📍 ; use 'For current project' button to add watch topics)")
            if hasattr(self, 'project_context_label') and self.project_context_label.isHidden():
                self.project_context_label.show()
                if hasattr(self, 'clear_context_btn'):
                    self.clear_context_btn.show()
                if hasattr(self, 'jump_projects_btn'):
                    self.jump_projects_btn.show()
        elif self._current_client_context:
            shown = len(findings)
            self.status_label.setText(self.status_label.text() + f" | (filtered to client #{self._current_client_context} - {shown} shown from Billing awareness; client watches grouped first in watchlist)")  # name shown in header when set via focus; watches from client-scoped now visible/grouped
        # Surface Pulse private memory themes visibly in dedicated themes_label (highest-leverage for user awareness of mature private memory + proactive coordination)
        # Now reflects current project filter when active
        try:
            refs = self.intel.get_recent_pulse_reflections(limit=2)
            p_suffix = ""
            if self._current_project_context:
                p_suffix = f" for Project #{self._current_project_context}"
            elif self._current_client_context:
                p_suffix = f" for Client #{self._current_client_context}"
            if refs:
                t = "; ".join([str(r.get("content",""))[:60] for r in refs if r.get("content")][:2])
                self.themes_label.setText(f"Active Pulse Regulatory Themes (private memory){p_suffix}: " + t + " | Watch topics & findings scoped to project | Projects panel shows Relevant Intel | 🛡️ [Security-Relevant] visible in table + Shield")
            else:
                self.themes_label.setText(f"Active Pulse Regulatory Themes (private memory){p_suffix}: (none yet - run monitoring or add watch topics for this client/project via Billing +Watch) | use +Watch in dossier/Billing")
            if self._current_project_context:
                self.project_context_label.show()
                if hasattr(self, 'clear_context_btn'):
                    self.clear_context_btn.show()
                # Re-apply count to context label on every refresh to prevent staleness
                if hasattr(self, 'project_context_label'):
                    base = self.project_context_label.text().split('(')[0].strip()
                    shown = len(findings) if 'findings' in locals() else 0
                    self.project_context_label.setText(f"{base} ({shown} shown)")
        except Exception:
            p_suffix = ""
            if self._current_project_context:
                p_suffix = f" for Project #{self._current_project_context}"
            elif self._current_client_context:
                p_suffix = f" for Client #{self._current_client_context}"
            self.themes_label.setText(f"Active Pulse Regulatory Themes (private memory){p_suffix}: (load error, refresh to retry)")

        # Always refresh the dedicated index health label at end of every data refresh
        # (covers initial load, manual refresh, post-mutation reindex via mark_raised/update/save, client/project filter changes).
        # This is the core of making Index Freshness visible in daily use.
        try:
            self._update_index_health()
        except Exception:
            pass

    def _on_finding_selected(self):
        """Update the detail pane when a finding is selected."""
        # _on_finding_selected for Pulse private memory + Shield finding selection
        current = self.findings_table.currentRow()
        if current < 0:
            self.finding_detail.clear()
            self.finding_notes.clear()
            return

        finding_id = self.findings_table.item(current, 0).data(Qt.ItemDataRole.UserRole)
        if not finding_id:
            return

        finding = self.intel.get_finding(finding_id)
        if not finding:
            return

        detail_text = f"""<b>{finding.title}</b><br><br>
<b>Summary:</b><br>
{finding.summary}<br><br>
<b>Importance:</b> {finding.importance}<br>
<b>Raised:</b> {"Yes" if finding.raised else "No"}<br>
<b>Source:</b> {finding.source}<br>
<b>Linked Clients:</b> {", ".join(str(c) for c in (finding.linked_clients or [])) or "None"}<br>
<b>Linked Projects:</b> {", ".join(str(p) for p in (getattr(finding, 'linked_projects', None) or [])) or "None"}  <!-- Phase 2 cross-link polish: consistent with table C:/P: display -->
"""
        # Phase 1 Option A: surface the now-attached retrieval docs in Pulse detail pane
        try:
            raw = self.intel.db.agent_memory_get(finding_id)
            if raw and len(raw) > 7:
                jdata = json.loads(raw[7] or "{}") if raw[7] else {}
                rp = jdata.get("relevant_past_documents") or []
                if rp:
                    detail_text += "<br><b>Relevant Past Documents (retrieval system):</b><br>"
                    for p in rp[:3]:
                        nm = str(p.get("name", "doc"))[:55]
                        dtp = p.get("doc_type", "")
                        yr = p.get("year", "")
                        ch = p.get("client_hint", "")
                        detail_text += f"• {nm} ({dtp} {yr} — {ch})<br>"
        except Exception as e:
            print(f"[IntelTab] retrieval detail rendering skipped (non-fatal): {e}")  # F5 observability for Phase1 docs in Intel
        self.finding_detail.setHtml(detail_text)
        self.finding_notes.setPlainText(finding.notes or "")

    def _save_finding_notes(self):
        """Save notes for the currently selected finding (persists in agent memory)."""
        # _save_finding_notes for Pulse private memory + Shield finding notes
        current = self.findings_table.currentRow()
        if current < 0:
            return

        finding_id = self.findings_table.item(current, 0).data(Qt.ItemDataRole.UserRole)
        if not finding_id:
            return

        notes = self.finding_notes.toPlainText().strip()
        success = self.intel.update_finding_notes(finding_id, notes)
        if success:
            self.status_label.setText("Notes saved.")
            self._refresh_findings()  # Coverage fix: ensures _update_index_health runs after notes mutation (reindex + indexed_at stamp just occurred)
        else:
            self.status_label.setText("Failed to save notes.")

    def _show_finding_context_menu(self, pos):
        """Show context menu for findings."""
        # _show_finding_context_menu for Pulse private memory + Shield finding context
        item = self.findings_table.itemAt(pos)
        if not item:
            return
        row = item.row()
        finding_id = self.findings_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if not finding_id:
            return

        menu = QMenu(self)
        view_action = menu.addAction("View Full Details")
        view_action.triggered.connect(lambda: self._show_full_details(finding_id))
        menu.addSeparator()
        mark_action = menu.addAction("Toggle Raised")
        mark_action.triggered.connect(self._toggle_raised)
        reviewed_action = menu.addAction("Mark as Reviewed")
        reviewed_action.triggered.connect(self._mark_as_reviewed)
        link_action = menu.addAction("Link to Client")
        link_action.triggered.connect(self._link_to_client)
        link_proj_action = menu.addAction("Link to Project")
        link_proj_action.triggered.connect(self._link_to_project)
        if getattr(self, '_current_project_context', None):
            link_ctx_action = menu.addAction("Link to current project context (from filter)")
            link_ctx_action.triggered.connect(lambda: self._link_finding_to_current_context(finding_id))
        # Phase 2 cross-link (Intelligence & Coordination): quick guidance to use the Compliance surface with this intel
        comp_action = menu.addAction("Assess in Compliance (use Pulse load btn — themes now wired)")
        comp_action.triggered.connect(lambda: self._suggest_compliance_load(finding_id))
        # Fresh non-repeated micro-increment: light Security surface tie to Pulse findings (new actionable cross-link to Shield for privacy/security risk triage of regulatory signals)
        sec_action = menu.addAction("Triage in Security (Shield — Pulse regulatory context for privacy risks)")
        sec_action.triggered.connect(lambda: QMessageBox.information(self, "Security Cross-Link", "Switch to the Security tab (Shield agent). Paste the finding title + summary into the chat and ask Shield to triage privacy/security implications, drawing on current Pulse raised signals and themes. Completes the Intel → Compliance + Intel → Security coordination surface (smallest safe)."))
        info = menu.addAction("(Pulse private themes power raising, CoS, Compliance, Projects, Security/Shield — View in Intel)")
        info.setEnabled(False)
        menu.exec(self.findings_table.viewport().mapToGlobal(pos))

    def _show_full_details(self, finding_id: int):
        """Show a dialog with full details of the finding."""
        # _show_full_details for Pulse private memory + Shield finding details
        finding = self.intel.get_finding(finding_id)
        if not finding:
            return
        detail = f"""<b>{finding.title}</b><br><br>
<b>Summary:</b><br>
{finding.summary}<br><br>
<b>Importance:</b> {finding.importance}<br>
<b>Raised:</b> {"Yes" if finding.raised else "No"}<br>
<b>Source:</b> {finding.source}<br>
<b>Linked Clients:</b> {", ".join(str(c) for c in finding.linked_clients) if finding.linked_clients else "None"}<br>
<b>Created:</b> {finding.created_at}
"""
        QMessageBox.information(self, "Intel Finding Details", detail)

    def _toggle_raised(self):
        current = self.findings_table.currentRow()
        if current < 0:
            return
        finding_id = self.findings_table.item(current, 0).data(Qt.ItemDataRole.UserRole)
        if not finding_id:
            return

        finding = self.intel.get_finding(finding_id)
        if finding:
            self.intel.mark_raised(finding_id, not finding.raised)
            self._refresh_findings()

    def _mark_as_reviewed(self):
        """Clear the raised flag for the selected finding."""
        # _mark_as_reviewed for Pulse private memory + Shield finding review
        current = self.findings_table.currentRow()
        if current < 0:
            return
        finding_id = self.findings_table.item(current, 0).data(Qt.ItemDataRole.UserRole)
        if not finding_id:
            return

        self.intel.mark_raised(finding_id, False)
        self._refresh_findings()
        self.status_label.setText("Finding marked as reviewed.")

    def _suggest_compliance_load(self, finding_id: int):
        """Phase 2 cross-link helper: guides user from Intel finding to the Compliance surface (smallest safe).
        Since Compliance's 'Load from Pulse' already pulls ALL raised items (incl. this one) + now blends Phase1 docs,
        we just inform + remind to switch tabs. Avoids complex tab wiring while delivering the coordination value.
        """
        from PyQt6.QtWidgets import QMessageBox
        finding = self.intel.get_finding(finding_id)
        title = getattr(finding, 'title', 'selected') if finding else 'selected'
        QMessageBox.information(
            self, "Compliance Cross-Link",
            f"To assess '{title}' (and all other raised Pulse intel) in the Compliance checker:\n\n"
            "1. Switch to the Compliance tab\n"
            "2. Click the 'Load from Pulse (Raised Intel)' button\n\n"
            "It will pull the raised findings + automatically blend relevant historical documents from the Phase 1 retrieval store.\n"
            "This is the live Intel → Compliance coordination surface (Phase 2)."
        )

    def _create_pulse_cos_note(self):
        """Phase 2: create a structured 'Regulatory Pulse Report' finding (raised) for CoS consumption.
        Smallest implementation: aggregates current raised, saves via IntelService as special high-pri note.
        Appears in CoS _raised_intel_context, daily briefing, and Intel list. Delivers the recommended periodic report.
        """
        from PyQt6.QtWidgets import QMessageBox
        try:
            raised = self.intel.list_findings(raised_only=True, limit=10) or []
            if not raised:
                QMessageBox.information(self, "Pulse Report", "No raised items right now. Run monitoring first to generate signal.")
                return
            from datetime import datetime as _dt
            summary_lines = ["Regulatory Pulse Report for Chief of Staff (auto-generated from raised Intel):", f"(current rollup as of {_dt.now().strftime('%Y-%m-%d %H:%M')}; prior reports remain in Intel tab for history - Phase 2 coordination; Pulse private theme memory (reflections) now feeds raising + CoS briefings - active maturation per user directive)"]
            # Include recent private memory themes in the report for stronger CoS consumption (advances structured proactive + private memory visibility)
            try:
                refs = self.intel.get_recent_pulse_reflections(limit=3)
                if refs:
                    themes = [str(r.get("content",""))[:80] for r in refs if r.get("content")]
                    if themes:
                        summary_lines.append("Recent Pulse Regulatory Themes (private memory): " + " | ".join(themes))
            except Exception:
                pass
            # Fresh: count [Security-Relevant] in this report for Shield visibility (private memory consumption + reporting coordination)
            sec_count = sum(1 for f in raised if "[Security-Relevant]" in (getattr(f, "title", "") or ""))
            if sec_count:
                summary_lines.append(f"({sec_count} [Security-Relevant] items included — triage in Security/Shield tab)")
            for f in raised:
                summary_lines.append(f"• [{f.importance}] {f.title}: {f.summary[:120]}...")
            summary = "\n".join(summary_lines)
            # Save as new raised finding (reuses save, will show in all coordination surfaces)
            # Context-aware: auto-link report to current project filter if active (makes "View in Intel for Project" produce usable CoS artifacts)
            link_kwargs = {}
            if self._current_project_context:
                link_kwargs["linked_projects"] = [self._current_project_context]
            fid = self.intel.save_finding(
                title="Regulatory Pulse Report (for CoS briefing)",
                summary=summary,
                source="pulse_report_note",
                importance="high",
                raised=True,
                **link_kwargs
            )
            self._refresh_findings()
            QMessageBox.information(self, "Pulse Report Created", f"Created raised Pulse Report note (id {fid}, themes included, linked to project if filtered).\n\nIt will appear in CoS context, daily briefings, and Compliance loads. Use for coordination/planning. (View in Intel for full private memory surface)")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not create Pulse report: {e}")

    def _link_to_client(self):
        current = self.findings_table.currentRow()
        if current < 0:
            return
        finding_id = self.findings_table.item(current, 0).data(Qt.ItemDataRole.UserRole)
        if not finding_id:
            return

        finding = self.intel.get_finding(finding_id)
        if not finding:
            return

        # Simple client selector dialog
        clients = self.db.list_clients(active_only=False, limit=200)
        if not clients:
            QMessageBox.information(self, "Intel", "No clients found.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Select Client")
        layout = QVBoxLayout(dlg)
        list_widget = QListWidget()
        try:
            from core.intel import IntelService
            isvc = IntelService(self.db)
        except Exception:
            isvc = None
        for c in clients:
            cid = c.get('id')
            cname = f"{c.get('name')} (#{cid})"
            if isvc:
                try:
                    w_list = [w for w in (isvc.list_watch_topics() or []) if getattr(w, 'client_id', None) == cid]
                    has_r = bool(isvc.list_findings(client_id=cid, raised_only=True, limit=1))
                    if w_list or has_r:
                        cname += " 📡"
                        tip = "Pulse watches: " + ", ".join([getattr(w,'topic','')[:20] for w in w_list[:2]]) if w_list else "Has recent raised intel"
                        item = QListWidgetItem(cname)
                        item.setToolTip(tip)
                    else:
                        item = QListWidgetItem(cname)
                except Exception:
                    item = QListWidgetItem(cname)
            else:
                item = QListWidgetItem(cname)
            item.setData(Qt.ItemDataRole.UserRole, cid)
            list_widget.addItem(item)
        layout.addWidget(list_widget)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            selected = list_widget.currentItem()
            if selected:
                client_id = selected.data(Qt.ItemDataRole.UserRole)
                # Use dedicated update path (not save_finding) to avoid duplicating the finding row
                self.intel.update_finding(
                    finding.id,
                    linked_clients=finding.linked_clients + [client_id],
                    linked_projects=finding.linked_projects,
                )
                self._refresh_findings()

    def _link_to_project(self):
        """Phase 2: symmetric project linking for Intel findings (cross-link to Projects tab / dossier). Smallest safe copy of client logic + reuse save with projects list."""
        current = self.findings_table.currentRow()
        if current < 0:
            return
        finding_id = self.findings_table.item(current, 0).data(Qt.ItemDataRole.UserRole)
        if not finding_id:
            return

        finding = self.intel.get_finding(finding_id)
        if not finding:
            return

        # Simple project selector (reuse client list pattern; projects from db)
        projects = self.db.list_projects(limit=200) or []
        if not projects:
            QMessageBox.information(self, "Intel", "No projects found.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Select Project")
        layout = QVBoxLayout(dlg)
        list_widget = QListWidget()
        for p in projects:
            item = QListWidgetItem(f"{p.get('name','(untitled)')} (#{p.get('id')})")
            item.setData(Qt.ItemDataRole.UserRole, p.get('id'))
            list_widget.addItem(item)
        layout.addWidget(list_widget)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            selected = list_widget.currentItem()
            if selected:
                proj_id = selected.data(Qt.ItemDataRole.UserRole)
                # Use dedicated update path to avoid duplicating the finding
                self.intel.update_finding(
                    finding.id,
                    linked_clients=finding.linked_clients,
                    linked_projects=(finding.linked_projects or []) + [proj_id],
                )
                self._refresh_findings()

    # ---------------- Public API for main window ----------------

    def get_raised_count(self) -> int:
        """Used by the main window to show a badge on the Intel tab."""
        return self.intel.get_raised_count()

    def refresh(self):
        """Can be called by the main window to refresh data."""
        self._refresh_watchlist()
        self._refresh_findings()

    def _set_project_context(self, project_id: int) -> None:
        """Tiny handler for focus from Projects panel: show temporary header note and (future) filter hint. Keeps diff minimal."""
        try:
            # Get project name for nice message
            proj = self.db.client_get(project_id) if hasattr(self.db, 'client_get') else None  # fallback safe
            # Actually use list_projects or simple
            p_name = f"#{project_id}"
            try:
                projs = self.db.list_projects(limit=50) or []
                for p in projs:
                    if p.get('id') == project_id:
                        p_name = p.get('name', p_name)
                        break
            except Exception:
                pass
            self._current_project_context = project_id
            self.project_context_label.setText(f"Project filter active for {p_name}: table shows only relevant findings, new items auto-link, right-click to manage links. Click Clear or refresh for all.")
            self.project_context_label.show()
            self.clear_context_btn.show()
            if hasattr(self, 'jump_projects_btn'):
                self.jump_projects_btn.show()
            self.status_label.setText(f"Project #{project_id} context active - table filtered, new findings will auto-link.")
            if hasattr(self, 'watch_topic_input'):
                self.watch_topic_input.setPlaceholderText(f"Display name (e.g. FDA AI/ML Guidance for Project #{project_id})")
            if hasattr(self, 'watch_group'):
                self.watch_group.setTitle(f"Watch Topics (for Project #{project_id} - auto-associated on create)")
            if hasattr(self, 'btn_for_proj'):
                self.btn_for_proj.setText(f"For Project #{project_id}")
                self.btn_for_proj.show()
            if hasattr(self, 'btn_research'):
                self.btn_research.setToolTip(f"Research (will be linked to current project #{project_id})")
            if hasattr(self, 'btn_run_monitor'):
                self.btn_run_monitor.setToolTip(f"Run Monitoring Now (findings from project-associated topics will auto-link to #{project_id})")
            self._refresh_findings()  # apply filter immediately
        except Exception:
            self.project_context_label.setText(f"Project context #{project_id} (cross-link from Projects).")
            self.project_context_label.show()
            self.clear_context_btn.show()

    def _set_client_context(self, client_id: int) -> None:
        """Tiny handler for focus from Billing Pulse awareness row: filter findings table to this client's linked intel."""
        try:
            self._current_client_context = client_id
            self._current_project_context = None  # client takes precedence for Billing use-case
            c_name = f"#{client_id}"
            try:
                clis = self.db.list_clients(active_only=False, limit=100) or []
                for c in clis:
                    if c.get('id') == client_id:
                        c_name = c.get('name', c_name)
                        break
            except Exception:
                pass
            if hasattr(self, 'project_context_label'):
                self.project_context_label.setText(f"Client filter active for {c_name} (from Billing): table shows client-linked Pulse findings (incl. from client-scoped watches)")
                self.project_context_label.show()
            if hasattr(self, 'clear_context_btn'):
                self.clear_context_btn.show()
            self.status_label.setText(f"Client {c_name} filter active from Billing — viewing relevant Pulse intel (findings from client-scoped watches included).")
            if hasattr(self, 'header_label'):
                self.header_label.setText(f"Intel — Pulse | Client: {c_name}")  # rock-solid client context in header when set from dossier View button
            if hasattr(self, 'btn_run_monitor'):
                self.btn_run_monitor.setToolTip("Run Monitoring Now (client context from Billing filters results view; monitoring scopes to project watches if any)")
            if hasattr(self, 'watch_topic_input'):
                self.watch_topic_input.setPlaceholderText(f"Display name (e.g. regulatory update for client {c_name})")
            if hasattr(self, 'watch_group'):
                self.watch_group.setTitle(f"Watch Topics (for Client {c_name} from Billing - 👤 client-scoped; grouped first in list, actionable via +Watch or create)")
            if hasattr(self, 'btn_research'):
                self.btn_research.setToolTip(f"Research (will be linked to current client {c_name} from Billing)")
            self._refresh_findings()
            if hasattr(self, '_refresh_watchlist'):
                self._refresh_watchlist()  # ensure client watches grouped/highlighted when context set from dossier/Billing
        except Exception:
            self.status_label.setText(f"Client context #{client_id} (from Billing).")

    def _clear_project_context(self):
        """Clear filter and header (tiny control for user when context active from Projects or Billing client awareness; called on tab switches via showEvent too)."""
        self._current_project_context = None
        self._current_client_context = None
        self.project_context_label.hide()
        self.clear_context_btn.hide()
        if hasattr(self, 'jump_projects_btn'):
            self.jump_projects_btn.hide()
        if hasattr(self, 'btn_for_proj'):
            self.btn_for_proj.setText("For current project")  # reset text on clear
            self.btn_for_proj.hide()
        if hasattr(self, 'watch_group'):
            self.watch_group.setTitle("Watch Topics")  # reset title on clear (client/project scoped notes cleared)
        if hasattr(self, 'watch_topic_input'):
            self.watch_topic_input.setPlaceholderText("Display name (e.g. FDA AI/ML Guidance; context may auto-scope to project/client)")
        # Ensure clean global reset: no stale filter text (project or client from Billing), default themes/status, table tooltip cleared
        self.project_context_label.setText("")  # explicit clear of any context text
        self.themes_label.setText("Active Pulse Regulatory Themes (private memory): (run monitoring or refresh)")
        self.status_label.setText("Context cleared - showing all findings")
        if hasattr(self, 'findings_table'):
            self.findings_table.setToolTip("")
        if hasattr(self, 'btn_run_monitor'):
            self.btn_run_monitor.setToolTip("Run Monitoring Now (respects active project filter when set)")
        if hasattr(self, 'btn_research'):
            self.btn_research.setToolTip("Research (will be linked to current project/client if filtered)")
        if hasattr(self, 'header_label'):
            self.header_label.setText("Intel — Pulse")  # reset any client/project context from dossier/Billing button
        self._refresh_findings()
        if hasattr(self, '_refresh_watchlist'):
            self._refresh_watchlist()  # clean watch grouping after clear (from dossier button use)

    def _jump_to_project(self):
        """Tiny actionable jump back: if parent supports, focus Projects tab and try to select the current project (reuses existing switch patterns from clients_tab etc.)."""
        if self._current_project_context and hasattr(self, 'parent') and self.parent():
            p = self.parent()
            # Try common patterns for switching to projects
            if hasattr(p, 'tab_widget'):
                for i in range(p.tab_widget.count()):
                    if 'Project' in str(p.tab_widget.tabText(i) or '') or 'Tasks' in str(p.tab_widget.tabText(i) or ''):
                        p.tab_widget.setCurrentIndex(i)
                        break
            # Fallback message
            self.status_label.setText(f"Switched toward Projects for #{self._current_project_context} (use panel to select specific row).")

    def _link_finding_to_current_context(self, finding_id):
        """Tiny action: link the selected finding to the current project filter if not already (when Intel is filtered)."""
        if not self._current_project_context:
            return
        try:
            finding = self.intel.get_finding(finding_id)
            if not finding:
                return
            current_projs = getattr(finding, 'linked_projects', None) or []
            if self._current_project_context not in current_projs:
                self.intel.save_finding(
                    title=finding.title,
                    summary=finding.summary,
                    source=finding.source,
                    importance=finding.importance,
                    linked_clients=getattr(finding, 'linked_clients', None) or [],
                    linked_projects=current_projs + [self._current_project_context],
                    raised=getattr(finding, 'raised', False),
                )
                self._refresh_findings()
                self.status_label.setText(f"Linked finding to current project context #{self._current_project_context}. The Relevant Pulse Intel in Projects panel will update on Refresh or its 'Refresh Intel' button.")
        except Exception as e:
            self.status_label.setText(f"Link failed: {str(e)[:50]}")

    def showEvent(self, event):
        """Ensure no stale header ts or context labels on tab switch/return (re-apply using current contexts + freshness)."""
        super().showEvent(event)
        try:
            if hasattr(self, 'header_label') and hasattr(self, 'intel'):
                ts = self.intel.get_last_pulse_display()
                self.header_label.setText(f"Intel — Pulse | last: {ts}")
            # Re-apply any active context labels without full table reload if possible
            if (getattr(self, '_current_project_context', None) or getattr(self, '_current_client_context', None)) and hasattr(self, '_refresh_findings'):
                self._refresh_findings()
        except Exception:
            pass
