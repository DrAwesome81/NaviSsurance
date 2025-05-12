import sys
import os
import logging
from PyQt6.QtWidgets import QApplication
from gui.interface import ChatWindow
from PyQt6.QtGui import QIcon
from core.index_dropbox import auto_index_on_launch
from core.api import get_dropbox_client
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(level=logging.DEBUG,
                   format='%(asctime)s - %(levelname)s - %(message)s',
                   handlers=[logging.StreamHandler()])
logger = logging.getLogger(__name__)

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Load environment variables
try:
    load_dotenv(os.path.join(os.path.dirname(__file__), "config", ".env"), override=True)
    logger.info("Environment variables loaded successfully")
except Exception as e:
    logger.error(f"Error loading environment variables: {e}")
    sys.exit(1)

if __name__ == "__main__":
    try:
        logger.info("Starting application...")
        app = QApplication(sys.argv)
        
        logger.info("Initializing Dropbox client...")
        dbx = get_dropbox_client()
        
        logger.info("Running auto index...")
        auto_index_on_launch(dbx)
        
        logger.info("Setting up application window...")
        app.setWindowIcon(QIcon("assets/logo v2.png"))
        
        try:
            with open("styles.qss", "r") as f:
                app.setStyleSheet(f.read())
            logger.info("Stylesheet loaded successfully")
        except Exception as e:
            logger.error(f"Error loading stylesheet: {e}")
        
        logger.info("Creating main window...")
        chatWindow = ChatWindow()
        
        logger.info("Showing main window...")
        chatWindow.show()
        
        logger.info("Entering application event loop...")
        sys.exit(app.exec())
    except Exception as e:
        logger.error(f"Critical error in main: {e}", exc_info=True)
        sys.exit(1)