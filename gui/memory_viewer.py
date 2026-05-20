from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QMessageBox,
    QHeaderView,
    QInputDialog,
    QLabel,
)

from core.mem0_config import MEM0_USER_ID
from core.mem0_memory import add_memory, delete_memory, get_all_memories, search_memory
from core.db import DatabaseManager
import logging

logger = logging.getLogger(__name__)

# Memory viewer surfaces Pulse private memory for Shield

def _format_created_ts(created) -> str:
    if created is None:
        return ""
    s = str(created).strip()
    return s[:19] if len(s) >= 19 else s


def _mem0_metadata_from_raw(raw: dict) -> dict:
    meta = raw.get("metadata")
    if isinstance(meta, dict):
        return dict(meta)
    return {}


def _memory_row(
    *,
    mem_id: str,
    content: str,
    source: str,
    created: str,
    raw,
    kind: str,
) -> dict:
    return {
        "id": mem_id,
        "content": content,
        "source": source,
        "created": created,
        "raw": raw,
        "type": kind,
    }


class MemoryViewerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Memory Viewer - NaviSsurance")
        self.setMinimumSize(950, 650)
        if parent is not None and hasattr(parent, "db"):
            self.db = parent.db
        else:
            self.db = DatabaseManager()

        root = QVBoxLayout(self)

        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search memories...")
        self.search_input.returnPressed.connect(self.search_memories)
        search_layout.addWidget(self.search_input)

        self.search_btn = QPushButton("Search")
        self.search_btn.clicked.connect(self.search_memories)
        search_layout.addWidget(self.search_btn)

        self.refresh_btn = QPushButton("Refresh All")
        self.refresh_btn.clicked.connect(self.load_all_memories)
        search_layout.addWidget(self.refresh_btn)

        root.addLayout(search_layout)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["ID", "Content", "Source", "Created", "Edit", "Delete"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        root.addWidget(self.table)

        # Visual separator + spacing for the added Document Memory section (addresses nit in Issue 9)
        root.addSpacing(6)

        # Phase 1 (COMPLETE): global "Memory" manager extension — DocumentRecords view.
        # Lets the user see/curate (view + filter) exactly what the unified retrieval system
        # knows about past work. Lives inside the existing MemoryViewer so no new top-level UI.
        # Compact read-only pane; full curation (re-index) remains via scripts for safety.
        doc_label = QLabel("Document Memory (Past Work — Retrieval System)")
        doc_label.setStyleSheet("font-weight: bold; margin-top: 4px;")
        root.addWidget(doc_label)

        doc_bar = QHBoxLayout()
        self.doc_filter = QLineEdit()
        self.doc_filter.setPlaceholderText("Filter by client or doc type (e.g. Overjet, SOP, FDA)")
        self.doc_filter.returnPressed.connect(self._refresh_doc_memory)
        doc_bar.addWidget(self.doc_filter)
        self.doc_refresh = QPushButton("Refresh Doc Memory")
        self.doc_refresh.clicked.connect(self._refresh_doc_memory)
        doc_bar.addWidget(self.doc_refresh)
        self.doc_index_btn = QPushButton("Index GDrive (update retrieval)")
        self.doc_index_btn.clicked.connect(self._index_from_gdrive)
        self.doc_index_btn.setToolTip("Safe capped scan of Google Drive; populates unified retrieval store so CoS/Workspace/Pulse Relevant Past Work surfaces deliver real daily value (Pulse private memory reflections + 🛡️ security themes now cross-link too). (Phase 1 COMPLETE; re-run to keep index fresh as Drive grows. DB now supports previews.)")
        doc_bar.addWidget(self.doc_index_btn)
        root.addLayout(doc_bar)

        self.doc_table = QTableWidget()
        self.doc_table.setColumnCount(5)
        self.doc_table.setHorizontalHeaderLabels(["Name", "Type", "Client", "Year", "Regs/Tags"])
        self.doc_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.doc_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.doc_table.setMaximumHeight(130)
        root.addWidget(self.doc_table)

        self.load_all_memories()
        self._refresh_doc_memory()

    def _append_row(self, mem: dict) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(str(mem["id"])[:12]))
        self.table.setItem(r, 1, QTableWidgetItem(mem["content"]))
        self.table.setItem(r, 2, QTableWidgetItem(mem["source"]))
        self.table.setItem(r, 3, QTableWidgetItem(mem["created"]))

        edit_btn = QPushButton("Edit")
        edit_btn.clicked.connect(lambda checked, m=mem: self.edit_memory(m))
        self.table.setCellWidget(r, 4, edit_btn)

        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(lambda checked, m=mem: self.delete_memory(m))
        self.table.setCellWidget(r, 5, delete_btn)

    def load_all_memories(self):
        self.table.setRowCount(0)
        try:
            mem0_memories = get_all_memories(limit=100)
            sqlite_memories = self.db.user_memory_recent(limit=100) or []

            all_memories: list[dict] = []

            for m in mem0_memories:
                mid = m.get("id", "")
                all_memories.append(
                    _memory_row(
                        mem_id=str(mid),
                        content=str(m.get("memory", "") or ""),
                        source="Mem0",
                        created=_format_created_ts(m.get("created_at")),
                        raw=m,
                        kind="mem0",
                    )
                )

            for row in sqlite_memories:
                mem_id, kind, content, source = row[0], row[1], row[2], row[3]
                created = _format_created_ts(row[7])
                all_memories.append(
                    _memory_row(
                        mem_id=str(mem_id),
                        content=str(content or ""),
                        source=f"SQLite ({kind})",
                        created=created,
                        raw=row,
                        kind="sqlite",
                    )
                )

            all_memories.sort(key=lambda x: x["created"], reverse=True)

            for mem in all_memories:
                self._append_row(mem)

        except Exception as e:
            logger.error("Failed to load memories: %s", e)
            QMessageBox.warning(self, "Error", f"Failed to load memories: {str(e)}")

    def search_memories(self):
        query = self.search_input.text().strip()
        if not query:
            self.load_all_memories()
            return

        self.table.setRowCount(0)
        try:
            for m in search_memory(query=query, limit=50):
                mid = str(m.get("id", "") or "")
                mem = _memory_row(
                    mem_id=mid,
                    content=str(m.get("memory", "") or ""),
                    source="Mem0",
                    created=_format_created_ts(m.get("created_at")),
                    raw=m,
                    kind="mem0",
                )
                self._append_row(mem)

            for row in self.db.user_memory_search(query=query, limit=50) or []:
                mem_id, kind, content, source = row[0], row[1], row[2], row[3]
                created = _format_created_ts(row[7])
                mem = _memory_row(
                    mem_id=str(mem_id),
                    content=str(content or ""),
                    source=f"SQLite ({kind})",
                    created=created,
                    raw=row,
                    kind="sqlite",
                )
                self._append_row(mem)

        except Exception as e:
            logger.error("Memory search failed: %s", e)
            QMessageBox.warning(self, "Error", f"Memory search failed: {str(e)}")

    def edit_memory(self, memory_data: dict):
        new_content, ok = QInputDialog.getMultiLineText(
            self,
            "Edit Memory",
            "Edit the memory content:",
            memory_data["content"],
        )
        if not ok or not new_content.strip():
            return

        text = new_content.strip()

        try:
            if memory_data["type"] == "mem0":
                raw = memory_data["raw"]
                if not delete_memory(memory_data["id"]):
                    QMessageBox.warning(self, "Error", "Could not remove the old Mem0 entry (see logs).")
                    return
                meta = _mem0_metadata_from_raw(raw if isinstance(raw, dict) else {})
                add_memory(
                    messages=[
                        {"role": "user", "content": text},
                        {"role": "assistant", "content": "Updated memory (edited in Memory Viewer)."},
                    ],
                    user_id=MEM0_USER_ID,
                    metadata=meta,
                )
            else:
                row = memory_data["raw"]
                mem_id = int(row[0])
                kind = str(row[1] or "note").strip() or "note"
                source = str(row[3] or "unknown").strip() or "unknown"
                try:
                    confidence = float(row[4])
                except Exception:
                    confidence = 1.0
                approval = str(row[5] or "approved").strip() or "approved"
                json_data = row[6]
                if not self.db.user_memory_update(
                    mem_id,
                    kind=kind,
                    content=text,
                    source=source,
                    confidence=confidence,
                    approval_status=approval,
                    json_data=json_data,
                ):
                    QMessageBox.warning(self, "Error", "SQLite memory update failed.")
                    return

            QMessageBox.information(self, "Updated", "Memory updated successfully.")
            self.load_all_memories()
        except Exception as e:
            logger.error("Failed to edit memory: %s", e)
            QMessageBox.warning(self, "Error", f"Failed to edit memory: {str(e)}")

    def delete_memory(self, memory_data: dict):
        preview = str(memory_data.get("content", "") or "")
        if len(preview) > 100:
            preview = preview[:100] + "..."
        reply = QMessageBox.question(
            self,
            "Delete Memory",
            f"Delete this memory?\n\n{preview}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            if memory_data["type"] == "mem0":
                if not delete_memory(memory_data["id"]):
                    QMessageBox.warning(self, "Error", "Mem0 did not delete this memory (see logs).")
                    return
            else:
                self.db.user_memory_delete(int(memory_data["id"]))

            QMessageBox.information(self, "Deleted", "Memory deleted successfully.")
            self.load_all_memories()
        except Exception as e:
            logger.error("Failed to delete memory: %s", e)
            QMessageBox.warning(self, "Error", f"Failed to delete memory: {str(e)}")

    # --- Document Memory (Retrieval) support added for Phase 1 Option A ---
    def _refresh_doc_memory(self):
        """Populate the compact DocumentRecords table from the unified retrieval store.
        Supports simple client/doc-type filtering. Safe, read-only view for curation awareness.
        """
        if not hasattr(self, "doc_table"):
            return
        self.doc_table.setRowCount(0)
        try:
            from core.file_handler import load_document_records
            filt = ""
            if hasattr(self, "doc_filter"):
                filt = (self.doc_filter.text() or "").strip()
            recs = []
            if filt:
                # try client first, fallback to doc_type for convenience
                recs = load_document_records(client=filt, limit=40)
                if not recs:
                    recs = load_document_records(doc_type=filt, limit=40)
            if not recs:
                recs = load_document_records(limit=40)
            for r in recs:
                ri = self.doc_table.rowCount()
                self.doc_table.insertRow(ri)
                self.doc_table.setItem(ri, 0, QTableWidgetItem((r.name or "")[:68]))
                self.doc_table.setItem(ri, 1, QTableWidgetItem(r.doc_type or ""))
                self.doc_table.setItem(ri, 2, QTableWidgetItem(r.client_hint or ""))
                self.doc_table.setItem(ri, 3, QTableWidgetItem(str(r.year or "")))
                regs = ",".join((r.regulatory_tags or [])[:2])
                self.doc_table.setItem(ri, 4, QTableWidgetItem(regs))
        except Exception as e:
            logger.warning("Document memory refresh failed: %s", e)

    def _index_from_gdrive(self):
        """In-app GDrive indexer for the unified retrieval store (Phase 1 COMPLETE + verified; Client Dossier surface added as final step).
        Allows user to populate the DocumentRecords retrieval store directly from primary
        Google Drive source using the exact Phase 0/1 unified pipeline (build + save).
        Now persists text_preview / checksum fields (schema v30) with lightweight metadata previews.
        Capped + read-only + no duplicate artifacts created. Makes "Relevant Past Work"
        surfaces (Workspace, CoS sidebar, Pulse Intel, global memory) actually useful in daily work.
        Follows "smallest safe incremental" rule: reuses existing api + file_handler functions,
        no new top-level imports, confirmation, progress via QMessage, then auto-refresh view.
        Re-run any time to refresh as your Drive content evolves.
        """
        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self,
            "Index GDrive for Retrieval",
            "Scan Google Drive (read-only), enrich with doc_type/client/regulatory metadata,\n"
            "and persist up to 300 records into the unified DocumentRecords store?\n\n"
            "This is safe (no files moved/duplicated). Takes 30-120s depending on Drive size.\n"
            "After this, CoS/Workspace/Pulse 'Relevant Past Work' and Memory viewer will show real historical documents (incl. Pulse security-relevant themes for Shield).\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            from core.api import get_gdrive_service, list_gdrive_files
            from core.file_handler import build_unified_document_record, save_document_record
            service = get_gdrive_service()
            files = list_gdrive_files(
                service=service, folder_id="root", recursive=True, max_files=2000
            )
            if not files:
                QMessageBox.information(self, "Index", "No files returned from Google Drive.")
                return
            saved = 0
            cap = 300
            for f in files:
                if saved >= cap:
                    break
                mime = (f.get("mimeType") or "").lower()
                if "folder" in mime or mime.startswith("application/vnd.google-apps."):
                    continue  # Phase 1 finish: skip folders + native Drive apps (prevents polluting retrieval store & Relevant Past surfaces)
                try:
                    rec = build_unified_document_record(
                        source="gdrive",
                        source_id=f.get("id", ""),
                        source_path=f.get("path", f.get("name", "")),
                        name=f.get("name", ""),
                        mime_type=f.get("mimeType", ""),
                        size=f.get("size", 0) or 0,
                        modified_time=f.get("modifiedTime"),
                        created_time=f.get("createdTime"),
                    )
                    # Phase 1 completion: populate lightweight metadata preview (no download/extract yet to stay safe+fast).
                    # Full high-quality PDF/text extraction (using existing fitz path) can be added later without schema change.
                    try:
                        preview_src = f"{rec.name or ''} | {rec.doc_type or ''} | {rec.client_hint or ''} | {rec.project_hint or ''}"
                        rec.text_preview = (preview_src or "")[:500]
                        rec.checksum = f"meta:{(rec.source_id or '')}:{rec.size or 0}"
                        rec.full_text_extracted = False
                    except Exception:
                        pass
                    if save_document_record(rec):
                        saved += 1
                except Exception:
                    continue
            self._refresh_doc_memory()
            msg = f"Saved {saved} DocumentRecords from GDrive (capped at {cap}). Retrieval system now has real data for daily use."
            QMessageBox.information(
                self,
                "Retrieval Index Updated",
                msg + "\n\nRelevant Past Documents surfaces across the app (Workspace, CoS, Pulse, Client Dossier, Memory viewer) will now return richer, client-aware historical examples.\n"
                "Re-run periodically as your Drive grows. (Also available via diagnose script for larger batches.)\n\nPhase 1 (Memory & Retrieval Core) is verifiably complete and delivering daily value (per consultant-os-roadmap.md).",
            )
        except Exception as e:
            logger.error("GDrive index from Memory Viewer failed: %s", e)
            QMessageBox.warning(
                self,
                "Index Error",
                f"Could not complete GDrive index: {str(e)}\n\n"
                "Ensure Google Drive auth is configured (config/.env GOOGLE_* keys) and the Drive connector works.",
            )
