"""
MorningPlanView - visual day timeline for proposed morning plan.

Simple QGraphicsView based timeline (8:00-18:00) showing existing
calendar events (gray) and proposed blocks (colored).
"""

from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsTextItem
from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QBrush, QPen, QColor
from datetime import datetime, timedelta


class MorningPlanView(QGraphicsView):
    plan_changed = pyqtSignal(list)  # list of block dicts

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene()
        self.setScene(self.scene)
        self.setFixedHeight(280)
        self.hour_height = 40
        self.start_hour = 8
        self.end_hour = 18
        self._blocks = []  # proposed blocks
        self._existing = []  # existing calendar events

    def set_existing_events(self, events: list):
        self._existing = events or []
        self._redraw()

    def set_proposed_blocks(self, blocks: list):
        self._blocks = blocks or []
        self._redraw()

    def _redraw(self):
        self.scene.clear()
        width = 520
        height = (self.end_hour - self.start_hour) * self.hour_height
        self.scene.setSceneRect(0, 0, width, height)

        # Draw hour lines
        for h in range(self.start_hour, self.end_hour + 1):
            y = (h - self.start_hour) * self.hour_height
            self.scene.addLine(60, y, width, y, QPen(QColor("#3a3d42")))
            label = QGraphicsTextItem(f"{h:02d}:00")
            label.setPos(5, y - 8)
            label.setDefaultTextColor(QColor("#9aa0a6"))
            self.scene.addItem(label)

        # Draw existing events (gray)
        for ev in self._existing:
            self._draw_block(ev, QColor("#555a60"), editable=False)

        # Draw proposed blocks (colored)
        for blk in self._blocks:
            self._draw_block(blk, QColor("#4a90d9"), editable=True)

    def _draw_block(self, block: dict, color: QColor, editable: bool = True):
        title = block.get("title", "Block")
        start = block.get("start", "")
        end = block.get("end", "")
        try:
            sdt = datetime.fromisoformat(start.replace("Z", ""))
            edt = datetime.fromisoformat(end.replace("Z", ""))
        except Exception:
            return

        y1 = (sdt.hour - self.start_hour) * self.hour_height + (sdt.minute / 60.0) * self.hour_height
        y2 = (edt.hour - self.start_hour) * self.hour_height + (edt.minute / 60.0) * self.hour_height
        rect = QRectF(70, y1, 440, max(20, y2 - y1))
        item = QGraphicsRectItem(rect)
        item.setBrush(QBrush(color))
        item.setPen(QPen(Qt.PenStyle.NoPen))
        if editable:
            item.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable)
        self.scene.addItem(item)

        txt = QGraphicsTextItem(title)
        txt.setPos(75, y1 + 4)
        txt.setDefaultTextColor(QColor("#e8eaed"))
        self.scene.addItem(txt)