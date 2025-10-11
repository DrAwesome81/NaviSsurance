"""Utility functions for the ChatWindow GUI.

This module contains helper functions for setting up shortcuts, status bar,
context menus, and other UI-related utilities extracted from interface.py.
"""

from PyQt6.QtWidgets import QMessageBox, QLabel, QMenu, QFileDialog
from PyQt6.QtGui import QAction
from PyQt6.QtCore import QTimer, Qt, QPoint
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gui.interface import ChatWindow

def setup_shortcuts(window: 'ChatWindow') -> None:
    """Set up keyboard shortcuts for common actions."""
    # Chat shortcuts
    send_action = QAction("Send Message", window)
    send_action.setShortcut("Ctrl+Return")
    send_action.triggered.connect(window.sendMessage)
    window.addAction(send_action)
    
    # Tab navigation shortcuts
    next_tab_action = QAction("Next Tab", window)
    next_tab_action.setShortcut("Ctrl+Tab")
    next_tab_action.triggered.connect(lambda: next_tab(window))
    window.addAction(next_tab_action)
    
    prev_tab_action = QAction("Previous Tab", window)
    prev_tab_action.setShortcut("Ctrl+Shift+Tab")
    prev_tab_action.triggered.connect(lambda: previous_tab(window))
    window.addAction(prev_tab_action)
    
    # Task shortcuts
    add_task_action = QAction("Add Task", window)
    add_task_action.setShortcut("Ctrl+T")
    add_task_action.triggered.connect(window.addTask)
    window.addAction(add_task_action)
    
    # Search shortcuts
    search_action = QAction("Search Leads", window)
    search_action.setShortcut("Ctrl+F")
    search_action.triggered.connect(window.focus_search)
    window.addAction(search_action)
    
    # Refresh shortcuts
    refresh_action = QAction("Refresh", window)
    refresh_action.setShortcut("F5")
    refresh_action.triggered.connect(window.refresh_leads)
    window.addAction(refresh_action)
    
    # Settings shortcut
    settings_action = QAction("Settings", window)
    settings_action.setShortcut("Ctrl+,")
    settings_action.triggered.connect(window.open_settings)
    window.addAction(settings_action)
    
    # Help shortcut
    help_action = QAction("Help", window)
    help_action.setShortcut("F1")
    help_action.triggered.connect(window.show_help)
    window.addAction(help_action)
    
    # Exit shortcut
    exit_action = QAction("Exit", window)
    exit_action.setShortcut("Ctrl+Q")
    exit_action.triggered.connect(window.close)
    window.addAction(exit_action)

def setup_status_bar(window: 'ChatWindow') -> None:
    """Set up status bar with various indicators."""
    window.statusBar = window.statusBar()
    
    # Main status label
    window.status_label = QLabel("Ready")
    window.statusBar.addWidget(window.status_label)
    
    
    # Time display
    window.time_label = QLabel()
    window.statusBar.addPermanentWidget(window.time_label)
    
    # Update time every second
    window.time_timer = QTimer()
    window.time_timer.timeout.connect(lambda: update_time(window))
    window.time_timer.start(1000)
    update_time(window)

def update_time(window: 'ChatWindow') -> None:
    """Update the time display in status bar."""
    current_time = datetime.now().strftime("%H:%M:%S")
    window.time_label.setText(current_time)

def update_status(window: 'ChatWindow', message: str, timeout: int = 3000) -> None:
    """Update status bar message with optional timeout."""
    window.status_label.setText(message)
    if timeout > 0:
        QTimer.singleShot(timeout, lambda: window.status_label.setText("Ready"))



def next_tab(window: 'ChatWindow') -> None:
    """Navigate to next tab."""
    current_index = window.tab_widget.currentIndex()
    next_index = (current_index + 1) % window.tab_widget.count()
    window.tab_widget.setCurrentIndex(next_index)

def previous_tab(window: 'ChatWindow') -> None:
    """Navigate to previous tab."""
    current_index = window.tab_widget.currentIndex()
    prev_index = (current_index - 1) % window.tab_widget.count()
    window.tab_widget.setCurrentIndex(prev_index)

def focus_search(window: 'ChatWindow') -> None:
    """Focus on the search input field."""
    if hasattr(window, 'searchInput'):
        window.searchInput.setFocus()
        window.searchInput.selectAll()

def show_help(window: 'ChatWindow') -> None:
    """Show help dialog with keyboard shortcuts."""
    help_text = (
        "<h2>Keyboard Shortcuts</h2>"
        "<table>"
        "<tr><td><b>Ctrl+Return</b></td><td>Send chat message</td></tr>"
        "<tr><td><b>Ctrl+Tab</b></td><td>Next tab</td></tr>"
        "<tr><td><b>Ctrl+Shift+Tab</b></td><td>Previous tab</td></tr>"
        "<tr><td><b>Ctrl+T</b></td><td>Add new task</td></tr>"
        "<tr><td><b>Ctrl+F</b></td><td>Focus search field</td></tr>"
        "<tr><td><b>F5</b></td><td>Refresh leads</td></tr>"
        "<tr><td><b>Ctrl+,</b></td><td>Open settings</td></tr>"
        "<tr><td><b>F1</b></td><td>Show this help</td></tr>"
        "<tr><td><b>Ctrl+Q</b></td><td>Exit application</td></tr>"
        "</table>"
        "<h3>Tips</h3>"
        "<ul>"
        "<li>Use Tab to navigate between form fields</li>"
        "<li>Press Enter to activate buttons</li>"
        "<li>Use arrow keys to navigate lists and tables</li>"
        "<li>Right-click for context menus</li>"
        "</ul>"
    )
    
    msg = QMessageBox(window)
    msg.setWindowTitle("Help - Keyboard Shortcuts")
    msg.setTextFormat(Qt.TextFormat.RichText)
    msg.setText(help_text)
    msg.setStandardButtons(QMessageBox.StandardButton.Ok)
    msg.exec()

def show_chat_context_menu(window: 'ChatWindow', position: QPoint) -> None:
    menu = QMenu(window)
    
    cut_action = menu.addAction("Cut")
    cut_action.triggered.connect(lambda: window.chatInput.cut())
    
    copy_action = menu.addAction("Copy")
    copy_action.triggered.connect(lambda: window.chatInput.copy())
    
    paste_action = menu.addAction("Paste")
    paste_action.triggered.connect(lambda: window.chatInput.paste())
    
    menu.addSeparator()
    
    clear_action = menu.addAction("Clear")
    clear_action.triggered.connect(lambda: window.chatInput.clear())
    
    select_all_action = menu.addAction("Select All")
    select_all_action.triggered.connect(lambda: window.chatInput.selectAll())
    
    menu.exec(window.chatInput.mapToGlobal(position))

def show_button_context_menu(window: 'ChatWindow', position: QPoint) -> None:
    menu = QMenu(window)
    
    send_action = menu.addAction("Send Message")
    send_action.triggered.connect(window.sendMessage)
    
    menu.addSeparator()
    
    templates_menu = menu.addMenu("Quick Messages")
    
    template1 = templates_menu.addAction("Hello, how can I help you today?")
    template1.triggered.connect(lambda: window.insert_template("Hello, how can I help you today?"))
    
    template2 = templates_menu.addAction("Thank you for your inquiry.")
    template2.triggered.connect(lambda: window.insert_template("Thank you for your inquiry."))
    
    template3 = templates_menu.addAction("I'll get back to you shortly.")
    template3.triggered.connect(lambda: window.insert_template("I'll get back to you shortly."))
    
    menu.exec(window.sendButton.mapToGlobal(position))

def show_chat_display_context_menu(window: 'ChatWindow', position: QPoint) -> None:
    menu = QMenu(window)
    
    copy_action = menu.addAction("Copy Selected Text")
    copy_action.triggered.connect(lambda: window.chatDisplay.copy())
    
    select_all_action = menu.addAction("Select All")
    select_all_action.triggered.connect(lambda: window.chatDisplay.selectAll())
    
    menu.addSeparator()
    
    save_chat_action = menu.addAction("Save Chat History")
    save_chat_action.triggered.connect(window.save_chat_history)
    
    clear_chat_action = menu.addAction("Clear Chat")
    clear_chat_action.triggered.connect(window.clear_chat_history)
    
    menu.addSeparator()
    
    export_menu = menu.addMenu("Export")
    
    export_text_action = export_menu.addAction("Export as Text")
    export_text_action.triggered.connect(window.export_chat_as_text)
    
    export_html_action = export_menu.addAction("Export as HTML")
    export_html_action.triggered.connect(window.export_chat_as_html)
    
    menu.exec(window.chatDisplay.mapToGlobal(position))

def insert_template(window: 'ChatWindow', template_text: str) -> None:
    window.chatInput.setText(template_text)
    window.chatInput.setFocus()
    window.chatInput.selectAll()

def _export_chat(window: 'ChatWindow', path: str, content: str, fmt: str) -> bool:
    """
    Helper function to write chat content to file.
    
    Args:
        window: The ChatWindow instance
        path: File path to write to
        content: Content to write
        fmt: Format ('text' or 'html') for success message
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        success_msg = f"Chat exported as {fmt} successfully."
        QMessageBox.information(window, "Success", success_msg)
        return True
    except Exception as e:
        QMessageBox.critical(window, "Error", f"Failed to export chat: {str(e)}")
        return False


def export_chat(window: 'ChatWindow', format='text', title="Export Chat", default_filename="chat_export") -> None:
    """
    Export chat content in the specified format.
    
    Args:
        window: The ChatWindow instance
        format: Export format ('text', 'html', or 'both' for user selection)
        title: Dialog title
        default_filename: Default filename (without extension)
    """
    try:
        if format == 'text':
            file_filter = "Text Files (*.txt)"
            default_file = f"{default_filename}.txt"
            content = window.chatDisplay.toPlainText()
            fmt = "text"
        elif format == 'html':
            file_filter = "HTML Files (*.html)"
            default_file = f"{default_filename}.html"
            content = window.chatDisplay.toHtml()
            fmt = "HTML"
        else:  # format == 'both' or any other value
            file_filter = "Text Files (*.txt);;HTML Files (*.html)"
            default_file = default_filename
            content = window.chatDisplay.toPlainText()  # Default to text
            fmt = "text"
        
        filename, _ = QFileDialog.getSaveFileName(
            window, title, default_file, file_filter
        )
        
        if filename:
            # Determine format from filename extension if user selected 'both' format
            if format == 'both' and filename.endswith('.html'):
                content = window.chatDisplay.toHtml()
                fmt = "HTML"
            
            # Use helper function for file writing
            _export_chat(window, filename, content, fmt)
    except Exception as e:
        QMessageBox.critical(window, "Error", f"Failed to export chat: {str(e)}")


def save_chat_history(window: 'ChatWindow') -> None:
    """Save chat history with format selection."""
    export_chat(window, format='both', title="Save Chat History", default_filename="chat_history")


def clear_chat_history(window: 'ChatWindow') -> None:
    reply = QMessageBox.question(
        window, "Clear Chat", "Are you sure you want to clear the chat history?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    if reply == QMessageBox.StandardButton.Yes:
        window.chatDisplay.clear()


def export_chat_as_text(window: 'ChatWindow') -> None:
    """Export chat as text format."""
    export_chat(window, format='text', title="Export Chat as Text", default_filename="chat_export")


def export_chat_as_html(window: 'ChatWindow') -> None:
    """Export chat as HTML format."""
    export_chat(window, format='html', title="Export Chat as HTML", default_filename="chat_export")

def loadStylesheet(window: 'ChatWindow', filename: str) -> None:
    try:
        with open(filename, "r") as f:
            window.setStyleSheet(f.read())
    except FileNotFoundError:
        pass
    except Exception as e:
        pass
