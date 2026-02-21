import sys
import os
import logging
from dotenv import load_dotenv

# Load environment variables FIRST before any other imports that might need them
load_dotenv(os.path.join(os.path.dirname(__file__), "config", ".env"), override=True)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QRect, Qt
from gui.interface import ChatWindow, EnhancedSplashScreen
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor
from core.api import get_dropbox_client

# Import centralized paths
from config import LOGS_DIR

# Create logs directory if it doesn't exist
os.makedirs(LOGS_DIR, exist_ok=True)

# Set up logging - WARNING level to reduce console verbosity (INFO still goes to file)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.WARNING)  # Only show warnings and errors in console

file_handler = logging.FileHandler(os.path.join(LOGS_DIR, 'app.log'))
file_handler.setLevel(logging.INFO)  # Keep INFO level for file logging

logging.basicConfig(
    level=logging.INFO,  # Root level (file will get INFO, console will get WARNING+)
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        file_handler,
        console_handler
    ]
)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    try:
        logger.info("Starting NaviSsurance application...")
        app = QApplication(sys.argv)
        
        # Create and show splash screen
        splash_pix = QPixmap(500, 350)
        splash_pix.fill(QColor(27, 28, 30))
        logo_path = os.path.join(os.path.dirname(__file__), "assets", "logo v2.png")
        if os.path.exists(logo_path):
            logo = QPixmap(logo_path)
            if not logo.isNull():
                # Scale logo to fit, centered
                scaled = logo.scaled(400, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                painter = QPainter(splash_pix)
                x = (500 - scaled.width()) // 2
                painter.drawPixmap(x, 20, scaled)
                painter.end()
        
        splash = EnhancedSplashScreen(splash_pix)
        splash.show()
        app.processEvents()
        
        splash.update_progress(10, "Initializing...", "Starting NaviSsurance")
        app.processEvents()
        
        logger.info("Initializing Dropbox client...")
        try:
            dbx = get_dropbox_client()
            logger.info("Dropbox client initialized successfully")
            splash.update_progress(30, "Dropbox connected", "Dropbox client initialized")
        except Exception as e:
            logger.error(f"Error initializing Dropbox client: {e}")
            dbx = None
            splash.update_progress(30, "Continuing without Dropbox", f"Dropbox init failed: {e}")
        app.processEvents()
        
        # Dropbox indexing removed - using RAG index instead
        
        logger.info("Setting up application window...")
        if os.path.exists(logo_path):
            app.setWindowIcon(QIcon(logo_path))
        splash.update_progress(40, "Creating main window...", "Setting up application window")
        app.processEvents()
        
        logger.info("Creating main window with enhanced splash screen...")
        try:
            chatWindow = ChatWindow()
            logger.info("ChatWindow created successfully")
            splash.update_progress(80, "Main window ready", "ChatWindow created successfully")
        except Exception as e:
            logger.error(f"Error creating ChatWindow: {e}", exc_info=True)
            splash.finish(None)
            sys.exit(1)
        app.processEvents()
        
        # Set window geometry with smart sizing based on available screen space
        try:
            # Get available screen geometry (excludes taskbar, dock, etc.)
            screen = app.primaryScreen()
            available_rect = screen.availableGeometry()
            
            # Preferred window size (full HD resolution)
            preferred_width = 1920
            preferred_height = 1080
            
            # Calculate actual window size (shrink if screen is too small)
            window_width = min(preferred_width, available_rect.width())
            window_height = min(preferred_height, available_rect.height())
            
            # Center the window on the available screen space
            x = available_rect.x() + (available_rect.width() - window_width) // 2
            y = available_rect.y() + (available_rect.height() - window_height) // 2
            
            chatWindow.setGeometry(QRect(x, y, window_width, window_height))
            logger.info(f"Window geometry set to {window_width}x{window_height} (available: {available_rect.width()}x{available_rect.height()})")
        except Exception as e:
            logger.error(f"Error setting window geometry: {e}", exc_info=True)
            # Fallback to default size if dynamic detection fails
            chatWindow.setGeometry(QRect(100, 100, 1200, 800))
        
        splash.update_progress(95, "Launching...", "Showing main window")
        app.processEvents()
        
        logger.info("Showing main window...")
        try:
            chatWindow.show()
            logger.info("Main window shown successfully")
            splash.update_progress(100, "Ready", "NaviSsurance ready")
            app.processEvents()
        except Exception as e:
            logger.error(f"Error showing main window: {e}", exc_info=True)
        
        splash.finish(chatWindow)
        
        logger.info("Application initialization complete, entering event loop...")
        try:
            logger.info("Starting PyQt event loop...")
            result = app.exec()
            logger.info(f"Event loop exited with code: {result}")
            sys.exit(result)
        except Exception as e:
            logger.error(f"Error in event loop: {e}", exc_info=True)
            sys.exit(1)
    except Exception as e:
        logger.error(f"Critical error in main: {e}", exc_info=True)
        sys.exit(1)