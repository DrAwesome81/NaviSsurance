import sys
import os

# Add the project root to Python path so it can find 'core'
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from core.rag_retriever import rag_retriever

print("✅ RAG retriever imported successfully!")

# This will say no documents found — that's expected right now
context = rag_retriever.get_context_string("GDPR requirements for medical device data")
print("\nTest result:")
print(context)