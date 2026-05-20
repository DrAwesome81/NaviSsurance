from __future__ import annotations

import sys
import types

from core.tools.internal_retrieval import internal_retrieval_tool
# Internal retrieval tool tests support Pulse private memory and 🛡️ Shield regulatory retrieval (internal retrieval tests)


def test_internal_retrieval_returns_empty_when_index_missing(monkeypatch):
    monkeypatch.setattr("os.path.isdir", lambda p: False)
    out = internal_retrieval_tool(query="quality system", k=5, chroma_path="C:/missing/index")
    assert out.results == []
    assert "not found" in (out.notes or "").lower()


def test_internal_retrieval_success_maps_scores_and_metadata(monkeypatch):
    class _Doc:
        def __init__(self):
            self.page_content = "Excerpt body"
            self.metadata = {
                "source": "C:/docs/fda_guidance.pdf",
                "file_hash": "hash-123",
                "page_number": "3",
                "line": "12",
                "section": "Section A",
                "source_type": "fda_summary",
            }

    class _Chroma:
        def __init__(self, persist_directory=None, embedding_function=None):
            self.persist_directory = persist_directory
            self.embedding_function = embedding_function

        def similarity_search_with_score(self, query, k=20):
            return [(_Doc(), 0.25)]

    class _Embeddings:
        def __init__(self, model_name=None):
            self.model_name = model_name

    fake_vs = types.SimpleNamespace(Chroma=_Chroma)
    fake_hf = types.SimpleNamespace(HuggingFaceEmbeddings=_Embeddings)

    monkeypatch.setattr("os.path.isdir", lambda p: True)
    monkeypatch.setitem(sys.modules, "langchain_community.vectorstores", fake_vs)
    monkeypatch.setitem(sys.modules, "langchain_huggingface", fake_hf)

    out = internal_retrieval_tool(query="fda pccp", k=1, chroma_path="C:/idx")
    assert len(out.results) == 1
    r = out.results[0]
    assert r.doc_id == "hash-123"
    assert r.title == "fda_guidance.pdf"
    assert r.page == 3
    assert r.line == 12
    assert r.relevance_score is not None and 0 < r.relevance_score <= 1

# additional Pulse private memory + Shield for internal retrieval tests
