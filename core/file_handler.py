import fitz
from docx import Document
from dropbox import Dropbox, files
import logging
from requests import Timeout
import tempfile
import os

def extract_text_from_pdf(pdf_path):
    document = fitz.open(pdf_path)
    text = ""
    for page_num in range(min(3, len(document))):
        page = document.load_page(page_num)
        text += page.get_text()
    document.close()
    return text[:1000]

def extract_text_from_docx(docx_path):
    doc = Document(docx_path)
    full_text = [para.text for para in doc.paragraphs]
    return '\n'.join(full_text)[:1000]

def extract_text_from_txt(txt_path):
    with open(txt_path, 'r', encoding='utf-8') as file:
        return file.read()[:1000]

def search_dropbox(self, query, folder_path=""):
    dbx = self
    print(f"Smart searching Dropbox for: {query}")
    try:
        result = dbx.files_list_folder(folder_path)
        files_data = []
        supported_types = {'.pdf', '.txt', '.docx', '.xlsx', '.xls'}
        for entry in result.entries:
            if isinstance(entry, files.FileMetadata) and os.path.splitext(entry.name)[1].lower() in supported_types:
                temp_dir = tempfile.gettempdir()
                safe_name = "".join(c if c.isalnum() or c in ['.', '_'] else '_' for c in entry.name)
                temp_path = os.path.join(temp_dir, safe_name)
                print(f"Downloading {entry.name} to {temp_path}")
                dbx.files_download_to_file(temp_path, entry.path_lower)
                if entry.name.endswith(".pdf"):
                    content = extract_text_from_pdf(temp_path)
                elif entry.name.endswith(".docx"):
                    content = extract_text_from_docx(temp_path)
                elif entry.name.endswith(".txt"):
                    content = extract_text_from_txt(temp_path)
                elif entry.name.endswith((".xlsx", ".xls")):
                    content = "(Excel file - content extraction not supported yet)"
                else:
                    content = ""  # Shouldn’t hit this with filter
                shared_link = None
                try:
                    shared_link = dbx.sharing_create_shared_link(entry.path_lower).url
                except Exception as e:
                    print(f"Failed to create link for {entry.name}: {e}")
                files_data.append({
                    "name": entry.name,
                    "path": entry.path_display,
                    "content": content,
                    "link": shared_link
                })
                try:
                    os.remove(temp_path)
                except Exception as e:
                    print(f"Failed to delete temp file {temp_path}: {e}")
        print(f"Extracted content from {len(files_data)} files")
        return files_data
    except Exception as e:
        print(f"Dropbox search error: {e}")
        return []