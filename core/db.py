# db.py
import sqlite3
from datetime import datetime, UTC

class DatabaseManager:
    def __init__(self):
        self.db_name = r"F:\naviSsurance_index.db"  # Switch to your indexed DB
        self.setup_db()

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
            
            # Drop and recreate archived_tasks table
            conn.execute('DROP TABLE IF EXISTS archived_tasks')
            conn.execute('''CREATE TABLE archived_tasks (
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

    def add_task(self, session_id, task_text, due_date):
        with sqlite3.connect(self.db_name) as conn:
            conn.execute('INSERT INTO tasks (session_id, task, due_date) VALUES (?, ?, ?)',
                        (session_id, task_text, due_date))
            conn.commit()

    def get_tasks(self):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute('SELECT id, task, due_date, completed FROM tasks ORDER BY date(due_date) ASC')
            return cursor.fetchall()

    def delete_task(self, task_text):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute('SELECT id FROM tasks WHERE task = ? ORDER BY created_at DESC LIMIT 1', (task_text,))
            task_id = cursor.fetchone()
            if task_id:
                conn.execute('DELETE FROM tasks WHERE id = ?', (task_id[0],))
                conn.commit()

    def update_task_status(self, task_text, completed):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute('SELECT id FROM tasks WHERE task = ? ORDER BY created_at DESC LIMIT 1', (task_text,))
            task_id = cursor.fetchone()
            if task_id:
                conn.execute('UPDATE tasks SET completed = ? WHERE id = ?', (completed, task_id[0]))
                conn.commit()

    def archive_task(self, task_text, due_date, completed):
        with sqlite3.connect(self.db_name) as conn:
            conn.execute('''INSERT INTO archived_tasks 
                          (task, due_date, completed, session_id, created_at) 
                          VALUES (?, ?, ?, ?, ?)''',
                        (task_text, due_date, completed, None, datetime.now()))
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

    def clear_tasks(self):
        with sqlite3.connect(self.db_name) as conn:
            conn.execute('DELETE FROM tasks')
            conn.commit()