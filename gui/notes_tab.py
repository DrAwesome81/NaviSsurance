from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QLineEdit, QLabel, QTextBrowser, QFileDialog
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt6.QtGui import QKeyEvent
from datetime import datetime
import json
import re
from core.db import DatabaseManager
from docx import Document

def robust_json_parse(response: str, logger=print):
    """
    Robustly parse JSON from an LLM response that *should* be JSON,
    but may have extra text or small formatting issues.
    Returns (data, success: bool).
    """
    import json
    import re

    if response is None:
        logger("DEBUG: robust_json_parse received None response")
        return None, False

    original_response = response
    response = response.strip()
    logger(f"DEBUG: Starting robust_json_parse. Raw response (truncated): {original_response[:200]}")

    # First: try direct parse
    try:
        data = json.loads(response)
        logger("DEBUG: Direct JSON parse succeeded")
        return data, True
    except json.JSONDecodeError as e:
        logger(f"DEBUG: Direct parse failed: {e}")

    # Second: extract {...} block
    json_match = re.search(r'\{.*\}', response, re.DOTALL)
    if json_match:
        candidate = json_match.group(0).strip()
        logger(f"DEBUG: Found JSON-looking block (truncated): {candidate[:200]}")
        try:
            data = json.loads(candidate)
            logger("DEBUG: Parsed JSON from extracted block")
            return data, True
        except json.JSONDecodeError as e:
            logger(f"DEBUG: Extracted block parse failed: {e}")

    # Third: clean whitespace, trailing commas
    cleaned = response.replace('\r', ' ').replace('\n', ' ')
    cleaned = re.sub(r'\s+', ' ', cleaned)
    cleaned = re.sub(r',\s*}', '}', cleaned)
    cleaned = re.sub(r',\s*]', ']', cleaned)
    cleaned = cleaned.rstrip('\'"')
    logger(f"DEBUG: Attempting cleaned JSON parse (truncated): {cleaned[:200]}")

    try:
        data = json.loads(cleaned)
        logger("DEBUG: Cleaned JSON parse succeeded")
        return data, True
    except json.JSONDecodeError as e:
        logger(f"DEBUG: Cleaned parse still failed: {e}")

    # If everything fails but we still have some text, treat it as a plain string
    cleaned_str = original_response.strip()
    if cleaned_str:
        logger("DEBUG: robust_json_parse failed to parse JSON; returning plain string fallback")
        return cleaned_str, True

    # If there is truly nothing useful, log and return failure
    logger("DEBUG: robust_json_parse ultimately failed with empty/whitespace response")
    return None, False

class NoteProcessingThread(QThread):
    result_signal = pyqtSignal(str)  # Emits the formatted/organized response
    error_signal = pyqtSignal(str)   # Emits error messages

    def __init__(self, chat_handler, prompt, session_id):
        super().__init__()
        self.chat_handler = chat_handler
        self.prompt = prompt
        self.session_id = session_id

    def run(self):
        try:
            response = self.chat_handler.get_response(self.prompt, self.session_id, conversation_history=[])
            self.result_signal.emit(response)
        except Exception as e:
            self.error_signal.emit(str(e))

class NoteTakingSystem(QWidget):
    def __init__(self, chat_handler):
        super().__init__()
        self.chat_handler = chat_handler
        self.db = DatabaseManager()
        self.db.init_notes_table()
        self.notes = []  # Temporary in-memory storage for notes
        self.organized = False
        self.context = None  # Add context attribute
        self.setup_ui()

    def setup_ui(self):
        layout = QHBoxLayout(self)
        
        # Left: Chat Window
        chat_widget = QWidget()
        chat_layout = QVBoxLayout(chat_widget)
        
        # Add context input field
        context_label = QLabel("Context (what you're working on):")
        context_label.setStyleSheet("color: white; font-weight: bold;")
        chat_layout.addWidget(context_label)
        
        self.context_input = QLineEdit()
        self.context_input.setPlaceholderText("Enter context (e.g., 'Working on FDA protocol review')")
        self.context_input.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white; border: 1px solid rgba(253, 98, 98, 0.5); padding: 5px;")
        self.context_input.returnPressed.connect(self.update_context)
        chat_layout.addWidget(self.context_input)
        
        # Create a custom QTextEdit subclass for proper key event handling
        class CustomTextEdit(QTextEdit):
            def __init__(self, parent=None):
                super().__init__(parent)
                self.parent_widget = parent
            
            def keyPressEvent(self, event):
                if event.key() == Qt.Key.Key_Return and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    # Enter key pressed (without Shift)
                    if hasattr(self.parent_widget, 'process_note'):
                        self.parent_widget.process_note()
                        self.clear()
                    event.accept()
                else:
                    # Let the default QTextEdit handle other keys
                    super().keyPressEvent(event)
        
        self.chat_input = CustomTextEdit(self)
        self.chat_input.setPlaceholderText("Enter thoughts (e.g., 'Section 5 should be in the protocol; not this report')")
        chat_layout.addWidget(self.chat_input)
        layout.addWidget(chat_widget, stretch=1)

        # Right: Notes Pane
        notes_widget = QWidget()
        notes_layout = QVBoxLayout(notes_widget)
        self.notes_display = QTextEdit()
        self.notes_display.setReadOnly(True)
        self.notes_display.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white;")
        notes_layout.addWidget(self.notes_display)
        
        # Buttons
        export_btn = QPushButton("Export Notes")
        export_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white;")
        export_btn.clicked.connect(self.export_notes)
        notes_layout.addWidget(export_btn)
        
        layout.addWidget(notes_widget, stretch=1)
        self.setLayout(layout)

    def update_context(self):
        """Update the context and notify Navi."""
        self.context = self.context_input.text().strip()
        if self.context:
            self.context_input.clear()
            self.notes_display.append(f"<b>Context set:</b> {self.context}<br>")
            # Clear organized notes when context changes to allow fresh categorization
            self.organized = False
            self.db.clear_organized_notes()

    def process_note(self):
        content = self.chat_input.toPlainText().strip()
        if not content or len(content) < 10:
            return
        
        context_info = f"Context: {self.context}" if self.context else "No context set"
        prompt = f"""{context_info}. 

INSTRUCTION: Take the user's note and format it into a clear, professional note.

USER'S NOTE: '{content}'

INSTRUCTIONS:
- Format the note to be clear and professional
- Keep the original meaning and intent
- Make it more readable and well-structured
- Do NOT add commentary about categorization or other notes
- Do NOT respond with meta-comments about the process

RESPONSE FORMAT: You must respond with ONLY valid JSON in this exact format:
{{"formatted": "Your formatted note text here"}}

Example: If user writes "need to check section 5", you should respond:
{{"formatted": "Need to review and verify Section 5 of the document"}}

IMPORTANT: Respond with ONLY the JSON. No other text or explanations."""

        # Start background thread for formatting
        self.note_thread = NoteProcessingThread(self.chat_handler, prompt, "notes_session")
        self.note_thread.result_signal.connect(self.handle_note_formatted)
        self.note_thread.error_signal.connect(self.handle_note_error)
        self.note_thread.start()

        # Disable input while processing
        self.chat_input.setEnabled(False)
        self.notes_display.append("<i>Formatting note...</i><br>")

    def handle_note_formatted(self, response):
        QTimer.singleShot(0, lambda: self._handle_note_formatted_safe(response))

    def _handle_note_formatted_safe(self, response):
        """Thread-safe version of handle_note_formatted with robust, shape-tolerant parsing."""
        try:
            # Use robust JSON parsing
            note_data, success = robust_json_parse(
                response,
                logger=lambda msg: print(f"Note formatting: {msg}")
            )

            formatted = None

            if success and note_data:
                # 1) Expected shape: {"formatted": "..."}
                if isinstance(note_data, dict) and "formatted" in note_data:
                    formatted = note_data["formatted"]

                # 2) Sometimes models wrap things in a list: [{"formatted": "..."}]
                elif isinstance(note_data, list):
                    for item in note_data:
                        if isinstance(item, dict) and "formatted" in item:
                            formatted = item["formatted"]
                            break

                # 3) If the model just returns a plain string, treat it as already formatted
                elif isinstance(note_data, str):
                    formatted = note_data

            # 4) Last-ditch fallback: regex directly on the raw response if we still don't have text
            if not formatted and '"formatted"' in response:
                try:
                    import re
                    m = re.search(r'"formatted"\s*:\s*"(.+?)"', response, re.DOTALL)
                    if m:
                        formatted = m.group(1)
                except Exception as e:
                    print(f"Note formatting fallback regex failed: {e}")

            if formatted:
                # Normal success path
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.db.save_note(formatted, timestamp, self.context)
                self.notes.append(formatted)
                self.update_notes_display()

                # Re-enable input
                self.chat_input.setEnabled(True)
                self.chat_input.clear()
                self.chat_input.setFocus()

                # Trigger organization if enough notes
                if len(self.notes) >= 2:
                    self.try_organize_notes()
            else:
                # Only hit this if *all* attempts to salvage text failed
                self.notes_display.append("Error: Could not parse note formatting response")
                self.notes_display.append(f"Raw response: {response[:500]}.")  # Truncate for display
                self.chat_input.setEnabled(True)

        except Exception as e:
            # Hard failure – show the error and the raw response to help debugging
            self.notes_display.append(f"Error processing note: {str(e)}")
            self.notes_display.append(f"Raw response: {response[:500]}.")  # Truncate for display
        finally:
            # Make absolutely sure input is enabled again
            self.chat_input.setEnabled(True)

    def handle_note_error(self, error):
        QTimer.singleShot(0, lambda: self._handle_note_error_safe(error))

    def _handle_note_error_safe(self, error):
        self.notes_display.append(f"Error processing note: {error}")
        self.chat_input.setEnabled(True)

    def try_organize_notes(self):
        if sum(len(note) for note in self.notes) > 7000:  # Approximate token limit check
            self.notes_display.append("Warning: Notes may exceed token limit; categorization skipped.")
            return
        
        context_info = f"Context: {self.context}" if self.context else "No context set"
        prompt = f"""{context_info}. 

INSTRUCTION: Categorize the existing notes into logical groups.

EXISTING NOTES TO CATEGORIZE:
{chr(10).join([f"- {note}" for note in self.notes])}

INSTRUCTIONS:
- These are the actual notes that need to be categorized
- Look for common themes or topics among these specific notes
- If you can identify 2 or more clear categories, organize the notes accordingly
- If the notes are too diverse or no clear patterns emerge, return empty JSON
- Use the EXACT note text as provided - do not modify or summarize the notes
- Do NOT add commentary about the categorization process
- Do NOT respond with meta-comments about the notes
- Do NOT generate new content - only categorize the existing notes
- Even with just 2 notes, try to find a logical grouping if possible
RESPONSE FORMAT: You must respond with ONLY valid JSON in one of these formats:
If categories are found:
{{"categories": {{"Category Name": ["exact note text 1", "exact note text 2"], "Another Category": ["exact note text 3"]}}}}
If no clear patterns (return empty):
{{}}
Example categories might be: "Protocol Review", "Documentation", "Follow-up Tasks", "Questions", "Data Handling", "Requirements", etc.
IMPORTANT: 
- Use the exact note text as provided above
- Respond with ONLY the JSON. No other text or explanations."""

        # Start background thread for organization
        self.organize_thread = NoteProcessingThread(self.chat_handler, prompt, "notes_session")
        self.organize_thread.result_signal.connect(self.handle_organization_result)
        self.organize_thread.error_signal.connect(self.handle_organization_error)
        self.organize_thread.start()

        # Disable UI while processing
        self.chat_input.setEnabled(False)
        self.notes_display.append("<i>Organizing notes...</i><br>")

    def handle_organization_result(self, response):
        QTimer.singleShot(0, lambda: self._handle_organization_result_safe(response))

    def _handle_organization_result_safe(self, response):
        try:
            organized_data, success = robust_json_parse(response, logger=print)
            if not success or organized_data is None:
                self.notes_display.append("<i>No clear categories found, showing unorganized notes</i><br>")
                self.update_notes_display(organized=False)
                self.chat_input.setEnabled(True)
                return
            
            if 'categories' in organized_data and organized_data['categories']:
                self.organized = True
                self.db.save_organized_notes(organized_data['categories'])
                self.notes_display.append(f"<i>Notes organized into {len(organized_data['categories'])} categories</i><br>")
                self.update_notes_display()
            else:
                self.notes_display.append("<i>No clear categories found, showing unorganized notes</i><br>")
                self.update_notes_display(organized=False)
        except Exception as e:
            self.notes_display.append(f"Error: {str(e)}")
            print(f"DEBUG: Unexpected error: {e}")
        finally:
            self.chat_input.setEnabled(True)

    def handle_organization_error(self, error):
        QTimer.singleShot(0, lambda: self._handle_organization_error_safe(error))

    def _handle_organization_error_safe(self, error):
        self.notes_display.append(f"Error organizing notes: {error}")
        self.chat_input.setEnabled(True)

    def update_notes_display(self, organized=False):
        self.notes_display.clear()
        
        # Display current context if set
        if self.context:
            self.notes_display.append(f"<b>Current Context:</b> {self.context}<br><br>")
        
        # Show empty state if no notes
        if not self.notes and not organized:
            self.notes_display.append('<div style="text-align: center; color: #888; margin-top: 40px;">')
            self.notes_display.append('<h3>No notes yet—start typing!</h3>')
            self.notes_display.append('<p>Use the input field on the left to add your thoughts and ideas.</p>')
            self.notes_display.append('</div>')
            return
        
        if not organized:
            for note in self.notes:
                self.notes_display.append(f"{note}<br>")
        else:
            organized_notes = self.db.get_organized_notes()
            if organized_notes and len(organized_notes) > 0:
                for category, notes_list in organized_notes.items():
                    self.notes_display.append(f"<b>{category}</b>:<br>")
                    for note in notes_list:
                        self.notes_display.append(f"  • {note}<br>")
                    self.notes_display.append("<br>")
            else:
                # Fallback to showing unorganized notes if no organized notes found
                self.notes_display.append("<b>Notes (Unorganized):</b><br>")
                for note in self.notes:
                    self.notes_display.append(f"  • {note}<br>")

    def export_notes(self):
        """Export current notes to a .docx file chosen by the user."""
        # Debug: confirm the method is being called
        print("DEBUG: export_notes called")

        # If there are no notes, show a message and bail out
        if not self.notes:
            self.notes_display.append("<i>No notes to export.</i><br>")
            return

        # Default suggested filename
        default_filename = "notes_export.docx"

        # Open a Save As dialog so the user can pick the location and filename
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Notes",
            default_filename,
            "Word Document (*.docx)"
        )

        # Debug: show what the dialog returned
        print(f"DEBUG: QFileDialog returned file_path={file_path!r}, filter={selected_filter!r}")

        # If user cancelled the dialog, do nothing
        if not file_path:
            self.notes_display.append("<i>Export cancelled.</i><br>")
            return

        # Ensure the file has .docx extension
        if not file_path.lower().endswith(".docx"):
            file_path += ".docx"

        try:
            # Create a Word document
            doc = Document()

            # Title
            doc.add_heading("NaviSsurance Notes Export", level=1)

            # Context, if set
            if self.context:
                doc.add_paragraph(f"Context: {self.context}")
                doc.add_paragraph("")  # blank line

            # Add each note as a bullet point
            doc.add_paragraph("Notes:", style="Heading 2")
            for note in self.notes:
                doc.add_paragraph(note, style="List Bullet")

            # Save the document
            doc.save(file_path)

            # Let the user know it worked
            self.notes_display.append(
                f"<i>Notes exported successfully to:</i> {file_path}<br>"
            )
            print(f"DEBUG: Notes exported successfully to {file_path}")

        except Exception as e:
            # Show any error in the UI
            self.notes_display.append(
                f"<b>Error exporting notes:</b> {str(e)}<br>"
            )
            print("ERROR exporting notes:", e)
