import os
import sqlite3
import fitz
from docx import Document
from dropbox import Dropbox, files
from core.api import get_dropbox_client
import tempfile
import sys
import pickle

def extract_text_from_pdf(pdf_path):
    try:
        document = fitz.open(pdf_path)
        text = ""
        for page_num in range(len(document)):
            page = document.load_page(page_num)
            text += page.get_text()
        document.close()
        return text
    except Exception as e:
        print(f"\nPDF extraction failed for {pdf_path}: {e}")
        return ""

def extract_text_from_docx(docx_path):
    doc = Document(docx_path)
    full_text = [para.text for para in doc.paragraphs]
    return '\n'.join(full_text)

def extract_text_from_txt(txt_path):
    with open(txt_path, 'r', encoding='utf-8') as file:
        return file.read()

def extract_text_from_excel(excel_path):
    return "(Excel file - content extraction not supported yet)"

def save_cursor(cursor, cursor_file="F:/dropbox_index_cursor.pkl"):
    with open(cursor_file, 'wb') as f:
        pickle.dump(cursor, f)

def load_cursor(cursor_file="F:/dropbox_index_cursor.pkl"):
    try:
        with open(cursor_file, 'rb') as f:
            return pickle.load(f)
    except FileNotFoundError:
        return None

def index_dropbox_files(dbx, db_path="F:/navisurance_index.db"):
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS dropbox_files (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, path TEXT UNIQUE NOT NULL, link TEXT)")
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS dropbox_index USING fts5 (name, content, tokenize='porter')")
    conn.commit()

    full_index_types = {'.pdf', '.txt', '.docx', '.xlsx', '.xls'}
    processed_files = 0
    cursor_file = "F:/dropbox_index_cursor.pkl"

    # Load last cursor if exists
    last_cursor = load_cursor(cursor_file)
    if last_cursor:
        print(f"Resuming from last cursor: {last_cursor[:20]}...")
    else:
        print("Starting fresh—hold tight, Dr. Odeh!")

    try:
        # Start or resume
        if last_cursor:
            result = dbx.files_list_folder_continue(last_cursor)
        else:
            result = dbx.files_list_folder("", recursive=True)

        while True:
            for entry in result.entries:
                if not isinstance(entry, files.FileMetadata):
                    continue
                processed_files += 1
                print(f"Processed {processed_files} files - {entry.name}", end="\r")
                sys.stdout.flush()

                name = entry.name
                path = entry.path_display
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
                    finally:
                        try:
                            os.remove(temp_path)
                        except Exception as e:
                            print(f"\nFailed to delete temp file {temp_path}: {e}")

                conn.execute("INSERT OR IGNORE INTO dropbox_files (name, path, link) VALUES (?, ?, ?)", (name, path, link))
                conn.execute("INSERT INTO dropbox_index (name, content) VALUES (?, ?)", (name, content))

            # Commit periodically to save progress
            conn.commit()
            if result.has_more:
                save_cursor(result.cursor, cursor_file)
                result = dbx.files_list_folder_continue(result.cursor)
            else:
                os.remove(cursor_file) if os.path.exists(cursor_file) else None
                break

        print(f"\nDone! Indexed {processed_files} files total.")
    except Exception as e:
        print(f"\nIndexing paused: {e}")
        print(f"Processed {processed_files} files so far. Rerun to continue.")
        conn.commit()  # Save what we’ve got
    finally:
        conn.close()

if __name__ == "__main__":
    dbx = get_dropbox_client()
    index_dropbox_files(dbx)