import fitz
import sqlite3
from docx import Document
from dropbox import Dropbox, files
import logging
from requests import Timeout
import tempfile
import os
import pytesseract
from PIL import Image

def extract_text_from_pdf(pdf_path):
    document = fitz.open(pdf_path)
    text = ""
    print(f"Extracting text from {pdf_path}: len(text) = {len(text)}")
    for page_num in range(len(document)):
        page = document.load_page(page_num)
        page_text = page.get_text()
        if page_text.strip():  # If text layer exists
            text += page_text
        else:  # Fallback to OCR
            pix = page.get_pixmap()
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            text += pytesseract.image_to_string(img)
    document.close()
    return text

def extract_text_from_docx(docx_path):
    doc = Document(docx_path)
    full_text = [para.text for para in doc.paragraphs]
    return '\n'.join(full_text)

def extract_text_from_txt(txt_path):
    with open(txt_path, 'r', encoding='utf-8') as file:
        return file.read()

def search_dropbox_index(db_manager, query):
    """Search indexed Dropbox files using FTS5."""
    try:
        with sqlite3.connect(db_manager.db_name) as conn:
            cursor = conn.execute("""
                SELECT f.name, f.path, f.link, i.content
                FROM dropbox_index i
                JOIN dropbox_files f ON i.name = f.name
                WHERE dropbox_index MATCH ?
                ORDER BY rank
            """, (query,))
            results = [
                {"name": row[0], "path": row[1], "link": row[2], "content": row[3]}
                for row in cursor.fetchall()
            ]
            print(f"Found {len(results)} matches for '{query}' in index.")
            return results
    except Exception as e:
        print(f"Search error: {e}")
        return []
    
def extract_for_dataset(file_path, prompt_template="Generate draft from this:"):
    text = extract_text_from_file(file_path)  # Use your existing extract functions
    return {"prompt": f"{prompt_template} {text}", "completion": ""}  # Completion can be filled later (e.g., manual/AI drafts)

def extract_text_from_file(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.pdf':
        return extract_text_from_pdf(file_path)
    elif ext == '.docx':
        return extract_text_from_docx(file_path)
    elif ext == '.txt':
        return extract_text_from_txt(file_path)
    return ""  # Fallback for unsupported types