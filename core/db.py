# db.py
import sqlite3
from datetime import datetime, UTC, date
from typing import Iterable, Optional, Tuple

from core import settings

class DatabaseManager:
    def __init__(self):
        self.db_name = str(settings.db_path())
        self.setup_db()

    @staticmethod
    def _parse_date_to_iso(value: str) -> Optional[str]:
        if not value:
            return None
        v = value.strip()
        # Already ISO
        try:
            return date.fromisoformat(v).isoformat()
        except ValueError:
            pass
        # Common legacy formats used in this repo
        for fmt in ("%m-%d-%Y", "%m-%d-%y", "%m/%d/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(v, fmt).date().isoformat()
            except ValueError:
                continue
        return None

    def setup_db(self):
        with sqlite3.connect(self.db_name) as conn:
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
                task TEXT,
                due_date TEXT,
                completed INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            
            # Archived tasks (do not drop on startup)
            conn.execute('''CREATE TABLE IF NOT EXISTS archived_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task TEXT,
                due_date TEXT,
                completed INTEGER,
                session_id TEXT,
                created_at DATETIME,
                archived_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            
            # Dropbox index tables
            conn.execute('''CREATE TABLE IF NOT EXISTS dropbox_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                path TEXT UNIQUE NOT NULL,
                link TEXT,
                modified_time TEXT,
                size INTEGER
            )''')
            conn.execute('''CREATE VIRTUAL TABLE IF NOT EXISTS dropbox_index
                USING fts5 (name, content, tokenize='porter')
            ''')
            conn.execute('''CREATE TABLE IF NOT EXISTS index_metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )''')
            conn.commit()

            # Best-effort migration: normalize legacy due_date strings to ISO for correct sorting/filtering.
            try:
                cursor = conn.execute("SELECT id, due_date FROM tasks")
                updates: list[Tuple[str, int]] = []
                for task_id, due_date_val in cursor.fetchall():
                    iso = self._parse_date_to_iso(str(due_date_val or ""))
                    if iso and iso != due_date_val:
                        updates.append((iso, task_id))
                if updates:
                    conn.executemany("UPDATE tasks SET due_date = ? WHERE id = ?", updates)
                    conn.commit()
            except Exception:
                # Don't block app startup on migration issues.
                pass

    def save_message(self, session_id, role, content):
        with sqlite3.connect(self.db_name) as conn:
            conn.execute('INSERT INTO conversation (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)',
                        (session_id, role, content, datetime.now(UTC).isoformat()))
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

    def get_messages_by_date_range(self, session_id: str, start_iso: str, end_iso: str):
        """Return messages for a session between [start_iso, end_iso)."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute(
                """
                SELECT role, content, timestamp
                FROM conversation
                WHERE session_id = ?
                  AND timestamp >= ?
                  AND timestamp < ?
                ORDER BY timestamp ASC
                """,
                (session_id, start_iso, end_iso),
            )
            return cursor.fetchall()

    def add_task(self, session_id, task_text, due_date):
        iso_due = self._parse_date_to_iso(str(due_date or "")) or str(due_date or "")
        with sqlite3.connect(self.db_name) as conn:
            conn.execute('INSERT INTO tasks (session_id, task, due_date) VALUES (?, ?, ?)',
                        (session_id, task_text, iso_due))
            conn.commit()

    def get_tasks(self):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute('SELECT id, task, due_date, completed FROM tasks ORDER BY due_date ASC')
            return cursor.fetchall()

    def delete_task(self, task_text):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute('SELECT id FROM tasks WHERE task = ? ORDER BY created_at DESC LIMIT 1', (task_text,))
            task_id = cursor.fetchone()
            if task_id:
                conn.execute('DELETE FROM tasks WHERE id = ?', (task_id[0],))
                conn.commit()

    def delete_task_by_id(self, task_id: int) -> None:
        with sqlite3.connect(self.db_name) as conn:
            conn.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
            conn.commit()

    def update_task_status(self, task_text, completed):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute('SELECT id FROM tasks WHERE task = ? ORDER BY created_at DESC LIMIT 1', (task_text,))
            task_id = cursor.fetchone()
            if task_id:
                conn.execute('UPDATE tasks SET completed = ? WHERE id = ?', (completed, task_id[0]))
                conn.commit()

    def update_task_status_by_id(self, task_id: int, completed: bool) -> None:
        with sqlite3.connect(self.db_name) as conn:
            conn.execute('UPDATE tasks SET completed = ? WHERE id = ?', (1 if completed else 0, task_id))
            conn.commit()

    def update_task_by_id(self, task_id: int, task_text: str, due_date: str) -> None:
        iso_due = self._parse_date_to_iso(str(due_date or "")) or str(due_date or "")
        with sqlite3.connect(self.db_name) as conn:
            conn.execute(
                'UPDATE tasks SET task = ?, due_date = ? WHERE id = ?',
                (task_text, iso_due, task_id),
            )
            conn.commit()

    def archive_task(self, task_text, due_date, completed):
        iso_due = self._parse_date_to_iso(str(due_date or "")) or str(due_date or "")
        with sqlite3.connect(self.db_name) as conn:
            conn.execute('''INSERT INTO archived_tasks 
                          (task, due_date, completed, session_id, created_at) 
                          VALUES (?, ?, ?, ?, ?)''',
                        (task_text, iso_due, completed, None, datetime.now(UTC).isoformat()))
            conn.commit()

    def archive_task_by_id(self, task_id: int) -> bool:
        """
        Archive a task by id, preserving session_id + created_at, then remove it from tasks.
        Returns True if a row was archived, False if not found.
        """
        with sqlite3.connect(self.db_name) as conn:
            row = conn.execute(
                "SELECT task, due_date, completed, session_id, created_at FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            if not row:
                return False
            task_text, due_date, completed, session_id, created_at = row
            iso_due = self._parse_date_to_iso(str(due_date or "")) or str(due_date or "")
            conn.execute(
                """
                INSERT INTO archived_tasks (task, due_date, completed, session_id, created_at, archived_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(task_text),
                    iso_due,
                    int(completed or 0),
                    session_id,
                    created_at,
                    datetime.now(UTC).isoformat(),
                ),
            )
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            conn.commit()
            return True

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