# Unified Search (Dropbox + Local + Google Drive) with Duplicate Detection

Status: roadmap / design document, not a full description of shipped behavior.

Last updated: 2026-04-01

## Purpose
Build a single search capability that lets the Chief of Staff assistant (and the UI) find relevant information across:
- **Dropbox** (existing indexing/search foundation)
- **Local files** (one or more user-selected folders)
- **Google Drive** (My Drive + optionally Shared Drives)

Results should be **passage-based** (best excerpts) with links to the source files, and duplicates across sources should be **recognized and collapsed**.

## Current implementation note
Parts of this design are implemented, but the full end-state in this document is still aspirational.

Today the repo primarily exposes:
- `core/cos_doc_search.py` for note search, local markdown/text search, and optional Chroma search
- `core/tools/internal_retrieval.py` for agent-facing Chroma retrieval
- `core/chat_retrieval.py` for long-term chat retrieval
- `core/user_memory.py` for durable memory retrieval

Use this document as the target design for broader unified search rather than as a precise description of shipped behavior.

## Principles
- **Index once, search many**: normalize all sources into one schema and one query path.
- **Chunked retrieval**: search over document chunks (pages/sections) rather than entire files.
- **Deterministic dedup**: use strong hashes where possible; keep near-dup detection conservative and auditable.
- **Incremental sync**: avoid full re-indexing; use provider change APIs/cursors.
- **Untrusted content**: retrieved text is reference only (not instructions).

## Scope
### In scope
- Metadata sync + incremental updates for all three sources
- Text extraction (PDF/DOCX/TXT + Drive export types)
- Chunking + indexing (SQLite + FTS)
- Search API returning ranked excerpts and links
- Exact duplicate detection and grouping across sources
- Optional “possible duplicate” signals (near-dup), gated behind review

### Out of scope (initially)
- Automatic merging/rewriting of files
- Autonomous sharing/permission changes in Drive/Dropbox
- OCR at scale (can be added later)

## Architecture Overview

### Source connectors
Implement connectors with a shared interface:
- **List/sync**: enumerate files and metadata, support incremental changes
- **Fetch content**: download/export content for extraction
- **Identity**: stable source identifiers (Dropbox path/id, Drive fileId, local absolute path + inode)

Connectors:
- **DropboxConnector**
  - incremental via cursor (`files_list_folder` + `continue`)
  - strong hash: Dropbox `content_hash`
- **LocalConnector**
  - full scan + incremental via watcher or periodic rescan
  - strong hash: `sha256(file_bytes)`
- **GoogleDriveConnector**
  - incremental via `changes.list` (startPageToken)
  - strong hash: `md5Checksum` for binaries when present; otherwise hash exported bytes/text
  - export for Google-native docs (Docs/Sheets/Slides)

### Indexing pipeline (per file)
1. **Upsert metadata** into unified `documents`
2. **Compute strong hash** (if available / feasible)
3. **Extract text** (download/export + parse)
4. **Chunk** into passages (size/overlap tuned for retrieval)
5. **Upsert chunks** into `document_chunks` + FTS table
6. **Dedup grouping**
   - exact duplicates grouped automatically (same strong hash)
   - near-duplicates flagged (optional)

### Search pipeline (query-time)
1. Parse query + optional filters (source/client/type/date)
2. Retrieve candidates with **FTS** (chunks + summaries)
3. Rank using a hybrid score:
   - FTS rank (e.g., `bm25`)
   - metadata boosts (recency, client/project match, filename match)
4. Collapse by `dedup_group_id`:
   - show a canonical result with the best excerpt
   - list “also available in” other sources (Dropbox/Drive/local)
5. Return top results with:
   - filename + link(s)
   - best excerpt(s) + location (page/section if available)
   - tags (client/project/doc type)

## Data Model (SQLite)
This plan assumes a unified schema even if the implementation migrates in phases.

### documents
- `doc_id` (pk)
- `source` (`dropbox|local|gdrive`)
- `source_file_id` (Dropbox file id or path; Drive fileId; local stable id)
- `name`, `path`
- `mime_type`, `ext`
- `size`, `modified_time`
- `web_link` (Dropbox shared link, Drive webViewLink, `file://...`)
- `strong_hash`
- `hash_method` (`dropbox_content_hash|sha256|md5|export_sha256|none`)
- `dedup_group_id` (nullable)
- `content_version` (rev/etag/Drive version)
- `indexed_at`

### document_chunks
- `chunk_id` (pk)
- `doc_id` (fk)
- `chunk_index`
- `text`
- `start_ref`, `end_ref` (page number, byte offset, etc.)
- optional: `chunk_hash`

### FTS
- `document_chunks_fts` virtual table including:
  - `text` (chunk text)
  - `name`, `path`, `source`
  - denormalized tags (client/project/topic) for filterable search

### Dedup tables
- `dedup_groups(group_id, strong_hash, created_at)`
- `dedup_members(group_id, doc_id, is_canonical, reason)`

### Tags (optional but recommended)
- `document_tags(doc_id, tag_type, tag_value, confidence, created_at)`
  - `tag_type`: `client|project|person|topic|doctype|intent`

## Duplicate Detection Strategy

### Tier A: exact duplicates (automatic)
Use strong hashes whenever possible:
- Dropbox: `content_hash`
- Drive binaries: `md5Checksum`
- Local: `sha256(file_bytes)`
- Drive Google-native docs: `sha256(exported_bytes)` for a chosen export format

Rule: matching `strong_hash` ⇒ same `dedup_group_id`.

### Tier B: near duplicates (optional, review-based)
Detect likely duplicates across different formats or lightly edited versions:
- SimHash/MinHash over extracted text (or chunk hashes)
- Conservative thresholding + “possible duplicate” labeling
- Never auto-merge; allow “link as related” after review

## Google Drive Details
- Index scope:
  - My Drive
  - Shared drives (optional, but common in org setups)
- Content extraction:
  - Docs → export text (`text/plain`) or PDF then extract
  - Sheets → export CSV
  - Slides → export text/PDF
- Incremental updates:
  - Drive `changes.getStartPageToken` + `changes.list`
  - store token in DB metadata

## Local Files Details
- Configure one or more roots (e.g., `data/clients`, or any folder).
- Incremental updates:
  - watcher (best UX) or periodic rescan (simpler)
- Links:
  - store absolute path + generate `file://` URLs for UI open

## Chief of Staff Integration
Expose one unified command (internally and optionally as a chat control):
- `DOC_SEARCH:<query>`

Support filters in a structured form (recommended evolution):
- `source:dropbox|gdrive|local`
- `client:<name>`
- `type:pdf|docx|sheet`
- `modified:>=YYYY-MM-DD`

Assistant response should:
- show canonical item + best excerpt
- show “also in” alternate source locations (dedup members)
- optionally offer: “open”, “add task”, “summarize”, “draft email using this”

## Milestones (Suggested)
1. **Phase 1 (Local + unify schema + FTS chunks)**: get a second source working end-to-end quickly.
2. **Phase 2 (Dropbox migration)**: map existing Dropbox index to unified tables and search path.
3. **Phase 3 (Google Drive)**: implement connector + export + incremental changes.
4. **Phase 4 (Exact dedup)**: strong hashes + grouping + UI/agent result collapsing.
5. **Phase 5 (Near-dup + tuning)**: optional similarity-based duplicate suggestions + evaluation set.

## Rough Timeline
- Unified search across 3 sources with exact dedup (FTS + strong hashes): **~1–2 weeks**
- Near-dup detection + significant relevance tuning (eval-driven): **+1–2 weeks**
