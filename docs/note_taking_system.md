# Note-Taking System Documentation

## Overview
The Note-Taking System is an AI-powered feature that provides intelligent note formatting, context-aware processing, and dynamic categorization. It uses a local Llama 3.1-8B-Instruct model for processing with robust error handling and export capabilities.

## Architecture

### Core Components
- **`gui/interface.py`**: Main UI implementation with `NoteTakingSystem` class
- **`core/llama_worker.py`**: Local AI model worker process
- **`core/db.py`**: Database management for notes and categories
- **`core/api.py`**: Dropbox integration for file exports

### Data Flow
1. User sets context (optional) → stored in database
2. User enters note → sent to AI for formatting
3. Formatted note → stored in database with context
4. When 2+ notes exist → AI categorizes into logical groups
5. Categories → stored in database and displayed in UI
6. Export → generates TXT/DOCX/PDF with context and uploads to Dropbox

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
- Automatically categorizes notes when 2 or more exist
- Uses exact note text without modification
- Supports dynamic re-categorization as new notes are added
- Falls back to unorganized display if no clear categories found

### Export Capabilities
- **TXT**: Plain text with context and categorized notes
- **DOCX**: Formatted Word document with context and categories
- **PDF**: Professional PDF with context and categorized notes
- **Dropbox Integration**: Automatic upload to cloud storage

## Technical Implementation

### AI Model Configuration
```python
# core/llama_worker.py
llm = Llama(
    model_path=model_path,
    n_gpu_layers=33,
    n_ctx=8192,  # Context window
    n_threads=4,
    verbose=True,
    chat_format="llama-3"
)

response = llm.create_chat_completion(
    messages=all_messages,
    max_tokens=1000,  # Response limit
    temperature=0.9,
    top_p=0.9
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
    timestamp TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
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
- **JSON Parsing**: Robust extraction from AI responses using regex
- **Truncation Detection**: Checks for incomplete JSON responses
- **Fallback Mechanisms**: Graceful degradation when AI fails
- **User Feedback**: Clear error messages and status updates

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
2. Choose export format (TXT/DOCX/PDF)
3. Files are generated with context and categories
4. Files are automatically uploaded to Dropbox

## Configuration

### Token Limits
- **Response Limit**: 1000 tokens (configurable in `core/llama_worker.py`)
- **Context Window**: 8192 tokens
- **Worker Processes**: Subprocess-based for model loading

### Model Settings
- **Model**: Llama 3.1-8B-Instruct-GGUF
- **GPU Layers**: 33 (for GPU acceleration)
- **Threads**: 4 (for CPU processing)
- **Temperature**: 0.9 (for creative responses)
- **Top-p**: 0.9 (for response diversity)

## Troubleshooting

### Common Issues
1. **"Invalid response format"**: AI returned non-JSON response
   - Solution: Check AI model loading and prompts
2. **Truncated responses**: Response cut off mid-sentence
   - Solution: Increase max_tokens or improve prompts
3. **Missing notes under categories**: Display logic issue
   - Solution: Check database queries and UI updates

### Debug Information
- Raw AI responses are logged for debugging
- Truncation detection provides warnings
- Error messages include response details
- Database queries can be inspected for data integrity

## Future Enhancements
- **Multi-language support**: Internationalization for note content
- **Advanced categorization**: Hierarchical categories and subcategories
- **Collaborative features**: Shared note-taking sessions
- **Integration**: Connect with task management and CRM systems
- **Advanced exports**: Custom templates and branding options 