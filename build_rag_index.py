import os
import json
import hashlib
import shutil
import logging
from tqdm import tqdm
from langchain_community.document_loaders import DirectoryLoader, PyPDFLoader, Docx2txtLoader, TextLoader
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.document_loaders import GoogleDriveLoader, DropboxLoader
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(filename='indexing.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Load credentials from rag_config.json
try:
    with open("rag_config.json", "r") as f:
        config = json.load(f)
except Exception as e:
    logging.error(f"Failed to load rag_config.json: {e}")
    raise

# Paths and credentials (leave paths blank for testing)
LOCAL_PATH = config.get("local_path", "")
DROPBOX_PATH = config.get("dropbox_path", "")
GDRIVE1_FOLDER_ID = config.get("gdrive1_folder_id", "")
GDRIVE2_FOLDER_ID = config.get("gdrive2_folder_id", "")
DROPBOX_TOKEN = config.get("dropbox_access_token", "")
GDRIVE1_CREDENTIALS = config.get("gdrive1_credentials_file", "")
GDRIVE2_CREDENTIALS = config.get("gdrive2_credentials_file", "")

# Initialize embedding model
try:
    embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-large-en-v1.5")
    logging.info("Embedding model initialized")
except Exception as e:
    logging.error(f"Failed to initialize embeddings: {e}")
    raise

# Chroma database
CHROMA_PATH = "chroma_index"
BATCH_SIZE = 5000  # Chroma batch limit workaround

def hash_content(content, source, page_number=None):
    """Generate MD5 hash for document content, source, and page number."""
    try:
        hasher = hashlib.md5()
        content_str = f"{content}{source}{page_number or ''}".encode("utf-8")
        hasher.update(content_str)
        return hasher.hexdigest()
    except Exception as e:
        logging.error(f"Error hashing content for {source} (page {page_number or 'N/A'}): {e}")
        return None

def load_local_files(path):
    """Load and hash local files, splitting PDFs by page."""
    if not path or not os.path.exists(path):
        logging.warning(f"Path {path} is empty or does not exist")
        return []
    documents = []
    
    # Handle PDFs separately - use PyPDFLoader with page mode to get individual pages
    import glob
    pdf_files = glob.glob(os.path.join(path, "**/*.[pP][dD][fF]"), recursive=True)
    for pdf_file in tqdm(pdf_files, desc="Processing PDF files"):
        try:
            # Use PyPDFLoader with mode="page" to get individual pages
            loader = PyPDFLoader(pdf_file)
            page_docs = loader.load()  # This loads each page as a separate document
            for i, page_doc in enumerate(page_docs):
                page_number = i + 1
                file_hash = hash_content(page_doc.page_content, pdf_file, page_number)
                if file_hash:
                    page_doc.metadata["file_hash"] = file_hash
                    page_doc.metadata["page_number"] = page_number
                    logging.info(f"Loaded local PDF page: {pdf_file} (page {page_number}) - Hash: {file_hash}")
                    documents.append(page_doc)
                else:
                    logging.warning(f"Skipping invalid local PDF page: {pdf_file} (page {page_number})")
        except Exception as e:
            logging.error(f"Error processing PDF {pdf_file}: {e}")
    
    # Handle non-PDF files
    for loader_class, glob_pattern in [(Docx2txtLoader, "**/*.[dD][oO][cC][xX]"), 
                                    (TextLoader, "**/*.[tT][xX][tT]")]:
        try:
            loader = DirectoryLoader(path, glob=glob_pattern, loader_cls=loader_class, show_progress=True)
            docs = loader.load()
            for doc in tqdm(docs, desc=f"Processing {loader_class.__name__} files"):
                source = doc.metadata["source"]
                file_hash = hash_content(doc.page_content, source)
                if file_hash:
                    doc.metadata["file_hash"] = file_hash
                    # Add consistent metadata for non-PDFs
                    doc.metadata["page_number"] = None
                    logging.info(f"Loaded local file: {source} - Hash: {file_hash}")
                    documents.append(doc)
                else:
                    logging.warning(f"Skipping invalid local file: {source}")
        except Exception as e:
            logging.error(f"Error loading files with {loader_class.__name__}: {e}")
    return documents

def load_dropbox_files(path, token):
    """Load and hash Dropbox files."""
    if not path or not token:
        logging.warning(f"Dropbox path or token missing: {path}, {token}")
        return []
    try:
        loader = DropboxLoader(dropbox_access_token=token, folder_path=path)
        docs = loader.load()
        documents = []
        for doc in tqdm(docs, desc="Processing Dropbox files"):
            source = doc.metadata["source"]
            file_hash = hash_content(doc.page_content, source)
            if file_hash:
                doc.metadata["file_hash"] = file_hash
                logging.info(f"Loaded Dropbox file: {source} - Hash: {file_hash}")
                documents.append(doc)
            else:
                logging.warning(f"Skipping invalid Dropbox file: {source}")
        return documents
    except Exception as e:
        logging.error(f"Error loading Dropbox files: {e}")
        return []

def load_gdrive_files(folder_id, credentials_file):
    """Load and hash Google Drive files."""
    if not folder_id or not credentials_file:
        logging.warning(f"Google Drive folder ID or credentials missing: {folder_id}, {credentials_file}")
        return []
    try:
        loader = GoogleDriveLoader(folder_id=folder_id, credentials_path=credentials_file, file_types=["document", "pdf"])
        docs = loader.load()
        documents = []
        for doc in tqdm(docs, desc="Processing Google Drive files"):
            source = doc.metadata["source"]
            file_hash = hash_content(doc.page_content, source)
            if file_hash:
                doc.metadata["file_hash"] = file_hash
                logging.info(f"Loaded Google Drive file: {source} - Hash: {file_hash}")
                documents.append(doc)
            else:
                logging.warning(f"Skipping invalid Google Drive file: {source}")
        return documents
    except Exception as e:
        logging.error(f"Error loading Google Drive files: {e}")
        return []

def main():
    # Clear existing Chroma index
    if os.path.exists(CHROMA_PATH):
        shutil.rmtree(CHROMA_PATH)
        logging.info(f"Cleared existing index at {CHROMA_PATH}")

    # Load all documents
    documents = []
    documents.extend(load_local_files(LOCAL_PATH))
    documents.extend(load_dropbox_files(DROPBOX_PATH, DROPBOX_TOKEN))
    documents.extend(load_gdrive_files(GDRIVE1_FOLDER_ID, GDRIVE1_CREDENTIALS))
    documents.extend(load_gdrive_files(GDRIVE2_FOLDER_ID, GDRIVE2_CREDENTIALS))

    # Deduplicate by hash
    seen_hashes = set()
    unique_docs = []
    for doc in tqdm(documents, desc="Deduplicating documents"):
        file_hash = doc.metadata.get("file_hash")
        if file_hash:
            if file_hash not in seen_hashes:
                seen_hashes.add(file_hash)
                unique_docs.append(doc)
                logging.info(f"Added file to index: {doc.metadata.get('source', 'unknown')} - Hash: {file_hash}")
            else:
                logging.warning(f"Skipping duplicate file: {doc.metadata.get('source', 'unknown')} - Hash: {file_hash}")
        else:
            logging.warning(f"Skipping invalid file: {doc.metadata.get('source', 'unknown')}")

    # Create Chroma index in batches
    if unique_docs:
        try:
            for i in tqdm(range(0, len(unique_docs), BATCH_SIZE), desc="Indexing batches"):
                batch = unique_docs[i:i + BATCH_SIZE]
                Chroma.from_documents(batch, embeddings, persist_directory=CHROMA_PATH)
                logging.info(f"Indexed batch {i//BATCH_SIZE + 1} with {len(batch)} documents")
            print(f"Indexed {len(unique_docs)} documents to {CHROMA_PATH}")
        except Exception as e:
            logging.error(f"Error creating Chroma index: {e}")
            raise
    else:
        logging.warning("No valid documents indexed; check paths or file types in rag_config.json")
        print("No valid documents indexed; check paths or file types in rag_config.json")

if __name__ == "__main__":
    load_dotenv()
    main()