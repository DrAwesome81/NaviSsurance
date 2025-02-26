# db.py
import sqlite3
from datetime import datetime, UTC

class DatabaseManager:
    def __init__(self):
        self.db_name = r"F:\naviSsurance_index.db"  # Switch to your indexed DB
        self.setup_db()

    def setup_db(self):
        with sqlite3.connect(self.db_name) as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS conversation (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            conn.execute('''CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                task TEXT,
                due_date TEXT
            )''')
            conn.commit()

    def save_message(self, session_id, role, content):
        with sqlite3.connect(self.db_name) as conn:
            conn.execute('INSERT INTO conversation (session_id, role, content) VALUES (?, ?, ?)',
                        (session_id, role, content))
            conn.commit()

    def get_chat_history(self, session_id):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute('SELECT role, content, timestamp FROM conversation WHERE session_id = ? ORDER BY timestamp DESC LIMIT 20',
                                 (session_id,))
            return cursor.fetchall()

    def add_task(self, session_id, task_text, due_date):
        with sqlite3.connect(self.db_name) as conn:
            conn.execute('INSERT INTO tasks (session_id, task, due_date) VALUES (?, ?, ?)',
                        (session_id, task_text, due_date))
            conn.commit()

    def get_tasks(self):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute('SELECT task, due_date FROM tasks ORDER BY date(due_date) ASC')
            return cursor.fetchall()

    def delete_task(self, task_text):
        with sqlite3.connect(self.db_name) as conn:
            conn.execute('DELETE FROM tasks WHERE task = ?', (task_text,))
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