import os
import json
import hashlib
import shutil
import logging
from tqdm import tqdm
from datetime import datetime

from langchain_community.document_loaders import DirectoryLoader, PyPDFLoader, Docx2txtLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

from dotenv import load_dotenv

logger = logging.getLogger(__name__)
# RAG index build powers retrieval for Pulse private memory regulatory themes, Intel, and 🛡️ Shield compliance docs (RAG-intel coordination)
# Pulse private memory + Shield (build rag index surface)

# Load config
try:
    with open("rag_config.json", "r", encoding="utf-8") as f:
        config = json.load(f)
except Exception as e:
    logger.error(f"Failed to load rag_config.json: {e}")
    raise

LOCAL_PATH = config.get("local_path", "")

embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-large-en-v1.5")

CHROMA_PATH = "chroma_index"

# Better splitter for regulatory documents
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=800,
    chunk_overlap=150,
    separators=["\n\n## ", "\n\n### ", "\n\n#### ", "\n\n", "\n", ". ", " ", ""],
)

def hash_content(content: str, source: str, page: int | None = None) -> str:
    hasher = hashlib.md5()
    hasher.update(f"{source}{page or ''}".encode())
    hasher.update(content.encode())
    return hasher.hexdigest()

def main():
    if os.path.exists(CHROMA_PATH):
        shutil.rmtree(CHROMA_PATH)
        print(f"Cleared old index at {CHROMA_PATH}")

    documents = []

    # Load local files (your main folder when ready)
    if LOCAL_PATH and os.path.exists(LOCAL_PATH):
        # PDFs - page by page
        import glob
        pdf_files = glob.glob(os.path.join(LOCAL_PATH, "**/*.[pP][dD][fF]"), recursive=True)
        for pdf_file in tqdm(pdf_files, desc="Processing PDFs"):
            try:
                loader = PyPDFLoader(pdf_file)
                pages = loader.load()
                for i, page in enumerate(pages):
                    chunks = text_splitter.split_documents([page])
                    for chunk in chunks:
                        chunk.metadata["source"] = pdf_file
                        chunk.metadata["page_number"] = i + 1
                        chunk.metadata["file_hash"] = hash_content(chunk.page_content, pdf_file, i+1)
                        documents.append(chunk)
            except Exception as e:
                logger.error(f"Error with PDF {pdf_file}: {e}")

        # Other files
        for loader_cls, pattern in [(Docx2txtLoader, "**/*.[dD][oO][cC][xX]"), (TextLoader, "**/*.[tT][xX][tT]")]:
            try:
                loader = DirectoryLoader(LOCAL_PATH, glob=pattern, loader_cls=loader_cls, show_progress=True)
                docs = loader.load()
                for doc in docs:
                    chunks = text_splitter.split_documents([doc])
                    for chunk in chunks:
                        chunk.metadata["file_hash"] = hash_content(chunk.page_content, doc.metadata["source"])
                        documents.append(chunk)
            except Exception as e:
                logger.error(f"Error loading {pattern}: {e}")

    # Create index
    if documents:
        vectorstore = Chroma.from_documents(documents, embeddings, persist_directory=CHROMA_PATH)
        print(f"✅ Indexed {len(documents)} chunks successfully.")
    else:
        print("No documents found. Set local_path in rag_config.json when ready.")

if __name__ == "__main__":
    from config import CONFIG_DIR
    load_dotenv(os.path.join(CONFIG_DIR, ".env"))
    main()