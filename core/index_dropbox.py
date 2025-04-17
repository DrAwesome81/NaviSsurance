import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import sqlite3
import fitz
from docx import Document
from dropbox import Dropbox, files
from core.api import get_dropbox_client  # Now works after path fix
import tempfile
import time
from datetime import datetime, timedelta
import pandas as pd

def extract_text_from_pdf(pdf_path):
    document = fitz.open(pdf_path)
    text = ""
    for page_num in range(len(document)):
        page = document.load_page(page_num)
        text += page.get_text()
    document.close()
    return text

def extract_text_from_docx(docx_path):
    doc = Document(docx_path)
    full_text = [para.text for para in doc.paragraphs]
    return '\n'.join(full_text)

def extract_text_from_txt(txt_path):
    with open(txt_path, 'r', encoding='utf-8') as file:
        return file.read()

def extract_text_from_excel(excel_path):
    return "(Excel file - content extraction not supported yet)"

#def save_cursor(cursor, cursor_file="F:/dropbox_index_cursor.pkl"):
    with open(cursor_file, 'wb') as f:
        pickle.dump(cursor, f)

#def load_cursor(cursor_file="F:/dropbox_index_cursor.pkl"):
    try:
        with open(cursor_file, 'rb') as f:
            return pickle.load(f)
    except FileNotFoundError:
        return None

def count_dropbox_files(dbx):
    total = 0
    result = dbx.files_list_folder("", recursive=True)
    while True:
        total += sum(1 for e in result.entries if isinstance(e, files.FileMetadata))
        if result.has_more:
            result = dbx.files_list_folder_continue(result.cursor)
        else:
            break
    print(f"Total files: {total}")
    return total

def index_dropbox(dbx, db_path="F:/naviSsurance_index.db", progress_callback=None):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS dropbox_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            path TEXT UNIQUE NOT NULL,
            link TEXT,
            modified_time TEXT,
            size INTEGER
        )
    """)
    c.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS dropbox_index
        USING fts5 (name, content, tokenize='porter')
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS index_metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()

    c.execute("SELECT path, modified_time, size FROM dropbox_files")
    db_files = {row[0]: (row[1], row[2]) for row in c.fetchall()}
    c.execute("SELECT value FROM index_metadata WHERE key = 'last_cursor'")
    row = c.fetchone()
    last_cursor = row[0] if row else None


    full_index_types = {'.pdf', '.txt', '.docx', '.xlsx', '.xls'}
    processed_files = 0
    added_or_updated = 0
    start_time = time.time()
    total_files = None
    unreadable_files = []

    def default_progress():
        nonlocal total_files
        elapsed = time.time() - start_time
        if total_files and processed_files > 0:
            percent = min(100, (processed_files / total_files) * 100)
            bar_length = 20
            filled = int(bar_length * percent / 100)
            bar = '#' * filled + ' ' * (bar_length - filled)
            print(f"\r[{bar}] {percent:.1f}% ({processed_files}/{total_files}, {elapsed:.1f}s)", end="")
        else:
            print(f"\rScanning... {processed_files} files checked, {elapsed:.1f}s", end="")
        sys.stdout.flush()

    callback = progress_callback or default_progress

    try:
        total_processed = 0  # Track total across refreshes
        if last_cursor:
            result = dbx.files_list_folder_continue(last_cursor)
        else:
            result = dbx.files_list_folder("", recursive=True)
        files_to_index = []
        while True:
            for entry in result.entries:
                if isinstance(entry, files.FileMetadata):
                    # Skip files in /Archive
                    if not entry.path_lower.startswith('/archive'):
                        files_to_index.append(entry)
            if result.has_more:
                result = dbx.files_list_folder_continue(result.cursor)
            else:
                break
        while True:
            for entry in result.entries:
                if not isinstance(entry, files.FileMetadata):
                    continue
                processed_files += 1
                total_processed += 1
                name = entry.name
                path = entry.path_display
                mod_time = entry.server_modified.isoformat()
                size = entry.size

                if path not in db_files or mod_time != db_files[path][0] or size != db_files[path][1]:
                    link = None
                    try:
                        link = dbx.sharing_create_shared_link(path).url
                    except Exception as e:
                        print(f"\nFailed to create link for {name}: {e}")

                    content = ""
                    ext = os.path.splitext(name)[1].lower()
                    if ext in full_index_types:
                        temp_dir = tempfile.gettempdir()
                        safe_name = "".join(c if c.isalnum() or c in ['.', '_'] else '_' for c in name)
                        temp_path = os.path.join(temp_dir, safe_name)
                        dbx.files_download_to_file(temp_path, entry.path_lower)
                        try:
                            if ext == ".pdf":
                                content = extract_text_from_pdf(temp_path)
                            elif ext == ".docx":
                                content = extract_text_from_docx(temp_path)
                            elif ext == ".txt":
                                content = extract_text_from_txt(temp_path)
                            elif ext in (".xlsx", ".xls"):
                                content = extract_text_from_excel(temp_path)
                        except Exception as e:
                            print(f"\nFailed to extract content from {name}: {e}")
                            unreadable_files.append((name, path))
                        finally:
                            try:
                                os.remove(temp_path)
                            except Exception as e:
                                print(f"\nFailed to delete temp file {temp_path}: {e}")

                    c.execute("""
                        INSERT OR REPLACE INTO dropbox_files (name, path, link, modified_time, size)
                        VALUES (?, ?, ?, ?, ?)
                    """, (name, path, link, mod_time, size))
                    c.execute("DELETE FROM dropbox_index WHERE name = ?", (name,))
                    c.execute("INSERT INTO dropbox_index (name, content) VALUES (?, ?)", (name, content))
                    added_or_updated += 1

                if processed_files % 10 == 0:
                    callback()
                    # Save periodically and refresh token if needed
                    elapsed = time.time() - start_time
                    if elapsed > 7200:  # 2 hours, halfway to expiry
                        conn.commit()
                        if unreadable_files:
                            df = pd.DataFrame(unreadable_files, columns=["File Name", "Path"])
                            csv_path = "F:/unreadable_files.csv"
                            df.to_csv(csv_path, index=False)
                            print(f"Saved {len(unreadable_files)} unreadable files to {csv_path} at {processed_files} files")
                        dbx = get_dropbox_client()  # Refresh token
                        start_time = time.time()  # Reset timer
            c.execute("INSERT OR REPLACE INTO index_metadata (key, value) VALUES ('last_cursor', ?)", (result.cursor,))
            conn.commit()

            if result.has_more:
                result = dbx.files_list_folder_continue(result.cursor)
            else:
                break

        callback()
        print(f"\nDone! Checked {processed_files} files, added/updated {added_or_updated}.")
        if unreadable_files:
            df = pd.DataFrame(unreadable_files, columns=["File Name", "Path"])
            csv_path = "F:/unreadable_files.csv"
            df.to_csv(csv_path, index=False)
            print(f"Saved {len(unreadable_files)} unreadable files to {csv_path}")
        c.execute("INSERT OR REPLACE INTO index_metadata (key, value) VALUES ('last_index_time', ?)",
                  (datetime.now().isoformat(),))
        conn.commit()
        return added_or_updated
    except Exception as e:
        print(f"\nError: {e}")
        callback()
        if unreadable_files:
            df = pd.DataFrame(unreadable_files, columns=["File Name", "Path"])
            csv_path = "F:/unreadable_files.csv"
            df.to_csv(csv_path, index=False)
            print(f"Saved {len(unreadable_files)} unreadable files to {csv_path}")
        conn.commit()
        return added_or_updated
    finally:
        conn.close()

def should_auto_index(db_path="F:/naviSsurance_index.db", weeks=2):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT value FROM index_metadata WHERE key = 'last_index_time'")
    result = c.fetchone()
    conn.close()
    if not result:
        return True
    last_dt = datetime.fromisoformat(result[0])
    return datetime.now() - last_dt > timedelta(weeks=weeks)

# Trigger 1: Auto-check on app launch
def auto_index_on_launch(dbx, db_path="F:/naviSsurance_index.db"):
    if should_auto_index(db_path):
        print("Indexing Dropbox—more than 2 weeks since last run.")
        return index_dropbox(dbx, db_path)
    else:
        print("Dropbox index up-to-date (less than 2 weeks old).")
        return 0

# Trigger 2: Button press (for future UI)
def manual_index(dbx, db_path="F:/naviSsurance_index.db"):
    print("Manual Dropbox index update triggered.")
    return index_dropbox(dbx, db_path)

# Trigger 3: Chat command (for local AI detection)
def chat_index(dbx, db_path="F:/naviSsurance_index.db"):
    """Called by local AI when 'index Dropbox' intent is detected."""
    updated_count = index_dropbox(dbx, db_path)
    return f"ADD_TASK:Confirm Dropbox index updated with {updated_count} files|{datetime.now().strftime('%m-%d-%Y')}"

def log_unreadable_pdfs(db_path="F:/naviSsurance_index.db", csv_path="F:/unreadable_files.csv"):
    import time
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    start = time.time()
    try:
        existing = pd.read_csv(csv_path).values.tolist()
    except FileNotFoundError:
        existing = []
    print(f"CSV load: {time.time() - start:.2f}s")
    
    start = time.time()
    c.execute("SELECT COUNT(*) FROM dropbox_files WHERE lower(name) LIKE '%.pdf'")
    total_pdfs = c.fetchone()[0]
    print(f"Total PDFs in dropbox_files: {total_pdfs}")
    print(f"Count query: {time.time() - start:.2f}s")
    
    start = time.time()
    c.execute("SELECT lower(name) FROM dropbox_index WHERE content != '' AND lower(name) LIKE '%.pdf'")
    readable_pdfs = set(row[0] for row in c.fetchall())
    print(f"Readable PDFs: {len(readable_pdfs)}")
    print(f"Readable PDFs query: {time.time() - start:.2f}s")
    
    start = time.time()
    c.execute("SELECT name, path FROM dropbox_files WHERE lower(name) LIKE '%.pdf'")
    all_pdfs = c.fetchall()
    unreadable_pdfs = [(name, path) for name, path in all_pdfs if name.lower() not in readable_pdfs]
    print(f"Unreadable PDFs: {len(unreadable_pdfs)}")
    print(f"Main query and filter: {time.time() - start:.2f}s")
    
    all_unreadable = existing[:45] + unreadable_pdfs
    if unreadable_pdfs:
        print(f"Found {len(unreadable_pdfs)} unreadable PDFs in DB")
    if all_unreadable:
        start = time.time()
        df = pd.DataFrame(all_unreadable, columns=["File Name", "Path"])
        df.to_csv(csv_path, index=False)
        print(f"CSV write: {time.time() - start:.2f}s")
        print(f"Updated {csv_path} with {len(all_unreadable)} unreadable files")
    conn.close()

if __name__ == "__main__":
    dbx = get_dropbox_client()
    count_dropbox_files(dbx)
    index_dropbox(dbx)
    log_unreadable_pdfs()  # Add this