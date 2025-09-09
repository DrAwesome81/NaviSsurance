from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QLineEdit, QLabel, QTextBrowser
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt6.QtGui import QKeyEvent
from datetime import datetime
import json
import re
from core.db import DatabaseManager
from core.api import DropboxClient
from docx import Document
from fpdf import FPDF
from dropbox import files
import os

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
        self.dropbox_client = DropboxClient()
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

TASK: Take the user's note and format it into a clear, professional note.

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
        try:
            response_clean = response.strip()
            if not response_clean.startswith('{'):
                import re
                json_match = re.search(r'\\{.*\\}', response_clean, re.DOTALL)
                if json_match:
                    response_clean = json_match.group(0)
            
            note_data = json.loads(response_clean)
            formatted = note_data['formatted']
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
        except json.JSONDecodeError:
            self.notes_display.append("Error: Invalid response format")
            self.notes_display.append(f"Raw response: {response}")
        except Exception as e:
            self.notes_display.append(f"Error: {str(e)}")
        finally:
            self.chat_input.setEnabled(True)

    def handle_note_error(self, error):
        self.notes_display.append(f"Error processing note: {error}")
        self.chat_input.setEnabled(True)

    def try_organize_notes(self):
        if sum(len(note) for note in self.notes) > 7000:  # Approximate token limit check
            self.notes_display.append("Warning: Notes may exceed token limit; categorization skipped.")
            return
        
        context_info = f"Context: {self.context}" if self.context else "No context set"
        prompt = f"""{context_info}. 

TASK: Categorize the existing notes into logical groups.

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
        try:
            response_clean = response.strip()
            print(f"DEBUG: Original response length: {len(response)}")
            print(f"DEBUG: Cleaned response: '{response_clean}'")
            
            if not response_clean.startswith('{'):
                json_match = re.search(r'\\{.*\\}', response_clean, re.DOTALL)
                if json_match:
                    response_clean = json_match.group(0)
                    print(f"DEBUG: Extracted JSON: '{response_clean}'")
            
            if response_clean.count('"') % 2 != 0 or not response_clean.endswith('}'):
                self.notes_display.append("Warning: Response appears to be truncated, skipping categorization.")
                print(f"DEBUG: Response appears truncated - quote count: {response_clean.count('"')}, ends with '}}': {response_clean.endswith('}')}")
                self.chat_input.setEnabled(True)
                return
            
            try:
                organized_data = json.loads(response_clean)
                print(f"DEBUG: Successfully parsed JSON: {organized_data}")
            except json.JSONDecodeError as json_err:
                print(f"DEBUG: JSON decode error: {json_err}")
                response_clean = response_clean.replace('\n', ' ').replace('\r', ' ')
                response_clean = re.sub(r'\s+', ' ', response_clean)
                response_clean = re.sub(r',\s*}', '}', response_clean)
                response_clean = re.sub(r'"\s*}', '}', response_clean)
                response_clean = response_clean.rstrip("'\"")
                print(f"DEBUG: Attempting to fix JSON: '{response_clean}'")
                organized_data = json.loads(response_clean)
                print(f"DEBUG: Successfully parsed fixed JSON: {organized_data}")
            
            if 'categories' in organized_data and organized_data['categories']:
                self.organized = True
                self.db.save_organized_notes(organized_data['categories'])
                self.notes_display.append(f"<i>Notes organized into {len(organized_data['categories'])} categories</i><br>")
                self.update_notes_display()
            else:
                self.notes_display.append("<i>No clear categories found, showing unorganized notes</i><br>")
                self.update_notes_display(organized=False)
        except json.JSONDecodeError as json_err:
            self.notes_display.append("Error: Invalid organization format")
            self.notes_display.append(f"Raw response: {response}")
            print(f"DEBUG: Final JSON decode error: {json_err}")
        except Exception as e:
            self.notes_display.append(f"Error: {str(e)}")
            print(f"DEBUG: Unexpected error: {e}")
        finally:
            self.chat_input.setEnabled(True)

    def handle_organization_error(self, error):
        self.notes_display.append(f"Error organizing notes: {error}")
        self.chat_input.setEnabled(True)

    def update_notes_display(self, organized=False):
        self.notes_display.clear()
        
        # Display current context if set
        if self.context:
            self.notes_display.append(f"<b>Current Context:</b> {self.context}<br><br>")
        
        if not organized:
            for note in self.notes:
                self.notes_display.append(f"{note}<br>")
        else:
            organized_notes = self.db.get_organized_notes()
            if organized_notes and len(organized_notes) > 0:
                for category, notes_list in organized_notes.items():
                    self.notes_display.append(f"<b>{category}</b>:<br>")
                    for note in notes_list:
                        self.notes_display.append(f"  â€¢ {note}<br>")
                    self.notes_display.append("<br>")
            else:
                # Fallback to showing unorganized notes if no organized notes found
                self.notes_display.append("<b>Notes (Unorganized):</b><br>")
                for note in self.notes:
                    self.notes_display.append(f"  â€¢ {note}<br>")

    def export_notes(self):
        organized_notes = self.db.get_organized_notes() or {"Uncategorized": self.notes}
        if not organized_notes:
            self.notes_display.append("No notes to export.")
            return
        
        # Export as TXT
        txt_path = "notes_export.txt"
        with open(txt_path, "w", encoding='utf-8') as f:
            if self.context:
                f.write(f"Context: {self.context}\n\n")
            for category, notes_list in organized_notes.items():
                f.write(f"{category}:\n")
                for note in notes_list:
                    f.write(f"- {note}\n")
                f.write("\n")
        
        # Export as Word (.docx)
        doc = Document()
        if self.context:
            doc.add_heading(f"Context: {self.context}", level=1)
            doc.add_paragraph("")  # Add some space
        for category, notes_list in organized_notes.items():
            doc.add_heading(category, level=1)
            for note in notes_list:
                doc.add_paragraph(note, style='ListBullet')
        docx_path = "notes_export.docx"
        doc.save(docx_path)
        
        # Export as PDF
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        if self.context:
            pdf.set_font("Arial", "B", 16)
            pdf.cell(0, 10, f"Context: {self.context}", ln=True)
            pdf.ln(5)
        for category, notes_list in organized_notes.items():
            pdf.set_font("Arial", "B", 16)
            pdf.cell(0, 10, category, ln=True)
            pdf.set_font("Arial", size=12)
            for note in notes_list:
                pdf.multi_cell(0, 10, f"- {note}")
            pdf.ln(5)
        pdf_path = "notes_export.pdf"
        pdf.output(pdf_path)
        
        # Upload to Dropbox
        try:
            for local_path in [txt_path, docx_path, pdf_path]:
                remote_path = f"/NaviSsurance Exports/{os.path.basename(local_path)}"
                with open(local_path, "rb") as f:
                    self.dropbox_client.dbx.files_upload(f.read(), remote_path, mode=files.WriteMode('overwrite'))
            self.notes_display.append("Notes exported to Dropbox successfully.")
        except Exception as e:
            self.notes_display.append(f"Error uploading to Dropbox: {str(e)}")
