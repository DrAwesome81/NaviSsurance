from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QPushButton,
    QLineEdit,
    QLabel,
    QFileDialog,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QComboBox,
    QCheckBox,
    QMessageBox,
    QDialog,
    QDialogButtonBox,
    QTreeWidget,
    QTreeWidgetItem,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread
from datetime import datetime
import json
import re
from core.db import DatabaseManager
from docx import Document
from fpdf import FPDF

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
        self.context = None  # Add context attribute
        self._current_note_id: int | None = None
        self._selected_note_id: int | None = None
        self._organize_in_progress = False
        self.setup_ui()
        self.refresh_notes()

    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Shared styles (keep consistent with other tabs)
        input_style = (
            "background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; "
            "padding: 8px 10px; border-radius: 6px;"
        )
        box_style = (
            "background-color: #22252c; color: #e8eaed; border: 1px solid #2e2f32; "
            "border-radius: 6px;"
        )
        btn_style = (
            "QPushButton { background-color: #FD6262; color: white; border: none; padding: 8px 12px; "
            "border-radius: 6px; font-weight: 500; }"
            "QPushButton:hover { background-color: rgba(253, 98, 98, 0.92); }"
            "QPushButton:disabled { background-color: #3a3d46; color: #9aa0a6; }"
        )
        
        # Left: Chat Window
        chat_widget = QWidget()
        chat_layout = QVBoxLayout(chat_widget)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(6)
        
        # Add context input field
        context_label = QLabel("Context (what you're working on):")
        context_label.setStyleSheet("color: #e8eaed; font-weight: 600; font-size: 13px;")
        chat_layout.addWidget(context_label)
        
        self.context_input = QLineEdit()
        self.context_input.setPlaceholderText("Enter context (e.g., 'Working on FDA protocol review')")
        self.context_input.setStyleSheet(input_style)
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
                    event.accept()
                else:
                    # Let the default QTextEdit handle other keys
                    super().keyPressEvent(event)
        
        self.chat_input = CustomTextEdit(self)
        self.chat_input.setPlaceholderText("Enter thoughts (e.g., 'Section 5 should be in the protocol; not this report')")
        self.chat_input.setStyleSheet(box_style)
        chat_layout.addWidget(self.chat_input)
        layout.addWidget(chat_widget, stretch=1)

        # Right: Notes Pane (browse + categories + detail)
        notes_widget = QWidget()
        notes_layout = QVBoxLayout(notes_widget)
        notes_layout.setContentsMargins(0, 0, 0, 0)
        notes_layout.setSpacing(6)

        # Controls row
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(6)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search notes…")
        self.search_input.setStyleSheet(input_style)
        self.search_input.textChanged.connect(self.refresh_notes)
        controls.addWidget(self.search_input, 2)

        self.context_filter = QComboBox()
        self.context_filter.addItem("All contexts")
        self.context_filter.setStyleSheet(input_style)
        self.context_filter.currentTextChanged.connect(self.refresh_notes)
        controls.addWidget(self.context_filter, 1)

        self.range_filter = QComboBox()
        self.range_filter.addItems(["All time", "Last 7 days", "Last 30 days", "Last 90 days"])
        self.range_filter.setStyleSheet(input_style)
        self.range_filter.currentTextChanged.connect(self.refresh_notes)
        controls.addWidget(self.range_filter)

        self.pinned_only = QCheckBox("Pinned only")
        self.pinned_only.stateChanged.connect(self.refresh_notes)
        controls.addWidget(self.pinned_only)

        self.reorg_btn = QPushButton("Re-organize")
        self.reorg_btn.setStyleSheet(btn_style)
        self.reorg_btn.clicked.connect(self.reorganize_notes)
        controls.addWidget(self.reorg_btn)

        export_btn = QPushButton("Export…")
        export_btn.setStyleSheet(btn_style)
        export_btn.clicked.connect(self.export_notes)
        controls.addWidget(export_btn)

        notes_layout.addLayout(controls)

        # Splitter: list + detail + categories tree
        splitter = QSplitter(Qt.Orientation.Horizontal)
        notes_layout.addWidget(splitter, 1)

        # Timeline list
        self.notes_list = QListWidget()
        self.notes_list.setStyleSheet(box_style)
        self.notes_list.itemSelectionChanged.connect(self._on_note_selected)
        splitter.addWidget(self.notes_list)

        # Detail pane
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        self.note_detail = QTextEdit()
        self.note_detail.setReadOnly(True)
        self.note_detail.setStyleSheet(box_style)
        detail_layout.addWidget(self.note_detail, 1)

        actions = QHBoxLayout()
        self.pin_btn = QPushButton("Pin/Unpin")
        self.pin_btn.setStyleSheet(btn_style)
        self.pin_btn.clicked.connect(self.toggle_pin_selected)
        actions.addWidget(self.pin_btn)
        self.edit_btn = QPushButton("Edit")
        self.edit_btn.setStyleSheet(btn_style)
        self.edit_btn.clicked.connect(self.edit_selected_note)
        actions.addWidget(self.edit_btn)
        self.del_btn = QPushButton("Delete")
        self.del_btn.setStyleSheet(btn_style)
        self.del_btn.clicked.connect(self.delete_selected_note)
        actions.addWidget(self.del_btn)
        self.retry_btn = QPushButton("Retry")
        self.retry_btn.setStyleSheet(btn_style)
        self.retry_btn.clicked.connect(self.retry_selected_note)
        actions.addWidget(self.retry_btn)
        self.move_btn = QPushButton("Move Category")
        self.move_btn.setStyleSheet(btn_style)
        self.move_btn.clicked.connect(self.move_selected_note_category)
        actions.addWidget(self.move_btn)
        self.copy_btn = QPushButton("Copy")
        self.copy_btn.setStyleSheet(btn_style)
        self.copy_btn.clicked.connect(self.copy_selected_note)
        actions.addWidget(self.copy_btn)
        self.task_btn = QPushButton("Create Task")
        self.task_btn.setStyleSheet(btn_style)
        self.task_btn.clicked.connect(self.create_task_from_selected)
        actions.addWidget(self.task_btn)
        self.remember_btn = QPushButton("Remember")
        self.remember_btn.setStyleSheet(btn_style)
        self.remember_btn.clicked.connect(self.remember_selected_note)
        actions.addWidget(self.remember_btn)
        actions.addStretch()
        detail_layout.addLayout(actions)
        splitter.addWidget(detail)

        # Categories tree (collapsible + clickable)
        self.categories_tree = QTreeWidget()
        self.categories_tree.setHeaderLabels(["Category / Note"])
        self.categories_tree.setStyleSheet(box_style)
        self.categories_tree.itemClicked.connect(self._on_category_item_clicked)
        splitter.addWidget(self.categories_tree)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 3)

        layout.addWidget(notes_widget, stretch=2)
        self.setLayout(layout)

    def update_context(self):
        """Update the context and notify Navi."""
        self.context = self.context_input.text().strip()
        if self.context:
            self.context_input.clear()
            self.db.clear_organized_notes()
            self.refresh_notes()

    def process_note(self):
        content = self.chat_input.toPlainText().strip()
        if not content or len(content) < 10:
            return

        # Create a draft row so text is never lost.
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        note_id = self.db.create_note_draft(raw_note=content, timestamp=ts, context=self.context)
        self._current_note_id = note_id or None
        self.refresh_notes()
        self._start_formatting_for_note(note_id=note_id, raw_text=content, context=self.context)

        # Disable input while processing
        self.chat_input.setEnabled(False)
        # Keep raw text in the input until formatting succeeds (user can copy it if needed).
        QTimer.singleShot(0, lambda: None)

    def _start_formatting_for_note(self, *, note_id: int, raw_text: str, context: str | None) -> None:
        """Start formatting for an existing note row (draft or retry)."""
        context_info = f"Context: {context}" if context else "No context set"
        prompt = f"""{context_info}. 

INSTRUCTION: Take the user's note and format it into a clear, professional note.

USER'S NOTE: '{raw_text}'

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

        try:
            self.db.update_note_by_id(int(note_id), raw_note=raw_text, state="pending", error_text=None)
        except Exception:
            pass
        self.note_thread = NoteProcessingThread(self.chat_handler, prompt, "notes_session")
        self.note_thread.result_signal.connect(lambda resp, nid=note_id: self.handle_note_formatted(resp, nid))
        self.note_thread.error_signal.connect(self.handle_note_error)
        self.note_thread.start()

    def handle_note_formatted(self, response, note_id: int):
        QTimer.singleShot(0, lambda: self._handle_note_formatted_safe(response, note_id))

    def _handle_note_formatted_safe(self, response, note_id: int):
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
                try:
                    self.db.update_note_by_id(
                        int(note_id),
                        formatted_note=str(formatted).strip(),
                        state="ready",
                        error_text=None,
                        category="Uncategorized",
                    )
                except Exception:
                    pass
                self.refresh_notes()

                # Re-enable input
                self.chat_input.setEnabled(True)
                self.chat_input.clear()
                self.chat_input.setFocus()

                # Trigger organization if enough notes
                self.maybe_auto_organize()
            else:
                # Only hit this if *all* attempts to salvage text failed
                try:
                    self.db.update_note_by_id(int(note_id), state="error", error_text="Could not parse formatting response")
                except Exception:
                    pass
                QMessageBox.warning(self, "Notes", "Could not parse note formatting response. The raw text was saved; select the note and click Retry.")
                self.refresh_notes()
                self.chat_input.setEnabled(True)

        except Exception as e:
            # Hard failure – show the error and the raw response to help debugging
            try:
                self.db.update_note_by_id(int(note_id), state="error", error_text=str(e))
            except Exception:
                pass
            QMessageBox.warning(self, "Notes", f"Error processing note: {e}")
            self.refresh_notes()
        finally:
            # Make absolutely sure input is enabled again
            self.chat_input.setEnabled(True)

    def handle_note_error(self, error):
        QTimer.singleShot(0, lambda: self._handle_note_error_safe(error))

    def _handle_note_error_safe(self, error):
        if self._current_note_id:
            try:
                self.db.update_note_by_id(int(self._current_note_id), state="error", error_text=str(error))
            except Exception:
                pass
        QMessageBox.warning(self, "Notes", f"Error processing note: {error}")
        self.refresh_notes()
        self.chat_input.setEnabled(True)

    # -------------------------------------------------------------------------
    # Browsing / UI helpers
    # -------------------------------------------------------------------------

    def _active_context_filter(self) -> str | None:
        c = (self.context_filter.currentText() or "").strip()
        if not c or c == "All contexts":
            return None
        return c

    def _active_range_days(self) -> int | None:
        t = (self.range_filter.currentText() or "").strip().lower()
        if "7" in t:
            return 7
        if "30" in t:
            return 30
        if "90" in t:
            return 90
        return None

    @staticmethod
    def _note_ts_in_days(note_ts: str, days: int) -> bool:
        try:
            dt = datetime.strptime((note_ts or "").strip(), "%Y-%m-%d %H:%M:%S")
            return (datetime.now() - dt).days <= int(days)
        except Exception:
            return True

    def refresh_notes(self):
        """Reload notes from DB into list, context dropdown, and category view."""
        try:
            # Populate contexts dropdown
            all_notes = self.db.list_notes(limit=500)
            contexts = sorted({(n.get("context") or "").strip() for n in all_notes if (n.get("context") or "").strip()})
            cur = self.context_filter.currentText()
            self.context_filter.blockSignals(True)
            self.context_filter.clear()
            self.context_filter.addItem("All contexts")
            for c in contexts:
                self.context_filter.addItem(c)
            if cur and cur in contexts:
                self.context_filter.setCurrentText(cur)
            self.context_filter.blockSignals(False)

            ctx = self._active_context_filter()
            days = self._active_range_days()
            query = (self.search_input.text() or "").strip()
            if query:
                notes = self.db.search_notes(query=query, context=ctx, limit=500)
            else:
                notes = self.db.list_notes(context=ctx, limit=500)
            if days is not None:
                notes = [n for n in notes if self._note_ts_in_days(n.get("timestamp") or "", int(days))]
            if self.pinned_only.isChecked():
                notes = [n for n in notes if int(n.get("pinned") or 0) == 1]

            self.notes_list.clear()
            for n in notes:
                nid = int(n["id"])
                ts = (n.get("timestamp") or "").strip()
                cat = (n.get("category") or "Uncategorized").strip()
                state = (n.get("state") or "ready").strip()
                pin = "📌 " if int(n.get("pinned") or 0) else ""
                preview = (n.get("formatted_note") or n.get("raw_note") or "").strip().replace("\n", " ")
                if len(preview) > 90:
                    preview = preview[:87] + "…"
                label = f"{pin}{ts} [{cat}] ({state}) {preview}"
                it = QListWidgetItem(label)
                it.setData(Qt.ItemDataRole.UserRole, nid)
                self.notes_list.addItem(it)

            # Keep selection if possible
            if self._selected_note_id:
                for i in range(self.notes_list.count()):
                    it = self.notes_list.item(i)
                    if int(it.data(Qt.ItemDataRole.UserRole)) == int(self._selected_note_id):
                        self.notes_list.setCurrentItem(it)
                        break

            self._render_categories(notes)
            if self._selected_note_id:
                self._render_note_detail(self._selected_note_id)
            elif self.notes_list.count() > 0:
                self.notes_list.setCurrentRow(0)
        except Exception as e:
            try:
                self.note_detail.setPlainText(f"Error loading notes: {e}")
            except Exception:
                pass

    def _on_note_selected(self):
        items = self.notes_list.selectedItems()
        if not items:
            self._selected_note_id = None
            self.note_detail.setPlainText("")
            return
        nid = int(items[0].data(Qt.ItemDataRole.UserRole))
        self._selected_note_id = nid
        self._render_note_detail(nid)

    def _render_note_detail(self, note_id: int):
        # Find note from DB
        note = None
        try:
            all_notes = self.db.list_notes(limit=2000)
            for n in all_notes:
                if int(n.get("id") or 0) == int(note_id):
                    note = n
                    break
        except Exception:
            note = None

        if not note:
            self.note_detail.setPlainText("(Note not found)")
            return
        formatted = (note.get("formatted_note") or "").strip()
        raw = (note.get("raw_note") or "").strip()
        ctx = (note.get("context") or "").strip()
        cat = (note.get("category") or "Uncategorized").strip()
        ts = (note.get("timestamp") or "").strip()
        state = (note.get("state") or "ready").strip()
        err = (note.get("error_text") or "").strip()
        pinned = bool(int(note.get("pinned") or 0))
        parts = [
            f"ID: {note_id}",
            f"Timestamp: {ts}",
            f"Context: {ctx or '(none)'}",
            f"Category: {cat}",
            f"Pinned: {'Yes' if pinned else 'No'}",
            f"State: {state}",
        ]
        if err:
            parts.append(f"Error: {err}")
        parts.append("\n---\nFormatted:\n" + (formatted or "(empty)"))
        if raw and raw != formatted:
            parts.append("\n---\nRaw:\n" + raw)
        self.note_detail.setPlainText("\n".join(parts))

    def toggle_pin_selected(self):
        if not self._selected_note_id:
            return
        try:
            # Fetch current pinned state
            notes = self.db.list_notes(limit=2000)
            cur = 0
            for n in notes:
                if int(n["id"]) == int(self._selected_note_id):
                    cur = int(n.get("pinned") or 0)
                    break
            self.db.update_note_by_id(int(self._selected_note_id), pinned=0 if cur else 1)
        except Exception:
            pass
        self.refresh_notes()

    def edit_selected_note(self):
        if not self._selected_note_id:
            return
        # Load note
        note = None
        for n in self.db.list_notes(limit=2000):
            if int(n["id"]) == int(self._selected_note_id):
                note = n
                break
        if not note:
            return

        class _EditDialog(QDialog):
            def __init__(self, parent, note_dict: dict):
                super().__init__(parent)
                self.setWindowTitle("Edit Note")
                self._note = note_dict
                lay = QVBoxLayout(self)
                self.text = QTextEdit(self)
                self.text.setPlainText(note_dict.get("formatted_note") or "")
                lay.addWidget(self.text)
                row = QHBoxLayout()
                row.addWidget(QLabel("Category:"))
                self.cat = QLineEdit(self)
                self.cat.setText(note_dict.get("category") or "Uncategorized")
                row.addWidget(self.cat)
                lay.addLayout(row)
                btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
                btns.accepted.connect(self.accept)
                btns.rejected.connect(self.reject)
                lay.addWidget(btns)

            def values(self) -> tuple[str, str]:
                return (self.text.toPlainText() or "").strip(), (self.cat.text() or "").strip()

        dlg = _EditDialog(self, note)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        text, cat = dlg.values()
        if not text:
            return
        if not cat:
            cat = "Uncategorized"
        try:
            self.db.update_note_by_id(int(self._selected_note_id), formatted_note=text, category=cat, state="ready", error_text=None)
        except Exception:
            pass
        self.refresh_notes()

    def delete_selected_note(self):
        if not self._selected_note_id:
            return
        reply = QMessageBox.question(
            self,
            "Delete Note",
            "Delete this note? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self.db.delete_note_by_id(int(self._selected_note_id))
        except Exception:
            pass
        self._selected_note_id = None
        self.refresh_notes()

    def retry_selected_note(self):
        if not self._selected_note_id:
            return
        # Re-run formatting on raw note
        note = None
        for n in self.db.list_notes(limit=2000):
            if int(n["id"]) == int(self._selected_note_id):
                note = n
                break
        if not note:
            return
        raw = (note.get("raw_note") or "").strip() or (note.get("formatted_note") or "").strip()
        if not raw:
            return
        self._current_note_id = int(self._selected_note_id)
        self._start_formatting_for_note(note_id=int(self._selected_note_id), raw_text=raw, context=note.get("context"))
        self.chat_input.setEnabled(False)

    def create_task_from_selected(self):
        if not self._selected_note_id:
            return
        note = None
        for n in self.db.list_notes(limit=2000):
            if int(n["id"]) == int(self._selected_note_id):
                note = n
                break
        if not note:
            return
        text = (note.get("formatted_note") or "").strip()
        if not text:
            return

        class _TaskDialog(QDialog):
            def __init__(self, parent, default_text: str):
                super().__init__(parent)
                self.setWindowTitle("Create Task")
                lay = QVBoxLayout(self)
                lay.addWidget(QLabel("Task text:"))
                self.task = QTextEdit(self)
                self.task.setPlainText(default_text)
                lay.addWidget(self.task)
                row = QHBoxLayout()
                row.addWidget(QLabel("Due (MM-DD-YYYY or blank):"))
                self.due = QLineEdit(self)
                row.addWidget(self.due)
                row.addWidget(QLabel("Category:"))
                self.cat = QComboBox(self)
                self.cat.addItems(["Business", "Personal"])
                row.addWidget(self.cat)
                lay.addLayout(row)
                btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
                btns.accepted.connect(self.accept)
                btns.rejected.connect(self.reject)
                lay.addWidget(btns)

            def values(self):
                return (self.task.toPlainText() or "").strip(), (self.due.text() or "").strip(), (self.cat.currentText() or "Business").strip()

        dlg = _TaskDialog(self, text[:4000])
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        task_text, due, cat = dlg.values()
        if not task_text:
            return
        due_val = due if due else None
        try:
            self.db.add_task("notes_session", task_text, due_val, category=cat)
            QMessageBox.information(self, "Notes", "Task created.")
        except Exception as e:
            QMessageBox.warning(self, "Notes", f"Failed to create task: {e}")

    def remember_selected_note(self):
        if not self._selected_note_id:
            return
        note = None
        for n in self.db.list_notes(limit=2000):
            if int(n["id"]) == int(self._selected_note_id):
                note = n
                break
        if not note:
            return
        content = (note.get("formatted_note") or "").strip()
        if not content:
            return
        try:
            payload = {
                "note_id": int(self._selected_note_id),
                "context": note.get("context"),
                "timestamp": note.get("timestamp"),
                "category": note.get("category"),
            }
            self.db.cos_memory_add(chat_id=None, kind="note", content=content, json_data=json.dumps(payload))
            QMessageBox.information(self, "Notes", "Saved to Navi memory.")
        except Exception as e:
            QMessageBox.warning(self, "Notes", f"Could not save to memory: {e}")

    def maybe_auto_organize(self):
        """Auto-organize when there are at least 2 ready notes in the active context."""
        try:
            ctx = self._active_context_filter()
            notes = self.db.list_notes(context=ctx, limit=2000)
            ready = [n for n in notes if (n.get("state") or "") == "ready"]
            if len(ready) >= 2:
                self.reorganize_notes()
        except Exception:
            return

    def reorganize_notes(self):
        if self._organize_in_progress:
            return
        self._organize_in_progress = True
        try:
            ctx = self._active_context_filter()
            notes = self.db.list_notes(context=ctx, limit=2000)
            ready = [n for n in notes if (n.get("state") or "") == "ready"]
            if len(ready) < 2:
                self._organize_in_progress = False
                return

            # Build prompt using stable IDs to avoid ambiguity
            items = [{"id": int(n["id"]), "text": (n.get("formatted_note") or "").strip()} for n in ready if (n.get("formatted_note") or "").strip()]
            context_info = f"Context: {ctx}" if ctx else "No context set"
            prompt = f"""{context_info}.

INSTRUCTION: Categorize the existing notes into logical groups.

NOTES (id + text):
{json.dumps(items, ensure_ascii=False)}

RULES:
- Use ONLY the provided note IDs (integers).
- Do not invent notes or IDs.
- Create 2+ categories if there are clear themes; otherwise return empty JSON.
- Keep category names short.

RESPONSE FORMAT: Return ONLY valid JSON:
{{"categories": {{"Category Name": [1, 2, 3], "Another": [4]}}}}
or if no clear patterns:
{{}}
"""
            self.organize_thread = NoteProcessingThread(self.chat_handler, prompt, "notes_session")
            self.organize_thread.result_signal.connect(self.handle_organization_result)
            self.organize_thread.error_signal.connect(self.handle_organization_error)
            self.organize_thread.start()
        except Exception:
            self._organize_in_progress = False
            raise

    def handle_organization_result(self, response):
        QTimer.singleShot(0, lambda: self._handle_organization_result_safe(response))

    def _handle_organization_result_safe(self, response):
        try:
            organized_data, success = robust_json_parse(response, logger=print)
            if not success or organized_data is None:
                QMessageBox.information(self, "Notes", "No clear categories found.")
                return
            
            cats = organized_data.get("categories") if isinstance(organized_data, dict) else None
            if isinstance(cats, dict) and cats:
                # Persist organized view (ids), and also write category onto each note row.
                self.db.save_organized_notes(cats)
                # Reset categories then apply
                for cat, ids in cats.items():
                    if not isinstance(ids, list):
                        continue
                    for nid in ids:
                        try:
                            self.db.update_note_by_id(int(nid), category=str(cat), state="ready", error_text=None)
                        except Exception:
                            continue
                QMessageBox.information(self, "Notes", f"Organized into {len(cats)} categories.")
            else:
                QMessageBox.information(self, "Notes", "No clear categories found.")
        except Exception as e:
            print(f"DEBUG: Unexpected error: {e}")
        finally:
            self._organize_in_progress = False
            self.refresh_notes()

    def handle_organization_error(self, error):
        QTimer.singleShot(0, lambda: self._handle_organization_error_safe(error))

    def _handle_organization_error_safe(self, error):
        self._organize_in_progress = False
        QMessageBox.warning(self, "Notes", f"Error organizing notes: {error}")

    def _render_categories(self, notes: list[dict]) -> None:
        """Render categories into a collapsible tree."""
        try:
            self.categories_tree.clear()
            groups: dict[str, list[dict]] = {}
            for n in notes:
                if (n.get("state") or "") != "ready":
                    continue
                cat = (n.get("category") or "Uncategorized").strip() or "Uncategorized"
                groups.setdefault(cat, []).append(n)
            for cat in sorted(groups.keys(), key=lambda s: s.lower()):
                top = QTreeWidgetItem([f"{cat} ({len(groups[cat])})"])
                top.setData(0, Qt.ItemDataRole.UserRole, None)
                self.categories_tree.addTopLevelItem(top)
                # Sort within category: pinned first, newest first
                def _k(n):
                    return (int(n.get("pinned") or 0), str(n.get("timestamp") or ""))
                for n in sorted(groups[cat], key=_k, reverse=True):
                    nid = int(n["id"])
                    text = (n.get("formatted_note") or "").strip().replace("\n", " ")
                    if len(text) > 120:
                        text = text[:117] + "…"
                    child = QTreeWidgetItem([f"{nid}: {text}"])
                    child.setData(0, Qt.ItemDataRole.UserRole, nid)
                    top.addChild(child)
                top.setExpanded(True)
        except Exception:
            return

    def _on_category_item_clicked(self, item, column):
        try:
            nid = item.data(0, Qt.ItemDataRole.UserRole)
            if nid:
                # Select in timeline list and render
                self._selected_note_id = int(nid)
                self._render_note_detail(int(nid))
        except Exception:
            return

    def move_selected_note_category(self):
        if not self._selected_note_id:
            return
        # Suggest existing categories
        notes = self.db.list_notes(limit=2000)
        cats = sorted({(n.get("category") or "Uncategorized").strip() for n in notes if (n.get("category") or "").strip()})
        cur = ""
        for n in notes:
            if int(n["id"]) == int(self._selected_note_id):
                cur = (n.get("category") or "Uncategorized").strip()
                break

        class _MoveDialog(QDialog):
            def __init__(self, parent, categories: list[str], current: str):
                super().__init__(parent)
                self.setWindowTitle("Move Note to Category")
                lay = QVBoxLayout(self)
                lay.addWidget(QLabel("Category:"))
                self.combo = QComboBox(self)
                self.combo.setEditable(True)
                for c in categories:
                    self.combo.addItem(c)
                if current:
                    self.combo.setCurrentText(current)
                lay.addWidget(self.combo)
                btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
                btns.accepted.connect(self.accept)
                btns.rejected.connect(self.reject)
                lay.addWidget(btns)

            def value(self) -> str:
                return (self.combo.currentText() or "").strip()

        dlg = _MoveDialog(self, cats, cur)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_cat = dlg.value() or "Uncategorized"
        try:
            self.db.update_note_by_id(int(self._selected_note_id), category=new_cat)
        except Exception:
            pass
        self.refresh_notes()

    def copy_selected_note(self):
        if not self._selected_note_id:
            return
        note = None
        for n in self.db.list_notes(limit=2000):
            if int(n["id"]) == int(self._selected_note_id):
                note = n
                break
        if not note:
            return
        text = (note.get("formatted_note") or "").strip()
        if not text:
            return
        try:
            from PyQt6.QtWidgets import QApplication
            QApplication.clipboard().setText(text)
            QMessageBox.information(self, "Notes", "Copied to clipboard.")
        except Exception:
            pass

    def export_notes(self):
        """Export notes to DOCX, Markdown, or PDF."""
        ctx = self._active_context_filter()
        notes = self.db.list_notes(context=ctx, limit=5000)
        notes = [n for n in notes if (n.get("state") or "") == "ready"]
        if not notes:
            QMessageBox.information(self, "Export", "No notes to export.")
            return
        default_filename = "notes_export.docx"
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Notes",
            default_filename,
            "Word Document (*.docx);;Markdown (*.md);;PDF (*.pdf)",
        )
        if not file_path:
            return
        ext = file_path.lower().rsplit(".", 1)[-1] if "." in file_path else ""
        if selected_filter.startswith("Word") or ext == "docx":
            if not file_path.lower().endswith(".docx"):
                file_path += ".docx"
            doc = Document()
            doc.add_heading("NaviSsurance Notes Export", level=1)
            if ctx:
                doc.add_paragraph(f"Context: {ctx}")
            doc.add_paragraph(f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            doc.add_paragraph("")
            for n in notes:
                ts = n.get("timestamp") or ""
                cat = n.get("category") or "Uncategorized"
                text = (n.get("formatted_note") or "").strip()
                doc.add_paragraph(f"[{ts}] ({cat}) {text}", style="List Bullet")
            doc.save(file_path)
            QMessageBox.information(self, "Export", f"Exported to {file_path}")
            return
        if selected_filter.startswith("Markdown") or ext == "md":
            if not file_path.lower().endswith(".md"):
                file_path += ".md"
            lines = []
            lines.append("# NaviSsurance Notes Export")
            if ctx:
                lines.append(f"**Context:** {ctx}")
            lines.append(f"**Exported:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            lines.append("")
            # Group by category
            groups: dict[str, list[dict]] = {}
            for n in notes:
                groups.setdefault((n.get("category") or "Uncategorized").strip() or "Uncategorized", []).append(n)
            for cat in sorted(groups.keys(), key=lambda s: s.lower()):
                lines.append(f"## {cat}")
                for n in sorted(groups[cat], key=lambda x: str(x.get("timestamp") or "")):
                    ts = n.get("timestamp") or ""
                    text = (n.get("formatted_note") or "").strip().replace("\n", " ")
                    lines.append(f"- [{ts}] {text}")
                lines.append("")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines).rstrip() + "\n")
            QMessageBox.information(self, "Export", f"Exported to {file_path}")
            return
        # PDF
        if not file_path.lower().endswith(".pdf"):
            file_path += ".pdf"
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        pdf.set_font("Helvetica", size=14)
        pdf.multi_cell(0, 8, "NaviSsurance Notes Export")
        pdf.ln(2)
        pdf.set_font("Helvetica", size=10)
        if ctx:
            pdf.multi_cell(0, 6, f"Context: {ctx}")
        pdf.multi_cell(0, 6, f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        pdf.ln(2)
        pdf.set_font("Helvetica", size=11)
        # Group by category
        groups: dict[str, list[dict]] = {}
        for n in notes:
            groups.setdefault((n.get("category") or "Uncategorized").strip() or "Uncategorized", []).append(n)
        for cat in sorted(groups.keys(), key=lambda s: s.lower()):
            pdf.set_font("Helvetica", style="B", size=12)
            pdf.multi_cell(0, 7, cat)
            pdf.set_font("Helvetica", size=11)
            for n in sorted(groups[cat], key=lambda x: str(x.get("timestamp") or "")):
                ts = n.get("timestamp") or ""
                text = (n.get("formatted_note") or "").strip().replace("\n", " ")
                pdf.multi_cell(0, 6, f"- [{ts}] {text}")
            pdf.ln(1)
        pdf.output(file_path)
        QMessageBox.information(self, "Export", f"Exported to {file_path}")
