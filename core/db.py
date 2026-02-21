# db.py
import sqlite3
from datetime import datetime, UTC
import json
import sys
import os

# Import centralized database path and artifact store
from config import DATABASE_PATH, ARTIFACTS_DIR

class DatabaseManager:
    def __init__(self):
        self.db_name = DATABASE_PATH
        self.current_schema_version = 8  # Increment this when making schema changes
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
        
        # Multi-agent tables are created in migration 2 -> 3 (see _migrate_schema)

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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cos_weekly_plans_week_start ON cos_weekly_plans(week_start)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cos_daily_plans_date ON cos_daily_plans(date)")
            
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
        # Lazy import: document extraction deps are heavy and optional for most runtime paths.
        from core.file_handler import extract_for_dataset
        entry = extract_for_dataset(file_path)
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
        
        print(f"Schema migration from version {from_version} to {to_version} completed.")

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
                           notes: str = None) -> int:
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute(
                """INSERT INTO cos_projects
                   (name, client, description, status, priority, deadline, next_action, blockers, tags, last_touched, created_at, updated_at, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (name, client or "", description or "", status, priority, deadline, next_action or "", blockers or "", tags or "", now, now, now, notes or "")
            )
            conn.commit()
            return cursor.lastrowid

    def cos_update_project(self, project_id: int, **kwargs):
        allowed = ("name", "client", "description", "status", "priority", "deadline",
                   "next_action", "blockers", "blockers_json", "tags", "last_touched",
                   "notes", "priority_tier",
                   "suggested_next_action", "suggested_blockers_json", "suggested_priority_tier", "suggested_why", "suggested_at",
                   "accepted_at")
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
                          accepted_at
                   FROM cos_projects WHERE id = ?""",
                (project_id,)
            )
            return cursor.fetchone()

    def cos_get_projects(self, status: str = None, client: str = None):
        with sqlite3.connect(self.db_name) as conn:
            query = """SELECT id, name, client, description, status, priority, deadline,
                          next_action, blockers, tags, last_touched, created_at, updated_at,
                          notes, blockers_json, priority_tier,
                          suggested_next_action, suggested_blockers_json, suggested_priority_tier, suggested_why, suggested_at,
                          accepted_at
                   FROM cos_projects WHERE 1=1"""
            params = []
            if status:
                query += " AND status = ?"
                params.append(status)
            if client:
                query += " AND client = ?"
                params.append(client)
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
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
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

    def cos_update_chat(self, chat_id: int, title: str = None, project: str = None):
        """Update a CoS chat's title and/or project. updated_at is set to now."""
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
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

    def close(self):
        """Close database connection."""
        pass  # SQLite connections are automatically closed