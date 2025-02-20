import sys
import os
from PyQt6.QtWidgets import QApplication
from gui.interface import ChatWindow
from PyQt6.QtGui import QIcon

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon("logo v2.png"))
    with open("styles.qss", "r") as f:
        app.setStyleSheet(f.read())
    chatWindow = ChatWindow()
    chatWindow.show()
    sys.exit(app.exec())