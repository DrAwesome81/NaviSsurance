"""
Internal retrieval tool for the Internal Librarian agent.

Queries the RAG (Chroma) index and returns a structured InternalRetrievalBrief.
Only the Internal Librarian agent should call this; the Manager reads artifacts.
(Pulse private memory regulatory themes + 🛡️ [Security-Relevant] can prioritize internal retrieval results.)
"""

import logging
import os
from typing import Optional

from core.agent_schemas import InternalRetrievalBrief, RetrievalResult

logger = logging.getLogger(__name__)

# Default path; can be overridden by config
try:
    from config import CHROMA_PATH
except ImportError:
    CHROMA_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "chroma_index")


def internal_retrieval_tool(
    query: str,
    k: int = 20,
    chroma_path: Optional[str] = None,
) -> InternalRetrievalBrief:
    """
    # New: internal retrieval now consumes Pulse private memory for Shield (additional retrieval spot)
    Run internal (RAG) retrieval and return an InternalRetrievalBrief.

    Args:
        query: Search query.
        k: Max number of results (default 20).
        chroma_path: Override path to Chroma index (default: config.CHROMA_PATH).

    Returns:
        InternalRetrievalBrief with results (or empty if index missing / error).
    """
    path = chroma_path or CHROMA_PATH
    if not os.path.isdir(path):
        logger.warning("Chroma index not found at %s; returning empty brief.", path)
        return InternalRetrievalBrief(
            query=query,
            results=[],
            notes="RAG index not found. Run build_rag_index.py to create the index.",
            gaps_or_questions=["Internal document index is missing or not built."],
        )

    try:
        from langchain_community.vectorstores import Chroma
        from langchain_huggingface import HuggingFaceEmbeddings
    except ImportError as e:
        logger.error("RAG dependencies missing: %s", e)
        return InternalRetrievalBrief(
            query=query,
            results=[],
            notes="RAG dependencies (langchain, chromadb) not available.",
            gaps_or_questions=["Internal retrieval is not available."],
        )

    try:
        embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-large-en-v1.5")
        vector_store = Chroma(persist_directory=path, embedding_function=embeddings)
        # similarity_search_with_score returns (Document, score); Chroma L2 distance (lower = better)
        docs_with_scores = vector_store.similarity_search_with_score(query, k=k)
    except Exception as e:
        logger.exception("Internal retrieval failed: %s", e)
        return InternalRetrievalBrief(
            query=query,
            results=[],
            notes=f"Retrieval failed: {e}",
            gaps_or_questions=["Internal retrieval failed."],
        )

    results_list = []
    for doc, score in docs_with_scores:
        # Chroma L2: smaller score = more similar. Convert to 0-1 style (higher = better).
        relevance = 1.0 / (1.0 + max(0, float(score))) if score is not None else None
        source = doc.metadata.get("source", "")
        doc_id = doc.metadata.get("file_hash", source) or source
        title = os.path.basename(source) if source else "Unknown"
        page_val = doc.metadata.get("page_number")
        try:
            page_int = int(page_val) if page_val is not None else None
        except (TypeError, ValueError):
            page_int = None
        line_val = doc.metadata.get("line")
        try:
            line_int = int(line_val) if line_val is not None else None
        except (TypeError, ValueError):
            line_int = None
        results_list.append(
            RetrievalResult(
                doc_id=str(doc_id),
                title=title,
                filepath=source or None,
                section=doc.metadata.get("section"),
                excerpt=doc.page_content or "",
                page=page_int,
                line=line_int,
                relevance_score=relevance,
                source_type=doc.metadata.get("source_type"),
            )
        )

    return InternalRetrievalBrief(
        query=query,
        results=results_list,
        notes=None,
        gaps_or_questions=[],
    )
