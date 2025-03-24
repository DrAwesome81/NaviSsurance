import sys
import os
from PyQt6.QtWidgets import QApplication
from gui.interface import ChatWindow
from PyQt6.QtGui import QIcon
from core.index_dropbox import auto_index_on_launch
from core.api import get_dropbox_client

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    dbx = get_dropbox_client()
    auto_index_on_launch(dbx)
    app.setWindowIcon(QIcon("assets/logo v2.png"))
    with open("styles.qss", "r") as f:
        app.setStyleSheet(f.read())
    chatWindow = ChatWindow()
    chatWindow.show()
    sys.exit(app.exec())