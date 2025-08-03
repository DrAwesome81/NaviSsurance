import os
os.environ["TORCH_DYNAMO_DISABLE"] = "1"
from PyQt6.QtWidgets import QApplication, QMainWindow, QPushButton
from llama_cpp import Llama
import sys

model_path = "C:/Users/adamo/.cache/huggingface/hub/models--bartowski--Meta-Llama-3-8B-Instruct-GGUF/snapshots/2c3f8d7f3db06e3f9e8c4c6b6e6c7f3f8d9e4c6/Meta-Llama-3-8B-Instruct-Q4_K_M.gguf"

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Test")
        button = QPushButton("Load Model", self)
        button.clicked.connect(self.load_model)
        self.setCentralWidget(button)
        self.llm = None

    def load_model(self):
        try:
            print("Loading Llama...")
            self.llm = Llama(
                model_path=model_path,
                n_gpu_layers=33,
                n_ctx=2048,
                n_threads=4,
                verbose=False,
                chat_format="llama-3"
            )
            print("Model loaded!")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())