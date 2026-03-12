# Note-Taking System Documentation

## Overview
The Notes tab is now a context-document workspace rather than a loose-note inbox. Each work context becomes one living document. As you add observations while reviewing material, Navi merges them into that context document, rewrites them for clarity, and reorganizes them into cleaner sections and bullet points.

## Architecture

### Core Components
- **`gui/notes_tab.py`**: Main UI implementation with `NoteTakingSystem`
- **`core/db.py`**: Stores hidden note-capture history plus first-class context documents
- **`core/response_handler.py`**: Keeps `notes_session` traffic out of task/news/search routing
- **`core/llama_worker.py`**: Local LLM worker used for document updates and re-organization

### Data Model
- **`notes`**: Hidden ingestion history. Raw observations are still inserted immediately so user text is never lost.
- **`notes_documents`**: Primary user-facing storage. One row per context containing the current compiled document.

## Data Flow
1. User sets or selects a context.
2. The UI loads or creates one document for that context.
3. User enters a raw observation.
4. A hidden draft row is added to `notes`.
5. Navi receives the current document plus the new observation and returns an updated document.
6. The context document is saved back to `notes_documents`.
7. Export uses the active context document directly.

## UX Model

### Contexts
- The left sidebar lists context documents.
- Entering a context name creates or activates that document.
- There are no loose note rows in the UI.

### Capture
- The capture box is for fast raw observations while reviewing material.
- Press `Enter` to merge the observation into the active document.
- Press `Shift+Enter` for a newline inside the capture box.

### Document View
- The main editor shows the current compiled document for the active context.
- Manual edits can be saved directly with `Save Document`.
- `Re-organize` asks Navi to clean up the current document without adding a new observation.

### Export
- Export works on the active document only.
- Supported formats:
  - DOCX
  - Markdown
  - PDF

## AI Behavior

### Incremental Merge
For each new observation, Navi gets:
- the context
- the current document
- the new raw observation

It returns an updated document in JSON:

```json
{"document": "Updated document text here"}
```

### Re-organization
`Re-organize` uses the current document as input and asks Navi to:
- tighten section structure
- improve bullet clarity
- merge duplicates
- preserve substance

## Database Schema

### Hidden Observation History
```sql
CREATE TABLE notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    formatted_note TEXT NOT NULL,
    category TEXT NOT NULL,
    context TEXT,
    raw_note TEXT,
    state TEXT NOT NULL DEFAULT 'ready',
    error_text TEXT,
    pinned INTEGER NOT NULL DEFAULT 0,
    timestamp TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Context Documents
```sql
CREATE TABLE notes_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    context TEXT NOT NULL UNIQUE,
    title TEXT,
    document_text TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'ready',
    error_text TEXT,
    source_note_count INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

## Migration Behavior
- Existing `ready` note rows are backfilled into one starter document per context.
- Legacy note rows are preserved for traceability and rollback safety.
- Old `organized_notes` data is no longer the runtime source of truth.

## Error Handling
- Raw observations are inserted before AI processing so text is not lost.
- Robust JSON parsing still uses multiple fallbacks:
  1. direct parse
  2. extracted JSON block
  3. cleaned JSON retry
  4. plain-string fallback
- If a document update fails, the active document is left intact and the error is surfaced in the UI.

## Session Routing
The Notes tab still uses `notes_session`, which bypasses:
- task routing
- news routing
- `!search` handling

This keeps document-update prompts focused on note processing instead of command interpretation.

## Manual Test Focus
- Context selection creates/loads one document
- Entering a raw note updates the active document
- Multiple notes reorganize into cleaner sections/themes
- Export writes the active document, not a list of note rows
- Failures preserve hidden note history and show user feedback
