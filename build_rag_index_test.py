import os
import json
import hashlib
import shutil
from langchain_community.document_loaders import DirectoryLoader, PyPDFLoader
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

# Test path (small folder with ~10 PDFs)
TEST_PATH = "C:/Users/adamo/Dropbox/_Consulting/NaviSsurance/test_folder/"

# Chroma database
CHROMA_PATH = "chroma_index_test"

def hash_file(file_path):
    """Generate MD5 hash for file content."""
    try:
        hasher = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception as e:
        print(f"Error hashing {file_path}: {e}")
        return None

def load_test_files(path):
    """Load and hash test files, skipping invalid ones."""
    if not path or not os.path.exists(path):
        print(f"Path {path} is empty or does not exist")
        return []
    documents = []
    loader = DirectoryLoader(path, glob="**/*.[pP][dD][fF]", loader_cls=PyPDFLoader, show_progress=True)
    try:
        docs = loader.load()
        for doc in docs:
            file_hash = hash_file(doc.metadata["source"])
            if file_hash:
                doc.metadata["file_hash"] = file_hash
                print(f"Loaded file: {doc.metadata['source']} - Hash: {file_hash}")
                documents.append(doc)
            else:
                print(f"Skipping invalid file: {doc.metadata['source']}")
    except Exception as e:
        print(f"Error loading files: {e}")
    return documents

def main():
    # Clear existing Chroma index
    if os.path.exists(CHROMA_PATH):
        shutil.rmtree(CHROMA_PATH)
        print(f"Cleared existing index at {CHROMA_PATH}")

    # Initialize embedding model
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")

    # Load test documents
    documents = load_test_files(TEST_PATH)

    # Deduplicate by hash
    seen_hashes = set()
    unique_docs = []
    for doc in documents:
        file_hash = doc.metadata.get("file_hash")
        if file_hash:
            if file_hash not in seen_hashes:
                seen_hashes.add(file_hash)
                unique_docs.append(doc)
                print(f"Added file to index: {doc.metadata['source']} - Hash: {file_hash}")
            else:
                print(f"Skipping duplicate file: {doc.metadata['source']} - Hash: {file_hash}")
        else:
            print(f"Skipping invalid file: {doc.metadata['source']}")

    # Create Chroma index
    if unique_docs:
        Chroma.from_documents(unique_docs, embeddings, persist_directory=CHROMA_PATH)
        print(f"Indexed {len(unique_docs)} documents to {CHROMA_PATH}")
    else:
        print("No valid documents indexed; check test folder for PDFs")

if __name__ == "__main__":
    main()