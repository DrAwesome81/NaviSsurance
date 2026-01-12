# db.py
import sqlite3
from datetime import datetime, UTC
import json
import sys
import os
from core.file_handler import extract_for_dataset

# Import centralized database path
from config import DATABASE_PATH

class DatabaseManager:
    def __init__(self):
        self.db_name = DATABASE_PATH
        self.current_schema_version = 2  # Increment this when making schema changes
        self.setup_db()
        self.create_indexes()

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
            
            # Check if the table exists with old schema and migrate it
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(tasks)")
            columns = [col[1] for col in cursor.fetchall()]
            
            # If task_text doesn't exist, try to migrate from common alternatives
            if 'task_text' not in columns:
                if 'task' in columns:
                    # Rename 'task' to 'task_text'
                    conn.execute("ALTER TABLE tasks RENAME COLUMN task TO task_text")
                    print("DEBUG: Migrated 'task' column to 'task_text'")
                elif 'description' in columns:
                    # Rename 'description' to 'task_text'
                    conn.execute("ALTER TABLE tasks RENAME COLUMN description TO task_text")
                    print("DEBUG: Migrated 'description' column to 'task_text'")
                elif 'content' in columns:
                    # Rename 'content' to 'task_text'
                    conn.execute("ALTER TABLE tasks RENAME COLUMN content TO task_text")
                    print("DEBUG: Migrated 'content' column to 'task_text'")
                else:
                    print("WARNING: Could not find task column to migrate")
            
            # Add missing columns if they don't exist
            if 'category' not in columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN category TEXT DEFAULT 'Business'")
                print("DEBUG: Added 'category' column with default 'Business'")
            
            if 'recurrence' not in columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN recurrence TEXT DEFAULT 'None'")
                print("DEBUG: Added 'recurrence' column with default 'None'")
            
            if 'session_id' not in columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN session_id TEXT")
                print("DEBUG: Added 'session_id' column")
            
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
            
            # Dropbox index tables removed - using RAG index instead
            
            # Notes table for the NoteTakingSystem
            conn.execute('''CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                formatted_note TEXT NOT NULL,
                category TEXT NOT NULL,
                context TEXT,
                timestamp TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            
            # Add context column if it doesn't exist (for existing databases)
            try:
                conn.execute('ALTER TABLE notes ADD COLUMN context TEXT')
            except sqlite3.OperationalError:
                # Column already exists
                pass
            
            # Organized notes table
            conn.execute('''CREATE TABLE IF NOT EXISTS organized_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                notes_json TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            
            # Vikunja task metadata table for custom fields not in Vikunja
            conn.execute('''CREATE TABLE IF NOT EXISTS vikunja_task_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vikunja_task_id INTEGER NOT NULL UNIQUE,
                estimated_duration_minutes INTEGER,
                custom_fields_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            
            conn.commit()

    def create_indexes(self):
        """Create database indexes for optimal query performance."""
        with sqlite3.connect(self.db_name) as conn:
            # Primary indexes for tasks table
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_completed ON tasks(completed)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_category ON tasks(category)")
            
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
            
            # Indexes for vikunja_task_metadata table
            conn.execute("CREATE INDEX IF NOT EXISTS idx_vikunja_task_metadata_task_id ON vikunja_task_metadata(vikunja_task_id)")
            
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

    def add_task(self, session_id, task_text, due_date, category="Business", recurrence="None", completed=0):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute('INSERT INTO tasks (session_id, task_text, due_date, category, recurrence, completed) VALUES (?, ?, ?, ?, ?, ?)',
                        (session_id, task_text, due_date, category, recurrence, completed))
            conn.commit()
            return cursor.lastrowid

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

    def store_dataset_entry(self, file_path, jsonl_path="data/fine_tune.jsonl"):
        entry = extract_for_dataset(file_path)  # From file_handler
        with open(jsonl_path, 'a') as f:  # Append to JSONL
            f.write(json.dumps(entry) + '\n')

    # Notes methods for NoteTakingSystem
    def init_notes_table(self):
        """Initialize notes table (already done in setup_db, but kept for compatibility)."""
        pass

    def save_note(self, formatted_note, timestamp, context=None):
        """Save a formatted note to the database."""
        with sqlite3.connect(self.db_name) as conn:
            conn.execute('INSERT INTO notes (formatted_note, category, context, timestamp) VALUES (?, ?, ?, ?)',
                        (formatted_note, "Uncategorized", context, timestamp))
            conn.commit()

    def get_notes(self):
        """Get all notes from the database."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute('SELECT formatted_note, context FROM notes ORDER BY created_at DESC')
            return [(row[0], row[1]) for row in cursor.fetchall()]

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

    # News methods for dashboard news feed
    def store_news_item(self, title, content, url=None, source=None, published_date=None):
        """Store a news item in the database, avoiding duplicates."""
        try:
            with sqlite3.connect(self.db_name) as conn:
                # Check if item already exists before inserting
                cursor = conn.execute('SELECT id FROM news_items WHERE title = ? OR (url IS NOT NULL AND url = ?)', (title, url))
                if cursor.fetchone():
                    print(f"News item already exists: {title[:50]}...")
                    return False
                
                conn.execute('''INSERT INTO news_items 
                    (title, content, url, source, published_date, created_at) 
                    VALUES (?, ?, ?, ?, ?, datetime('now'))''',
                    (title, content, url, source, published_date))
                conn.commit()
                print(f"Successfully stored news item: {title[:50]}...")
                return True
        except Exception as e:
            print(f"Error storing news item: {e}")
            return False

    def get_recent_news(self, days=7):
        """Get news items from the last N days."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute('''SELECT title, content, url, source, published_date, created_at 
                FROM news_items 
                WHERE created_at >= datetime('now', '-{} days')
                ORDER BY created_at DESC'''.format(days))
            return cursor.fetchall()

    def check_news_exists(self, title, url=None):
        """Check if a news item already exists in the database."""
        with sqlite3.connect(self.db_name) as conn:
            if url:
                cursor = conn.execute('SELECT id FROM news_items WHERE title = ? OR url = ?', (title, url))
            else:
                cursor = conn.execute('SELECT id FROM news_items WHERE title = ?', (title,))
            return cursor.fetchone() is not None

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
        
        print(f"Schema migration from version {from_version} to {to_version} completed.")

    def close(self):
        """Close database connection."""
        pass  # SQLite connections are automatically closed