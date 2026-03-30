# db.py
import sqlite3
from datetime import datetime, UTC
import json
import sys
import os

# Import centralized database path and artifact store
from config import DATABASE_PATH, ARTIFACTS_DIR

_UNSET = object()

class DatabaseManager:
    def __init__(self, db_name: str | None = None):
        self.db_name = str(db_name or DATABASE_PATH)
        self.current_schema_version = 20  # Increment this when making schema changes
        self.setup_db()
        self.create_indexes()
        # Additive tables for newer features (safe for legacy DBs)
        try:
            self.init_workspace_collab_tables()
        except Exception:
            pass
        try:
            self.init_workspace_state_tables()
        except Exception:
            pass
        try:
            self.init_meetings_tables()
        except Exception:
            pass
        try:
            self.seed_default_agents()
        except Exception:
            pass

    def setup_db(self):
        with sqlite3.connect(self.db_name) as conn:
            # Initialize schema versioning
            self._initialize_schema_version(conn)
            
            # Check if migration is needed
            current_version = self._get_schema_version(conn)
            if current_version < self.current_schema_version:
                print(f"Database schema version {current_version} detected. Migrating to version {self.current_schema_version}...")
                self._migrate_schema(conn, current_version, self.current_schema_version)
                self._set_schema_version(conn, self.current_schema_version)
                print("Schema migration completed.")
            
            # Create conversation table with FTS5 support if it doesn't exist
            conn.execute('''CREATE VIRTUAL TABLE IF NOT EXISTS conversation
                USING fts5 (
                    session_id,
                    role,
                    content,
                    timestamp,
                    tokenize='porter'
                )''')
            
            conn.execute('''CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                task_text TEXT,
                due_date TEXT,
                category TEXT,
                recurrence TEXT,
                completed INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            
            # Check if the table exists with old schema and migrate it (wrapped in transaction)
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(tasks)")
            columns = [col[1] for col in cursor.fetchall()]

            conn.execute("BEGIN")
            try:
                # If task_text doesn't exist, try to migrate from common alternatives
                if 'task_text' not in columns:
                    if 'task' in columns:
                        conn.execute("ALTER TABLE tasks RENAME COLUMN task TO task_text")
                        print("DEBUG: Migrated 'task' column to 'task_text'")
                    elif 'description' in columns:
                        conn.execute("ALTER TABLE tasks RENAME COLUMN description TO task_text")
                        print("DEBUG: Migrated 'description' column to 'task_text'")
                    elif 'content' in columns:
                        conn.execute("ALTER TABLE tasks RENAME COLUMN content TO task_text")
                        print("DEBUG: Migrated 'content' column to 'task_text'")
                    else:
                        print("WARNING: Could not find task column to migrate")

                # Re-fetch columns after potential rename
                cursor.execute("PRAGMA table_info(tasks)")
                columns = [col[1] for col in cursor.fetchall()]

                if 'category' not in columns:
                    conn.execute("ALTER TABLE tasks ADD COLUMN category TEXT DEFAULT 'Business'")
                    print("DEBUG: Added 'category' column with default 'Business'")

                if 'recurrence' not in columns:
                    conn.execute("ALTER TABLE tasks ADD COLUMN recurrence TEXT DEFAULT 'None'")
                    print("DEBUG: Added 'recurrence' column with default 'None'")

                if 'session_id' not in columns:
                    conn.execute("ALTER TABLE tasks ADD COLUMN session_id TEXT")
                    print("DEBUG: Added 'session_id' column")

                # Backfill/extend tasks schema with richer fields (legacy DBs)
                cursor.execute("PRAGMA table_info(tasks)")
                columns = [col[1] for col in cursor.fetchall()]
                if "priority" not in columns:
                    conn.execute("ALTER TABLE tasks ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")
                if "tags_json" not in columns:
                    conn.execute("ALTER TABLE tasks ADD COLUMN tags_json TEXT")
                if "next_action_date" not in columns:
                    conn.execute("ALTER TABLE tasks ADD COLUMN next_action_date TEXT")
                if "snoozed_until" not in columns:
                    conn.execute("ALTER TABLE tasks ADD COLUMN snoozed_until TEXT")
                if "updated_at" not in columns:
                    conn.execute("ALTER TABLE tasks ADD COLUMN updated_at DATETIME")
                if "cos_project_id" not in columns:
                    conn.execute("ALTER TABLE tasks ADD COLUMN cos_project_id INTEGER")
                # Project-management extensions
                if "start_date" not in columns:
                    conn.execute("ALTER TABLE tasks ADD COLUMN start_date TEXT")
                if "estimate_minutes" not in columns:
                    conn.execute("ALTER TABLE tasks ADD COLUMN estimate_minutes INTEGER NOT NULL DEFAULT 0")
                if "blockers" not in columns:
                    conn.execute("ALTER TABLE tasks ADD COLUMN blockers TEXT")
                if "depends_on_json" not in columns:
                    conn.execute("ALTER TABLE tasks ADD COLUMN depends_on_json TEXT")

                conn.commit()
            except Exception:
                conn.rollback()
                raise
            
            # Update archived_tasks table to match new schema
            conn.execute('DROP TABLE IF EXISTS archived_tasks')
            conn.execute('''CREATE TABLE archived_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_text TEXT,
                due_date TEXT,
                category TEXT,
                recurrence TEXT,
                completed INTEGER,
                session_id TEXT,
                created_at DATETIME,
                archived_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            
            # News table for storing news items with URLs and duplicate checking
            conn.execute('''CREATE TABLE IF NOT EXISTS news_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                url TEXT,
                source TEXT,
                published_date TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(title, url)
            )''')

            # Dedup index for news_items. This lets us dedup across:
            # - tracking-param variations in URLs (canonicalization)
            # - minor title variations (normalized title + date fallback)
            conn.execute('''CREATE TABLE IF NOT EXISTS news_dedup (
                dedup_key TEXT PRIMARY KEY,
                news_id INTEGER,
                first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_shown DATETIME
            )''')

            conn.execute("CREATE INDEX IF NOT EXISTS idx_news_dedup_news_id ON news_dedup(news_id)")

            # App settings (simple persistent key/value store)
            conn.execute('''CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')

            # Lead generation tables
            conn.execute('''CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_key TEXT NOT NULL UNIQUE,
                company_key TEXT,
                name TEXT NOT NULL,
                company TEXT NOT NULL,
                title TEXT,
                linkedin_url TEXT,
                company_url TEXT,
                rationale TEXT,
                message TEXT,
                status TEXT NOT NULL DEFAULT 'new',
                contacted INTEGER DEFAULT 0,
                contact_date TEXT,
                next_action_date TEXT,
                notes TEXT,
                signals_json TEXT,
                sources_json TEXT,
                signals_score INTEGER DEFAULT 0,
                fit_score INTEGER DEFAULT 0,
                confidence_score INTEGER DEFAULT 0,
                total_score INTEGER DEFAULT 0,
                first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')

            # Chief of Staff memory (structured, searchable)
            conn.execute('''CREATE TABLE IF NOT EXISTS cos_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                kind TEXT NOT NULL,
                content TEXT NOT NULL,
                json_data TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cos_memory_chat_id ON cos_memory(chat_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cos_memory_kind ON cos_memory(kind)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cos_memory_created_at ON cos_memory(created_at)")

            # FTS for cos_memory (mem_id used to retrieve full row)
            conn.execute('''CREATE VIRTUAL TABLE IF NOT EXISTS cos_memory_fts
                USING fts5 (
                    mem_id UNINDEXED,
                    chat_id UNINDEXED,
                    kind UNINDEXED,
                    content,
                    created_at UNINDEXED,
                    tokenize='porter'
                )''')

            # Agent directory + assignment workflow (Chief of Staff delegation backbone)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_directory (
                    code TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    role_title TEXT NOT NULL,
                    home_tab TEXT NOT NULL,
                    aliases_json TEXT NOT NULL DEFAULT '[]',
                    capabilities_json TEXT NOT NULL DEFAULT '[]',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_threads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_code TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT 'New thread',
                    session_id TEXT NOT NULL UNIQUE,
                    context_json TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    last_message_at TEXT,
                    FOREIGN KEY (agent_code) REFERENCES agent_directory(code)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_assignments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    brief_md TEXT NOT NULL,
                    requester_code TEXT NOT NULL,
                    assignee_code TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 3,
                    due_date TEXT,
                    status TEXT NOT NULL DEFAULT 'queued',
                    source_thread_id INTEGER,
                    source_project_id INTEGER,
                    context_json TEXT,
                    result_summary_md TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    completed_at TEXT,
                    FOREIGN KEY (requester_code) REFERENCES agent_directory(code),
                    FOREIGN KEY (assignee_code) REFERENCES agent_directory(code),
                    FOREIGN KEY (source_thread_id) REFERENCES agent_threads(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_assignment_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    assignment_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    from_status TEXT,
                    to_status TEXT,
                    actor_code TEXT,
                    note TEXT,
                    created_at TEXT,
                    FOREIGN KEY (assignment_id) REFERENCES agent_assignments(id),
                    FOREIGN KEY (actor_code) REFERENCES agent_directory(code)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    assignment_id INTEGER,
                    thread_id INTEGER,
                    artifact_type TEXT NOT NULL,
                    title TEXT,
                    content_md TEXT,
                    content_json TEXT,
                    file_path TEXT,
                    created_at TEXT,
                    FOREIGN KEY (assignment_id) REFERENCES agent_assignments(id),
                    FOREIGN KEY (thread_id) REFERENCES agent_threads(id)
                )
                """
            )
            
            # Dropbox index tables removed - using RAG index instead
            
            # Notes table for the NoteTakingSystem
            conn.execute('''CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                formatted_note TEXT NOT NULL,
                category TEXT NOT NULL,
                context TEXT,
                raw_note TEXT,
                state TEXT NOT NULL DEFAULT 'ready', -- ready|pending|error
                error_text TEXT,
                pinned INTEGER NOT NULL DEFAULT 0,
                timestamp TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            
            # Add context column if it doesn't exist (for existing databases)
            try:
                conn.execute('ALTER TABLE notes ADD COLUMN context TEXT')
            except sqlite3.OperationalError:
                # Column already exists
                pass

            # Backfill/extend notes table schema for legacy DBs
            self._ensure_notes_schema(conn)

            # FTS for notes (best-effort). If FTS5 isn't available, search falls back to LIKE.
            try:
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts
                    USING fts5(
                        formatted_note,
                        context,
                        category,
                        content='notes',
                        content_rowid='id',
                        tokenize='porter'
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
                        INSERT INTO notes_fts(rowid, formatted_note, context, category)
                        VALUES (new.id, new.formatted_note, new.context, new.category);
                    END;
                    """
                )
                conn.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
                        INSERT INTO notes_fts(notes_fts, rowid, formatted_note, context, category)
                        VALUES('delete', old.id, old.formatted_note, old.context, old.category);
                    END;
                    """
                )
                conn.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
                        INSERT INTO notes_fts(notes_fts, rowid, formatted_note, context, category)
                        VALUES('delete', old.id, old.formatted_note, old.context, old.category);
                        INSERT INTO notes_fts(rowid, formatted_note, context, category)
                        VALUES (new.id, new.formatted_note, new.context, new.category);
                    END;
                    """
                )
            except Exception:
                pass

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notes_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    context TEXT NOT NULL UNIQUE,
                    title TEXT,
                    document_text TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL DEFAULT 'ready',
                    error_text TEXT,
                    source_note_count INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self._ensure_notes_documents_schema(conn)

            # Keep legacy organized notes storage available during the transition.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS organized_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    notes_json TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self._backfill_notes_documents_from_legacy_notes(conn)
            conn.commit()

    def _ensure_notes_schema(self, conn) -> None:
        """Best-effort notes-table backfill for legacy databases."""
        try:
            cursor = conn.execute("PRAGMA table_info(notes)")
            cols = {row[1] for row in cursor.fetchall()}
            if not cols:
                return
            if "raw_note" not in cols:
                conn.execute("ALTER TABLE notes ADD COLUMN raw_note TEXT")
            if "state" not in cols:
                conn.execute("ALTER TABLE notes ADD COLUMN state TEXT NOT NULL DEFAULT 'ready'")
            if "error_text" not in cols:
                conn.execute("ALTER TABLE notes ADD COLUMN error_text TEXT")
            if "pinned" not in cols:
                conn.execute("ALTER TABLE notes ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
            if "updated_at" not in cols:
                conn.execute("ALTER TABLE notes ADD COLUMN updated_at DATETIME")
                conn.execute("UPDATE notes SET updated_at = COALESCE(updated_at, created_at, datetime('now'))")
        except Exception:
            pass

    def _ensure_notes_documents_schema(self, conn) -> None:
        """Best-effort notes-documents backfill for legacy databases."""
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notes_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    context TEXT NOT NULL UNIQUE,
                    title TEXT,
                    document_text TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL DEFAULT 'ready',
                    error_text TEXT,
                    source_note_count INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor = conn.execute("PRAGMA table_info(notes_documents)")
            cols = {row[1] for row in cursor.fetchall()}
            if not cols:
                return
            if "title" not in cols:
                conn.execute("ALTER TABLE notes_documents ADD COLUMN title TEXT")
            if "document_text" not in cols:
                conn.execute("ALTER TABLE notes_documents ADD COLUMN document_text TEXT NOT NULL DEFAULT ''")
            if "state" not in cols:
                conn.execute("ALTER TABLE notes_documents ADD COLUMN state TEXT NOT NULL DEFAULT 'ready'")
            if "error_text" not in cols:
                conn.execute("ALTER TABLE notes_documents ADD COLUMN error_text TEXT")
            if "source_note_count" not in cols:
                conn.execute("ALTER TABLE notes_documents ADD COLUMN source_note_count INTEGER NOT NULL DEFAULT 0")
            if "updated_at" not in cols:
                conn.execute("ALTER TABLE notes_documents ADD COLUMN updated_at DATETIME")
                conn.execute(
                    "UPDATE notes_documents SET updated_at = COALESCE(updated_at, created_at, datetime('now'))"
                )
        except Exception:
            pass

    @staticmethod
    def _normalize_notes_context(context: str | None) -> str:
        value = (context or "").strip()
        return value or "General Notes"

    def _build_legacy_notes_document(self, context: str, rows: list[dict]) -> str:
        groups: dict[str, list[str]] = {}
        for row in rows:
            category = (row.get("category") or "Notes").strip() or "Notes"
            text = (row.get("formatted_note") or row.get("raw_note") or "").strip()
            if not text:
                continue
            groups.setdefault(category, []).append(text)

        lines: list[str] = []
        for category in sorted(groups.keys(), key=lambda s: s.lower()):
            lines.append(f"## {category}")
            seen: set[str] = set()
            for text in groups[category]:
                norm = text.strip().lower()
                if not norm or norm in seen:
                    continue
                seen.add(norm)
                lines.append(f"- {text}")
            lines.append("")
        return "\n".join(lines).strip()

    def _backfill_notes_documents_from_legacy_notes(self, conn) -> None:
        """Seed one starter document per context from existing ready note rows."""
        try:
            self._ensure_notes_schema(conn)
            self._ensure_notes_documents_schema(conn)
            existing = {
                (row[0] or "").strip()
                for row in conn.execute("SELECT context FROM notes_documents").fetchall()
                if (row[0] or "").strip()
            }
            rows = conn.execute(
                """
                SELECT formatted_note, raw_note, category, context
                FROM notes
                WHERE state = 'ready'
                ORDER BY created_at ASC, id ASC
                """
            ).fetchall()
            grouped: dict[str, list[dict]] = {}
            for formatted_note, raw_note, category, context in rows:
                normalized = self._normalize_notes_context(context)
                if normalized in existing:
                    continue
                grouped.setdefault(normalized, []).append(
                    {
                        "formatted_note": formatted_note or "",
                        "raw_note": raw_note or "",
                        "category": category or "Notes",
                    }
                )

            for context, items in grouped.items():
                document_text = self._build_legacy_notes_document(context, items)
                conn.execute(
                    """
                    INSERT INTO notes_documents (
                        context, title, document_text, state, error_text, source_note_count, created_at, updated_at
                    )
                    VALUES (?, ?, ?, 'ready', NULL, ?, datetime('now'), datetime('now'))
                    ON CONFLICT(context) DO NOTHING
                    """,
                    (context, context, document_text, len(items)),
                )
        except Exception:
            pass

        # Multi-agent tables are created in migration 2 -> 3 (see _migrate_schema)

        # Best-effort: backfill dedup keys for existing news items
        self.backfill_news_dedup()

    def get_setting(self, key: str, default=None):
        try:
            with sqlite3.connect(self.db_name) as conn:
                row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
                return row[0] if row and row[0] is not None else default
        except Exception:
            return default

    def set_setting(self, key: str, value) -> None:
        try:
            with sqlite3.connect(self.db_name) as conn:
                conn.execute(
                    """
                    INSERT INTO app_settings (key, value, updated_at)
                    VALUES (?, ?, datetime('now'))
                    ON CONFLICT(key) DO UPDATE SET
                        value=excluded.value,
                        updated_at=excluded.updated_at
                    """,
                    (key, str(value)),
                )
                conn.commit()
        except Exception:
            return

    # ------------------------------------------------------------------
    # Email rules + unreplied emails (UI support)
    # ------------------------------------------------------------------

    def get_email_rules(self) -> dict:
        """
        Return email classification rules for client/potential detection.
        Stored in app_settings as JSON under key 'email_rules_json'.
        Falls back to environment variables for backward compatibility.
        """
        import json
        import os

        raw = ""
        try:
            raw = str(self.get_setting("email_rules_json", "") or "").strip()
        except Exception:
            raw = ""

        if raw:
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    return {
                        "client_domains": data.get("client_domains") or [],
                        "potential_domains": data.get("potential_domains") or [],
                        "client_labels": data.get("client_labels") or [],
                        "potential_labels": data.get("potential_labels") or [],
                    }
            except Exception:
                pass

        # Env fallback
        def _split(name: str, default: str = "") -> list[str]:
            try:
                v = os.getenv(name) or default
                return [s.strip() for s in v.split(",") if s.strip()]
            except Exception:
                return [s.strip() for s in default.split(",") if s.strip()]

        return {
            "client_domains": _split("EMAIL_CLIENT_DOMAINS", "goldbugstrategies.com,dovahealth.ca"),
            "potential_domains": _split("EMAIL_POTENTIAL_DOMAINS", ""),
            "client_labels": _split("EMAIL_CLIENT_LABELS", "Clients,Client"),
            "potential_labels": _split("EMAIL_POTENTIAL_LABELS", "Leads,Lead"),
        }

    def set_email_rules(
        self,
        *,
        client_domains: list[str],
        potential_domains: list[str],
        client_labels: list[str],
        potential_labels: list[str],
    ) -> None:
        import json

        payload = {
            "client_domains": [str(s).strip() for s in (client_domains or []) if str(s).strip()],
            "potential_domains": [str(s).strip() for s in (potential_domains or []) if str(s).strip()],
            "client_labels": [str(s).strip() for s in (client_labels or []) if str(s).strip()],
            "potential_labels": [str(s).strip() for s in (potential_labels or []) if str(s).strip()],
        }
        self.set_setting("email_rules_json", json.dumps(payload, ensure_ascii=False))

    def list_important_emails(
        self,
        *,
        limit: int = 50,
        days: int = 30,
        include_triaged: bool = False,
    ) -> list[dict]:
        """Return important emails for dashboard triage."""
        from datetime import timedelta

        cutoff = int((datetime.now(UTC) - timedelta(days=int(days))).timestamp())
        where = ["e.timestamp >= ?"]
        params: list[object] = [cutoff]
        if not include_triaged:
            where.append("COALESCE(e.needs_attention, 0) = 1")
            where.append("COALESCE(e.triage_status, 'new') IN ('new', 'important')")
        query = f"""
            SELECT
                e.id,
                e.sender,
                e.subject,
                e.timestamp,
                e.content,
                e.replied,
                e.is_client,
                e.is_potential,
                e.source,
                e.folder,
                e.account,
                e.triage_status,
                e.importance_score,
                e.needs_attention,
                e.importance_reason_json,
                e.triaged_at,
                e.triage_source,
                e.client_id,
                e.cos_project_id,
                c.name AS client_name,
                p.name AS project_name
            FROM emails e
            LEFT JOIN clients c ON c.id = e.client_id
            LEFT JOIN cos_projects p ON p.id = e.cos_project_id
            WHERE {' AND '.join(where)}
            ORDER BY COALESCE(e.importance_score, 0) DESC, e.timestamp DESC
            LIMIT ?
        """
        params.append(int(limit))
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            rows = [dict(r) for r in conn.execute(query, params).fetchall()]
        for row in rows:
            raw_reasons = row.get("importance_reason_json")
            try:
                row["importance_reasons"] = json.loads(raw_reasons) if raw_reasons else []
            except Exception:
                row["importance_reasons"] = []
        return rows

    def update_email_triage(
        self,
        email_id: str,
        *,
        triage_status=_UNSET,
        importance_score=_UNSET,
        needs_attention=_UNSET,
        importance_reason_json=_UNSET,
        triage_source=_UNSET,
        client_id=_UNSET,
        cos_project_id=_UNSET,
    ) -> bool:
        updates = []
        values: list[object] = []

        if triage_status is not _UNSET:
            status_value = str(triage_status or "new").strip() or "new"
            updates.append("triage_status = ?")
            values.append(status_value)
            updates.append("triaged_at = ?")
            values.append(datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
            if needs_attention is _UNSET:
                if status_value in {"archived", "unimportant", "junk"}:
                    needs_attention = 0
                elif status_value == "important":
                    needs_attention = 1

        if importance_score is not _UNSET:
            updates.append("importance_score = ?")
            values.append(int(importance_score or 0))
        if needs_attention is not _UNSET:
            updates.append("needs_attention = ?")
            values.append(int(bool(needs_attention)))
        if importance_reason_json is not _UNSET:
            payload = importance_reason_json
            if isinstance(payload, (list, dict)):
                payload = json.dumps(payload, ensure_ascii=False)
            payload = str(payload or "[]")
            updates.append("importance_reason_json = ?")
            values.append(payload)
        if triage_source is not _UNSET:
            updates.append("triage_source = ?")
            values.append(str(triage_source) if triage_source else None)
        if client_id is not _UNSET:
            updates.append("client_id = ?")
            values.append(int(client_id) if client_id is not None else None)
        if cos_project_id is not _UNSET:
            updates.append("cos_project_id = ?")
            values.append(int(cos_project_id) if cos_project_id is not None else None)

        if not updates:
            return False

        values.append(str(email_id))
        with sqlite3.connect(self.db_name) as conn:
            conn.execute(f"UPDATE emails SET {', '.join(updates)} WHERE id = ?", values)
            conn.commit()
        return True

    def link_email_to_client(self, email_id: str, client_id: int | None) -> None:
        self.update_email_triage(
            email_id,
            client_id=client_id,
            triage_source="manual",
        )

    def link_email_to_project(self, email_id: str, cos_project_id: int | None) -> None:
        self.update_email_triage(
            email_id,
            cos_project_id=cos_project_id,
            triage_source="manual",
        )

    def list_unreplied_emails(
        self,
        *,
        limit: int = 50,
        only_clients_or_potentials: bool = True,
        days: int = 14,
    ) -> list[dict]:
        """Return unreplied emails (best-effort) for a dedicated UI view."""
        from datetime import datetime, UTC, timedelta

        cutoff = int((datetime.now(UTC) - timedelta(days=int(days))).timestamp())
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            if only_clients_or_potentials:
                cur = conn.execute(
                    """
                    SELECT id, sender, subject, timestamp, content, replied, is_client, is_potential, source, folder, account
                    FROM emails
                    WHERE replied = 0
                      AND timestamp >= ?
                      AND (is_client = 1 OR is_potential = 1)
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (cutoff, int(limit)),
                )
            else:
                cur = conn.execute(
                    """
                    SELECT id, sender, subject, timestamp, content, replied, is_client, is_potential, source, folder, account
                    FROM emails
                    WHERE replied = 0
                      AND timestamp >= ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (cutoff, int(limit)),
                )
            return [dict(r) for r in cur.fetchall()]

    def mark_email_replied(self, email_id: str, replied: int = 1) -> None:
        with sqlite3.connect(self.db_name) as conn:
            conn.execute("UPDATE emails SET replied = ? WHERE id = ?", (int(replied), str(email_id)))
            conn.commit()

    def reclassify_emails(self, *, days: int = 30) -> int:
        """
        Recompute is_client/is_potential for recent emails using current rules.
        Returns number of rows updated (best-effort).
        """
        from datetime import datetime, UTC, timedelta
        from core.email_utils import classify_email

        rules = self.get_email_rules()
        cutoff = int((datetime.now(UTC) - timedelta(days=int(days))).timestamp())
        updated = 0
        with sqlite3.connect(self.db_name) as conn:
            cur = conn.execute(
                """
                SELECT id, sender, folder
                FROM emails
                WHERE timestamp >= ?
                """,
                (cutoff,),
            )
            rows = cur.fetchall()
            for email_id, sender, folder in rows:
                try:
                    is_client, is_potential = classify_email(
                        sender_header=sender,
                        folder=folder,
                        client_domains=rules.get("client_domains") or [],
                        potential_domains=rules.get("potential_domains") or [],
                        client_labels=rules.get("client_labels") or [],
                        potential_labels=rules.get("potential_labels") or [],
                    )
                    conn.execute(
                        "UPDATE emails SET is_client = ?, is_potential = ? WHERE id = ?",
                        (int(is_client), int(is_potential), str(email_id)),
                    )
                    updated += 1
                except Exception:
                    continue
            conn.commit()
        return int(updated)

    def create_indexes(self):
        """Create database indexes for optimal query performance."""
        with sqlite3.connect(self.db_name) as conn:
            # Primary indexes for tasks table
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_completed ON tasks(completed)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_category ON tasks(category)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_next_action_date ON tasks(next_action_date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_snoozed_until ON tasks(snoozed_until)")
            
            # Composite indexes for common query patterns
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_due_completed ON tasks(due_date, completed)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_category_due ON tasks(category, due_date)")
            
            # Session-based queries
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id)")
            
            # Indexes for archived_tasks table
            conn.execute("CREATE INDEX IF NOT EXISTS idx_archived_tasks_due_date ON archived_tasks(due_date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_archived_tasks_completed ON archived_tasks(completed)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_archived_tasks_category ON archived_tasks(category)")
            
            # Note: conversation table is a virtual FTS5 table, so indexes are not supported
            # FTS5 provides its own internal indexing for full-text search
            
            # Indexes for news_items table
            conn.execute("CREATE INDEX IF NOT EXISTS idx_news_created_at ON news_items(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_news_source ON news_items(source)")

            # Indexes for leads table
            conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_company_key ON leads(company_key)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_contacted ON leads(contacted)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_total_score ON leads(total_score)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_last_seen ON leads(last_seen)")
            
            # Indexes for multi-agent tables
            conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_created_at ON projects(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_task_plans_project_id ON task_plans(project_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_project_tasks_project_id ON project_tasks(project_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_project_tasks_status ON project_tasks(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_project_id ON runs(project_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_project_task_id ON runs(project_task_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_project_id ON artifacts(project_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_run_id ON artifacts(run_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_artifact_type ON artifacts(artifact_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_logs_run_id ON agent_logs(run_id)")
            
            # Chief of Staff tables
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cos_projects_status ON cos_projects(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cos_projects_client ON cos_projects(client)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cos_projects_client_id ON cos_projects(client_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cos_weekly_plans_week_start ON cos_weekly_plans(week_start)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cos_daily_plans_date ON cos_daily_plans(date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cos_chats_updated_at ON cos_chats(updated_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cos_memory_chat_kind ON cos_memory(chat_id, kind)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_user_memory_kind ON user_memory(kind)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_user_memory_source ON user_memory(source)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_user_memory_created_at ON user_memory(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_user_memory_confidence ON user_memory(confidence)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_user_memory_approval_status ON user_memory(approval_status)")

            # Delegation / agent workflow tables
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_threads_agent_updated "
                "ON agent_threads(agent_code, updated_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_assignments_assignee_status "
                "ON agent_assignments(assignee_code, status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_assignments_status_priority_due "
                "ON agent_assignments(status, priority, due_date)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_assignments_requester "
                "ON agent_assignments(requester_code)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_assignment_events_assignment "
                "ON agent_assignment_events(assignment_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_artifacts_assignment "
                "ON agent_artifacts(assignment_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_artifacts_thread "
                "ON agent_artifacts(thread_id)"
            )

            # Billing tables
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_billing_clients_active "
                "ON billing_clients(is_active, name)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_clients_active ON clients(is_active, name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_client_contacts_client_id ON client_contacts(client_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_client_contacts_email ON client_contacts(email)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_client_contacts_domain ON client_contacts(domain)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_time_entries_client_start "
                "ON time_entries(client_id, start_ts)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_invoice_drafts_client_period "
                "ON invoice_drafts(client_id, period_start, period_end)"
            )
            
            conn.commit()

    def save_message(self, session_id, role, content):
        with sqlite3.connect(self.db_name) as conn:
            conn.execute('INSERT INTO conversation (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)',
                        (session_id, role, content, datetime.now()))
            conn.commit()

    def search_conversations(self, search_terms, date_range=None):
        """
        Search conversations using full-text search.
        
        Args:
            search_terms (str): The search query
            date_range (tuple, optional): (start_date, end_date) for filtering results
            
        Returns:
            list: List of tuples (role, content, timestamp) matching the search
        """
        with sqlite3.connect(self.db_name) as conn:
            query = '''
                SELECT role, content, timestamp 
                FROM conversation 
                WHERE conversation MATCH ?
            '''
            params = [search_terms]
            
            if date_range:
                query += ' AND timestamp BETWEEN ? AND ?'
                params.extend(date_range)
            
            query += ' ORDER BY timestamp DESC'
            
            cursor = conn.execute(query, params)
            return cursor.fetchall()

    def search_chat_history(self, session_id, search_terms, limit=8):
        """
        Search messages within a single chat session.

        Args:
            session_id (str): Conversation session id to scope results to
            search_terms (str): Search phrase or keywords
            limit (int): Maximum number of rows to return

        Returns:
            list: List of tuples (role, content, timestamp) ordered newest-first
        """
        session = str(session_id or "").strip()
        query = str(search_terms or "").strip()
        max_rows = max(1, min(int(limit or 8), 20))
        if not session:
            return []
        with sqlite3.connect(self.db_name) as conn:
            if query:
                like = f"%{'%'.join(query.split())}%"
                cursor = conn.execute(
                    """
                    SELECT role, content, timestamp
                    FROM conversation
                    WHERE session_id = ?
                      AND content LIKE ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (session, like, max_rows),
                )
                rows = cursor.fetchall()
                if rows:
                    return rows
            cursor = conn.execute(
                """
                SELECT role, content, timestamp
                FROM conversation
                WHERE session_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (session, max_rows),
            )
            return cursor.fetchall()

    def add_task(
        self,
        session_id,
        task_text,
        due_date,
        category="Business",
        recurrence="None",
        completed=0,
        cos_project_id=None,
        *,
        start_date: str | None = None,
        estimate_minutes: int | None = None,
        blockers: str | None = None,
        depends_on_json: str | None = None,
    ):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute(
                """
                INSERT INTO tasks
                    (
                        session_id,
                        task_text,
                        due_date,
                        category,
                        recurrence,
                        completed,
                        priority,
                        tags_json,
                        next_action_date,
                        snoozed_until,
                        created_at,
                        updated_at,
                        cos_project_id,
                        start_date,
                        estimate_minutes,
                        blockers,
                        depends_on_json
                    )
                VALUES
                    (?, ?, ?, ?, ?, ?, COALESCE(?, 0), COALESCE(?, '[]'), ?, ?, datetime('now'), datetime('now'), ?, ?, COALESCE(?, 0), ?, COALESCE(?, '[]'))
                """,
                (
                    session_id,
                    task_text,
                    due_date,
                    category,
                    recurrence,
                    completed,
                    0,
                    "[]",
                    None,
                    None,
                    int(cos_project_id) if cos_project_id is not None else None,
                    start_date,
                    int(estimate_minutes) if estimate_minutes is not None else 0,
                    blockers,
                    depends_on_json,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    _UNSET = object()

    def update_task_by_id(
        self,
        task_id: int,
        *,
        task_text: str | object = _UNSET,
        due_date: str | None | object = _UNSET,
        start_date: str | None | object = _UNSET,
        category: str | object = _UNSET,
        completed: int | object = _UNSET,
        priority: int | object = _UNSET,
        tags_json: str | None | object = _UNSET,
        next_action_date: str | None | object = _UNSET,
        snoozed_until: str | None | object = _UNSET,
        cos_project_id: int | None | object = _UNSET,
        estimate_minutes: int | object = _UNSET,
        blockers: str | None | object = _UNSET,
        depends_on_json: str | None | object = _UNSET,
    ) -> None:
        fields = []
        params = []
        if task_text is not self._UNSET:
            fields.append("task_text = ?")
            params.append(str(task_text))
        if due_date is not self._UNSET:
            fields.append("due_date = ?")
            params.append(due_date)
        if start_date is not self._UNSET:
            fields.append("start_date = ?")
            params.append(start_date)
        if category is not self._UNSET:
            fields.append("category = ?")
            params.append(str(category))
        if completed is not self._UNSET:
            fields.append("completed = ?")
            params.append(int(completed))
        if priority is not self._UNSET:
            fields.append("priority = ?")
            params.append(int(priority))
        if tags_json is not self._UNSET:
            fields.append("tags_json = ?")
            params.append(str(tags_json))
        if next_action_date is not self._UNSET:
            fields.append("next_action_date = ?")
            params.append(next_action_date)
        if snoozed_until is not self._UNSET:
            fields.append("snoozed_until = ?")
            params.append(snoozed_until)
        if cos_project_id is not self._UNSET:
            fields.append("cos_project_id = ?")
            params.append(int(cos_project_id) if cos_project_id is not None else None)
        if estimate_minutes is not self._UNSET:
            fields.append("estimate_minutes = ?")
            params.append(int(estimate_minutes) if estimate_minutes is not None else 0)
        if blockers is not self._UNSET:
            fields.append("blockers = ?")
            params.append(blockers)
        if depends_on_json is not self._UNSET:
            fields.append("depends_on_json = ?")
            params.append(str(depends_on_json) if depends_on_json is not None else "[]")
        if not fields:
            return
        fields.append("updated_at = datetime('now')")
        with sqlite3.connect(self.db_name) as conn:
            conn.execute(
                f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?",
                tuple(params + [int(task_id)]),
            )
            conn.commit()

    def get_task_by_id(self, task_id: int) -> dict | None:
        """Return a single task row as a dict (best-effort)."""
        try:
            with sqlite3.connect(self.db_name) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    """
                    SELECT
                        id, session_id, task_text, due_date, start_date, category, recurrence, completed,
                        COALESCE(priority, 0) AS priority,
                        COALESCE(tags_json, '[]') AS tags_json,
                        next_action_date,
                        snoozed_until,
                        created_at,
                        updated_at,
                        cos_project_id,
                        COALESCE(estimate_minutes, 0) AS estimate_minutes,
                        COALESCE(blockers, '') AS blockers,
                        COALESCE(depends_on_json, '[]') AS depends_on_json
                    FROM tasks
                    WHERE id = ?
                    """,
                    (int(task_id),),
                ).fetchone()
                return dict(row) if row else None
        except Exception:
            return None

    def list_tasks_rich(
        self,
        *,
        category: str | None = None,
        date_filter: str | None = None,
        specific_date: str | None = None,
        include_completed: bool = False,
        include_snoozed: bool = False,
        search: str | None = None,
        cos_project_id: int | None = None,
        sort_by: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
        """
        Return task rows as dicts including richer fields (priority/tags/next_action/snooze).
        Filtering and sorting is done in Python for correctness with MM-DD-YYYY legacy date strings.
        """
        import json
        from datetime import datetime

        def _parse_mmddyyyy(s: str | None) -> datetime | None:
            ss = (s or "").strip()
            if not ss or ss.lower() == "unknown":
                return None
            try:
                return datetime.strptime(ss, "%m-%d-%Y")
            except Exception:
                return None

        today = datetime.now()
        today_str = today.strftime("%m-%d-%Y")
        search_l = (search or "").strip().lower()

        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                """
                SELECT
                    id, session_id, task_text, due_date, category, recurrence, completed,
                    COALESCE(priority, 0) AS priority,
                    COALESCE(tags_json, '[]') AS tags_json,
                    next_action_date,
                    snoozed_until,
                    created_at,
                    cos_project_id,
                    start_date,
                    COALESCE(estimate_minutes, 0) AS estimate_minutes,
                    COALESCE(blockers, '') AS blockers,
                    COALESCE(depends_on_json, '[]') AS depends_on_json
                FROM tasks
                WHERE 1=1
                """
                + (" AND category = ?" if category else "")
                + (" AND cos_project_id = ?" if cos_project_id is not None else "")
                + " ORDER BY id DESC LIMIT ?",
                tuple(
                    ([category] if category else [])
                    + ([int(cos_project_id)] if cos_project_id is not None else [])
                    + [int(limit) * 5]
                ),
            )
            rows = [dict(r) for r in cur.fetchall()]

        out = []
        for r in rows:
            if not include_completed and int(r.get("completed") or 0) == 1:
                continue

            due_dt = _parse_mmddyyyy(r.get("due_date"))
            next_dt = _parse_mmddyyyy(r.get("next_action_date"))
            snooze_dt = _parse_mmddyyyy(r.get("snoozed_until"))

            # Snooze filter
            if not include_snoozed and snooze_dt and snooze_dt.date() > today.date():
                continue

            # Date filters (apply to due date)
            df = (date_filter or "").strip()
            if df and df != "All":
                if df == "Today":
                    if (r.get("due_date") or "") != today_str:
                        continue
                elif df == "Overdue":
                    if not due_dt or not (due_dt.date() < today.date()):
                        continue
                elif df == "No Date":
                    if due_dt is not None:
                        continue
                elif df == "Specific Date" and specific_date:
                    if (r.get("due_date") or "") != specific_date:
                        continue

            # Search filter
            if search_l:
                tt = (r.get("task_text") or "").lower()
                tags = ""
                try:
                    tj = json.loads(r.get("tags_json") or "[]")
                    if isinstance(tj, list):
                        tags = " ".join(str(x) for x in tj).lower()
                except Exception:
                    tags = (r.get("tags_json") or "").lower()
                if search_l not in tt and search_l not in tags:
                    continue

            # Project filter (cos_project_id already in SQL when provided)
            # (handled in WHERE clause)

            r["_due_dt"] = due_dt
            r["_next_dt"] = next_dt
            r["_snooze_dt"] = snooze_dt
            out.append(r)

        # Sort
        sort_by = (sort_by or "").strip().lower() or "priority"
        def _key(r):
            pr = int(r.get("priority") or 0)
            nd = r.get("_next_dt")
            dd = r.get("_due_dt")
            nd_sort = nd if nd is not None else datetime.max
            dd_sort = dd if dd is not None else datetime.max
            rid = int(r.get("id") or 0)
            if sort_by == "due_date":
                return (dd_sort, nd_sort, -pr, -rid)
            if sort_by == "next_action":
                return (nd_sort, dd_sort, -pr, -rid)
            if sort_by == "newest":
                return (-rid, -pr, dd_sort, nd_sort)
            # default: priority desc, then next action, due, newest
            return (-pr, nd_sort, dd_sort, -rid)

        out.sort(key=_key)
        return out[: int(limit)]

    def get_tasks(self, category=None, date_filter=None, specific_date=None):
        with sqlite3.connect(self.db_name) as conn:
            query = "SELECT id, task_text, due_date, category, recurrence, completed FROM tasks WHERE 1=1"
            params = []
            if category:
                query += " AND category = ?"
                params.append(category)
            if date_filter == "Today":
                query += " AND due_date = ?"
                params.append(datetime.now().strftime("%m-%d-%Y"))
            elif date_filter == "Overdue":
                query += " AND due_date IS NOT NULL AND due_date < ?"
                params.append(datetime.now().strftime("%m-%d-%Y"))
            elif date_filter == "No Date":
                query += " AND due_date IS NULL"
            elif date_filter == "Specific Date" and specific_date:
                query += " AND due_date = ?"
                params.append(specific_date)
            query += " ORDER BY due_date IS NULL, due_date ASC"

            cursor = conn.execute(query, params)
            results = cursor.fetchall()

            return results

    def update_task_completed_by_id(self, task_id: int, completed: int) -> None:
        """Mark a task complete/incomplete by id."""
        with sqlite3.connect(self.db_name) as conn:
            conn.execute(
                "UPDATE tasks SET completed = ? WHERE id = ?",
                (int(completed), int(task_id)),
            )
            conn.commit()

    def delete_task_by_id(self, task_id: int) -> None:
        """Delete a task by id."""
        with sqlite3.connect(self.db_name) as conn:
            conn.execute("DELETE FROM tasks WHERE id = ?", (int(task_id),))
            conn.commit()

    def get_task_category(self, task_text):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute("SELECT category FROM tasks WHERE task_text = ?", (task_text,))
            result = cursor.fetchone()
            return result[0] if result else "Personal"

    def get_task_recurrence(self, task_id):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute("SELECT recurrence FROM tasks WHERE id = ?", (task_id,))
            result = cursor.fetchone()
            return result[0] if result else "None"

    def delete_task(self, task_text):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute('SELECT id FROM tasks WHERE task_text = ? ORDER BY created_at DESC LIMIT 1', (task_text,))
            task_id = cursor.fetchone()
            if task_id:
                conn.execute('DELETE FROM tasks WHERE id = ?', (task_id[0],))
                conn.commit()

    def update_task_status(self, task_text, completed):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute('SELECT id FROM tasks WHERE task_text = ? ORDER BY created_at DESC LIMIT 1', (task_text,))
            task_id = cursor.fetchone()
            if task_id:
                conn.execute('UPDATE tasks SET completed = ? WHERE id = ?', (completed, task_id[0]))
                conn.commit()

    def archive_task(self, task_text, due_date, category, recurrence, completed):
        with sqlite3.connect(self.db_name) as conn:
            conn.execute('''INSERT INTO archived_tasks
                          (task_text, due_date, category, recurrence, completed, session_id, created_at)
                          VALUES (?, ?, ?, ?, ?, ?, ?)''',
                        (task_text, due_date, category, recurrence, completed, None, datetime.now()))
            conn.commit()

    def init_email_calendar_tables(self):
        with sqlite3.connect(self.db_name) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS emails (
                    id TEXT PRIMARY KEY,
                    sender TEXT,
                    subject TEXT,
                    timestamp INTEGER,
                    content TEXT,
                    replied INTEGER DEFAULT 0,
                    is_client INTEGER DEFAULT 0,
                    is_potential INTEGER DEFAULT 0,
                    source TEXT
                )
            """)
            # Backfill/extend email schema (legacy DBs) with additional metadata used by briefing + reply tracking.
            try:
                cursor = conn.execute("PRAGMA table_info(emails)")
                cols = {row[1] for row in cursor.fetchall()}
                if "folder" not in cols:
                    conn.execute("ALTER TABLE emails ADD COLUMN folder TEXT")
                if "account" not in cols:
                    conn.execute("ALTER TABLE emails ADD COLUMN account TEXT")
                if "rfc822_message_id" not in cols:
                    conn.execute("ALTER TABLE emails ADD COLUMN rfc822_message_id TEXT")
                if "rfc822_in_reply_to" not in cols:
                    conn.execute("ALTER TABLE emails ADD COLUMN rfc822_in_reply_to TEXT")
                if "rfc822_references" not in cols:
                    conn.execute("ALTER TABLE emails ADD COLUMN rfc822_references TEXT")
                if "thread_id" not in cols:
                    conn.execute("ALTER TABLE emails ADD COLUMN thread_id TEXT")
                if "triage_status" not in cols:
                    conn.execute("ALTER TABLE emails ADD COLUMN triage_status TEXT NOT NULL DEFAULT 'new'")
                if "importance_score" not in cols:
                    conn.execute("ALTER TABLE emails ADD COLUMN importance_score INTEGER NOT NULL DEFAULT 0")
                if "needs_attention" not in cols:
                    conn.execute("ALTER TABLE emails ADD COLUMN needs_attention INTEGER NOT NULL DEFAULT 0")
                if "importance_reason_json" not in cols:
                    conn.execute("ALTER TABLE emails ADD COLUMN importance_reason_json TEXT NOT NULL DEFAULT '[]'")
                if "triaged_at" not in cols:
                    conn.execute("ALTER TABLE emails ADD COLUMN triaged_at TEXT")
                if "triage_source" not in cols:
                    conn.execute("ALTER TABLE emails ADD COLUMN triage_source TEXT")
                if "client_id" not in cols:
                    conn.execute("ALTER TABLE emails ADD COLUMN client_id INTEGER")
                if "cos_project_id" not in cols:
                    conn.execute("ALTER TABLE emails ADD COLUMN cos_project_id INTEGER")
                # Helpful indexes (best-effort)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_emails_timestamp ON emails(timestamp)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_emails_replied ON emails(replied)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_emails_rfc822_message_id ON emails(rfc822_message_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_emails_triage_status ON emails(triage_status)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_emails_needs_attention ON emails(needs_attention)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_emails_client_id ON emails(client_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_emails_cos_project_id ON emails(cos_project_id)")
            except Exception:
                pass
            conn.execute("""
                CREATE TABLE IF NOT EXISTS calendar_events (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    start_time TEXT,
                    end_time TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS attachments (
                    email_id TEXT,
                    filename TEXT,
                    PRIMARY KEY (email_id, filename)
                )
            """)
            conn.commit()

    def init_last_run_table(self):
        with sqlite3.connect(self.db_name) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS last_run (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    timestamp INTEGER
                )
            """)
            conn.execute("INSERT OR IGNORE INTO last_run (id, timestamp) VALUES (1, 0)")
            conn.commit()

    def init_meetings_tables(self):
        """Create tables used by the Meetings tab (safe additive init)."""
        with sqlite3.connect(self.db_name) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS meeting_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    meeting_date TEXT NOT NULL,
                    meeting_with TEXT,
                    notes TEXT,
                    source TEXT NOT NULL DEFAULT 'recording',
                    audio_file_path TEXT,
                    transcript_text TEXT,
                    transcript_file_path TEXT,
                    transcription_provider TEXT,
                    provider_transcript_id TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    error_message TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_meeting_records_date ON meeting_records(meeting_date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_meeting_records_status ON meeting_records(status)")
            try:
                cursor = conn.execute("PRAGMA table_info(meeting_records)")
                cols = {row[1] for row in cursor.fetchall()}
                if "client_id" not in cols:
                    conn.execute("ALTER TABLE meeting_records ADD COLUMN client_id INTEGER")
                if "cos_project_id" not in cols:
                    conn.execute("ALTER TABLE meeting_records ADD COLUMN cos_project_id INTEGER")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_meeting_records_client_id ON meeting_records(client_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_meeting_records_cos_project_id ON meeting_records(cos_project_id)")
            except Exception:
                pass
            conn.commit()

    def create_meeting_record(
        self,
        *,
        meeting_date: str,
        meeting_with: str | None = None,
        notes: str | None = None,
        source: str = "recording",
        audio_file_path: str | None = None,
        transcription_provider: str | None = None,
        status: str = "pending",
        client_id: int | None = None,
        cos_project_id: int | None = None,
    ) -> int:
        with sqlite3.connect(self.db_name) as conn:
            cur = conn.execute(
                """
                INSERT INTO meeting_records
                    (meeting_date, meeting_with, notes, source, audio_file_path, transcription_provider, status, client_id, cos_project_id, created_at, updated_at)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (
                    str(meeting_date),
                    (meeting_with or "").strip(),
                    (notes or "").strip(),
                    (source or "recording").strip(),
                    str(audio_file_path) if audio_file_path else None,
                    (transcription_provider or "").strip() or None,
                    (status or "pending").strip(),
                    int(client_id) if client_id is not None else None,
                    int(cos_project_id) if cos_project_id is not None else None,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def update_meeting_record(
        self,
        meeting_id: int,
        *,
        status: str | None = None,
        meeting_with: str | None = None,
        notes: str | None = None,
        provider_transcript_id: str | None = None,
        transcript_text: str | None = None,
        transcript_file_path: str | None = None,
        error_message: str | None = None,
        client_id = _UNSET,
        cos_project_id = _UNSET,
    ) -> None:
        fields = []
        params: list[object] = []
        if status is not None:
            fields.append("status = ?")
            params.append(str(status))
        if meeting_with is not None:
            fields.append("meeting_with = ?")
            params.append(str(meeting_with))
        if notes is not None:
            fields.append("notes = ?")
            params.append(str(notes))
        if provider_transcript_id is not None:
            fields.append("provider_transcript_id = ?")
            params.append(str(provider_transcript_id) if provider_transcript_id else None)
        if transcript_text is not None:
            fields.append("transcript_text = ?")
            params.append(str(transcript_text))
        if transcript_file_path is not None:
            fields.append("transcript_file_path = ?")
            params.append(str(transcript_file_path) if transcript_file_path else None)
        if error_message is not None:
            fields.append("error_message = ?")
            params.append(str(error_message) if error_message else None)
        if client_id is not _UNSET:
            fields.append("client_id = ?")
            params.append(int(client_id) if client_id is not None else None)
        if cos_project_id is not _UNSET:
            fields.append("cos_project_id = ?")
            params.append(int(cos_project_id) if cos_project_id is not None else None)
        if not fields:
            return
        fields.append("updated_at = datetime('now')")
        params.append(int(meeting_id))
        with sqlite3.connect(self.db_name) as conn:
            conn.execute(f"UPDATE meeting_records SET {', '.join(fields)} WHERE id = ?", params)
            conn.commit()

    def update_last_run(self):
        timestamp = int(datetime.now(UTC).timestamp())
        with sqlite3.connect(self.db_name) as conn:
            conn.execute("UPDATE last_run SET timestamp = ? WHERE id = 1", (timestamp,))
            conn.commit()

    def get_last_run(self):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute("SELECT timestamp FROM last_run WHERE id = 1")
            result = cursor.fetchone()
            return result[0] if result else 0

    def get_last_news_update(self):
        """Get the timestamp of the last news update."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute("SELECT timestamp FROM last_run WHERE id = 2")
            result = cursor.fetchone()
            return result[0] if result else 0

    def update_last_news_update(self):
        """Update the timestamp of the last news update."""
        timestamp = int(datetime.now(UTC).timestamp())
        with sqlite3.connect(self.db_name) as conn:
            # Ensure the news update record exists
            conn.execute("INSERT OR IGNORE INTO last_run (id, timestamp) VALUES (2, 0)")
            conn.execute("UPDATE last_run SET timestamp = ? WHERE id = 2", (timestamp,))
            conn.commit()

    def clear_tasks(self):
        with sqlite3.connect(self.db_name) as conn:
            conn.execute('DELETE FROM tasks')
            conn.commit()

    def create_workspace_tables(self):
        with sqlite3.connect(self.db_name) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS workspaces (
                    workspace_id INTEGER PRIMARY KEY,
                    client_name TEXT UNIQUE,
                    client_folder TEXT  -- e.g., data/clients/Abbott
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    doc_id INTEGER PRIMARY KEY,
                    workspace_id INTEGER,
                    category TEXT,  -- standards, reference
                    path TEXT,     -- file path or URL
                    name TEXT,     -- display name
                    FOREIGN KEY (workspace_id) REFERENCES workspaces (workspace_id)
                )
            """)
            conn.commit()

    def init_workspace_collab_tables(self):
        """
        Persist Dual-LLM Workspace collaboration runs (Grok <-> ChatGPT).
        Additive, best-effort: safe to call on every startup.
        """
        with sqlite3.connect(self.db_name) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workspace_collab_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    goal TEXT,
                    context TEXT,
                    style TEXT,
                    audience TEXT,
                    files_json TEXT,
                    rounds INTEGER,
                    status TEXT,
                    markdown TEXT,
                    grok_output TEXT,
                    chatgpt_output TEXT,
                    collaboration_json TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_workspace_collab_runs_created_at ON workspace_collab_runs(created_at)"
            )
            conn.commit()

    def init_workspace_state_tables(self):
        """
        Persist named Workspace tab state separately from collaboration run history.
        """
        with sqlite3.connect(self.db_name) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workspace_saved_states (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    state_json TEXT NOT NULL DEFAULT '{}',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_workspace_saved_states_name ON workspace_saved_states(name)"
            )
            conn.commit()

    def workspace_collab_insert_run(
        self,
        *,
        goal: str,
        context: str | None,
        style: str | None,
        audience: str | None,
        files: list[dict] | None,
        rounds: int,
        status: str,
        markdown: str,
        grok_output: str,
        chatgpt_output: str,
        collaboration_history: list[dict] | None,
    ) -> int:
        """Insert a completed collaboration run. Returns run id."""
        payload_files = json.dumps(files or [], ensure_ascii=False)
        payload_hist = json.dumps(collaboration_history or [], ensure_ascii=False)
        with sqlite3.connect(self.db_name) as conn:
            cur = conn.execute(
                """
                INSERT INTO workspace_collab_runs
                    (goal, context, style, audience, files_json, rounds, status, markdown, grok_output, chatgpt_output, collaboration_json)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    goal,
                    context,
                    style,
                    audience,
                    payload_files,
                    int(rounds),
                    status,
                    markdown,
                    grok_output,
                    chatgpt_output,
                    payload_hist,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def workspace_state_upsert(self, *, name: str, state: dict | None) -> int:
        workspace_name = str(name or "").strip()
        if not workspace_name:
            raise ValueError("Workspace name is required")
        payload = json.dumps(state or {}, ensure_ascii=False)
        with sqlite3.connect(self.db_name) as conn:
            conn.execute(
                """
                INSERT INTO workspace_saved_states (name, state_json, updated_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(name) DO UPDATE SET
                    state_json=excluded.state_json,
                    updated_at=excluded.updated_at
                """,
                (workspace_name, payload),
            )
            row = conn.execute(
                "SELECT id FROM workspace_saved_states WHERE name = ?",
                (workspace_name,),
            ).fetchone()
            conn.commit()
            return int(row[0]) if row else 0

    def workspace_state_list(self) -> list[dict]:
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, name, created_at, updated_at
                FROM workspace_saved_states
                ORDER BY lower(name) ASC, id ASC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def workspace_state_get(self, workspace_id: int) -> dict | None:
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM workspace_saved_states WHERE id = ?",
                (int(workspace_id),),
            ).fetchone()
            return dict(row) if row else None

    def workspace_state_get_by_name(self, name: str) -> dict | None:
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM workspace_saved_states WHERE name = ?",
                (str(name or "").strip(),),
            ).fetchone()
            return dict(row) if row else None

    def workspace_state_delete(self, workspace_id: int) -> None:
        with sqlite3.connect(self.db_name) as conn:
            conn.execute(
                "DELETE FROM workspace_saved_states WHERE id = ?",
                (int(workspace_id),),
            )
            conn.commit()

    def workspace_state_set_last_used(self, workspace_id: int | None) -> None:
        self.set_setting("workspace.last_used_id", "" if workspace_id is None else str(int(workspace_id)))

    def workspace_state_get_last_used(self) -> dict | None:
        raw = str(self.get_setting("workspace.last_used_id", "") or "").strip()
        if not raw:
            return None
        try:
            return self.workspace_state_get(int(raw))
        except Exception:
            return None

    def workspace_session_save(self, state: dict | None) -> None:
        self.set_setting("workspace.last_session_json", json.dumps(state or {}, ensure_ascii=False))

    def workspace_session_load(self) -> dict:
        raw = str(self.get_setting("workspace.last_session_json", "") or "").strip()
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def workspace_collab_list_runs(self, *, limit: int = 50) -> list[dict]:
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                """
                SELECT id, created_at, goal, rounds, status
                FROM workspace_collab_runs
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(limit),),
            )
            return [dict(r) for r in cur.fetchall()]

    def workspace_collab_get_run(self, run_id: int) -> dict | None:
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT * FROM workspace_collab_runs WHERE id = ?",
                (int(run_id),),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def store_dataset_entry(self, file_path, jsonl_path="data/fine_tune.jsonl"):
        # Lazy import: document extraction deps are heavy and optional for most runtime paths.
        from core.file_handler import extract_for_dataset
        entry = extract_for_dataset(file_path)
        with open(jsonl_path, 'a') as f:  # Append to JSONL
            f.write(json.dumps(entry) + '\n')

    # Notes methods for NoteTakingSystem
    def init_notes_table(self):
        """Initialize notes table (already done in setup_db, but kept for compatibility)."""
        pass

    def create_note_draft(
        self,
        *,
        raw_note: str,
        timestamp: str,
        context: str | None = None,
        category: str = "Uncategorized",
    ) -> int:
        """
        Insert a draft note row immediately so user text is never lost.
        Returns note id.
        """
        rn = (raw_note or "").strip()
        if not rn:
            return 0
        with sqlite3.connect(self.db_name) as conn:
            self._ensure_notes_schema(conn)
            cur = conn.execute(
                """
                INSERT INTO notes (formatted_note, category, context, raw_note, state, error_text, pinned, timestamp, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'pending', NULL, 0, ?, datetime('now'), datetime('now'))
                """,
                (rn, category, context, rn, timestamp),
            )
            conn.commit()
            return int(cur.lastrowid)

    def update_note_by_id(
        self,
        note_id: int,
        *,
        formatted_note: str | None = None,
        raw_note: str | None = None,
        category: str | None = None,
        context: str | None = None,
        pinned: int | None = None,
        state: str | None = None,
        error_text: str | None = None,
        timestamp: str | None = None,
    ) -> None:
        fields = []
        params = []
        if formatted_note is not None:
            fields.append("formatted_note = ?")
            params.append(str(formatted_note))
        if raw_note is not None:
            fields.append("raw_note = ?")
            params.append(str(raw_note))
        if category is not None:
            fields.append("category = ?")
            params.append(str(category))
        if context is not None:
            fields.append("context = ?")
            params.append(str(context))
        if pinned is not None:
            fields.append("pinned = ?")
            params.append(int(pinned))
        if state is not None:
            fields.append("state = ?")
            params.append(str(state))
        if error_text is not None:
            fields.append("error_text = ?")
            params.append(str(error_text) if error_text else None)
        if timestamp is not None:
            fields.append("timestamp = ?")
            params.append(str(timestamp))
        if not fields:
            return
        fields.append("updated_at = datetime('now')")
        params.append(int(note_id))
        with sqlite3.connect(self.db_name) as conn:
            self._ensure_notes_schema(conn)
            conn.execute(f"UPDATE notes SET {', '.join(fields)} WHERE id = ?", params)
            conn.commit()

    def delete_note_by_id(self, note_id: int) -> None:
        with sqlite3.connect(self.db_name) as conn:
            conn.execute("DELETE FROM notes WHERE id = ?", (int(note_id),))
            conn.commit()

    def list_notes(
        self,
        *,
        context: str | None = None,
        include_pinned_first: bool = True,
        limit: int = 200,
    ) -> list[dict]:
        with sqlite3.connect(self.db_name) as conn:
            self._ensure_notes_schema(conn)
            where = "1=1"
            params: list = []
            if context is not None:
                where += " AND (context = ?)"
                params.append(str(context))
            order = "ORDER BY created_at DESC"
            if include_pinned_first:
                order = "ORDER BY pinned DESC, created_at DESC"
            q = f"""
                SELECT id, formatted_note, category, context, raw_note, state, error_text, pinned, timestamp, created_at, updated_at
                FROM notes
                WHERE {where}
                {order}
                LIMIT ?
            """
            params.append(int(limit))
            rows = conn.execute(q, params).fetchall()
        out = []
        for r in rows:
            (
                nid,
                formatted_note,
                category,
                ctx,
                raw_note,
                state,
                error_text,
                pinned,
                ts,
                created_at,
                updated_at,
            ) = r
            out.append(
                {
                    "id": int(nid),
                    "formatted_note": formatted_note or "",
                    "category": category or "Uncategorized",
                    "context": ctx,
                    "raw_note": raw_note or "",
                    "state": state or "ready",
                    "error_text": error_text,
                    "pinned": int(pinned or 0),
                    "timestamp": ts or "",
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
            )
        return out

    def search_notes(
        self,
        *,
        query: str,
        context: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        q = (query or "").strip()
        if not q:
            return self.list_notes(context=context, limit=limit)
        with sqlite3.connect(self.db_name) as conn:
            self._ensure_notes_schema(conn)
            # Prefer FTS if available.
            try:
                where = "notes_fts MATCH ?"
                params: list = [q]
                if context is not None:
                    where += " AND notes.context = ?"
                    params.append(str(context))
                params.append(int(limit))
                rows = conn.execute(
                    f"""
                    SELECT notes.id, notes.formatted_note, notes.category, notes.context, notes.raw_note, notes.state, notes.error_text,
                           notes.pinned, notes.timestamp, notes.created_at, notes.updated_at
                    FROM notes_fts
                    JOIN notes ON notes.id = notes_fts.rowid
                    WHERE {where}
                    ORDER BY notes.pinned DESC, notes.created_at DESC
                    LIMIT ?
                    """,
                    params,
                ).fetchall()
            except Exception:
                like = f"%{q}%"
                where = "(formatted_note LIKE ? OR raw_note LIKE ? OR context LIKE ? OR category LIKE ?)"
                params = [like, like, like, like]
                if context is not None:
                    where += " AND context = ?"
                    params.append(str(context))
                params.append(int(limit))
                rows = conn.execute(
                    f"""
                    SELECT id, formatted_note, category, context, raw_note, state, error_text, pinned, timestamp, created_at, updated_at
                    FROM notes
                    WHERE {where}
                    ORDER BY pinned DESC, created_at DESC
                    LIMIT ?
                    """,
                    params,
                ).fetchall()
        out = []
        for r in rows:
            (
                nid,
                formatted_note,
                category,
                ctx,
                raw_note,
                state,
                error_text,
                pinned,
                ts,
                created_at,
                updated_at,
            ) = r
            out.append(
                {
                    "id": int(nid),
                    "formatted_note": formatted_note or "",
                    "category": category or "Uncategorized",
                    "context": ctx,
                    "raw_note": raw_note or "",
                    "state": state or "ready",
                    "error_text": error_text,
                    "pinned": int(pinned or 0),
                    "timestamp": ts or "",
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
            )
        return out

    def save_note(self, formatted_note, timestamp, context=None):
        """Save a formatted note to the database. Returns note id."""
        with sqlite3.connect(self.db_name) as conn:
            self._ensure_notes_schema(conn)
            cur = conn.execute(
                """
                INSERT INTO notes (formatted_note, category, context, raw_note, state, error_text, pinned, timestamp, created_at, updated_at)
                VALUES (?, ?, ?, NULL, 'ready', NULL, 0, ?, datetime('now'), datetime('now'))
                """,
                (formatted_note, "Uncategorized", context, timestamp),
            )
            conn.commit()
            return int(cur.lastrowid)

    def get_notes(self):
        """Backward-compatible note list (formatted_note, context)."""
        rows = self.list_notes(limit=500)
        return [(r["formatted_note"], r.get("context")) for r in rows]

    def save_organized_notes(self, organized_notes):
        """Save organized notes as JSON."""
        with sqlite3.connect(self.db_name) as conn:
            # Clear existing organized notes
            conn.execute('DELETE FROM organized_notes')
            
            # Save new organized notes
            for category, notes in organized_notes.items():
                notes_json = json.dumps(notes)
                conn.execute('INSERT INTO organized_notes (category, notes_json) VALUES (?, ?)',
                            (category, notes_json))
            conn.commit()

    def get_organized_notes(self):
        """Get organized notes from the database."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute('SELECT category, notes_json FROM organized_notes')
            organized_notes = {}
            for row in cursor.fetchall():
                category, notes_json = row
                organized_notes[category] = json.loads(notes_json)
            return organized_notes

    def clear_organized_notes(self):
        """Clear all organized notes from the database."""
        with sqlite3.connect(self.db_name) as conn:
            conn.execute('DELETE FROM organized_notes')
            conn.commit()

    def list_note_documents(
        self,
        *,
        query: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        with sqlite3.connect(self.db_name) as conn:
            self._ensure_notes_documents_schema(conn)
            self._backfill_notes_documents_from_legacy_notes(conn)
            where = "1=1"
            params: list = []
            q = (query or "").strip()
            if q:
                like = f"%{q}%"
                where += " AND (context LIKE ? OR title LIKE ? OR document_text LIKE ?)"
                params.extend([like, like, like])
            params.append(int(limit))
            rows = conn.execute(
                f"""
                SELECT id, context, title, document_text, state, error_text, source_note_count, created_at, updated_at
                FROM notes_documents
                WHERE {where}
                ORDER BY updated_at DESC, context ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        out = []
        for row in rows:
            (
                doc_id,
                context,
                title,
                document_text,
                state,
                error_text,
                source_note_count,
                created_at,
                updated_at,
            ) = row
            out.append(
                {
                    "id": int(doc_id),
                    "context": context or "",
                    "title": title or context or "",
                    "document_text": document_text or "",
                    "state": state or "ready",
                    "error_text": error_text,
                    "source_note_count": int(source_note_count or 0),
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
            )
        return out

    def get_note_document(self, context: str | None, *, create: bool = False) -> dict | None:
        normalized = self._normalize_notes_context(context)
        with sqlite3.connect(self.db_name) as conn:
            self._ensure_notes_documents_schema(conn)
            self._backfill_notes_documents_from_legacy_notes(conn)
            row = conn.execute(
                """
                SELECT id, context, title, document_text, state, error_text, source_note_count, created_at, updated_at
                FROM notes_documents
                WHERE context = ?
                """,
                (normalized,),
            ).fetchone()
            if row is None and create:
                conn.execute(
                    """
                    INSERT INTO notes_documents (
                        context, title, document_text, state, error_text, source_note_count, created_at, updated_at
                    )
                    VALUES (?, ?, '', 'ready', NULL, 0, datetime('now'), datetime('now'))
                    """,
                    (normalized, normalized),
                )
                conn.commit()
                row = conn.execute(
                    """
                    SELECT id, context, title, document_text, state, error_text, source_note_count, created_at, updated_at
                    FROM notes_documents
                    WHERE context = ?
                    """,
                    (normalized,),
                ).fetchone()
        if row is None:
            return None
        (
            doc_id,
            row_context,
            title,
            document_text,
            state,
            error_text,
            source_note_count,
            created_at,
            updated_at,
        ) = row
        return {
            "id": int(doc_id),
            "context": row_context or "",
            "title": title or row_context or "",
            "document_text": document_text or "",
            "state": state or "ready",
            "error_text": error_text,
            "source_note_count": int(source_note_count or 0),
            "created_at": created_at,
            "updated_at": updated_at,
        }

    def save_note_document(
        self,
        context: str | None,
        *,
        document_text: str,
        title: str | None = None,
        state: str = "ready",
        error_text: str | None = None,
        source_note_count: int | None = None,
    ) -> None:
        normalized = self._normalize_notes_context(context)
        final_title = (title or normalized).strip() or normalized
        with sqlite3.connect(self.db_name) as conn:
            self._ensure_notes_documents_schema(conn)
            if source_note_count is None:
                row = conn.execute(
                    "SELECT COUNT(*) FROM notes WHERE context = ? AND state = 'ready'",
                    (normalized,),
                ).fetchone()
                source_note_count = int((row or [0])[0] or 0)
            conn.execute(
                """
                INSERT INTO notes_documents (
                    context, title, document_text, state, error_text, source_note_count, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                ON CONFLICT(context) DO UPDATE SET
                    title = excluded.title,
                    document_text = excluded.document_text,
                    state = excluded.state,
                    error_text = excluded.error_text,
                    source_note_count = excluded.source_note_count,
                    updated_at = datetime('now')
                """,
                (
                    normalized,
                    final_title,
                    document_text or "",
                    state or "ready",
                    error_text,
                    int(source_note_count or 0),
                ),
            )
            conn.commit()

    def count_ready_notes_for_context(self, context: str | None) -> int:
        normalized = self._normalize_notes_context(context)
        with sqlite3.connect(self.db_name) as conn:
            self._ensure_notes_schema(conn)
            row = conn.execute(
                "SELECT COUNT(*) FROM notes WHERE context = ? AND state = 'ready'",
                (normalized,),
            ).fetchone()
            return int((row or [0])[0] or 0)

    # News methods for dashboard news feed
    def store_news_item(self, title, content, url=None, source=None, published_date=None):
        """Store a news item in the database, avoiding duplicates."""
        try:
            from core.news_dedup import canonicalize_url, make_dedup_key

            canonical_url = canonicalize_url(url)
            key_url = make_dedup_key(title=title, url=canonical_url, published_date=published_date)
            key_title = make_dedup_key(title=title, url=None, published_date=published_date)
            with sqlite3.connect(self.db_name) as conn:
                # First: check dedup table (preferred)
                cursor = conn.execute(
                    "SELECT news_id FROM news_dedup WHERE dedup_key IN (?, ?) LIMIT 1",
                    (key_url, key_title),
                )
                if cursor.fetchone():
                    conn.execute(
                        "UPDATE news_dedup SET last_seen = datetime('now') WHERE dedup_key IN (?, ?)",
                        (key_url, key_title),
                    )
                    conn.commit()
                    return False

                # Backward-compat: check by exact title or URL match
                cursor = conn.execute(
                    "SELECT id, url, source, published_date FROM news_items WHERE title = ? OR (url IS NOT NULL AND url = ?)",
                    (title, canonical_url),
                )
                existing = cursor.fetchone()
                if existing:
                    existing_id, existing_url, existing_source, existing_published_date = existing
                    # Enrich existing rows when earlier ingest missed URL/source/date.
                    if (
                        (not existing_url and canonical_url)
                        or (not existing_source and source)
                        or (not existing_published_date and published_date)
                    ):
                        conn.execute(
                            """
                            UPDATE news_items
                            SET url = COALESCE(url, ?),
                                source = COALESCE(source, ?),
                                published_date = COALESCE(published_date, ?)
                            WHERE id = ?
                            """,
                            (canonical_url, source, published_date, existing_id),
                        )
                    # Attach a dedup key mapping so future checks are stable
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO news_dedup (dedup_key, news_id, first_seen, last_seen)
                        VALUES (?, ?, datetime('now'), datetime('now'))
                        """,
                        (key_url, existing_id),
                    )
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO news_dedup (dedup_key, news_id, first_seen, last_seen)
                        VALUES (?, ?, datetime('now'), datetime('now'))
                        """,
                        (key_title, existing_id),
                    )
                    conn.commit()
                    return False
                
                conn.execute('''INSERT INTO news_items 
                    (title, content, url, source, published_date, created_at) 
                    VALUES (?, ?, ?, ?, ?, datetime('now'))''',
                    (title, content, canonical_url, source, published_date))
                news_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                conn.execute(
                    """
                    INSERT OR REPLACE INTO news_dedup (dedup_key, news_id, first_seen, last_seen)
                    VALUES (?, ?, datetime('now'), datetime('now'))
                    """,
                    (key_url, news_id),
                )
                conn.execute(
                    """
                    INSERT OR REPLACE INTO news_dedup (dedup_key, news_id, first_seen, last_seen)
                    VALUES (?, ?, datetime('now'), datetime('now'))
                    """,
                    (key_title, news_id),
                )
                conn.commit()
                return True
        except Exception as e:
            print(f"Error storing news item: {e}")
            return False

    def get_recent_news(self, days=7):
        """Get news items from the last N days."""
        with sqlite3.connect(self.db_name) as conn:
            # Prefer one row per dedup_key (best-effort). Fall back to direct news_items if needed.
            try:
                cursor = conn.execute(
                    f"""
                    SELECT DISTINCT n.id, n.title, n.content, n.url, n.source, n.published_date, n.created_at
                    FROM news_items n
                    JOIN (
                        SELECT dedup_key, MAX(news_id) AS news_id
                        FROM news_dedup
                        GROUP BY dedup_key
                    ) d ON d.news_id = n.id
                    WHERE n.created_at >= datetime('now', ?)
                    ORDER BY n.created_at DESC
                    """,
                    (f"-{int(days)} days",),
                )
                rows = cursor.fetchall()
                if rows:
                    # Drop id column to preserve original return shape
                    return [(r[1], r[2], r[3], r[4], r[5], r[6]) for r in rows]
            except Exception:
                pass

            cursor = conn.execute(
                f"""SELECT title, content, url, source, published_date, created_at
                    FROM news_items
                    WHERE created_at >= datetime('now', '-{int(days)} days')
                    ORDER BY created_at DESC"""
            )
            return cursor.fetchall()

    def get_news_for_dashboard(self, days: int = 7, suppress_days: int = 2, limit: int = 50):
        """
        Return recent news items, suppressing items shown in the last N days.
        Uses news_dedup.last_shown aggregated per news_id.
        Returns rows shaped like get_recent_news plus an id: (id, title, content, url, source, published_date, created_at)
        """
        with sqlite3.connect(self.db_name) as conn:
            try:
                cursor = conn.execute(
                    """
                    SELECT
                        n.id,
                        n.title,
                        n.content,
                        n.url,
                        n.source,
                        n.published_date,
                        n.created_at,
                        MAX(d.last_shown) AS last_shown
                    FROM news_items n
                    LEFT JOIN news_dedup d ON d.news_id = n.id
                    WHERE n.created_at >= datetime('now', ?)
                    GROUP BY n.id
                    HAVING last_shown IS NULL OR last_shown < datetime('now', ?)
                    ORDER BY n.created_at DESC
                    LIMIT ?
                    """,
                    (f"-{int(days)} days", f"-{int(suppress_days)} days", int(limit)),
                )
                return [(r[0], r[1], r[2], r[3], r[4], r[5], r[6]) for r in cursor.fetchall()]
            except Exception:
                cursor = conn.execute(
                    f"""SELECT id, title, content, url, source, published_date, created_at
                        FROM news_items
                        WHERE created_at >= datetime('now', '-{int(days)} days')
                        ORDER BY created_at DESC
                        LIMIT {int(limit)}"""
                )
                return cursor.fetchall()

    def mark_news_shown(self, news_ids):
        """Mark a set of news_ids as shown now (updates all dedup keys for those items)."""
        ids = [int(i) for i in news_ids if i is not None]
        if not ids:
            return
        with sqlite3.connect(self.db_name) as conn:
            placeholders = ",".join(["?"] * len(ids))
            conn.execute(
                f"UPDATE news_dedup SET last_shown = datetime('now') WHERE news_id IN ({placeholders})",
                ids,
            )
            conn.commit()

    def check_news_exists(self, title, url=None):
        """Check if a news item already exists in the database."""
        with sqlite3.connect(self.db_name) as conn:
            from core.news_dedup import canonicalize_url, make_dedup_key

            canonical_url = canonicalize_url(url)
            key_url = make_dedup_key(title=title, url=canonical_url, published_date=None)
            key_title = make_dedup_key(title=title, url=None, published_date=None)

            try:
                cursor = conn.execute(
                    "SELECT 1 FROM news_dedup WHERE dedup_key IN (?, ?) LIMIT 1",
                    (key_url, key_title),
                )
                if cursor.fetchone():
                    return True
            except Exception:
                pass

            if canonical_url:
                cursor = conn.execute('SELECT id FROM news_items WHERE title = ? OR url = ?', (title, canonical_url))
            else:
                cursor = conn.execute('SELECT id FROM news_items WHERE title = ?', (title,))
            return cursor.fetchone() is not None

    def backfill_news_dedup(self) -> None:
        """
        Best-effort backfill of news_dedup mappings for existing news_items.
        Keeps newest entries preferred by processing most recent first.
        """
        try:
            from core.news_dedup import canonicalize_url, make_dedup_key
            with sqlite3.connect(self.db_name) as conn:
                (count,) = conn.execute("SELECT COUNT(*) FROM news_dedup").fetchone()
                if count and count > 0:
                    return

                rows = conn.execute(
                    "SELECT id, title, url, published_date FROM news_items ORDER BY created_at DESC"
                ).fetchall()
                for news_id, title, url, published_date in rows:
                    cu = canonicalize_url(url)
                    if cu and cu != url:
                        conn.execute("UPDATE news_items SET url = ? WHERE id = ?", (cu, news_id))

                    key_url = make_dedup_key(title=title, url=cu, published_date=published_date)
                    key_title = make_dedup_key(title=title, url=None, published_date=published_date)

                    conn.execute(
                        "INSERT OR IGNORE INTO news_dedup (dedup_key, news_id) VALUES (?, ?)",
                        (key_url, news_id),
                    )
                    conn.execute(
                        "INSERT OR IGNORE INTO news_dedup (dedup_key, news_id) VALUES (?, ?)",
                        (key_title, news_id),
                    )
                conn.commit()
        except Exception:
            return

    def cleanup_old_news(self, days=7):
        """Remove news items older than N days and malformed items."""
        with sqlite3.connect(self.db_name) as conn:
            # Count items before cleanup
            cursor = conn.execute('SELECT COUNT(*) FROM news_items')
            before_count = cursor.fetchone()[0]
            
            # Delete old items based on created_at
            cursor = conn.execute('DELETE FROM news_items WHERE created_at < datetime("now", "-{} days")'.format(days))
            deleted_old_count = cursor.rowcount
            
            # Delete malformed items (titles that start with ``` or are clearly not news titles)
            cursor = conn.execute("DELETE FROM news_items WHERE title LIKE '```%' OR title LIKE '* %' OR title = '' OR title IS NULL")
            deleted_malformed_count = cursor.rowcount
            
            # Delete items with very old published dates (older than 30 days) if we can parse them
            # This is a more aggressive cleanup for items that might have been stored recently but are old news
            cursor = conn.execute("""
                DELETE FROM news_items 
                WHERE published_date IS NOT NULL 
                AND (
                    published_date LIKE '%2023%' OR 
                    published_date LIKE '%2024%' OR
                    published_date LIKE '%2022%' OR
                    published_date LIKE '%2021%' OR
                    published_date LIKE '%2020%'
                )
            """)
            deleted_old_published_count = cursor.rowcount
            
            total_deleted = deleted_old_count + deleted_malformed_count + deleted_old_published_count
            
            # Count items after cleanup
            cursor = conn.execute('SELECT COUNT(*) FROM news_items')
            after_count = cursor.fetchone()[0]
            
            # Remove dedup rows pointing to deleted items
            try:
                conn.execute(
                    "DELETE FROM news_dedup WHERE news_id IS NOT NULL AND news_id NOT IN (SELECT id FROM news_items)"
                )
            except Exception:
                pass

            conn.commit()
            # Cleanup completed

    def get_chat_history(self, session_id="main_session", limit=50):
        """Get chat history from the conversation table."""
        try:
            with sqlite3.connect(self.db_name) as conn:
                cursor = conn.execute('''SELECT role, content 
                    FROM conversation 
                    WHERE session_id = ? 
                    ORDER BY timestamp DESC 
                    LIMIT ?''', (session_id, limit))
                history = cursor.fetchall()
                # Return in reverse order (oldest first) and format for display
                return [(role, content) for role, content in reversed(history)]
        except Exception as e:
            print(f"Error getting chat history: {e}")
            return []

    def init_db(self):
        """Initialize the database with the new schema."""
        self.setup_db()

    def _initialize_schema_version(self, conn):
        """Initialize schema versioning in the database."""
        # Create a table to track schema version if it doesn't exist
        conn.execute('''CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY
        )''')
        
        # If no version is set, assume version 0 (pre-versioning)
        cursor = conn.execute("SELECT version FROM schema_version LIMIT 1")
        if not cursor.fetchone():
            conn.execute("INSERT INTO schema_version (version) VALUES (0)")
            conn.commit()

    def _get_schema_version(self, conn):
        """Get the current schema version from the database."""
        cursor = conn.execute("SELECT version FROM schema_version LIMIT 1")
        result = cursor.fetchone()
        return result[0] if result else 0

    def _set_schema_version(self, conn, version):
        """Set the schema version in the database."""
        conn.execute("UPDATE schema_version SET version = ?", (version,))
        conn.commit()

    def _migrate_schema(self, conn, from_version, to_version):
        """Migrate database schema from one version to another."""
        print(f"Migrating schema from version {from_version} to {to_version}")
        
        # Version 0 to 1: Add category and recurrence columns to tasks table
        if from_version < 1 and to_version >= 1:
            print("  - Adding category and recurrence columns to tasks table")
            try:
                # Check if columns already exist
                cursor = conn.execute("PRAGMA table_info(tasks)")
                columns = [col[1] for col in cursor.fetchall()]
                
                if 'category' not in columns:
                    conn.execute("ALTER TABLE tasks ADD COLUMN category TEXT DEFAULT 'Business'")
                    print("    - Added 'category' column")
                
                if 'recurrence' not in columns:
                    conn.execute("ALTER TABLE tasks ADD COLUMN recurrence TEXT DEFAULT 'None'")
                    print("    - Added 'recurrence' column")
                    
            except Exception as e:
                print(f"    - Error adding columns: {e}")
        
        # Version 1 to 2: Add session_id column to tasks table
        if from_version < 2 and to_version >= 2:
            print("  - Adding session_id column to tasks table")
            try:
                cursor = conn.execute("PRAGMA table_info(tasks)")
                columns = [col[1] for col in cursor.fetchall()]
                
                if 'session_id' not in columns:
                    conn.execute("ALTER TABLE tasks ADD COLUMN session_id TEXT")
                    print("    - Added 'session_id' column")
                    
            except Exception as e:
                print(f"    - Error adding session_id column: {e}")
        
        # Version 2 to 3: Multi-agent AI ops tables (projects, task_plans, project_tasks, runs, artifacts, agent_logs)
        if from_version < 3 and to_version >= 3:
            print("  - Creating multi-agent tables: projects, task_plans, project_tasks, runs, artifacts, agent_logs")
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS projects (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        mode TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'draft',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        config_json TEXT
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS task_plans (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        project_id INTEGER NOT NULL,
                        plan_json TEXT NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (project_id) REFERENCES projects (id)
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS project_tasks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        project_id INTEGER NOT NULL,
                        plan_task_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        agent_type TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'queued',
                        dependencies_json TEXT,
                        definition_of_done TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (project_id) REFERENCES projects (id)
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS runs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        project_id INTEGER NOT NULL,
                        project_task_id INTEGER NOT NULL,
                        agent_type TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        started_at DATETIME,
                        finished_at DATETIME,
                        model_used TEXT,
                        FOREIGN KEY (project_id) REFERENCES projects (id),
                        FOREIGN KEY (project_task_id) REFERENCES project_tasks (id)
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS artifacts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        project_id INTEGER NOT NULL,
                        run_id INTEGER,
                        project_task_id INTEGER,
                        artifact_type TEXT NOT NULL,
                        content_json TEXT,
                        file_path TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (project_id) REFERENCES projects (id),
                        FOREIGN KEY (run_id) REFERENCES runs (id),
                        FOREIGN KEY (project_task_id) REFERENCES project_tasks (id)
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS agent_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id INTEGER NOT NULL,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        agent_type TEXT NOT NULL,
                        model_used TEXT,
                        inputs_json TEXT,
                        tool_outputs_json TEXT,
                        artifacts_produced_json TEXT,
                        token_metadata_json TEXT,
                        error_message TEXT,
                        FOREIGN KEY (run_id) REFERENCES runs (id)
                    )
                """)
                conn.commit()
                print("    - Multi-agent tables created")
            except Exception as e:
                print(f"    - Error creating multi-agent tables: {e}")
        
        # Version 3 to 4: House Style Guide table (single row for Writer)
        if from_version < 4 and to_version >= 4:
            print("  - Creating house_style_guide table")
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS house_style_guide (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        content_markdown TEXT NOT NULL DEFAULT '',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.execute("INSERT OR IGNORE INTO house_style_guide (id, content_markdown) VALUES (1, '')")
                conn.commit()
                print("    - house_style_guide table created")
            except Exception as e:
                print(f"    - Error creating house_style_guide: {e}")
        
        # Version 4 to 5: Add error_message to runs table
        if from_version < 5 and to_version >= 5:
            print("  - Adding error_message column to runs table")
            try:
                cursor = conn.execute("PRAGMA table_info(runs)")
                columns = [col[1] for col in cursor.fetchall()]
                if "error_message" not in columns:
                    conn.execute("ALTER TABLE runs ADD COLUMN error_message TEXT")
                    conn.commit()
                    print("    - Added error_message column to runs")
            except Exception as e:
                print(f"    - Error adding error_message to runs: {e}")
        
        # Version 5 to 6: Chief of Staff (CoS) tables
        if from_version < 6 and to_version >= 6:
            print("  - Creating Chief of Staff tables: cos_projects, cos_preferences, cos_weekly_plans, cos_daily_plans")
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS cos_projects (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        client TEXT,
                        description TEXT,
                        status TEXT NOT NULL,
                        priority INTEGER,
                        deadline TEXT,
                        next_action TEXT,
                        blockers TEXT,
                        tags TEXT,
                        last_touched TEXT,
                        created_at TEXT,
                        updated_at TEXT
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS cos_preferences (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        operating_system_md TEXT,
                        blocked_times_json TEXT,
                        deep_work_hours INTEGER,
                        behavior_prefs_json TEXT,
                        updated_at TEXT
                    )
                """)
                conn.execute("INSERT OR IGNORE INTO cos_preferences (id, updated_at) VALUES (1, datetime('now'))")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS cos_weekly_plans (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        week_start TEXT,
                        plan_md TEXT,
                        inputs_snapshot_json TEXT,
                        created_at TEXT
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS cos_daily_plans (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        date TEXT,
                        plan_md TEXT,
                        created_at TEXT
                    )
                """)
                conn.commit()
                print("    - Chief of Staff tables created")
            except Exception as e:
                print(f"    - Error creating CoS tables: {e}")
        
        # Version 6 to 7: CoS suggested/accepted fields (Suggest Next Actions workflow)
        # Must run before 7->8 so cos_projects has required columns
        if from_version < 7 and to_version >= 7:
            print("  - Adding cos_projects columns: notes, blockers_json, priority_tier, suggested_*, accepted_at")
            try:
                cursor = conn.execute("PRAGMA table_info(cos_projects)")
                cols = {row[1] for row in cursor.fetchall()}
                for col, typ in [
                    ("notes", "TEXT"),
                    ("blockers_json", "TEXT"),
                    ("priority_tier", "TEXT"),
                    ("suggested_next_action", "TEXT"),
                    ("suggested_blockers_json", "TEXT"),
                    ("suggested_priority_tier", "TEXT"),
                    ("suggested_why", "TEXT"),
                    ("suggested_at", "TEXT"),
                    ("accepted_at", "TEXT"),
                ]:
                    if col not in cols:
                        conn.execute(f"ALTER TABLE cos_projects ADD COLUMN {col} {typ}")
                        print(f"    - Added {col}")
                conn.commit()
            except Exception as e:
                print(f"    - Error adding CoS suggestion columns: {e}")

        # Version 7 to 8: CoS chat list (conversations organized by project)
        if from_version < 8 and to_version >= 8:
            print("  - Creating cos_chats table for Chief of Staff chat history")
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS cos_chats (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL DEFAULT 'New chat',
                        project TEXT,
                        created_at TEXT,
                        updated_at TEXT
                    )
                """)
                conn.commit()
                print("    - cos_chats created")
            except Exception as e:
                print(f"    - Error creating cos_chats: {e}")

        # Version 8 to 9: Leads table for lead generation
        if from_version < 9 and to_version >= 9:
            print("  - Creating leads table for lead generation")
            try:
                conn.execute('''CREATE TABLE IF NOT EXISTS leads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lead_key TEXT NOT NULL UNIQUE,
                    company_key TEXT,
                    name TEXT NOT NULL,
                    company TEXT NOT NULL,
                    title TEXT,
                    linkedin_url TEXT,
                    company_url TEXT,
                    rationale TEXT,
                    message TEXT,
                    status TEXT NOT NULL DEFAULT 'new',
                    contacted INTEGER DEFAULT 0,
                    contact_date TEXT,
                    next_action_date TEXT,
                    notes TEXT,
                    signals_json TEXT,
                    sources_json TEXT,
                    signals_score INTEGER DEFAULT 0,
                    fit_score INTEGER DEFAULT 0,
                    confidence_score INTEGER DEFAULT 0,
                    total_score INTEGER DEFAULT 0,
                    first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
                )''')
                conn.commit()
                print("    - leads table created")
            except Exception as e:
                print(f"    - Error creating leads table: {e}")

        # Version 9 to 10: Chief of Staff structured memory tables
        if from_version < 10 and to_version >= 10:
            print("  - Creating Chief of Staff memory tables: cos_memory, cos_memory_fts")
            try:
                conn.execute('''CREATE TABLE IF NOT EXISTS cos_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    json_data TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )''')
                conn.execute("CREATE INDEX IF NOT EXISTS idx_cos_memory_chat_id ON cos_memory(chat_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_cos_memory_kind ON cos_memory(kind)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_cos_memory_created_at ON cos_memory(created_at)")
                conn.execute('''CREATE VIRTUAL TABLE IF NOT EXISTS cos_memory_fts
                    USING fts5 (
                        mem_id UNINDEXED,
                        chat_id UNINDEXED,
                        kind UNINDEXED,
                        content,
                        created_at UNINDEXED,
                        tokenize='porter'
                    )''')
                conn.commit()
                print("    - cos_memory tables created")
            except Exception as e:
                print(f"    - Error creating cos_memory tables: {e}")

        # Version 10 to 11: Agent directory + delegation workflow tables
        if from_version < 11 and to_version >= 11:
            print("  - Creating agent workflow tables: agent_directory, agent_threads, agent_assignments, agent_assignment_events, agent_artifacts")
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS agent_directory (
                        code TEXT PRIMARY KEY,
                        display_name TEXT NOT NULL,
                        role_title TEXT NOT NULL,
                        home_tab TEXT NOT NULL,
                        aliases_json TEXT NOT NULL DEFAULT '[]',
                        capabilities_json TEXT NOT NULL DEFAULT '[]',
                        is_active INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT,
                        updated_at TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS agent_threads (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        agent_code TEXT NOT NULL,
                        title TEXT NOT NULL DEFAULT 'New thread',
                        session_id TEXT NOT NULL UNIQUE,
                        context_json TEXT,
                        created_at TEXT,
                        updated_at TEXT,
                        last_message_at TEXT,
                        FOREIGN KEY (agent_code) REFERENCES agent_directory(code)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS agent_assignments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        brief_md TEXT NOT NULL,
                        requester_code TEXT NOT NULL,
                        assignee_code TEXT NOT NULL,
                        priority INTEGER NOT NULL DEFAULT 3,
                        due_date TEXT,
                        status TEXT NOT NULL DEFAULT 'queued',
                        source_thread_id INTEGER,
                        source_project_id INTEGER,
                        context_json TEXT,
                        result_summary_md TEXT,
                        created_at TEXT,
                        updated_at TEXT,
                        completed_at TEXT,
                        FOREIGN KEY (requester_code) REFERENCES agent_directory(code),
                        FOREIGN KEY (assignee_code) REFERENCES agent_directory(code),
                        FOREIGN KEY (source_thread_id) REFERENCES agent_threads(id)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS agent_assignment_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        assignment_id INTEGER NOT NULL,
                        event_type TEXT NOT NULL,
                        from_status TEXT,
                        to_status TEXT,
                        actor_code TEXT,
                        note TEXT,
                        created_at TEXT,
                        FOREIGN KEY (assignment_id) REFERENCES agent_assignments(id),
                        FOREIGN KEY (actor_code) REFERENCES agent_directory(code)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS agent_artifacts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        assignment_id INTEGER,
                        thread_id INTEGER,
                        artifact_type TEXT NOT NULL,
                        title TEXT,
                        content_md TEXT,
                        content_json TEXT,
                        file_path TEXT,
                        created_at TEXT,
                        FOREIGN KEY (assignment_id) REFERENCES agent_assignments(id),
                        FOREIGN KEY (thread_id) REFERENCES agent_threads(id)
                    )
                    """
                )
                conn.commit()
                print("    - Agent workflow tables created")
            except Exception as e:
                print(f"    - Error creating agent workflow tables: {e}")

        # Version 11 to 12: Billing tables (manual time entry + invoice drafts)
        if from_version < 12 and to_version >= 12:
            print("  - Creating billing tables: billing_clients, time_entries, invoice_templates, invoice_drafts")
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS billing_clients (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        billing_contact_name TEXT,
                        billing_email TEXT,
                        default_rate REAL,
                        currency TEXT NOT NULL DEFAULT 'USD',
                        is_active INTEGER NOT NULL DEFAULT 1,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS time_entries (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        client_id INTEGER NOT NULL,
                        start_ts TEXT NOT NULL,
                        end_ts TEXT NOT NULL,
                        minutes INTEGER NOT NULL,
                        deliverable_label TEXT NOT NULL DEFAULT '',
                        work_performed TEXT NOT NULL DEFAULT '',
                        description TEXT NOT NULL DEFAULT '',
                        percent_of_total REAL,
                        rate_override REAL,
                        is_billable INTEGER NOT NULL DEFAULT 1,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (client_id) REFERENCES billing_clients(id)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS invoice_templates (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        template_body TEXT NOT NULL,
                        engine TEXT NOT NULL DEFAULT 'placeholder_v1',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS invoice_drafts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        client_id INTEGER NOT NULL,
                        period_start TEXT NOT NULL,
                        period_end TEXT NOT NULL,
                        invoice_number TEXT,
                        due_date TEXT,
                        generated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        status TEXT NOT NULL DEFAULT 'draft',
                        totals_json TEXT NOT NULL DEFAULT '{}',
                        rendered_body_md TEXT NOT NULL DEFAULT '',
                        file_path TEXT,
                        pdf_file_path TEXT,
                        FOREIGN KEY (client_id) REFERENCES billing_clients(id)
                    )
                    """
                )
                conn.commit()
                print("    - Billing tables created")
            except Exception as e:
                print(f"    - Error creating billing tables: {e}")

        # Version 12 to 13: Normalize assignment priority semantics (P5 = most urgent)
        # Historically some parts of the app treated lower numbers as "more urgent".
        # We standardize so higher numbers are more urgent everywhere.
        if from_version < 13 and to_version >= 13:
            print("  - Normalizing agent_assignments priority scale (invert 1..5)")
            try:
                # Only run if the table exists.
                row = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_assignments' LIMIT 1"
                ).fetchone()
                if row:
                    conn.execute(
                        """
                        UPDATE agent_assignments
                        SET priority = (6 - priority)
                        WHERE priority BETWEEN 1 AND 5
                        """
                    )
                    conn.commit()
                    # Avoid non-ASCII output (Windows console encoding).
                    print("    - agent_assignments priority values inverted (1<->5, 2<->4, 3 unchanged)")
            except Exception as e:
                print(f"    - Error normalizing agent_assignments priority: {e}")

        # Version 13 to 14: Billing time entry fields for invoice calculation
        # Add work_performed, percent_of_total (fixed-fee allocation), and per-entry rate override.
        if from_version < 14 and to_version >= 14:
            print("  - Adding billing calculation columns to time_entries")
            try:
                cursor = conn.execute("PRAGMA table_info(time_entries)")
                columns = [col[1] for col in cursor.fetchall()]

                if "work_performed" not in columns:
                    conn.execute("ALTER TABLE time_entries ADD COLUMN work_performed TEXT NOT NULL DEFAULT ''")
                    print("    - Added 'work_performed' column to time_entries")
                if "percent_of_total" not in columns:
                    conn.execute("ALTER TABLE time_entries ADD COLUMN percent_of_total REAL")
                    print("    - Added 'percent_of_total' column to time_entries")
                if "rate_override" not in columns:
                    conn.execute("ALTER TABLE time_entries ADD COLUMN rate_override REAL")
                    print("    - Added 'rate_override' column to time_entries")

                conn.commit()
            except Exception as e:
                print(f"    - Error adding billing calculation columns: {e}")
        
        # Version 14 to 15: add explicit deliverable/category label for grouped invoice output.
        if from_version < 15 and to_version >= 15:
            print("  - Adding deliverable/category labels to time_entries")
            try:
                cursor = conn.execute("PRAGMA table_info(time_entries)")
                columns = [col[1] for col in cursor.fetchall()]

                if "deliverable_label" not in columns:
                    conn.execute("ALTER TABLE time_entries ADD COLUMN deliverable_label TEXT NOT NULL DEFAULT ''")
                    print("    - Added 'deliverable_label' column to time_entries")

                conn.execute(
                    """
                    UPDATE time_entries
                    SET deliverable_label = COALESCE(NULLIF(deliverable_label, ''), work_performed, '')
                    WHERE COALESCE(deliverable_label, '') = ''
                    """
                )
                print("    - Backfilled deliverable labels from work_performed")
                conn.commit()
            except Exception as e:
                print(f"    - Error adding deliverable/category labels: {e}")

        # Version 15 to 16: invoice draft PDF export tracking.
        if from_version < 16 and to_version >= 16:
            print("  - Adding PDF export tracking to invoice_drafts")
            try:
                cursor = conn.execute("PRAGMA table_info(invoice_drafts)")
                columns = [col[1] for col in cursor.fetchall()]
                if "pdf_file_path" not in columns:
                    conn.execute("ALTER TABLE invoice_drafts ADD COLUMN pdf_file_path TEXT")
                    print("    - Added 'pdf_file_path' column to invoice_drafts")
                conn.commit()
            except Exception as e:
                print(f"    - Error adding invoice draft PDF tracking: {e}")

        # Version 16 to 17: billing contact and per-draft invoice metadata.
        if from_version < 17 and to_version >= 17:
            print("  - Adding billing contact and invoice metadata fields")
            try:
                cursor = conn.execute("PRAGMA table_info(billing_clients)")
                columns = [col[1] for col in cursor.fetchall()]
                if "billing_contact_name" not in columns:
                    conn.execute("ALTER TABLE billing_clients ADD COLUMN billing_contact_name TEXT")
                    print("    - Added 'billing_contact_name' column to billing_clients")

                cursor = conn.execute("PRAGMA table_info(invoice_drafts)")
                columns = [col[1] for col in cursor.fetchall()]
                if "invoice_number" not in columns:
                    conn.execute("ALTER TABLE invoice_drafts ADD COLUMN invoice_number TEXT")
                    print("    - Added 'invoice_number' column to invoice_drafts")
                if "due_date" not in columns:
                    conn.execute("ALTER TABLE invoice_drafts ADD COLUMN due_date TEXT")
                    print("    - Added 'due_date' column to invoice_drafts")
                conn.commit()
            except Exception as e:
                print(f"    - Error adding billing contact and invoice metadata fields: {e}")

        # Version 17 to 18: global durable user memory tables.
        if from_version < 18 and to_version >= 18:
            print("  - Creating global user memory tables: user_memory, user_memory_fts")
            try:
                conn.execute(
                    '''CREATE TABLE IF NOT EXISTS user_memory (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        kind TEXT NOT NULL,
                        content TEXT NOT NULL,
                        source TEXT NOT NULL DEFAULT 'unknown',
                        confidence REAL NOT NULL DEFAULT 1.0,
                        approval_status TEXT NOT NULL DEFAULT 'approved',
                        json_data TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )'''
                )
                conn.execute(
                    '''CREATE VIRTUAL TABLE IF NOT EXISTS user_memory_fts
                        USING fts5 (
                            mem_id UNINDEXED,
                            kind UNINDEXED,
                            content,
                            source UNINDEXED,
                            created_at UNINDEXED,
                            tokenize='porter'
                        )'''
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_user_memory_kind ON user_memory(kind)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_user_memory_source ON user_memory(source)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_user_memory_created_at ON user_memory(created_at)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_user_memory_confidence ON user_memory(confidence)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_user_memory_approval_status ON user_memory(approval_status)")
                conn.commit()
                print("    - user_memory tables created")
            except Exception as e:
                print(f"    - Error creating global user memory tables: {e}")

        # Version 18 to 19: approval state for global user memory.
        if from_version < 19 and to_version >= 19:
            print("  - Adding approval state to global user memory")
            try:
                cursor = conn.execute("PRAGMA table_info(user_memory)")
                columns = [col[1] for col in cursor.fetchall()]
                if "approval_status" not in columns:
                    conn.execute("ALTER TABLE user_memory ADD COLUMN approval_status TEXT NOT NULL DEFAULT 'approved'")
                    print("    - Added 'approval_status' column to user_memory")
                conn.execute(
                    """
                    UPDATE user_memory
                    SET approval_status = CASE
                        WHEN COALESCE(source, '') = 'auto_chat' AND COALESCE(approval_status, '') = 'approved' THEN 'pending'
                        WHEN COALESCE(approval_status, '') = '' THEN 'approved'
                        ELSE approval_status
                    END
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_user_memory_approval_status ON user_memory(approval_status)")
                conn.commit()
            except Exception as e:
                print(f"    - Error adding approval state to user_memory: {e}")

        # Version 19 to 20: important email triage + normalized clients.
        if from_version < 20 and to_version >= 20:
            print("  - Creating normalized client tables and important-email triage fields")
            try:
                table_names = {
                    str(row[0])
                    for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                }
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS clients (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL UNIQUE,
                        aliases_json TEXT NOT NULL DEFAULT '[]',
                        domain_rules_json TEXT NOT NULL DEFAULT '[]',
                        notes TEXT,
                        is_active INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT,
                        updated_at TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS client_contacts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        client_id INTEGER NOT NULL,
                        name TEXT,
                        email TEXT,
                        domain TEXT,
                        role TEXT,
                        notes TEXT,
                        created_at TEXT,
                        updated_at TEXT,
                        FOREIGN KEY (client_id) REFERENCES clients(id)
                    )
                    """
                )

                if "emails" in table_names:
                    cursor = conn.execute("PRAGMA table_info(emails)")
                    email_columns = {col[1] for col in cursor.fetchall()}
                    for col_name, col_type in [
                        ("triage_status", "TEXT NOT NULL DEFAULT 'new'"),
                        ("importance_score", "INTEGER NOT NULL DEFAULT 0"),
                        ("needs_attention", "INTEGER NOT NULL DEFAULT 0"),
                        ("importance_reason_json", "TEXT NOT NULL DEFAULT '[]'"),
                        ("triaged_at", "TEXT"),
                        ("triage_source", "TEXT"),
                        ("client_id", "INTEGER"),
                        ("cos_project_id", "INTEGER"),
                    ]:
                        if col_name not in email_columns:
                            conn.execute(f"ALTER TABLE emails ADD COLUMN {col_name} {col_type}")
                            print(f"    - Added '{col_name}' column to emails")

                if "meeting_records" in table_names:
                    cursor = conn.execute("PRAGMA table_info(meeting_records)")
                    meeting_columns = {col[1] for col in cursor.fetchall()}
                    for col_name in ("client_id", "cos_project_id"):
                        if col_name not in meeting_columns:
                            conn.execute(f"ALTER TABLE meeting_records ADD COLUMN {col_name} INTEGER")
                            print(f"    - Added '{col_name}' column to meeting_records")

                if "cos_projects" in table_names:
                    cursor = conn.execute("PRAGMA table_info(cos_projects)")
                    project_columns = {col[1] for col in cursor.fetchall()}
                    if "client_id" not in project_columns:
                        conn.execute("ALTER TABLE cos_projects ADD COLUMN client_id INTEGER")
                        print("    - Added 'client_id' column to cos_projects")

                now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                if "billing_clients" in table_names:
                    billing_rows = conn.execute(
                        "SELECT name, billing_email FROM billing_clients WHERE COALESCE(name, '') <> ''"
                    ).fetchall()
                    for client_name, billing_email in billing_rows:
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO clients (name, aliases_json, domain_rules_json, notes, is_active, created_at, updated_at)
                            VALUES (?, '[]', '[]', '', 1, ?, ?)
                            """,
                            (str(client_name).strip(), now, now),
                        )
                        if billing_email:
                            client_row = conn.execute(
                                "SELECT id FROM clients WHERE name = ?",
                                (str(client_name).strip(),),
                            ).fetchone()
                            if client_row:
                                domain = ""
                                try:
                                    domain = str(billing_email).split("@", 1)[1].strip().lower()
                                except Exception:
                                    domain = ""
                                conn.execute(
                                    """
                                    INSERT INTO client_contacts (client_id, name, email, domain, role, notes, created_at, updated_at)
                                    SELECT ?, ?, ?, ?, '', '', ?, ?
                                    WHERE NOT EXISTS (
                                        SELECT 1 FROM client_contacts
                                        WHERE client_id = ? AND LOWER(COALESCE(email, '')) = LOWER(?)
                                    )
                                    """,
                                    (
                                        int(client_row[0]),
                                        str(client_name).strip(),
                                        str(billing_email).strip(),
                                        domain,
                                        now,
                                        now,
                                        int(client_row[0]),
                                        str(billing_email).strip(),
                                    ),
                                )

                if "cos_projects" in table_names:
                    project_rows = conn.execute(
                        "SELECT id, client FROM cos_projects WHERE COALESCE(client, '') <> ''"
                    ).fetchall()
                    for project_id, client_name in project_rows:
                        clean_name = str(client_name).strip()
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO clients (name, aliases_json, domain_rules_json, notes, is_active, created_at, updated_at)
                            VALUES (?, '[]', '[]', '', 1, ?, ?)
                            """,
                            (clean_name, now, now),
                        )
                        client_row = conn.execute(
                            "SELECT id FROM clients WHERE name = ?",
                            (clean_name,),
                        ).fetchone()
                        if client_row:
                            conn.execute(
                                "UPDATE cos_projects SET client_id = COALESCE(client_id, ?) WHERE id = ?",
                                (int(client_row[0]), int(project_id)),
                            )

                conn.execute("CREATE INDEX IF NOT EXISTS idx_clients_active ON clients(is_active, name)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_client_contacts_client_id ON client_contacts(client_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_client_contacts_email ON client_contacts(email)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_client_contacts_domain ON client_contacts(domain)")
                if "emails" in table_names:
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_emails_triage_status ON emails(triage_status)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_emails_needs_attention ON emails(needs_attention)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_emails_client_id ON emails(client_id)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_emails_cos_project_id ON emails(cos_project_id)")
                if "meeting_records" in table_names:
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_meeting_records_client_id ON meeting_records(client_id)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_meeting_records_cos_project_id ON meeting_records(cos_project_id)")
                if "cos_projects" in table_names:
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_cos_projects_client_id ON cos_projects(client_id)")
                conn.commit()
            except Exception as e:
                print(f"    - Error creating important-email triage schema: {e}")

        print(f"Schema migration from version {from_version} to {to_version} completed.")

    # -------------------------------------------------------------------------
    # General dossier clients / contacts
    # -------------------------------------------------------------------------

    def client_create(
        self,
        *,
        name: str,
        aliases: list[str] | None = None,
        domains: list[str] | None = None,
        notes: str | None = None,
        is_active: int = 1,
    ) -> int:
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        with sqlite3.connect(self.db_name) as conn:
            cur = conn.execute(
                """
                INSERT INTO clients (name, aliases_json, domain_rules_json, notes, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(name).strip(),
                    json.dumps([str(v).strip() for v in (aliases or []) if str(v).strip()], ensure_ascii=False),
                    json.dumps([str(v).strip().lower() for v in (domains or []) if str(v).strip()], ensure_ascii=False),
                    str(notes or "").strip(),
                    int(is_active),
                    now,
                    now,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def clients_list(self, *, active_only: bool = True) -> list[dict]:
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM clients"
            if active_only:
                query += " WHERE is_active = 1"
            query += " ORDER BY name"
            rows = [dict(r) for r in conn.execute(query).fetchall()]
        for row in rows:
            for key in ("aliases_json", "domain_rules_json"):
                try:
                    row[key] = json.loads(row.get(key) or "[]")
                except Exception:
                    row[key] = []
        return rows

    def client_get(self, client_id: int) -> dict | None:
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM clients WHERE id = ?", (int(client_id),)).fetchone()
        if not row:
            return None
        data = dict(row)
        for key in ("aliases_json", "domain_rules_json"):
            try:
                data[key] = json.loads(data.get(key) or "[]")
            except Exception:
                data[key] = []
        return data

    def client_update(self, client_id: int, **kwargs) -> bool:
        allowed = {"name", "aliases_json", "domain_rules_json", "notes", "is_active"}
        updates = []
        values = []
        for k, v in kwargs.items():
            if k not in allowed:
                continue
            if k in {"aliases_json", "domain_rules_json"} and isinstance(v, (list, dict)):
                v = json.dumps(v, ensure_ascii=False)
            updates.append(f"{k} = ?")
            values.append(v)
        if not updates:
            return False
        updates.append("updated_at = ?")
        values.append(datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
        values.append(int(client_id))
        with sqlite3.connect(self.db_name) as conn:
            conn.execute(f"UPDATE clients SET {', '.join(updates)} WHERE id = ?", values)
            conn.commit()
        return True

    def client_contact_create(
        self,
        *,
        client_id: int,
        name: str | None = None,
        email: str | None = None,
        domain: str | None = None,
        role: str | None = None,
        notes: str | None = None,
    ) -> int:
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        email_value = str(email).strip() if email else None
        domain_value = str(domain).strip().lower() if domain else None
        if not domain_value and email_value and "@" in email_value:
            domain_value = email_value.split("@", 1)[1].strip().lower()
        with sqlite3.connect(self.db_name) as conn:
            cur = conn.execute(
                """
                INSERT INTO client_contacts (client_id, name, email, domain, role, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(client_id),
                    str(name or "").strip() or None,
                    email_value,
                    domain_value,
                    str(role or "").strip() or None,
                    str(notes or "").strip() or None,
                    now,
                    now,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def client_contacts_list(self, *, client_id: int | None = None) -> list[dict]:
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            if client_id is None:
                rows = conn.execute("SELECT * FROM client_contacts ORDER BY client_id, name, email").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM client_contacts WHERE client_id = ? ORDER BY name, email",
                    (int(client_id),),
                ).fetchall()
            return [dict(r) for r in rows]

    # -------------------------------------------------------------------------
    # Billing methods (clients, time entries, templates, invoice drafts)
    # -------------------------------------------------------------------------

    def billing_client_create(
        self,
        *,
        name: str,
        billing_contact_name: str | None = None,
        billing_email: str | None = None,
        default_rate: float | None = None,
        currency: str = "USD",
        is_active: int = 1,
    ) -> int:
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        with sqlite3.connect(self.db_name) as conn:
            cur = conn.execute(
                """
                INSERT INTO billing_clients (name, billing_contact_name, billing_email, default_rate, currency, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(name).strip(),
                    (str(billing_contact_name).strip() if billing_contact_name else None),
                    (str(billing_email).strip() if billing_email else None),
                    float(default_rate) if default_rate is not None else None,
                    str(currency or "USD").strip() or "USD",
                    int(is_active),
                    now,
                    now,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def billing_clients_list(self, *, active_only: bool = True) -> list[dict]:
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            if active_only:
                rows = conn.execute(
                    "SELECT * FROM billing_clients WHERE is_active = 1 ORDER BY name"
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM billing_clients ORDER BY name").fetchall()
            return [dict(r) for r in rows]

    def billing_client_get(self, client_id: int) -> dict | None:
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM billing_clients WHERE id = ?", (int(client_id),)).fetchone()
            return dict(row) if row else None

    def billing_client_update(self, client_id: int, **kwargs) -> bool:
        allowed = {"name", "billing_contact_name", "billing_email", "default_rate", "currency", "is_active"}
        updates = []
        values = []
        for k, v in kwargs.items():
            if k not in allowed:
                continue
            updates.append(f"{k} = ?")
            values.append(v)
        if not updates:
            return False
        updates.append("updated_at = ?")
        values.append(datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
        values.append(int(client_id))
        with sqlite3.connect(self.db_name) as conn:
            conn.execute(f"UPDATE billing_clients SET {', '.join(updates)} WHERE id = ?", values)
            conn.commit()
            return True

    def time_entry_add(
        self,
        *,
        client_id: int,
        start_ts: str,
        end_ts: str,
        minutes: int,
        deliverable_label: str = "",
        work_performed: str = "",
        description: str = "",
        percent_of_total: float | None = None,
        rate_override: float | None = None,
        is_billable: int = 1,
    ) -> int:
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        with sqlite3.connect(self.db_name) as conn:
            cur = conn.execute(
                """
                INSERT INTO time_entries (
                    client_id,
                    start_ts,
                    end_ts,
                    minutes,
                    deliverable_label,
                    work_performed,
                    description,
                    percent_of_total,
                    rate_override,
                    is_billable,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(client_id),
                    str(start_ts),
                    str(end_ts),
                    int(minutes),
                    str(deliverable_label or work_performed or ""),
                    str(work_performed or ""),
                    str(description or ""),
                    (float(percent_of_total) if percent_of_total is not None else None),
                    (float(rate_override) if rate_override is not None else None),
                    int(is_billable),
                    now,
                    now,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    @staticmethod
    def _normalize_time_entry_row(row: dict) -> dict:
        out = dict(row or {})
        deliverable = str(out.get("deliverable_label") or "").strip()
        work = str(out.get("work_performed") or "").strip()
        if not deliverable and work:
            deliverable = work
        out["deliverable_label"] = deliverable
        # Preserve legacy access for older callers/templates during migration.
        if not work and deliverable:
            out["work_performed"] = deliverable
        return out

    def time_entries_list(
        self,
        *,
        client_id: int,
        start_ts: str | None = None,
        end_ts: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            q = "SELECT * FROM time_entries WHERE client_id = ?"
            params: list[object] = [int(client_id)]
            if start_ts:
                q += " AND start_ts >= ?"
                params.append(str(start_ts))
            if end_ts:
                q += " AND end_ts <= ?"
                params.append(str(end_ts))
            q += " ORDER BY start_ts DESC LIMIT ?"
            params.append(int(limit))
            rows = conn.execute(q, tuple(params)).fetchall()
            return [self._normalize_time_entry_row(dict(r)) for r in rows]

    def time_entry_get(self, entry_id: int) -> dict | None:
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM time_entries WHERE id = ?", (int(entry_id),)).fetchone()
            return self._normalize_time_entry_row(dict(row)) if row else None

    def time_entry_update(self, entry_id: int, **kwargs) -> bool:
        allowed = {
            "deliverable_label",
            "work_performed",
            "description",
            "percent_of_total",
            "rate_override",
            "is_billable",
        }
        updates: list[str] = []
        values: list[object] = []
        deliverable_supplied = False
        work_supplied = False
        for k, v in kwargs.items():
            if k not in allowed:
                continue
            if k == "deliverable_label":
                deliverable_supplied = True
            if k == "work_performed":
                work_supplied = True
            updates.append(f"{k} = ?")
            values.append(v)
        if deliverable_supplied and not work_supplied:
            updates.append("work_performed = ?")
            values.append(kwargs.get("deliverable_label"))
        if work_supplied and not deliverable_supplied:
            updates.append("deliverable_label = ?")
            values.append(kwargs.get("work_performed"))
        if not updates:
            return False
        updates.append("updated_at = ?")
        values.append(datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
        values.append(int(entry_id))
        with sqlite3.connect(self.db_name) as conn:
            cur = conn.execute(f"UPDATE time_entries SET {', '.join(updates)} WHERE id = ?", values)
            conn.commit()
            return int(cur.rowcount) > 0

    def time_entry_delete(self, entry_id: int) -> bool:
        with sqlite3.connect(self.db_name) as conn:
            cur = conn.execute("DELETE FROM time_entries WHERE id = ?", (int(entry_id),))
            conn.commit()
            return int(cur.rowcount) > 0

    def invoice_template_create(self, *, name: str, template_body: str, engine: str = "placeholder_v1") -> int:
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        with sqlite3.connect(self.db_name) as conn:
            cur = conn.execute(
                """
                INSERT INTO invoice_templates (name, template_body, engine, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (str(name).strip(), str(template_body or ""), str(engine or "placeholder_v1"), now, now),
            )
            conn.commit()
            return int(cur.lastrowid)

    def invoice_templates_list(self) -> list[dict]:
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM invoice_templates ORDER BY updated_at DESC, id DESC").fetchall()
            return [dict(r) for r in rows]

    def invoice_template_get(self, template_id: int) -> dict | None:
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM invoice_templates WHERE id = ?", (int(template_id),)).fetchone()
            return dict(row) if row else None

    def invoice_template_update(self, template_id: int, *, name: str | None = None, template_body: str | None = None) -> bool:
        updates = []
        values = []
        if name is not None:
            updates.append("name = ?")
            values.append(str(name).strip())
        if template_body is not None:
            updates.append("template_body = ?")
            values.append(str(template_body))
        if not updates:
            return False
        updates.append("updated_at = ?")
        values.append(datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
        values.append(int(template_id))
        with sqlite3.connect(self.db_name) as conn:
            conn.execute(f"UPDATE invoice_templates SET {', '.join(updates)} WHERE id = ?", values)
            conn.commit()
            return True

    def invoice_draft_create(
        self,
        *,
        client_id: int,
        period_start: str,
        period_end: str,
        invoice_number: str | None = None,
        due_date: str | None = None,
        totals_json: str,
        rendered_body_md: str,
        file_path: str | None = None,
        pdf_file_path: str | None = None,
        status: str = "draft",
    ) -> int:
        with sqlite3.connect(self.db_name) as conn:
            cur = conn.execute(
                """
                INSERT INTO invoice_drafts (client_id, period_start, period_end, invoice_number, due_date, status, totals_json, rendered_body_md, file_path, pdf_file_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(client_id),
                    str(period_start),
                    str(period_end),
                    str(invoice_number).strip() if invoice_number else None,
                    str(due_date).strip() if due_date else None,
                    str(status or "draft"),
                    str(totals_json or "{}"),
                    str(rendered_body_md or ""),
                    str(file_path) if file_path else None,
                    str(pdf_file_path) if pdf_file_path else None,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def invoice_drafts_list(self, *, client_id: int | None = None, limit: int = 200) -> list[dict]:
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            if client_id is None:
                rows = conn.execute(
                    "SELECT * FROM invoice_drafts ORDER BY generated_at DESC, id DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM invoice_drafts WHERE client_id = ? ORDER BY generated_at DESC, id DESC LIMIT ?",
                    (int(client_id), int(limit)),
                ).fetchall()
            return [dict(r) for r in rows]

    def invoice_draft_get(self, draft_id: int) -> dict | None:
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM invoice_drafts WHERE id = ?", (int(draft_id),)).fetchone()
            return dict(row) if row else None

    def invoice_draft_update_status(self, draft_id: int, *, status: str) -> bool:
        with sqlite3.connect(self.db_name) as conn:
            cur = conn.execute(
                "UPDATE invoice_drafts SET status = ? WHERE id = ?",
                (str(status or "draft"), int(draft_id)),
            )
            conn.commit()
            return int(cur.rowcount) > 0

    def invoice_draft_update_artifacts(
        self,
        draft_id: int,
        *,
        rendered_body_md: str | None = None,
        totals_json: str | None = None,
        file_path: str | None = None,
        pdf_file_path: str | None = None,
        status: str | None = None,
    ) -> bool:
        updates: list[str] = []
        values: list[object] = []
        if rendered_body_md is not None:
            updates.append("rendered_body_md = ?")
            values.append(str(rendered_body_md))
        if totals_json is not None:
            updates.append("totals_json = ?")
            values.append(str(totals_json))
        if file_path is not None:
            updates.append("file_path = ?")
            values.append(str(file_path) if file_path else None)
        if pdf_file_path is not None:
            updates.append("pdf_file_path = ?")
            values.append(str(pdf_file_path) if pdf_file_path else None)
        if status is not None:
            updates.append("status = ?")
            values.append(str(status or "draft"))
        if not updates:
            return False
        values.append(int(draft_id))
        with sqlite3.connect(self.db_name) as conn:
            cur = conn.execute(
                f"UPDATE invoice_drafts SET {', '.join(updates)} WHERE id = ?",
                values,
            )
            conn.commit()
            return int(cur.rowcount) > 0

    # -------------------------------------------------------------------------
    # Lead generation methods
    # -------------------------------------------------------------------------

    @staticmethod
    def _normalize_key(s: str | None) -> str:
        import re
        t = (s or "").strip().lower()
        t = re.sub(r"\s+", " ", t)
        t = re.sub(r"[“”\"'’]", "", t)
        t = re.sub(r"[^a-z0-9\\s\\-\\.]", "", t)
        return t.strip()

    @classmethod
    def make_company_key(cls, company: str | None) -> str:
        return cls._normalize_key(company)

    @classmethod
    def make_lead_key(cls, *, name: str | None, company: str | None, linkedin_url: str | None = None) -> str:
        # Prefer LinkedIn URL if available; else name+company.
        li = (linkedin_url or "").strip()
        if li:
            try:
                from core.news_dedup import canonicalize_url
                li = canonicalize_url(li) or li
            except Exception:
                pass
            return "li:" + li.lower()
        return "nc:" + cls._normalize_key(name) + "|" + cls._normalize_key(company)

    @staticmethod
    def _sanitize_http_url(url: str | None) -> str:
        """
        Best-effort URL normalization for UI + keying:
        - strip whitespace and trailing punctuation
        - ensure scheme (https://) if it looks like a domain
        - fix common malformed forms like https:///example.com/...
        """
        u = (url or "").strip()
        if not u:
            return ""
        # Strip common trailing punctuation from copy/paste
        u = u.strip().strip("()[]{}<>,.;\"'")
        if not u:
            return ""
        # Fix accidental triple-slash after scheme
        if u.startswith("https:///"):
            u = "https://" + u[len("https:///") :]
        if u.startswith("http:///"):
            u = "http://" + u[len("http:///") :]
        # If no scheme, add https if it looks like a domain
        if "://" not in u:
            head = u.split("/", 1)[0]
            if head.startswith("www."):
                u = "https://" + u
            elif "." in head and " " not in head:
                u = "https://" + u
        return u

    @classmethod
    def _sanitize_linkedin_url(cls, url: str | None) -> str:
        u = cls._sanitize_http_url(url)
        if not u:
            return ""
        ul = u.lower()
        if "linkedin.com" not in ul:
            return ""
        # Prefer only direct profile/company URLs to avoid junk links.
        if any(p in ul for p in ("/in/", "/company/", "/pub/")):
            return u
        return ""

    def upsert_lead(self, lead: dict) -> int:
        """
        Insert/update a lead. Returns lead id.
        Expects: name, company, title?, rationale?, message?, linkedin_url?, company_url?, sources(list), signals(list), scores.
        """
        import json as _json
        name = (lead.get("name") or lead.get("full_name") or "").strip()
        company = (lead.get("company") or lead.get("company_name") or lead.get("organization") or "").strip()
        if not name or not company:
            raise ValueError("Lead must include name and company")

        linkedin_url = self._sanitize_linkedin_url(
            (lead.get("linkedin_url") or lead.get("linkedin") or lead.get("LinkedIn_url") or "")
        )
        company_url = self._sanitize_http_url((lead.get("company_url") or lead.get("website") or ""))

        lead_key = self.make_lead_key(name=name, company=company, linkedin_url=linkedin_url)
        company_key = self.make_company_key(company)

        sources = lead.get("sources") or []
        if isinstance(sources, str):
            sources = [sources]
        if not isinstance(sources, list):
            sources = []
        sources = [self._sanitize_http_url(str(s)) for s in sources if str(s).strip()]
        sources = [s for s in sources if s]

        signals = lead.get("signals") or []
        if isinstance(signals, str):
            signals = [signals]
        if not isinstance(signals, list):
            signals = []
        signals = [str(s).strip() for s in signals if str(s).strip()]
        sources_json = _json.dumps(sources, ensure_ascii=False)
        signals_json = _json.dumps(signals, ensure_ascii=False)

        status = (lead.get("status") or "new").strip() or "new"
        contacted = 1 if bool(lead.get("contacted")) else 0
        contact_date = lead.get("contact_date")
        next_action_date = lead.get("next_action_date")
        notes = lead.get("notes")

        signals_score = int(lead.get("signals_score") or 0)
        fit_score = int(lead.get("fit_score") or 0)
        confidence_score = int(lead.get("confidence_score") or 0)
        total_score = int(lead.get("total_score") or (signals_score + fit_score + confidence_score))

        with sqlite3.connect(self.db_name) as conn:
            cur = conn.execute(
                """
                INSERT INTO leads (
                    lead_key, company_key, name, company, title, linkedin_url, company_url,
                    rationale, message, status, contacted, contact_date, next_action_date, notes,
                    signals_json, sources_json, signals_score, fit_score, confidence_score, total_score,
                    first_seen, last_seen, last_updated
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?,
                    datetime('now'), datetime('now'), datetime('now')
                )
                ON CONFLICT(lead_key) DO UPDATE SET
                    company_key=excluded.company_key,
                    name=excluded.name,
                    company=excluded.company,
                    title=COALESCE(excluded.title, leads.title),
                    linkedin_url=COALESCE(excluded.linkedin_url, leads.linkedin_url),
                    company_url=COALESCE(excluded.company_url, leads.company_url),
                    rationale=COALESCE(excluded.rationale, leads.rationale),
                    message=COALESCE(excluded.message, leads.message),
                    signals_json=COALESCE(excluded.signals_json, leads.signals_json),
                    sources_json=COALESCE(excluded.sources_json, leads.sources_json),
                    signals_score=MAX(leads.signals_score, excluded.signals_score),
                    fit_score=MAX(leads.fit_score, excluded.fit_score),
                    confidence_score=MAX(leads.confidence_score, excluded.confidence_score),
                    total_score=MAX(leads.total_score, excluded.total_score),
                    status=CASE WHEN leads.status = 'contacted' THEN leads.status ELSE excluded.status END,
                    contacted=CASE WHEN leads.contacted = 1 THEN leads.contacted ELSE excluded.contacted END,
                    contact_date=COALESCE(leads.contact_date, excluded.contact_date),
                    next_action_date=COALESCE(leads.next_action_date, excluded.next_action_date),
                    notes=COALESCE(leads.notes, excluded.notes),
                    last_seen=datetime('now'),
                    last_updated=datetime('now')
                """,
                (
                    lead_key,
                    company_key,
                    name,
                    company,
                    (lead.get("title") or None),
                    (linkedin_url or None),
                    (company_url or None),
                    (lead.get("rationale") or None),
                    (lead.get("message") or None),
                    status,
                    contacted,
                    contact_date,
                    next_action_date,
                    notes,
                    signals_json,
                    sources_json,
                    signals_score,
                    fit_score,
                    confidence_score,
                    total_score,
                ),
            )
            conn.commit()

            row = conn.execute("SELECT id FROM leads WHERE lead_key = ?", (lead_key,)).fetchone()
            return int(row[0]) if row else int(cur.lastrowid)

    def list_leads(
        self,
        *,
        status: str | None = None,
        contacted: int | None = None,
        min_score: int | None = None,
        limit: int = 200,
    ) -> list[dict]:
        import json as _json
        q = """
            SELECT id, name, company, title, linkedin_url, company_url, rationale, message,
                   status, contacted, contact_date, next_action_date, notes,
                   signals_json, sources_json,
                   signals_score, fit_score, confidence_score, total_score,
                   first_seen, last_seen, last_updated
            FROM leads
            WHERE 1=1
        """
        params = []
        if status:
            q += " AND status = ?"
            params.append(status)
        if contacted is not None:
            q += " AND contacted = ?"
            params.append(int(contacted))
        if min_score is not None:
            q += " AND total_score >= ?"
            params.append(int(min_score))
        q += " ORDER BY last_seen DESC, total_score DESC LIMIT ?"
        params.append(int(limit))

        with sqlite3.connect(self.db_name) as conn:
            rows = conn.execute(q, params).fetchall()
        out = []
        for r in rows:
            (
                lead_id,
                name,
                company,
                title,
                linkedin_url,
                company_url,
                rationale,
                message,
                status,
                contacted,
                contact_date,
                next_action_date,
                notes,
                signals_json,
                sources_json,
                signals_score,
                fit_score,
                confidence_score,
                total_score,
                first_seen,
                last_seen,
                last_updated,
            ) = r
            try:
                sources = _json.loads(sources_json) if sources_json else []
            except Exception:
                sources = []
            try:
                signals = _json.loads(signals_json) if signals_json else []
            except Exception:
                signals = []
            out.append(
                {
                    "id": lead_id,
                    "name": str(name or ""),
                    "company": str(company or ""),
                    "title": str(title or ""),
                    "linkedin_url": self._sanitize_linkedin_url(linkedin_url),
                    "company_url": self._sanitize_http_url(company_url),
                    "rationale": rationale or "",
                    "message": message or "",
                    "status": status,
                    "contacted": bool(contacted),
                    "contact_date": contact_date,
                    "next_action_date": next_action_date,
                    "notes": notes or "",
                    "signals": signals,
                    "sources": sources,
                    "signals_score": int(signals_score or 0),
                    "fit_score": int(fit_score or 0),
                    "confidence_score": int(confidence_score or 0),
                    "total_score": int(total_score or 0),
                    "first_seen": first_seen,
                    "last_seen": last_seen,
                    "last_updated": last_updated,
                }
            )
        return out

    def set_lead_contacted(self, lead_id: int, contacted: bool) -> None:
        with sqlite3.connect(self.db_name) as conn:
            if contacted:
                conn.execute(
                    "UPDATE leads SET contacted = 1, status = 'contacted', contact_date = COALESCE(contact_date, date('now')), last_updated=datetime('now') WHERE id = ?",
                    (int(lead_id),),
                )
            else:
                conn.execute(
                    "UPDATE leads SET contacted = 0, last_updated=datetime('now') WHERE id = ?",
                    (int(lead_id),),
                )
            conn.commit()

    def delete_lead_by_id(self, lead_id: int) -> None:
        with sqlite3.connect(self.db_name) as conn:
            conn.execute("DELETE FROM leads WHERE id = ?", (int(lead_id),))
            conn.commit()

    def update_lead_by_id(
        self,
        lead_id: int,
        *,
        status: str | None = None,
        next_action_date: str | None = None,
        notes: str | None = None,
    ) -> None:
        sets = []
        vals = []
        if status is not None:
            sets.append("status = ?")
            vals.append(str(status))
        if next_action_date is not None:
            sets.append("next_action_date = ?")
            vals.append(next_action_date)
        if notes is not None:
            sets.append("notes = ?")
            vals.append(notes)
        if not sets:
            return
        sets.append("last_updated = datetime('now')")
        vals.append(int(lead_id))
        with sqlite3.connect(self.db_name) as conn:
            conn.execute(f"UPDATE leads SET {', '.join(sets)} WHERE id = ?", vals)
            conn.commit()

    # -------------------------------------------------------------------------
    # Multi-agent project / task / run / artifact / log methods
    # -------------------------------------------------------------------------

    def create_project(self, name: str, mode: str, config_json: str = None) -> int:
        """Create a new project. Returns project id."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute(
                "INSERT INTO projects (name, mode, status, config_json) VALUES (?, ?, 'draft', ?)",
                (name, mode, config_json)
            )
            conn.commit()
            return cursor.lastrowid

    def get_project(self, project_id: int):
        """Get project row by id. Returns (id, name, mode, status, created_at, config_json) or None."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute(
                "SELECT id, name, mode, status, created_at, config_json FROM projects WHERE id = ?",
                (project_id,)
            )
            return cursor.fetchone()

    def get_projects(self, status: str = None):
        """Get all projects, optionally filtered by status. Returns list of (id, name, mode, status, created_at, config_json)."""
        with sqlite3.connect(self.db_name) as conn:
            if status:
                cursor = conn.execute(
                    "SELECT id, name, mode, status, created_at, config_json FROM projects WHERE status = ? ORDER BY created_at DESC",
                    (status,)
                )
            else:
                cursor = conn.execute(
                    "SELECT id, name, mode, status, created_at, config_json FROM projects ORDER BY created_at DESC"
                )
            return cursor.fetchall()

    def update_project_status(self, project_id: int, status: str):
        """Update project status (e.g. draft, running, done)."""
        with sqlite3.connect(self.db_name) as conn:
            conn.execute("UPDATE projects SET status = ? WHERE id = ?", (status, project_id))
            conn.commit()

    def insert_task_plan(self, project_id: int, plan_json: str) -> int:
        """Store a TaskPlan as JSON. Returns task_plan id."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute(
                "INSERT INTO task_plans (project_id, plan_json) VALUES (?, ?)",
                (project_id, plan_json)
            )
            conn.commit()
            return cursor.lastrowid

    def get_task_plan_for_project(self, project_id: int):
        """Get latest task plan for project. Returns (id, project_id, plan_json, created_at) or None."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute(
                "SELECT id, project_id, plan_json, created_at FROM task_plans WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
                (project_id,)
            )
            return cursor.fetchone()

    def insert_project_task(self, project_id: int, plan_task_id: str, title: str, agent_type: str,
                            dependencies_json: str = None, definition_of_done: str = None) -> int:
        """Insert a project task (from plan). Returns project_tasks id."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute(
                """INSERT INTO project_tasks (project_id, plan_task_id, title, agent_type, status, dependencies_json, definition_of_done)
                   VALUES (?, ?, ?, ?, 'queued', ?, ?)""",
                (project_id, plan_task_id, title, agent_type, dependencies_json, definition_of_done)
            )
            conn.commit()
            return cursor.lastrowid

    def get_project_tasks(self, project_id: int):
        """Get all tasks for a project. Returns list of (id, project_id, plan_task_id, title, agent_type, status, ...)."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute(
                """SELECT id, project_id, plan_task_id, title, agent_type, status, dependencies_json, definition_of_done, created_at, updated_at
                   FROM project_tasks WHERE project_id = ? ORDER BY id""",
                (project_id,)
            )
            return cursor.fetchall()

    def update_project_task_status(self, project_task_id: int, status: str):
        """Update a project task status (queued, running, completed, failed)."""
        with sqlite3.connect(self.db_name) as conn:
            conn.execute(
                "UPDATE project_tasks SET status = ?, updated_at = datetime('now') WHERE id = ?",
                (status, project_task_id)
            )
            conn.commit()

    def insert_run(self, project_id: int, project_task_id: int, agent_type: str, model_used: str = None) -> int:
        """Start a run. Returns run id."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute(
                """INSERT INTO runs (project_id, project_task_id, agent_type, status, started_at, model_used)
                   VALUES (?, ?, ?, 'running', datetime('now'), ?)""",
                (project_id, project_task_id, agent_type, model_used)
            )
            conn.commit()
            return cursor.lastrowid

    def update_run_status(self, run_id: int, status: str, error_message: str = None):
        """Update run status (running, completed, failed) and set finished_at if completed/failed."""
        with sqlite3.connect(self.db_name) as conn:
            if status in ("completed", "failed"):
                conn.execute(
                    "UPDATE runs SET status = ?, finished_at = datetime('now'), error_message = ? WHERE id = ?",
                    (status, error_message, run_id)
                )
            else:
                conn.execute("UPDATE runs SET status = ? WHERE id = ?", (status, run_id))
            conn.commit()

    def insert_artifact(self, project_id: int, artifact_type: str, content_json: str,
                        run_id: int = None, project_task_id: int = None, file_path: str = None) -> int:
        """Store an artifact. Returns artifact id."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute(
                """INSERT INTO artifacts (project_id, run_id, project_task_id, artifact_type, content_json, file_path)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (project_id, run_id, project_task_id, artifact_type, content_json, file_path)
            )
            conn.commit()
            return cursor.lastrowid

    def insert_agent_log(self, run_id: int, agent_type: str, model_used: str = None,
                         inputs_json: str = None, tool_outputs_json: str = None,
                         artifacts_produced_json: str = None, token_metadata_json: str = None,
                         error_message: str = None):
        """Append an agent run log entry."""
        with sqlite3.connect(self.db_name) as conn:
            conn.execute(
                """INSERT INTO agent_logs (run_id, agent_type, model_used, inputs_json, tool_outputs_json,
                   artifacts_produced_json, token_metadata_json, error_message)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, agent_type, model_used, inputs_json, tool_outputs_json,
                 artifacts_produced_json, token_metadata_json, error_message)
            )
            conn.commit()

    def get_artifacts_for_project(self, project_id: int, artifact_type: str = None):
        """Get artifacts for a project, optionally by type. Returns list of (id, artifact_type, content_json, file_path, created_at)."""
        with sqlite3.connect(self.db_name) as conn:
            if artifact_type:
                cursor = conn.execute(
                    """SELECT id, artifact_type, content_json, file_path, created_at FROM artifacts
                       WHERE project_id = ? AND artifact_type = ? ORDER BY created_at""",
                    (project_id, artifact_type)
                )
            else:
                cursor = conn.execute(
                    """SELECT id, artifact_type, content_json, file_path, created_at FROM artifacts
                       WHERE project_id = ? ORDER BY created_at""",
                    (project_id,)
                )
            return cursor.fetchall()

    def get_runs_for_project(self, project_id: int):
        """Get runs for a project. Returns list of (id, project_task_id, agent_type, status, started_at, finished_at, model_used)."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute(
                """SELECT id, project_task_id, agent_type, status, started_at, finished_at, model_used
                   FROM runs WHERE project_id = ? ORDER BY started_at""",
                (project_id,)
            )
            return cursor.fetchall()

    def get_artifact_store_path(self, project_id: int, create: bool = True) -> str:
        """Return the local directory path for this project's artifacts (e.g. data/artifacts/1). Create it if create=True."""
        path = os.path.join(ARTIFACTS_DIR, str(project_id))
        if create and not os.path.isdir(path):
            os.makedirs(path, exist_ok=True)
        return path

    def get_house_style_guide(self) -> str:
        """Return the House Style Guide markdown (single row, id=1). Empty string if none set."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute("SELECT content_markdown FROM house_style_guide WHERE id = 1")
            row = cursor.fetchone()
            return row[0] if row else ""

    def set_house_style_guide(self, content_markdown: str):
        """Set or update the House Style Guide markdown."""
        with sqlite3.connect(self.db_name) as conn:
            conn.execute(
                """INSERT INTO house_style_guide (id, content_markdown, created_at, updated_at)
                   VALUES (1, ?, datetime('now'), datetime('now'))
                   ON CONFLICT(id) DO UPDATE SET content_markdown = ?, updated_at = datetime('now')""",
                (content_markdown, content_markdown)
            )
            conn.commit()

    # -------------------------------------------------------------------------
    # Chief of Staff (CoS) methods
    # -------------------------------------------------------------------------

    def cos_insert_project(self, name: str, client: str = None, description: str = None,
                           status: str = "Active", priority: int = None, deadline: str = None,
                           next_action: str = None, blockers: str = None, tags: str = None,
                           notes: str = None, client_id: int | None = None) -> int:
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute(
                """INSERT INTO cos_projects
                   (name, client, description, status, priority, deadline, next_action, blockers, tags, last_touched, created_at, updated_at, notes, client_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (name, client or "", description or "", status, priority, deadline, next_action or "", blockers or "", tags or "", now, now, now, notes or "", int(client_id) if client_id is not None else None)
            )
            conn.commit()
            return cursor.lastrowid

    def cos_update_project(self, project_id: int, **kwargs):
        allowed = ("name", "client", "description", "status", "priority", "deadline",
                   "next_action", "blockers", "blockers_json", "tags", "last_touched",
                   "notes", "priority_tier",
                   "suggested_next_action", "suggested_blockers_json", "suggested_priority_tier", "suggested_why", "suggested_at",
                   "accepted_at", "client_id")
        updates = []
        values = []
        for k, v in kwargs.items():
            if k in allowed:
                updates.append(f"{k} = ?")
                values.append(v)
        if not updates:
            return
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        updates.append("updated_at = ?")
        values.append(now)
        values.append(project_id)
        with sqlite3.connect(self.db_name) as conn:
            conn.execute(
                f"UPDATE cos_projects SET {', '.join(updates)} WHERE id = ?",
                values
            )
            conn.commit()

    def cos_get_project(self, project_id: int):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute(
                """SELECT id, name, client, description, status, priority, deadline,
                          next_action, blockers, tags, last_touched, created_at, updated_at,
                          notes, blockers_json, priority_tier,
                          suggested_next_action, suggested_blockers_json, suggested_priority_tier, suggested_why, suggested_at,
                          accepted_at, client_id
                   FROM cos_projects WHERE id = ?""",
                (project_id,)
            )
            return cursor.fetchone()

    def cos_get_projects(self, status: str = None, client: str = None, client_id: int | None = None):
        with sqlite3.connect(self.db_name) as conn:
            query = """SELECT id, name, client, description, status, priority, deadline,
                          next_action, blockers, tags, last_touched, created_at, updated_at,
                          notes, blockers_json, priority_tier,
                          suggested_next_action, suggested_blockers_json, suggested_priority_tier, suggested_why, suggested_at,
                          accepted_at, client_id
                   FROM cos_projects WHERE 1=1"""
            params = []
            if status:
                query += " AND status = ?"
                params.append(status)
            if client:
                query += " AND client = ?"
                params.append(client)
            if client_id is not None:
                query += " AND client_id = ?"
                params.append(int(client_id))
            query += " ORDER BY last_touched DESC, created_at DESC"
            cursor = conn.execute(query, params)
            return cursor.fetchall()

    def cos_delete_project(self, project_id: int):
        with sqlite3.connect(self.db_name) as conn:
            conn.execute("DELETE FROM cos_projects WHERE id = ?", (project_id,))
            conn.commit()

    def cos_update_project_suggestions(self, project_id: int, suggested_next_action: str = None,
                                       suggested_blockers_json: str = None, suggested_priority_tier: str = None,
                                       suggested_why: str = None):
        """Store LLM suggestions for a project. suggested_at set to now."""
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        with sqlite3.connect(self.db_name) as conn:
            conn.execute(
                """UPDATE cos_projects SET
                   suggested_next_action = ?, suggested_blockers_json = ?, suggested_priority_tier = ?, suggested_why = ?, suggested_at = ?,
                   updated_at = ?
                   WHERE id = ?""",
                (suggested_next_action or "", suggested_blockers_json or "[]", suggested_priority_tier or "", suggested_why or "", now, now, project_id)
            )
            conn.commit()

    def cos_accept_suggestion(self, project_id: int, next_action: str = None, blockers_json: str = None,
                              priority_tier: str = None):
        """Copy suggested (or provided) values into accepted fields and set accepted_at. blockers text = joined from blockers_json."""
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        with sqlite3.connect(self.db_name) as conn:
            if next_action is not None or blockers_json is not None or priority_tier is not None:
                blockers_text = ""
                if blockers_json:
                    try:
                        arr = json.loads(blockers_json)
                        blockers_text = ", ".join(str(x) for x in arr) if isinstance(arr, list) else blockers_json
                    except Exception:
                        blockers_text = blockers_json
                conn.execute(
                    """UPDATE cos_projects SET next_action = COALESCE(?, next_action),
                       blockers = ?, blockers_json = COALESCE(?, blockers_json),
                       priority_tier = COALESCE(?, priority_tier), accepted_at = ?, updated_at = ?, last_touched = ?
                       WHERE id = ?""",
                    (next_action, blockers_text, blockers_json, priority_tier, now, now, now, project_id)
                )
            else:
                row = conn.execute(
                    "SELECT suggested_next_action, suggested_blockers_json, suggested_priority_tier FROM cos_projects WHERE id = ?",
                    (project_id,)
                ).fetchone()
                if row:
                    _sna, _sbj, _spt = row
                    blockers_text = ""
                    if _sbj:
                        try:
                            arr = json.loads(_sbj)
                            blockers_text = ", ".join(str(x) for x in arr) if isinstance(arr, list) else _sbj
                        except Exception:
                            blockers_text = _sbj or ""
                    conn.execute(
                        """UPDATE cos_projects SET next_action = COALESCE(suggested_next_action, next_action),
                           blockers = ?, blockers_json = COALESCE(suggested_blockers_json, blockers_json, '[]'),
                           priority_tier = COALESCE(suggested_priority_tier, priority_tier),
                           accepted_at = ?, updated_at = ?, last_touched = ? WHERE id = ?""",
                        (blockers_text, now, now, now, project_id)
                    )
            conn.commit()

    def cos_clear_suggestions(self, project_id: int = None):
        """Clear suggested_* for one project or all. If project_id is None, clear all."""
        with sqlite3.connect(self.db_name) as conn:
            if project_id is not None:
                conn.execute(
                    """UPDATE cos_projects SET suggested_next_action = NULL, suggested_blockers_json = NULL,
                       suggested_priority_tier = NULL, suggested_why = NULL, suggested_at = NULL WHERE id = ?""",
                    (project_id,)
                )
            else:
                conn.execute(
                    """UPDATE cos_projects SET suggested_next_action = NULL, suggested_blockers_json = NULL,
                       suggested_priority_tier = NULL, suggested_why = NULL, suggested_at = NULL"""
                )
            conn.commit()

    def cos_get_preferences(self):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute(
                "SELECT operating_system_md, blocked_times_json, deep_work_hours, behavior_prefs_json, updated_at FROM cos_preferences WHERE id = 1"
            )
            return cursor.fetchone()

    def cos_set_preferences(self, operating_system_md: str = None, blocked_times_json: str = None,
                            deep_work_hours: int = None, behavior_prefs_json: str = None):
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        with sqlite3.connect(self.db_name) as conn:
            row = conn.execute("SELECT 1 FROM cos_preferences WHERE id = 1").fetchone()
            if row:
                sets = ["updated_at = ?"]
                vals = [now]
                if operating_system_md is not None:
                    sets.append("operating_system_md = ?")
                    vals.append(operating_system_md)
                if blocked_times_json is not None:
                    sets.append("blocked_times_json = ?")
                    vals.append(blocked_times_json)
                if deep_work_hours is not None:
                    sets.append("deep_work_hours = ?")
                    vals.append(deep_work_hours)
                if behavior_prefs_json is not None:
                    sets.append("behavior_prefs_json = ?")
                    vals.append(behavior_prefs_json)
                vals.append(1)
                conn.execute(f"UPDATE cos_preferences SET {', '.join(sets)} WHERE id = ?", vals)
            else:
                conn.execute(
                    """INSERT INTO cos_preferences (id, operating_system_md, blocked_times_json, deep_work_hours, behavior_prefs_json, updated_at)
                       VALUES (1, ?, ?, ?, ?, ?)""",
                    (operating_system_md or "", blocked_times_json or "[]", deep_work_hours or 0, behavior_prefs_json or "{}", now)
                )
            conn.commit()

    def cos_insert_weekly_plan(self, week_start: str, plan_md: str, inputs_snapshot_json: str = None) -> int:
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute(
                "INSERT INTO cos_weekly_plans (week_start, plan_md, inputs_snapshot_json, created_at) VALUES (?, ?, ?, ?)",
                (week_start, plan_md, inputs_snapshot_json or "{}", now)
            )
            conn.commit()
            return cursor.lastrowid

    def cos_get_weekly_plans(self, limit: int = 20):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute(
                "SELECT id, week_start, plan_md, inputs_snapshot_json, created_at FROM cos_weekly_plans ORDER BY created_at DESC LIMIT ?",
                (limit,)
            )
            return cursor.fetchall()

    def cos_get_latest_weekly_plan(self):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute(
                "SELECT id, week_start, plan_md, inputs_snapshot_json, created_at FROM cos_weekly_plans ORDER BY created_at DESC LIMIT 1"
            )
            return cursor.fetchone()

    def cos_insert_daily_plan(self, date: str, plan_md: str) -> int:
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute(
                "INSERT INTO cos_daily_plans (date, plan_md, created_at) VALUES (?, ?, ?)",
                (date, plan_md, now)
            )
            conn.commit()
            return cursor.lastrowid

    def cos_get_daily_plan_for_date(self, date: str):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute(
                "SELECT id, date, plan_md, created_at FROM cos_daily_plans WHERE date = ? ORDER BY created_at DESC LIMIT 1",
                (date,)
            )
            return cursor.fetchone()

    # -------------------------------------------------------------------------
    # CoS chat list (conversations; messages stored in conversation with session_id = "cos_<id>")
    # -------------------------------------------------------------------------

    def cos_create_chat(self, title: str = "New chat", project: str = None) -> int:
        """Create a new CoS chat. Returns chat id. Use session_id = 'cos_' + str(id) for save_message/get_chat_history."""
        # Include sub-second precision so rapid create/update calls preserve ordering.
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute(
                "INSERT INTO cos_chats (title, project, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (title or "New chat", project, now, now)
            )
            conn.commit()
            return cursor.lastrowid

    def cos_get_chats(self, project: str = None, limit: int = 100):
        """List CoS chats, optionally filtered by project. Returns [(id, title, project, created_at, updated_at), ...] by updated_at DESC."""
        with sqlite3.connect(self.db_name) as conn:
            if project is not None:
                cursor = conn.execute(
                    "SELECT id, title, project, created_at, updated_at FROM cos_chats WHERE project = ? ORDER BY updated_at DESC LIMIT ?",
                    (project, limit)
                )
            else:
                cursor = conn.execute(
                    "SELECT id, title, project, created_at, updated_at FROM cos_chats ORDER BY updated_at DESC LIMIT ?",
                    (limit,)
                )
            return cursor.fetchall()

    def cos_get_chat(self, chat_id: int):
        """Get one CoS chat by id. Returns (id, title, project, created_at, updated_at) or None."""
        with sqlite3.connect(self.db_name) as conn:
            return conn.execute(
                "SELECT id, title, project, created_at, updated_at FROM cos_chats WHERE id = ?", (chat_id,)
            ).fetchone()

    def cos_find_chat_by_title(self, title: str) -> int | None:
        """Return the most recently updated chat id with an exact title match, else None."""
        t = (title or "").strip()
        if not t:
            return None
        try:
            with sqlite3.connect(self.db_name) as conn:
                row = conn.execute(
                    "SELECT id FROM cos_chats WHERE title = ? ORDER BY updated_at DESC LIMIT 1",
                    (t,),
                ).fetchone()
                return int(row[0]) if row and row[0] is not None else None
        except Exception:
            return None

    def cos_find_latest_chat_by_title_prefix(self, prefix: str) -> int | None:
        """Return the most recently updated chat id where title starts with prefix, else None."""
        p = (prefix or "").strip()
        if not p:
            return None
        try:
            like = p + "%"
            with sqlite3.connect(self.db_name) as conn:
                row = conn.execute(
                    "SELECT id FROM cos_chats WHERE title LIKE ? ORDER BY updated_at DESC LIMIT 1",
                    (like,),
                ).fetchone()
                return int(row[0]) if row and row[0] is not None else None
        except Exception:
            return None

    def cos_update_chat(self, chat_id: int, title: str = None, project: str = None):
        """Update a CoS chat's title and/or project. updated_at is set to now."""
        # Include sub-second precision so rapid updates preserve ordering.
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        with sqlite3.connect(self.db_name) as conn:
            if title is not None and project is not None:
                conn.execute("UPDATE cos_chats SET title = ?, project = ?, updated_at = ? WHERE id = ?", (title, project, now, chat_id))
            elif title is not None:
                conn.execute("UPDATE cos_chats SET title = ?, updated_at = ? WHERE id = ?", (title, now, chat_id))
            elif project is not None:
                conn.execute("UPDATE cos_chats SET project = ?, updated_at = ? WHERE id = ?", (project, now, chat_id))
            else:
                conn.execute("UPDATE cos_chats SET updated_at = ? WHERE id = ?", (now, chat_id))
            conn.commit()

    def cos_delete_chat(self, chat_id: int):
        """Delete a CoS chat and its messages (conversation rows with session_id = 'cos_<id>')."""
        session_id = f"cos_{chat_id}"
        with sqlite3.connect(self.db_name) as conn:
            conn.execute("DELETE FROM conversation WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM cos_chats WHERE id = ?", (chat_id,))
            conn.commit()

    # -------------------------------------------------------------------------
    # CoS structured memory methods
    # -------------------------------------------------------------------------

    def cos_memory_add(self, *, chat_id: int | None, kind: str, content: str, json_data: str | None = None) -> int:
        """Insert one memory item and index it in FTS. Returns memory id."""
        if not content:
            return 0
        with sqlite3.connect(self.db_name) as conn:
            cur = conn.execute(
                "INSERT INTO cos_memory (chat_id, kind, content, json_data, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
                (int(chat_id) if chat_id is not None else None, str(kind), str(content), json_data),
            )
            mem_id = int(cur.lastrowid)
            try:
                conn.execute(
                    "INSERT INTO cos_memory_fts (mem_id, chat_id, kind, content, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
                    (mem_id, int(chat_id) if chat_id is not None else None, str(kind), str(content)),
                )
            except Exception:
                # FTS table might not exist in edge DB states; keep base row anyway.
                pass
            conn.commit()
            return mem_id

    def cos_memory_add_many(self, *, chat_id: int | None, items: list[dict]) -> int:
        """Insert many memory items. Returns count inserted."""
        if not items:
            return 0
        added = 0
        for it in items:
            try:
                kind = (it.get("kind") or "").strip() or "note"
                content = (it.get("content") or "").strip()
                json_data = it.get("json_data")
                if isinstance(json_data, (dict, list)):
                    json_data = json.dumps(json_data, ensure_ascii=False)
                self.cos_memory_add(chat_id=chat_id, kind=kind, content=content, json_data=json_data)
                added += 1
            except Exception:
                continue
        return added

    def cos_memory_recent(self, *, chat_id: int | None = None, limit: int = 20) -> list[tuple]:
        """Return recent cos_memory rows, optionally filtered by chat_id."""
        with sqlite3.connect(self.db_name) as conn:
            if chat_id is None:
                return conn.execute(
                    "SELECT id, chat_id, kind, content, json_data, created_at FROM cos_memory ORDER BY created_at DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
            return conn.execute(
                "SELECT id, chat_id, kind, content, json_data, created_at FROM cos_memory WHERE chat_id = ? ORDER BY created_at DESC LIMIT ?",
                (int(chat_id), int(limit)),
            ).fetchall()

    def cos_memory_search(self, *, query: str, chat_id: int | None = None, kind: str | None = None, limit: int = 10) -> list[tuple]:
        """
        Full-text search over cos_memory_fts content. Returns rows:
        (id, chat_id, kind, content, json_data, created_at)
        """
        q = (query or "").strip()
        if not q:
            return []

        try:
            with sqlite3.connect(self.db_name) as conn:
                where = "cos_memory_fts MATCH ?"
                params = [q]
                if chat_id is not None:
                    where += " AND chat_id = ?"
                    params.append(int(chat_id))
                if kind is not None:
                    where += " AND kind = ?"
                    params.append(str(kind))
                params.append(int(limit))
                rows = conn.execute(
                    f"""
                    SELECT m.id, m.chat_id, m.kind, m.content, m.json_data, m.created_at
                    FROM cos_memory_fts f
                    JOIN cos_memory m ON m.id = f.mem_id
                    WHERE {where}
                    ORDER BY bm25(cos_memory_fts)
                    LIMIT ?
                    """,
                    params,
                ).fetchall()
                return rows
        except Exception:
            # Fallback: LIKE search without FTS
            like = f"%{q}%"
            with sqlite3.connect(self.db_name) as conn:
                base = "SELECT id, chat_id, kind, content, json_data, created_at FROM cos_memory WHERE content LIKE ?"
                params = [like]
                if chat_id is not None:
                    base += " AND chat_id = ?"
                    params.append(int(chat_id))
                if kind is not None:
                    base += " AND kind = ?"
                    params.append(str(kind))
                base += " ORDER BY created_at DESC LIMIT ?"
                params.append(int(limit))
                return conn.execute(base, params).fetchall()

    def user_memory_add(
        self,
        *,
        kind: str,
        content: str,
        source: str = "unknown",
        confidence: float = 1.0,
        approval_status: str = "approved",
        json_data: str | dict | list | None = None,
    ) -> int:
        """Insert one durable user-memory item and index it in FTS."""
        text = str(content or "").strip()
        if not text:
            return 0
        payload = json_data
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload, ensure_ascii=False)
        with sqlite3.connect(self.db_name) as conn:
            cur = conn.execute(
                """
                INSERT INTO user_memory (kind, content, source, confidence, approval_status, json_data, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (
                    str(kind or "note").strip() or "note",
                    text,
                    str(source or "unknown").strip() or "unknown",
                    float(confidence),
                    str(approval_status or "approved").strip() or "approved",
                    payload,
                ),
            )
            mem_id = int(cur.lastrowid)
            try:
                conn.execute(
                    """
                    INSERT INTO user_memory_fts (mem_id, kind, content, source, created_at)
                    VALUES (?, ?, ?, ?, datetime('now'))
                    """,
                    (
                        mem_id,
                        str(kind or "note").strip() or "note",
                        text,
                        str(source or "unknown").strip() or "unknown",
                    ),
                )
            except Exception:
                pass
            conn.commit()
            return mem_id

    def user_memory_add_many(self, *, items: list[dict]) -> int:
        """Insert many durable user-memory items. Returns count inserted."""
        if not items:
            return 0
        added = 0
        for it in items:
            try:
                self.user_memory_add(
                    kind=(it.get("kind") or "note"),
                    content=(it.get("content") or ""),
                    source=(it.get("source") or "unknown"),
                    confidence=float(it.get("confidence", 1.0)),
                    approval_status=(it.get("approval_status") or "approved"),
                    json_data=it.get("json_data"),
                )
                added += 1
            except Exception:
                continue
        return added

    def user_memory_recent(
        self,
        *,
        kind: str | None = None,
        approval_status: str | None = None,
        limit: int = 20,
    ) -> list[tuple]:
        """
        Return recent user_memory rows:
        (id, kind, content, source, confidence, approval_status, json_data, created_at, updated_at)
        """
        with sqlite3.connect(self.db_name) as conn:
            if kind is None and approval_status is None:
                return conn.execute(
                    """
                    SELECT id, kind, content, source, confidence, approval_status, json_data, created_at, updated_at
                    FROM user_memory
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                    (int(limit),),
                ).fetchall()
            base = """
                SELECT id, kind, content, source, confidence, approval_status, json_data, created_at, updated_at
                FROM user_memory
                WHERE 1=1
            """
            params: list[object] = []
            if kind is not None:
                base += " AND kind = ?"
                params.append(str(kind))
            if approval_status is not None:
                base += " AND approval_status = ?"
                params.append(str(approval_status))
            base += " ORDER BY created_at DESC, id DESC LIMIT ?"
            params.append(int(limit))
            return conn.execute(base, params).fetchall()

    def user_memory_search(
        self,
        *,
        query: str,
        kind: str | None = None,
        approval_status: str | None = None,
        limit: int = 10,
    ) -> list[tuple]:
        """
        Full-text search over user_memory_fts. Returns rows:
        (id, kind, content, source, confidence, approval_status, json_data, created_at, updated_at)
        """
        q = (query or "").strip()
        if not q:
            return []

        try:
            with sqlite3.connect(self.db_name) as conn:
                where = "user_memory_fts MATCH ?"
                params = [q]
                if kind is not None:
                    where += " AND kind = ?"
                    params.append(str(kind))
                if approval_status is not None:
                    where += " AND m.approval_status = ?"
                    params.append(str(approval_status))
                params.append(int(limit))
                return conn.execute(
                    f"""
                    SELECT m.id, m.kind, m.content, m.source, m.confidence, m.approval_status, m.json_data, m.created_at, m.updated_at
                    FROM user_memory_fts f
                    JOIN user_memory m ON m.id = f.mem_id
                    WHERE {where}
                    ORDER BY bm25(user_memory_fts), m.confidence DESC, m.created_at DESC
                    LIMIT ?
                    """,
                    params,
                ).fetchall()
        except Exception:
            like = f"%{q}%"
            with sqlite3.connect(self.db_name) as conn:
                base = """
                    SELECT id, kind, content, source, confidence, approval_status, json_data, created_at, updated_at
                    FROM user_memory
                    WHERE (content LIKE ? OR source LIKE ?)
                """
                params = [like, like]
                if kind is not None:
                    base += " AND kind = ?"
                    params.append(str(kind))
                if approval_status is not None:
                    base += " AND approval_status = ?"
                    params.append(str(approval_status))
                base += " ORDER BY confidence DESC, created_at DESC, id DESC LIMIT ?"
                params.append(int(limit))
                return conn.execute(base, params).fetchall()

    def user_memory_alias_recent(
        self,
        *,
        approval_status: str | None = None,
        limit: int = 20,
    ) -> list[tuple]:
        """Return recent alias user-memory rows."""
        return self.user_memory_recent(kind="alias", approval_status=approval_status, limit=limit)

    def user_memory_alias_search(
        self,
        *,
        query: str,
        approval_status: str | None = None,
        limit: int = 10,
    ) -> list[tuple]:
        """Search alias memory rows, including structured json payloads when needed."""
        q = str(query or "").strip()
        if not q:
            return []
        rows = self.user_memory_search(query=q, kind="alias", approval_status=approval_status, limit=limit)
        seen_ids = {int(row[0]) for row in rows}
        if len(rows) >= int(limit):
            return rows[: int(limit)]
        like = f"%{q}%"
        with sqlite3.connect(self.db_name) as conn:
            base = """
                SELECT id, kind, content, source, confidence, approval_status, json_data, created_at, updated_at
                FROM user_memory
                WHERE kind = 'alias'
                  AND (content LIKE ? OR source LIKE ? OR COALESCE(json_data, '') LIKE ?)
            """
            params: list[object] = [like, like, like]
            if approval_status is not None:
                base += " AND approval_status = ?"
                params.append(str(approval_status))
            base += " ORDER BY confidence DESC, created_at DESC, id DESC LIMIT ?"
            params.append(int(limit))
            extra = conn.execute(base, params).fetchall()
        for row in extra:
            row_id = int(row[0])
            if row_id in seen_ids:
                continue
            seen_ids.add(row_id)
            rows.append(row)
            if len(rows) >= int(limit):
                break
        return rows

    def user_memory_delete(self, memory_id: int) -> bool:
        """Delete one durable user-memory row and its FTS entry."""
        with sqlite3.connect(self.db_name) as conn:
            try:
                conn.execute("DELETE FROM user_memory_fts WHERE mem_id = ?", (int(memory_id),))
            except Exception:
                pass
            cur = conn.execute("DELETE FROM user_memory WHERE id = ?", (int(memory_id),))
            conn.commit()
            return int(cur.rowcount or 0) > 0

    def user_memory_update(
        self,
        memory_id: int,
        *,
        kind: str,
        content: str,
        source: str,
        confidence: float,
        approval_status: str,
        json_data: str | dict | list | None = None,
    ) -> bool:
        """Update one durable user-memory row and refresh its FTS entry."""
        text = str(content or "").strip()
        if not text:
            return False
        payload = json_data
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload, ensure_ascii=False)
        kind_s = str(kind or "note").strip() or "note"
        source_s = str(source or "unknown").strip() or "unknown"
        with sqlite3.connect(self.db_name) as conn:
            cur = conn.execute(
                """
                UPDATE user_memory
                SET kind = ?, content = ?, source = ?, confidence = ?, approval_status = ?, json_data = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    kind_s,
                    text,
                    source_s,
                    float(confidence),
                    str(approval_status or "approved").strip() or "approved",
                    payload,
                    int(memory_id),
                ),
            )
            if int(cur.rowcount or 0) <= 0:
                conn.commit()
                return False
            try:
                conn.execute("DELETE FROM user_memory_fts WHERE mem_id = ?", (int(memory_id),))
                conn.execute(
                    """
                    INSERT INTO user_memory_fts (mem_id, kind, content, source, created_at)
                    SELECT id, kind, content, source, created_at
                    FROM user_memory
                    WHERE id = ?
                    """,
                    (int(memory_id),),
                )
            except Exception:
                pass
            conn.commit()
            return True

    def user_memory_set_approval_status(self, memory_id: int, approval_status: str) -> bool:
        """Set approval state for one durable user-memory row."""
        with sqlite3.connect(self.db_name) as conn:
            cur = conn.execute(
                "UPDATE user_memory SET approval_status = ?, updated_at = datetime('now') WHERE id = ?",
                (str(approval_status or "approved").strip() or "approved", int(memory_id)),
            )
            conn.commit()
            return int(cur.rowcount or 0) > 0

    def user_memory_count(self, *, kind: str | None = None, approval_status: str | None = None) -> int:
        """Count durable user-memory rows with optional filters."""
        with sqlite3.connect(self.db_name) as conn:
            base = "SELECT COUNT(*) FROM user_memory WHERE 1=1"
            params: list[object] = []
            if kind is not None:
                base += " AND kind = ?"
                params.append(str(kind))
            if approval_status is not None:
                base += " AND approval_status = ?"
                params.append(str(approval_status))
            row = conn.execute(base, params).fetchone()
            return int(row[0] or 0) if row else 0

    # -------------------------------------------------------------------------
    # Agent directory + delegation workflow methods
    # -------------------------------------------------------------------------

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def seed_default_agents(self) -> None:
        """Seed/refresh default agent directory entries."""
        now = self._now_iso()
        agents = [
            (
                "navi",
                "Navi",
                "Chief of Staff",
                "Chief of Staff",
                ["navi", "chief of staff", "cos"],
                ["delegate", "prioritize", "orchestrate", "follow_up"],
            ),
            (
                "atlas",
                "Atlas",
                "Deep Researcher",
                "Deep Research",
                ["atlas", "researcher", "deep research", "research"],
                ["deep_research", "synthesis", "citations", "briefing"],
            ),
            (
                "quill",
                "Quill",
                "Technical Writer",
                "Workspace",
                ["quill", "writer", "technical writer", "workspace"],
                ["drafting", "document_generation", "editing", "light_research"],
            ),
            (
                "sentinel",
                "Sentinel",
                "QA & Compliance",
                "Compliance",
                ["sentinel", "qa", "compliance", "quality assurance"],
                ["qa_review", "compliance_checks", "gap_analysis"],
            ),
            (
                "lex",
                "Lex",
                "Contracts Specialist",
                "Compliance",
                ["lex", "legal", "contracts", "contract review"],
                ["contract_review", "risk_flags", "redline_guidance"],
            ),
            (
                "scout",
                "Scout",
                "Lead Finder",
                "Leads",
                ["scout", "leads", "lead finder", "recruiter"],
                ["lead_discovery", "lead_scoring", "outreach_support"],
            ),
            (
                "mason",
                "Mason",
                "Project Manager",
                "Tasks",
                ["mason", "pm", "project manager", "tasks"],
                ["task_planning", "prioritization", "tracking"],
            ),
            (
                "ledger",
                "Ledger",
                "Billing Assistant",
                "Billing",
                ["ledger", "billing", "invoices", "invoice"],
                ["invoice_drafts", "billing_followups"],
            ),
            (
                "archive",
                "Archive",
                "Knowledge Librarian",
                "Library",
                ["archive", "librarian", "knowledge", "search"],
                ["unified_search", "retrieval", "citation_lookup"],
            ),
            (
                "pulse",
                "Pulse",
                "Market Intelligence Analyst",
                "Intel",
                ["pulse", "intel", "market intelligence", "analyst"],
                ["market_watch", "competitor_tracking", "trend_briefing"],
            ),
            (
                "shield",
                "Shield",
                "Security Steward",
                "Security",
                ["shield", "security", "cybersecurity", "privacy"],
                ["security_checks", "policy_validation", "sensitive_data_scan"],
            ),
        ]
        with sqlite3.connect(self.db_name) as conn:
            for code, display_name, role_title, home_tab, aliases, capabilities in agents:
                conn.execute(
                    """
                    INSERT INTO agent_directory
                        (code, display_name, role_title, home_tab, aliases_json, capabilities_json, is_active, created_at, updated_at)
                    VALUES
                        (?, ?, ?, ?, ?, ?, 1, ?, ?)
                    ON CONFLICT(code) DO UPDATE SET
                        display_name = excluded.display_name,
                        role_title = excluded.role_title,
                        home_tab = excluded.home_tab,
                        aliases_json = excluded.aliases_json,
                        capabilities_json = excluded.capabilities_json,
                        is_active = 1,
                        updated_at = excluded.updated_at
                    """,
                    (
                        str(code),
                        str(display_name),
                        str(role_title),
                        str(home_tab),
                        json.dumps(aliases, ensure_ascii=False),
                        json.dumps(capabilities, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
            conn.commit()

    def agents_list_active(self) -> list[dict]:
        """Return active agent directory rows as dicts."""
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT code, display_name, role_title, home_tab, aliases_json, capabilities_json, is_active, created_at, updated_at
                FROM agent_directory
                WHERE is_active = 1
                ORDER BY display_name
                """
            ).fetchall()
            return [dict(r) for r in rows]

    def agent_get(self, code: str) -> dict | None:
        """Return one agent row by code."""
        c = (code or "").strip().lower()
        if not c:
            return None
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT code, display_name, role_title, home_tab, aliases_json, capabilities_json, is_active, created_at, updated_at
                FROM agent_directory
                WHERE lower(code) = ?
                LIMIT 1
                """,
                (c,),
            ).fetchone()
            return dict(row) if row else None

    def agent_resolve_by_name(self, name_or_alias: str) -> dict | None:
        """
        Resolve an agent by code, display name, or alias (case-insensitive).
        Returns the agent row dict or None.
        """
        q = (name_or_alias or "").strip().lower()
        if not q:
            return None
        agents = self.agents_list_active()
        if not agents:
            return None

        # 1) exact code
        for a in agents:
            if str(a.get("code") or "").strip().lower() == q:
                return a

        # 2) exact display name
        for a in agents:
            if str(a.get("display_name") or "").strip().lower() == q:
                return a

        # 3) exact alias
        for a in agents:
            aliases = []
            try:
                aliases = json.loads(a.get("aliases_json") or "[]")
            except Exception:
                aliases = []
            aliases_l = {str(x).strip().lower() for x in aliases if str(x).strip()}
            if q in aliases_l:
                return a

        # 4) contains match in display name / aliases
        for a in agents:
            dn = str(a.get("display_name") or "").strip().lower()
            if q in dn:
                return a
            try:
                aliases = json.loads(a.get("aliases_json") or "[]")
            except Exception:
                aliases = []
            for al in aliases:
                als = str(al).strip().lower()
                if als and q in als:
                    return a
        return None

    def agent_create_thread(
        self,
        *,
        agent_code: str,
        title: str | None = None,
        context_json: str | dict | list | None = None,
        session_id: str | None = None,
    ) -> int:
        """Create an agent thread and return thread id."""
        import uuid

        code = (agent_code or "").strip().lower()
        if not code:
            return 0
        ag = self.agent_get(code)
        if not ag:
            return 0
        now = self._now_iso()
        t = (title or "").strip() or f"{ag.get('display_name') or code} thread"
        sess = (session_id or "").strip() or f"agent_{code}_{uuid.uuid4().hex[:12]}"
        ctx = context_json
        if isinstance(ctx, (dict, list)):
            ctx = json.dumps(ctx, ensure_ascii=False)
        if ctx is not None:
            ctx = str(ctx)
        with sqlite3.connect(self.db_name) as conn:
            cur = conn.execute(
                """
                INSERT INTO agent_threads
                    (agent_code, title, session_id, context_json, created_at, updated_at, last_message_at)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?)
                """,
                (code, t, sess, ctx, now, now, now),
            )
            conn.commit()
            return int(cur.lastrowid)

    def agent_list_threads(self, *, agent_code: str, limit: int = 100):
        """
        List threads for an agent.
        Returns [(id, agent_code, title, session_id, context_json, created_at, updated_at, last_message_at), ...].
        """
        code = (agent_code or "").strip().lower()
        with sqlite3.connect(self.db_name) as conn:
            return conn.execute(
                """
                SELECT id, agent_code, title, session_id, context_json, created_at, updated_at, last_message_at
                FROM agent_threads
                WHERE agent_code = ?
                ORDER BY COALESCE(last_message_at, updated_at, created_at) DESC
                LIMIT ?
                """,
                (code, int(limit)),
            ).fetchall()

    def agent_get_thread(self, thread_id: int):
        """Return one thread row by id or None."""
        with sqlite3.connect(self.db_name) as conn:
            return conn.execute(
                """
                SELECT id, agent_code, title, session_id, context_json, created_at, updated_at, last_message_at
                FROM agent_threads
                WHERE id = ?
                LIMIT 1
                """,
                (int(thread_id),),
            ).fetchone()

    def agent_touch_thread(self, thread_id: int, *, bump_last_message: bool = True) -> None:
        """Update updated_at (and optionally last_message_at) for a thread."""
        now = self._now_iso()
        with sqlite3.connect(self.db_name) as conn:
            if bump_last_message:
                conn.execute(
                    "UPDATE agent_threads SET updated_at = ?, last_message_at = ? WHERE id = ?",
                    (now, now, int(thread_id)),
                )
            else:
                conn.execute(
                    "UPDATE agent_threads SET updated_at = ? WHERE id = ?",
                    (now, int(thread_id)),
                )
            conn.commit()

    def agent_add_event(
        self,
        *,
        assignment_id: int,
        event_type: str,
        from_status: str | None = None,
        to_status: str | None = None,
        actor_code: str | None = None,
        note: str | None = None,
    ) -> int:
        """Append one assignment event and return event id."""
        now = self._now_iso()
        with sqlite3.connect(self.db_name) as conn:
            cur = conn.execute(
                """
                INSERT INTO agent_assignment_events
                    (assignment_id, event_type, from_status, to_status, actor_code, note, created_at)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(assignment_id),
                    str(event_type or "").strip() or "note",
                    from_status,
                    to_status,
                    (str(actor_code).strip().lower() if actor_code else None),
                    (str(note) if note is not None else None),
                    now,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def agent_create_assignment(
        self,
        *,
        title: str,
        brief_md: str,
        requester_code: str,
        assignee_code: str,
        priority: int = 3,
        due_date: str | None = None,
        status: str = "queued",
        source_thread_id: int | None = None,
        source_project_id: int | None = None,
        context_json: str | dict | list | None = None,
    ) -> int:
        """Create one assignment and return assignment id."""
        now = self._now_iso()
        rq = (requester_code or "").strip().lower()
        asg = (assignee_code or "").strip().lower()
        if not rq or not asg:
            return 0
        if not self.agent_get(rq):
            return 0
        if not self.agent_get(asg):
            return 0

        p = int(priority or 3)
        if p < 1:
            p = 1
        if p > 5:
            p = 5

        st = (status or "queued").strip().lower()
        if not st:
            st = "queued"

        ctx = context_json
        if isinstance(ctx, (dict, list)):
            ctx = json.dumps(ctx, ensure_ascii=False)
        if ctx is not None:
            ctx = str(ctx)

        with sqlite3.connect(self.db_name) as conn:
            cur = conn.execute(
                """
                INSERT INTO agent_assignments
                    (title, brief_md, requester_code, assignee_code, priority, due_date, status,
                     source_thread_id, source_project_id, context_json, result_summary_md, created_at, updated_at, completed_at)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL)
                """,
                (
                    str(title or "").strip() or "Untitled assignment",
                    str(brief_md or "").strip(),
                    rq,
                    asg,
                    p,
                    due_date,
                    st,
                    int(source_thread_id) if source_thread_id is not None else None,
                    int(source_project_id) if source_project_id is not None else None,
                    ctx,
                    now,
                    now,
                ),
            )
            assignment_id = int(cur.lastrowid)
            conn.execute(
                """
                INSERT INTO agent_assignment_events
                    (assignment_id, event_type, from_status, to_status, actor_code, note, created_at)
                VALUES
                    (?, 'created', NULL, ?, ?, NULL, ?)
                """,
                (assignment_id, st, rq, now),
            )
            conn.commit()
            return assignment_id

    def agent_list_assignments(
        self,
        *,
        assignee_code: str | None = None,
        requester_code: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """List assignments as dict rows with optional filters."""
        where = ["1=1"]
        params: list[object] = []
        if assignee_code:
            where.append("assignee_code = ?")
            params.append(str(assignee_code).strip().lower())
        if requester_code:
            where.append("requester_code = ?")
            params.append(str(requester_code).strip().lower())
        if status:
            where.append("status = ?")
            params.append(str(status).strip().lower())
        params.append(int(limit))
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT id, title, brief_md, requester_code, assignee_code, priority, due_date, status,
                       source_thread_id, source_project_id, context_json, result_summary_md, created_at, updated_at, completed_at
                FROM agent_assignments
                WHERE {' AND '.join(where)}
                ORDER BY
                    CASE status
                        WHEN 'in_progress' THEN 0
                        WHEN 'queued' THEN 1
                        WHEN 'awaiting_review' THEN 2
                        WHEN 'blocked' THEN 3
                        WHEN 'done' THEN 4
                        WHEN 'cancelled' THEN 5
                        ELSE 6
                    END,
                    priority DESC,
                    COALESCE(due_date, '9999-12-31') ASC,
                    id DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
            return [dict(r) for r in rows]

    def agent_get_assignment(self, assignment_id: int) -> dict | None:
        """Get one assignment as dict by id."""
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT id, title, brief_md, requester_code, assignee_code, priority, due_date, status,
                       source_thread_id, source_project_id, context_json, result_summary_md, created_at, updated_at, completed_at
                FROM agent_assignments
                WHERE id = ?
                LIMIT 1
                """,
                (int(assignment_id),),
            ).fetchone()
            return dict(row) if row else None

    def agent_get_assignment_events(self, *, assignment_id: int, limit: int = 200) -> list[dict]:
        """Get assignment event timeline (oldest first)."""
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, assignment_id, event_type, from_status, to_status, actor_code, note, created_at
                FROM agent_assignment_events
                WHERE assignment_id = ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (int(assignment_id), int(limit)),
            ).fetchall()
            return [dict(r) for r in rows]

    def agent_update_assignment_status(
        self,
        *,
        assignment_id: int,
        to_status: str,
        actor_code: str,
        note: str | None = None,
    ) -> bool:
        """Transition assignment status and log an event."""
        to_st = (to_status or "").strip().lower()
        allowed = {"queued", "in_progress", "awaiting_review", "blocked", "done", "cancelled"}
        if to_st not in allowed:
            return False

        current = self.agent_get_assignment(int(assignment_id))
        if not current:
            return False
        from_st = str(current.get("status") or "").strip().lower()
        now = self._now_iso()
        completed_at = now if to_st in {"done", "cancelled"} else None
        with sqlite3.connect(self.db_name) as conn:
            conn.execute(
                "UPDATE agent_assignments SET status = ?, updated_at = ?, completed_at = ? WHERE id = ?",
                (to_st, now, completed_at, int(assignment_id)),
            )
            conn.execute(
                """
                INSERT INTO agent_assignment_events
                    (assignment_id, event_type, from_status, to_status, actor_code, note, created_at)
                VALUES
                    (?, 'status_changed', ?, ?, ?, ?, ?)
                """,
                (int(assignment_id), from_st or None, to_st, (actor_code or "").strip().lower() or None, note, now),
            )
            conn.commit()
        return True

    def agent_update_assignment_fields(
        self,
        *,
        assignment_id: int,
        actor_code: str | None = None,
        priority: int | None = None,
        due_date: str | None | object = _UNSET,
        title: str | None = None,
        brief_md: str | None = None,
        note: str | None = None,
    ) -> bool:
        """
        Update assignment metadata fields (non-status) and append an audit event.
        Supports changing any subset of: priority, due_date, title, brief_md.
        """
        current = self.agent_get_assignment(int(assignment_id))
        if not current:
            return False

        updates: list[str] = []
        values: list[object] = []
        changes: list[str] = []

        if priority is not None:
            p = int(priority)
            if p < 1:
                p = 1
            if p > 5:
                p = 5
            old_p = int(current.get("priority") or 3)
            updates.append("priority = ?")
            values.append(p)
            if old_p != p:
                changes.append(f"priority {old_p} -> {p}")

        if due_date is not self._UNSET:
            due = (str(due_date).strip() if due_date is not None else "")
            new_due = due if due else None
            old_due = str(current.get("due_date") or "").strip() or None
            updates.append("due_date = ?")
            values.append(new_due)
            if old_due != new_due:
                changes.append(f"due_date {old_due or '(none)'} -> {new_due or '(none)'}")

        if title is not None:
            t = str(title).strip()
            old_t = str(current.get("title") or "").strip()
            updates.append("title = ?")
            values.append(t)
            if old_t != t:
                changes.append("title updated")

        if brief_md is not None:
            b = str(brief_md).strip()
            old_b = str(current.get("brief_md") or "").strip()
            updates.append("brief_md = ?")
            values.append(b)
            if old_b != b:
                changes.append("brief updated")

        if not updates:
            return False

        now = self._now_iso()
        updates.append("updated_at = ?")
        values.append(now)
        values.append(int(assignment_id))

        event_note = "; ".join(changes) if changes else "assignment fields updated"
        if note:
            event_note = f"{event_note} | {note}"

        with sqlite3.connect(self.db_name) as conn:
            conn.execute(
                f"UPDATE agent_assignments SET {', '.join(updates)} WHERE id = ?",
                values,
            )
            conn.execute(
                """
                INSERT INTO agent_assignment_events
                    (assignment_id, event_type, from_status, to_status, actor_code, note, created_at)
                VALUES
                    (?, 'assignment_updated', NULL, NULL, ?, ?, ?)
                """,
                (
                    int(assignment_id),
                    (str(actor_code).strip().lower() if actor_code else None),
                    event_note,
                    now,
                ),
            )
            conn.commit()
        return True

    def agent_set_assignment_result_summary(
        self,
        *,
        assignment_id: int,
        summary_md: str,
        actor_code: str | None = None,
        note: str | None = None,
    ) -> bool:
        """Store/update assignment result summary and append a timeline event."""
        current = self.agent_get_assignment(int(assignment_id))
        if not current:
            return False
        now = self._now_iso()
        summary = (summary_md or "").strip()
        with sqlite3.connect(self.db_name) as conn:
            conn.execute(
                "UPDATE agent_assignments SET result_summary_md = ?, updated_at = ? WHERE id = ?",
                (summary, now, int(assignment_id)),
            )
            conn.execute(
                """
                INSERT INTO agent_assignment_events
                    (assignment_id, event_type, from_status, to_status, actor_code, note, created_at)
                VALUES
                    (?, 'result_summary_updated', NULL, NULL, ?, ?, ?)
                """,
                (
                    int(assignment_id),
                    (str(actor_code).strip().lower() if actor_code else None),
                    note or ("Result summary set" if summary else "Result summary cleared"),
                    now,
                ),
            )
            conn.commit()
        return True

    def agent_reassign_assignment(
        self,
        *,
        assignment_id: int,
        new_assignee_code: str,
        actor_code: str,
        note: str | None = None,
    ) -> bool:
        """Reassign an assignment to another agent and log event."""
        asg = (new_assignee_code or "").strip().lower()
        if not asg or not self.agent_get(asg):
            return False
        current = self.agent_get_assignment(int(assignment_id))
        if not current:
            return False
        old = str(current.get("assignee_code") or "").strip().lower()
        now = self._now_iso()
        with sqlite3.connect(self.db_name) as conn:
            conn.execute(
                "UPDATE agent_assignments SET assignee_code = ?, updated_at = ? WHERE id = ?",
                (asg, now, int(assignment_id)),
            )
            conn.execute(
                """
                INSERT INTO agent_assignment_events
                    (assignment_id, event_type, from_status, to_status, actor_code, note, created_at)
                VALUES
                    (?, 'reassigned', ?, ?, ?, ?, ?)
                """,
                (
                    int(assignment_id),
                    old or None,
                    asg,
                    (actor_code or "").strip().lower() or None,
                    note,
                    now,
                ),
            )
            conn.commit()
        return True

    def agent_link_assignment_thread(
        self,
        *,
        assignment_id: int,
        thread_id: int,
        actor_code: str | None = None,
        note: str | None = None,
    ) -> bool:
        """Link an assignment to a source thread and append a timeline event."""
        current = self.agent_get_assignment(int(assignment_id))
        if not current:
            return False
        thread = self.agent_get_thread(int(thread_id))
        if not thread:
            return False
        now = self._now_iso()
        with sqlite3.connect(self.db_name) as conn:
            conn.execute(
                "UPDATE agent_assignments SET source_thread_id = ?, updated_at = ? WHERE id = ?",
                (int(thread_id), now, int(assignment_id)),
            )
            conn.execute(
                """
                INSERT INTO agent_assignment_events
                    (assignment_id, event_type, from_status, to_status, actor_code, note, created_at)
                VALUES
                    (?, 'thread_linked', NULL, NULL, ?, ?, ?)
                """,
                (
                    int(assignment_id),
                    (str(actor_code).strip().lower() if actor_code else None),
                    note or f"Linked to thread {int(thread_id)}",
                    now,
                ),
            )
            conn.commit()
        return True

    def agent_add_artifact(
        self,
        *,
        artifact_type: str,
        assignment_id: int | None = None,
        thread_id: int | None = None,
        title: str | None = None,
        content_md: str | None = None,
        content_json: str | dict | list | None = None,
        file_path: str | None = None,
    ) -> int:
        """Store an agent artifact. Returns artifact id."""
        now = self._now_iso()
        cjson = content_json
        if isinstance(cjson, (dict, list)):
            cjson = json.dumps(cjson, ensure_ascii=False)
        with sqlite3.connect(self.db_name) as conn:
            cur = conn.execute(
                """
                INSERT INTO agent_artifacts
                    (assignment_id, thread_id, artifact_type, title, content_md, content_json, file_path, created_at)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(assignment_id) if assignment_id is not None else None,
                    int(thread_id) if thread_id is not None else None,
                    str(artifact_type or "").strip() or "artifact",
                    str(title) if title is not None else None,
                    str(content_md) if content_md is not None else None,
                    str(cjson) if cjson is not None else None,
                    str(file_path) if file_path is not None else None,
                    now,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def agent_list_artifacts(
        self,
        *,
        assignment_id: int | None = None,
        thread_id: int | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """List agent artifacts filtered by assignment and/or thread."""
        where = ["1=1"]
        params: list[object] = []
        if assignment_id is not None:
            where.append("assignment_id = ?")
            params.append(int(assignment_id))
        if thread_id is not None:
            where.append("thread_id = ?")
            params.append(int(thread_id))
        params.append(int(limit))
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT id, assignment_id, thread_id, artifact_type, title, content_md, content_json, file_path, created_at
                FROM agent_artifacts
                WHERE {' AND '.join(where)}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
            return [dict(r) for r in rows]

    def close(self):
        """Close database connection."""
        pass  # SQLite connections are automatically closed