import sqlite3
import sys
import os

from sentence_transformers import SentenceTransformer
import torch

# Load model
model = SentenceTransformer('all-MiniLM-L6-v2').to("cuda:0")

# Query
query = "software verification and validation protocol"
query_emb = model.encode(query, convert_to_tensor=True).cpu().numpy()

# Search full index
print("Embedding all files—might take 5-10 mins...")

# Import config for database path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE_PATH

conn = sqlite3.connect('DATABASE_PATH')
cursor = conn.cursor()
cursor.execute("SELECT name, content FROM dropbox_index")
results = cursor.fetchall()

# Rank by similarity
rankings = []
for name, content in results:
    snippet = ' '.join(content.split())[:512]
    content_emb = model.encode(snippet, convert_to_tensor=True).cpu().numpy()
    similarity = torch.nn.functional.cosine_similarity(
        torch.tensor(query_emb), torch.tensor(content_emb), dim=0
    ).item()
    rankings.append((name, similarity, snippet))

# Top 5
rankings.sort(key=lambda x: x[1], reverse=True)
for i, (name, score, snippet) in enumerate(rankings[:5], 1):
    print(f"{i}. {name}: {score:.4f}")
    print(f"Snippet: {snippet[:200]}...\n")