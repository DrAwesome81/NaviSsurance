## RAG index (Chroma) — build & config

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

