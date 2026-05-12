import logging
from typing import List, Dict, Any, Optional

from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain.retrievers import ContextualCompressionRetriever
from langchain.retrievers.document_compressors import CrossEncoderReranker
from langchain_community.cross_encoders import HuggingFaceCrossEncoder

logger = logging.getLogger(__name__)

class RAGRetriever:
    """
    Flexible RAG retriever for NaviSsurance.
    - Works even if index is empty/partial (no crash).
    - Heading-aware splitting tuned for regulatory PDFs/SOPs.
    - Includes reranking for fewer false positives.
    - Easy to call from agents or Workspace.
    """

    def __init__(self, chroma_path: str = "chroma_index"):
        self.chroma_path = chroma_path
        self.embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-large-en-v1.5")
        
        # Prepare splitter optimized for structured regulatory docs
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=800,
            chunk_overlap=150,
            separators=["\n\n## ", "\n\n### ", "\n\n#### ", "\n\n", "\n", ". ", " ", ""],
        )

        try:
            self.vectorstore = Chroma(
                persist_directory=chroma_path,
                embedding_function=self.embeddings
            )
            # Reranker for better precision on technical content
            reranker = HuggingFaceCrossEncoder(model_name="BAAI/bge-reranker-large")
            compressor = CrossEncoderReranker(model=reranker, top_n=6)
            self.retriever = ContextualCompressionRetriever(
                base_compressor=compressor,
                base_retriever=self.vectorstore.as_retriever(search_kwargs={"k": 15})
            )
            logger.info("RAG retriever with reranking initialized")
        except Exception as e:
            logger.warning(f"Could not load Chroma index (normal if not yet built): {e}")
            self.vectorstore = None
            self.retriever = None

    def is_ready(self) -> bool:
        """Check if index exists and has documents."""
        if self.vectorstore is None:
            return False
        try:
            count = self.vectorstore._collection.count()
            return count > 0
        except Exception:
            return False

    def retrieve(self, query: str, k: int = 6, filters: Optional[Dict] = None) -> List[Any]:
        """Retrieve relevant chunks. Returns empty list gracefully if index not ready."""
        if not self.is_ready() or self.retriever is None:
            logger.warning(f"RAG not ready for query: {query[:80]}...")
            return []
        
        try:
            search_kwargs = {"k": 15}
            if filters:
                search_kwargs["filter"] = filters
            docs = self.retriever.get_relevant_documents(query, **search_kwargs)
            return docs[:k]
        except Exception as e:
            logger.error(f"RAG retrieval failed for '{query[:100]}...': {e}")
            return []

    def get_context_string(self, query: str, k: int = 6) -> str:
        """Return formatted context ready to inject into prompts."""
        docs = self.retrieve(query, k=k)
        if not docs:
            return "[No relevant documents found in current index. Consider re-indexing after organizing files.]"
        
        parts = []
        for i, doc in enumerate(docs, 1):
            source = doc.metadata.get("source", "unknown").split("/")[-1]
            page = doc.metadata.get("page_number", "")
            page_info = f" (p.{page})" if page else ""
            parts.append(f"--- [{i}] {source}{page_info} ---\n{doc.page_content.strip()}\n")
        
        return "\n".join(parts)

# Singleton for easy import across the app
rag_retriever = RAGRetriever()