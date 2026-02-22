# Note-Taking System Documentation

## Overview
The Note-Taking System is an AI-powered feature that provides intelligent note formatting, context-aware processing, and dynamic categorization. It uses a local Llama 3.1-8B-Instruct model for processing with robust error handling and export capabilities. The system features thread-safe UI updates, robust JSON parsing with multiple fallback strategies, and a Save As dialog for exporting notes to DOCX format.

## Architecture

### Core Components
- **`gui/notes_tab.py`**: Main UI implementation with `NoteTakingSystem` class
- **`core/llama_worker.py`**: Local AI model worker process (subprocess-based)
- **`core/db.py`**: Database management for notes and categories
- **`core/response_handler.py`**: Handles routing and ensures Notes session bypasses task/news/!search logic

### Data Flow
1. User sets context (optional) → stored in memory and database
2. User enters note → sent to AI for formatting via `notes_session` (bypasses task routing)
3. Formatted note → stored in database with context
4. When 2+ notes exist → AI categorizes into logical groups
5. Categories → stored in database and displayed in UI
6. Export → Save As dialog allows user to choose location and filename for DOCX export

## Features

### Context Setting
- Users can set context for their note-taking session
- Context is included in AI prompts for better formatting and categorization
- Context is stored with notes and included in exports
- Context changes trigger fresh categorization

### AI-Powered Formatting
- Notes are automatically formatted for clarity and professionalism
- Uses local Llama model with 1000-token response limit
- Robust JSON parsing with fallback mechanisms
- Handles truncation detection and error recovery

### Dynamic Categorization
- Automatically categorizes notes when 2 or more “ready” notes exist (per context)
- Categorization uses stable **note IDs** (not only note text) to avoid ambiguity
- Categories are shown in a **collapsible tree**, and notes can be **moved manually** to a different category
- Re-organize can be run at any time

### Export Capabilities
- **DOCX Export**
- **Markdown Export**
- **PDF Export**
- Export includes timestamps + categories (and context if filtered)

### Browsing / Search / Editing
- Notes are DB-backed and loaded on tab open
- Search box (FTS-backed when available; falls back to LIKE)
- Filters: context, time range (All/7/30/90 days), pinned-only
- Per-note actions: pin/unpin, edit, delete, retry formatting, copy to clipboard

### Integrations
- Create Task from a note (due date + category)
- Remember: store a note into Navi’s structured memory (`cos_memory`) for future recall

## Technical Implementation

### AI Model Configuration
```python
# core/llama_worker.py
llm = Llama(
    model_path=model_path,
    n_gpu_layers=33,
    n_ctx=8192,  # Context window
    n_threads=4,
    verbose=False,
    chat_format="llama-3"
)

response = llm.create_chat_completion(
    messages=all_messages,
    max_tokens=1000,  # Response limit
    temperature=0.2,  # Lower temperature for more deterministic output
    top_p=0.7         # Lower top_p for more focused responses
)
```

### Database Schema
```sql
-- Notes table
CREATE TABLE notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    formatted_note TEXT NOT NULL,
    category TEXT NOT NULL,
    context TEXT,  -- Context for the note
    raw_note TEXT,
    state TEXT NOT NULL DEFAULT 'ready',
    error_text TEXT,
    pinned INTEGER NOT NULL DEFAULT 0,
    timestamp TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Organized notes table
CREATE TABLE organized_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    notes_json TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Error Handling
- **Robust JSON Parsing**: Multi-strategy parsing with fallbacks:
  1. Direct JSON parse attempt
  2. Extract `{...}` block using regex
  3. Clean whitespace and trailing commas, then parse
  4. Regex fallback to extract `"formatted"` field directly
- **Shape-Tolerant Parsing**: Handles dict, list, or plain string responses
- **Thread-Safe UI Updates**: Uses `QTimer.singleShot(0, ...)` to ensure UI updates happen on main thread
- **Session Routing**: Notes session (`notes_session` or `notes_*` prefix) bypasses task/news/!search routing in `ResponseHandler.get_response`
- **User Feedback**: Clear error messages and status updates in UI

## Usage

### Setting Context
1. Enter context in the context input field
2. Press Enter to set context
3. Context is displayed and included in subsequent AI processing

### Taking Notes
1. Enter note in the chat input field
2. Press Enter to process note
3. AI formats note and adds to display
4. Automatic categorization occurs when 2+ notes exist

### Exporting Notes
1. Click "Export Notes" button
2. Choose format (DOCX / Markdown / PDF)
3. Save As dialog opens with default filename `notes_export.docx`
4. Export includes timestamps + categories (and context if filtered)

## Configuration

### Token Limits
- **Response Limit**: 1000 tokens (configurable in `core/llama_worker.py`)
- **Context Window**: 8192 tokens
- **Worker Processes**: Subprocess-based for model loading

### Model Settings
- **Model**: Llama 3.1-8B-Instruct-GGUF
- **GPU Layers**: 33 (for GPU acceleration)
- **Threads**: 4 (for CPU processing)
- **Temperature**: 0.2 (for deterministic, consistent responses)
- **Top-p**: 0.7 (for focused, relevant responses)
- **Worker Process**: Subprocess-based for isolation and stability
- **Thread Safety**: Threading lock ensures only one request at a time to worker

## Troubleshooting

### Common Issues
1. **"Could not parse note formatting response"**: AI returned non-JSON or malformed JSON
   - Solution: System uses robust parsing with multiple fallbacks; check raw response in error message
   - Root cause: Usually indicates model routing issue (fixed by Notes session guard)
2. **Notes hitting task list logic**: Notes being processed as tasks
   - Solution: Ensure session ID is `notes_session` or starts with `notes_` prefix
   - Root cause: Fixed by guard in `ResponseHandler.get_response` to bypass task routing
3. **Missing notes under categories**: Display logic issue
   - Solution: Check database queries and UI updates; verify `organized_notes` structure
4. **Export not opening Save As dialog**: Old duplicate class being used
   - Solution: Ensure only one `NoteTakingSystem` class exists in `gui/notes_tab.py`

### Debug Information
- Raw AI responses are logged for debugging
- Truncation detection provides warnings
- Error messages include response details
- Database queries can be inspected for data integrity

## Technical Details

### Thread Safety
- All UI updates from background threads use `QTimer.singleShot(0, ...)` to schedule updates on the main thread
- Worker subprocess communication uses `threading.Lock` to prevent concurrent access
- `NoteProcessingThread` (QThread subclass) handles async AI processing

### JSON Parsing Strategy
The `robust_json_parse` function in `gui/notes_tab.py` implements a multi-stage parsing approach:
1. Direct `json.loads()` attempt
2. Regex extraction of `{...}` block
3. Whitespace/trailing comma cleanup and retry
4. Regex fallback for `"formatted"` field extraction

### Session Routing
The Notes tab uses special session IDs (`notes_session` or `notes_*` prefix) that bypass:
- Task detection and routing
- News feed queries
- `!search` web search commands

This ensures note formatting prompts are sent directly to the LLM without interference.

## Future Enhancements
- **Multi-language support**: Internationalization for note content
- **Advanced categorization**: Hierarchical categories and subcategories
- **Collaborative features**: Shared note-taking sessions
- **Integration**: Connect with task management and CRM systems
- **Advanced exports**: Custom templates and multiple format options 