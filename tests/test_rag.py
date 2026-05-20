# Manual RAG retriever smoke check (run from repo root: python tests/test_rag.py)

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
# RAG retriever tests support Pulse private memory regulatory themes and 🛡️ Shield compliance docs (RAG tests)
# additional Pulse private memory + Shield for RAG tests



def main() -> None:
    from core.rag_retriever import rag_retriever

    print("✅ RAG retriever imported successfully!")
    context = rag_retriever.get_context_string("GDPR requirements for medical device data")
    print("\nTest result:")
    print(context)


if __name__ == "__main__":
    main()
