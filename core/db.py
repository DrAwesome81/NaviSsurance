# db.py
import sqlite3

class DatabaseManager:
    def __init__(self):
        self.db_name = "navissurance.db"
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