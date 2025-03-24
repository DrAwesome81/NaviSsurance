import sys
sys.path.append(r'C:\Users\adamo\Dropbox\_Consulting\NaviSsurance')
import fitz
import pytesseract
from PIL import Image
import os
import time
import tempfile
from dropbox import Dropbox
from dropbox import files
from core.api import get_dropbox_client
from concurrent.futures import ThreadPoolExecutor, as_completed

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
PROCESSED_LOG = r'C:\Users\adamo\Dropbox\_Consulting\NaviSsurance\processed_files.txt'

def ocr_page(page):
    pix = page.get_pixmap(dpi=300)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    return pytesseract.image_to_string(img).strip() or " [Image-only page] "

def convert_pdf(pdf_path, output_path):
    print(f"Converting {pdf_path}")
    try:
        document = fitz.open(pdf_path)
        print(f"Opened PDF with {len(document)} pages")
        new_doc = fitz.open()
        text_extracted = False
        
        for page_num in range(len(document)):
            page = document.load_page(page_num)
            page_text = page.get_text().strip()
            print(f"Page {page_num}: Text extracted - '{page_text[:50]}'...")
            if page_text:
                text_extracted = True
                new_page = new_doc.new_page()
                new_page.insert_text((72, 72), page_text)
            else:
                ocr_text = ocr_page(page)
                if ocr_text and ocr_text != " [Image-only page] ":
                    text_extracted = True
                new_page = new_doc.new_page()
                new_page.insert_text((72, 72), ocr_text)
        
        document.close()
        if text_extracted:
            new_doc.save(output_path)
            print(f"Saved converted PDF to {output_path}")
            new_doc.close()
            return True
        new_doc.close()
        print("No text extracted from any page")
        return False
    except Exception as e:
        print(f"Conversion failed for {pdf_path}: {e}")
        return False

def process_dropbox_pdfs():
    print("Starting process_dropbox_pdfs")
    dbx = get_dropbox_client()
    print("Dropbox client initialized")
    temp_dir = tempfile.gettempdir()
    unreadable_pdfs = []
    archive_folder = "/Archive"
    
    try:
        dbx.files_get_metadata(archive_folder)
        print(f"Cloud folder {archive_folder} exists")
    except:
        try:
            dbx.files_create_folder_v2(archive_folder)
            print(f"Created cloud folder {archive_folder}")
        except Exception as e:
            print(f"Failed to create {archive_folder} in cloud: {e}")
            return
    
    processed_files = set()
    if os.path.exists(PROCESSED_LOG):
        with open(PROCESSED_LOG, 'r') as f:
            processed_files = set(line.strip() for line in f if line.strip())
    print(f"Loaded {len(processed_files)} previously processed files")
    
    print("Fetching PDF list from cloud...")
    result = dbx.files_list_folder("", recursive=True)
    pdf_files = []
    while True:
        for entry in result.entries:
            if isinstance(entry, files.FileMetadata) and entry.name.lower().endswith('.pdf'):
                pdf_files.append((entry.name, entry.path_lower))
        if result.has_more:
            result = dbx.files_list_folder_continue(result.cursor)
        else:
            break
    
    print(f"Total PDFs found: {len(pdf_files)}")
    to_process = [(name, path) for name, path in pdf_files if path not in processed_files]
    print(f"Processing {len(to_process)} new PDFs")
    
    def process_one(name, path):
        archive_path = f"/Archive{path}"
        temp_path = os.path.join(temp_dir, name.replace('/', '_'))
        output_path = os.path.join(temp_dir, f"converted_{name}")
        
        start_time = time.time()
        print(f"Downloading {name} from {path} to {temp_path}")
        dbx.files_download_to_file(temp_path, path)
        print(f"Download took {time.time() - start_time:.2f}s")
        if os.path.exists(temp_path):
            start_time = time.time()
            if convert_pdf(temp_path, output_path):
                print(f"Conversion took {time.time() - start_time:.2f}s")
                if os.path.exists(output_path):
                    start_time = time.time()
                    print(f"Moving {path} to {archive_path} in cloud")
                    try:
                        orig_metadata = dbx.files_get_metadata(path)
                        print(f"Before move - Original at {path} - Size: {orig_metadata.size} bytes")
                        try:
                            metadata = dbx.files_get_metadata(archive_path)
                            if isinstance(metadata, files.FileMetadata):
                                dbx.files_delete_v2(archive_path)
                                print(f"Deleted existing file at {archive_path}")
                        except:
                            pass
                        move_result = dbx.files_move_v2(path, archive_path)
                        move_time = time.time() - start_time
                        print(f"Move took {move_time:.2f}s")
                        print(f"Move response: {move_result.metadata.path_display} - Size: {move_result.metadata.size} bytes")
                        arch_metadata = dbx.files_get_metadata(archive_path)
                        print(f"Move verified for {name} to {archive_path} - Size: {arch_metadata.size} bytes")
                        try:
                            dbx.files_get_metadata(path)
                            print(f"ERROR: Original still exists at {path}")
                        except:
                            print(f"Original confirmed removed from {path}")
                    except Exception as move_e:
                        print(f"Move failed for {name}: {move_e}")
                        return (name, path)
                    start_time = time.time()
                    print(f"Uploading {output_path} to {path} in cloud")
                    with open(output_path, 'rb') as f:
                        upload_result = dbx.files_upload(f.read(), path, mode=files.WriteMode('overwrite'))
                    upload_time = time.time() - start_time
                    print(f"Upload took {upload_time:.2f}s")
                    print(f"Upload response: {upload_result.path_display} - Size: {upload_result.size} bytes")
                    upload_metadata = dbx.files_get_metadata(path)
                    print(f"Upload verified for {name} to {path} - Size: {upload_metadata.size} bytes")
                    with open(PROCESSED_LOG, 'a') as f:
                        f.write(f"{path}\n")
                else:
                    print(f"Conversion failed to create {output_path}")
                    return (name, path)
            else:
                print(f"No text extracted for {name}")
                try:
                    move_result = dbx.files_move_v2(path, archive_path)
                    arch_metadata = dbx.files_get_metadata(archive_path)
                    print(f"Move verified for unreadable {name} to {archive_path} - Size: {arch_metadata.size} bytes")
                except Exception as move_e:
                    print(f"Move failed for unreadable {name}: {move_e}")
                return (name, archive_path)
        else:
            print(f"Download failed for {name}")
            return (name, path)
        return None
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(process_one, name, path) for name, path in to_process]
        for future in as_completed(futures):
            result = future.result()
            if result:
                unreadable_pdfs.append(result)
            # Cleanup handled in process_one
    
    if unreadable_pdfs:
        import pandas as pd
        df = pd.DataFrame(unreadable_pdfs, columns=["File Name", "Path"])
        df.to_csv("F:/converted_unreadable_files.csv", index=False)
        print(f"Saved {len(unreadable_pdfs)} unreadable PDFs to F:/converted_unreadable_files.csv")

if __name__ == "__main__":
    start_time = time.time()
    print("Script started")
    process_dropbox_pdfs()
    print(f"Total time: {time.time() - start_time:.2f}s")