## RAG index (Chroma) — build & config

Last updated: 2026-05-12

This repo includes a local RAG index builder in `build_rag_index.py` that creates a Chroma vector store in `chroma_index/`.

### Config files
- **`rag_config.json`**: local-only config (ignored by git). Contains paths and access tokens.
- **`rag_config.example.json`**: checked-in template you can copy.

Create your local config:

```bash
copy rag_config.example.json rag_config.json
```

Then edit `rag_config.json` and fill in whichever sources you want to index (leave unused sources blank).

### Build the index

```bash
python build_rag_index.py
```

Notes:
- If `chroma_index/` already exists, the script clears it and rebuilds from scratch.
- Local PDFs are indexed **page-by-page** (each page becomes a separate document).
- Indexing deduplicates by an MD5 hash of `(source, page_number, content)`.

### Security
- Do **not** commit `rag_config.json` (it may contain tokens). It is ignored by `.gitignore`.
- Prefer using environment variables for tokens where possible; if you must put tokens in `rag_config.json`, keep the file local-only.

## How this fits into current retrieval
NaviSsurance now has multiple retrieval layers:
- `core/cos_doc_search.py` for local notes/docs plus optional Chroma-backed RAG
- `core/chat_retrieval.py` for long-term chat retrieval
- `core/user_memory.py` for global durable structured memory
- `core/agent_memory.py` for per-agent and assignment-local memory retrieval

The Chroma index is therefore one retrieval source, not the entire memory system.

## Current guidance
- Use Chroma when you want semantic document retrieval over indexed local / imported content.
- Use the built-in structured memory and chat-retrieval layers for preferences, aliases, commitments, historical chat context, and layered agent/assignment memory.
- Treat retrieved text as untrusted reference material rather than executable instructions.

