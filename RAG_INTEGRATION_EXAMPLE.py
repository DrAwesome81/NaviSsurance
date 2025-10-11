"""
Example: How to integrate RAG search into WorkspaceTab

This shows how you could add RAG search functionality to your existing PyQt workspace tab.
You can use this as a reference when you decide where to implement RAG search.

Current options:
1. Keep separate Streamlit app (search_rag_index.py)
2. Integrate into existing WorkspaceTab (this example)
3. Create dedicated RAG search tab
"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                            QTextEdit, QLineEdit, QListWidget, QListWidgetItem, 
                            QSplitter, QTabWidget)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
import logging

logger = logging.getLogger(__name__)

class RAGSearchWorker(QThread):
    """Worker thread for RAG search to prevent UI blocking."""
    results_ready = pyqtSignal(list)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, query, chroma_path):
        super().__init__()
        self.query = query
        self.chroma_path = chroma_path
    
    def run(self):
        try:
            # Initialize embedding model
            embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-large-en-v1.5")
            
            # Load vector store
            vector_store = Chroma(persist_directory=self.chroma_path, embedding_function=embeddings)
            
            # Perform search
            results = vector_store.similarity_search(self.query, k=20)  # Limit results
            
            # Format results
            formatted_results = []
            for i, doc in enumerate(results):
                result = {
                    'rank': i + 1,
                    'source': doc.metadata.get('source', 'unknown'),
                    'content': doc.page_content[:200] + "..." if len(doc.page_content) > 200 else doc.page_content,
                    'full_content': doc.page_content,
                    'metadata': doc.metadata
                }
                formatted_results.append(result)
            
            self.results_ready.emit(formatted_results)
            
        except Exception as e:
            logger.error(f"RAG search error: {e}")
            self.error_occurred.emit(str(e))

class RAGSearchWidget(QWidget):
    """RAG search widget that could be integrated into WorkspaceTab."""
    
    def __init__(self, chroma_path="chroma_index"):
        super().__init__()
        self.chroma_path = chroma_path
        self.search_worker = None
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        # Search input
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Enter search query (e.g., '2024 budget notes')...")
        self.search_input.returnPressed.connect(self.perform_search)
        
        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self.perform_search)
        
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.search_button)
        layout.addLayout(search_layout)
        
        # Results area
        results_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Results list
        self.results_list = QListWidget()
        self.results_list.itemClicked.connect(self.show_result_details)
        results_splitter.addWidget(self.results_list)
        
        # Result details
        self.result_details = QTextEdit()
        self.result_details.setReadOnly(True)
        results_splitter.addWidget(self.result_details)
        
        results_splitter.setSizes([300, 500])
        layout.addWidget(results_splitter)
        
        # Status label
        self.status_label = QLabel("Ready to search")
        layout.addWidget(self.status_label)
    
    def perform_search(self):
        """Start RAG search in background thread."""
        query = self.search_input.text().strip()
        if not query:
            self.status_label.setText("Please enter a search query")
            return
        
        if self.search_worker and self.search_worker.isRunning():
            self.search_worker.terminate()
        
        self.status_label.setText(f"Searching for: {query}")
        self.results_list.clear()
        self.result_details.clear()
        
        # Start search in background thread
        self.search_worker = RAGSearchWorker(query, self.chroma_path)
        self.search_worker.results_ready.connect(self.display_results)
        self.search_worker.error_occurred.connect(self.handle_search_error)
        self.search_worker.start()
    
    def display_results(self, results):
        """Display search results in the list."""
        self.results_list.clear()
        
        if not results:
            self.status_label.setText("No results found")
            return
        
        self.status_label.setText(f"Found {len(results)} results")
        
        for result in results:
            item_text = f"[{result['rank']}] {result['source']}\n{result['content']}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, result)
            self.results_list.addItem(item)
    
    def show_result_details(self, item):
        """Show full details of selected result."""
        result = item.data(Qt.ItemDataRole.UserRole)
        if result:
            details = f"Source: {result['source']}\n\n"
            details += f"Content:\n{result['full_content']}\n\n"
            details += f"Metadata: {result['metadata']}"
            self.result_details.setPlainText(details)
    
    def handle_search_error(self, error_msg):
        """Handle search errors."""
        self.status_label.setText(f"Search error: {error_msg}")
        logger.error(f"RAG search failed: {error_msg}")

# Example: How to integrate into existing WorkspaceTab
class EnhancedWorkspaceTab(QWidget):
    """Example of how to add RAG search to existing WorkspaceTab."""
    
    def __init__(self, db, chat_handler):
        super().__init__()
        self.db = db
        self.chat_handler = chat_handler
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Create tab widget for different workspace functions
        self.tab_widget = QTabWidget()
        
        # Existing workspace functionality (file management, etc.)
        self.file_workspace = self.create_file_workspace_tab()
        self.tab_widget.addTab(self.file_workspace, "File Management")
        
        # New RAG search functionality
        self.rag_search = RAGSearchWidget()
        self.tab_widget.addTab(self.rag_search, "Document Search")
        
        layout.addWidget(self.tab_widget)
    
    def create_file_workspace_tab(self):
        """Create the existing file workspace functionality."""
        # This would contain your existing WorkspaceTab functionality
        # (file list, preview, etc.)
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel("File Management (existing functionality)"))
        return widget

"""
Integration Options:

1. ADD TO EXISTING WORKSPACE TAB:
   - Add RAG search as a new section in WorkspaceTab
   - Use QSplitter to separate file management and search
   - Good for users who work with files and search together

2. CREATE DEDICATED RAG TAB:
   - Add RAGSearchWidget as a new tab in main interface
   - Keep file management separate from search
   - Good for users who want dedicated search functionality

3. ADD SEARCH TO FILE CONTEXT:
   - Add search button/field to file preview area
   - Search within currently selected file or related files
   - Good for focused, contextual search

4. KEEP SEPARATE STREAMLIT APP:
   - Maintain current search_rag_index.py
   - Users run separate app when needed
   - Good for occasional use or power users

RECOMMENDATION:
Based on your app's workflow, I'd suggest Option 2 (dedicated RAG tab) because:
- Clean separation of concerns
- Consistent PyQt UI
- Easy to find and use
- Doesn't clutter existing workspace
- Can be enhanced with advanced search features later
"""


