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
)

from core.mem0_config import MEM0_USER_ID
from core.mem0_memory import add_memory, delete_memory, get_all_memories, search_memory
from core.db import DatabaseManager
import logging

logger = logging.getLogger(__name__)


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

        self.load_all_memories()

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
