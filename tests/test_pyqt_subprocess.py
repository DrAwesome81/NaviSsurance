import sys
import subprocess
import json
import time
from PyQt6.QtWidgets import QApplication, QMainWindow, QPushButton, QTextEdit, QVBoxLayout, QWidget
from PyQt6.QtCore import QTimer

class TestWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Subprocess Test")
        self.setGeometry(100, 100, 400, 300)
        
        layout = QVBoxLayout()
        self.button = QPushButton("Send Test Message")
        self.button.clicked.connect(self.send_test)
        layout.addWidget(self.button)
        
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output)
        
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)
        
        self.process = None
        self.start_worker()

    def start_worker(self):
        self.process = subprocess.Popen(
            ["c:/Users/adamo/Dropbox/_Consulting/NaviSsurance/cuda_env/Scripts/python.exe", "-u", "tests/llama_worker.py"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore"
        )
        
        QTimer.singleShot(100, self.check_load)

    def check_load(self):
        line = self.process.stderr.readline().strip()
        if line:
            self.output.append(line)
        if "MODEL_LOADED" in line:
            self.output.append("Model loaded in subprocess.")
            self.button.setEnabled(True)
        elif "LOAD_ERROR" in line:
            self.output.append("Load failed.")
        else:
            QTimer.singleShot(100, self.check_load)  # Poll until done

    def send_test(self):
        messages = [{"role": "user", "content": "Hello test"}]
        self.process.stdin.write(json.dumps({"messages": messages, "session_id": "test"}) + "\n")
        self.process.stdin.flush()
        
        QTimer.singleShot(100, self.read_response)

    def read_response(self):
        line = self.process.stdout.readline().strip()
        if line:
            try:
                response = json.loads(line)
                self.output.append(response.get("response", response.get("error")))
            except:
                self.output.append("Invalid response.")
        else:
            QTimer.singleShot(100, self.read_response)  # Poll

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TestWindow()
    window.show()
    sys.exit(app.exec())