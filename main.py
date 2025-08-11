import sys
import os
import logging
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QRect
from gui.interface import ChatWindow
from PyQt6.QtGui import QIcon
from core.index_dropbox import auto_index_on_launch
from core.api import get_dropbox_client
from dotenv import load_dotenv


# Create logs directory if it doesn't exist
logs_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(logs_dir, exist_ok=True)

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(logs_dir, 'app.log')),
        logging.StreamHandler()
    ]
)
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
        logger.info("Starting NaviSsurance application...")
        app = QApplication(sys.argv)
        
        logger.info("Initializing Dropbox client...")
        try:
            dbx = get_dropbox_client()
            logger.info("Dropbox client initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing Dropbox client: {e}")
            dbx = None
        
        logger.info("Running auto index...")
        try:
            auto_index_on_launch(dbx)
            logger.info("Auto index completed successfully")
        except Exception as e:
            logger.error(f"Error during auto index: {e}")
        
        logger.info("Setting up application window...")
        app.setWindowIcon(QIcon("assets/logo v2.png"))
        
        logger.info("Creating main window with enhanced splash screen...")
        chatWindow = ChatWindow()
        
        # Set default geometry to fullscreen-like dimensions
        chatWindow.setGeometry(QRect(0, 0, 1920, 1080))
        
        logger.info("Application initialization complete, entering event loop...")
        sys.exit(app.exec())
    except Exception as e:
        logger.error(f"Critical error in main: {e}", exc_info=True)
        sys.exit(1)