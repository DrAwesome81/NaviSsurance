from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QListWidget, QListWidgetItem, QTextEdit, QSplitter, QFileDialog
from PyQt6.QtCore import Qt
import os
from core.api import DropboxClient
from dropbox import files

class WorkspaceTab(QWidget):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.dropbox_client = DropboxClient()
        self.selected_file = None
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        # Create main splitter for the workspace
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(main_splitter)
        
        # Left: Folder Tree View (Dropbox/Google Drive files)
        self.setup_folder_tree(main_splitter)
        
        # Center: Document Preview Pane
        self.setup_preview_pane(main_splitter)
        
        # Right: Generation/Compliance Tools Sidebar
        self.setup_tools_sidebar(main_splitter)
        
        # Set splitter proportions (30% left, 50% center, 20% right)
        main_splitter.setSizes([576, 960, 384])  # 1920 * 0.3, 0.5, 0.2
        
        # Add status bar at bottom
        status_layout = QHBoxLayout()
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: white; padding: 5px;")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        
        # Add refresh button
        refresh_btn = QPushButton("Refresh Files")
        refresh_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white; border: none; padding: 5px 10px; border-radius: 3px;")
        refresh_btn.clicked.connect(self.refresh_files)
        status_layout.addWidget(refresh_btn)
        
        layout.addLayout(status_layout)
        
        # Load initial files after UI is fully set up
        self.load_dropbox_files()

    def setup_folder_tree(self, parent_splitter):
        """Setup the left folder tree view for Dropbox files."""
        tree_widget = QWidget()
        tree_layout = QVBoxLayout(tree_widget)
        tree_layout.setContentsMargins(0, 0, 0, 0)
        
        # Header
        tree_header = QLabel("File Explorer")
        tree_header.setStyleSheet("color: white; font-weight: bold; padding: 8px; background-color: rgba(253, 98, 98, 0.8); border-radius: 3px;")
        tree_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tree_layout.addWidget(tree_header)
        
        # Search box
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search files...")
        self.search_box.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white; border: 1px solid rgba(253, 98, 98, 0.5); padding: 5px; border-radius: 3px;")
        self.search_box.textChanged.connect(self.filter_files)
        tree_layout.addWidget(self.search_box)
        
        # File tree
        self.file_tree = QListWidget()
        self.file_tree.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white; border: 1px solid rgba(253, 98, 98, 0.3); border-radius: 3px;")
        self.file_tree.itemClicked.connect(self.on_file_selected)
        tree_layout.addWidget(self.file_tree)
        
        parent_splitter.addWidget(tree_widget)

    def setup_preview_pane(self, parent_splitter):
        """Setup the center document preview pane."""
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        
        # Header
        preview_header = QLabel("Document Preview")
        preview_header.setStyleSheet("color: white; font-weight: bold; padding: 8px; background-color: rgba(253, 98, 98, 0.8); border-radius: 3px;")
        preview_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(preview_header)
        
        # Preview area
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white; border: 1px solid rgba(253, 98, 98, 0.3); border-radius: 3px;")
        self.preview_text.setPlaceholderText("Select a file from the left panel to preview its contents...")
        preview_layout.addWidget(self.preview_text)
        
        # Document info
        info_layout = QHBoxLayout()
        self.file_info_label = QLabel("No file selected")
        self.file_info_label.setStyleSheet("color: white; padding: 5px;")
        info_layout.addWidget(self.file_info_label)
        info_layout.addStretch()
        
        # Download button
        self.download_btn = QPushButton("Download")
        self.download_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white; border: none; padding: 5px 10px; border-radius: 3px;")
        self.download_btn.clicked.connect(self.download_file)
        self.download_btn.setEnabled(False)
        info_layout.addWidget(self.download_btn)
        
        preview_layout.addLayout(info_layout)
        
        parent_splitter.addWidget(preview_widget)

    def setup_tools_sidebar(self, parent_splitter):
        """Setup the right sidebar with generation and compliance tools."""
        tools_widget = QWidget()
        tools_layout = QVBoxLayout(tools_widget)
        tools_layout.setContentsMargins(0, 0, 0, 0)
        
        # Header
        tools_header = QLabel("Tools & Analysis")
        tools_header.setStyleSheet("color: white; font-weight: bold; padding: 8px; background-color: rgba(253, 98, 98, 0.8); border-radius: 3px;")
        tools_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tools_layout.addWidget(tools_header)
        
        # Document Analysis Section
        analysis_group = QLabel("Document Analysis")
        analysis_group.setStyleSheet("color: white; font-weight: bold; margin-top: 10px;")
        tools_layout.addWidget(analysis_group)
        
        # Analysis buttons
        self.analyze_btn = QPushButton("Analyze Document")
        self.analyze_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white; border: none; padding: 8px; border-radius: 3px; margin: 2px;")
        self.analyze_btn.clicked.connect(self.analyze_document)
        self.analyze_btn.setEnabled(False)
        tools_layout.addWidget(self.analyze_btn)
        
        self.chunk_btn = QPushButton("Generate Chunks")
        self.chunk_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white; border: none; padding: 8px; border-radius: 3px; margin: 2px;")
        self.chunk_btn.clicked.connect(self.generate_chunks)
        self.chunk_btn.setEnabled(False)
        tools_layout.addWidget(self.chunk_btn)
        
        # Compliance Section
        compliance_group = QLabel("Compliance Tools")
        compliance_group.setStyleSheet("color: white; font-weight: bold; margin-top: 15px;")
        tools_layout.addWidget(compliance_group)
        
        self.compliance_btn = QPushButton("Run Compliance Check")
        self.compliance_btn.setStyleSheet("background-color: rgba(253, 98, 98, 0.8); color: white; border: none; padding: 8px; border-radius: 3px; margin: 2px;")
        self.compliance_btn.clicked.connect(self.run_compliance_check)
        self.compliance_btn.setEnabled(False)
        tools_layout.addWidget(self.compliance_btn)
        
        # Results display
        results_label = QLabel("Results:")
        results_label.setStyleSheet("color: white; font-weight: bold; margin-top: 15px;")
        tools_layout.addWidget(results_label)
        
        self.results_display = QTextEdit()
        self.results_display.setReadOnly(True)
        self.results_display.setMaximumHeight(200)
        self.results_display.setStyleSheet("background-color: rgba(27, 28, 30, 0.8); color: white; border: 1px solid rgba(253, 98, 98, 0.3); border-radius: 3px;")
        self.results_display.setPlaceholderText("Analysis results will appear here...")
        tools_layout.addWidget(self.results_display)
        
        # Add stretch to push everything to the top
        tools_layout.addStretch()
        
        parent_splitter.addWidget(tools_widget)

    def load_dropbox_files(self):
        """Load files from Dropbox into the tree view."""
        try:
            self.status_label.setText("Loading files from Dropbox...")
            dbx = self.dropbox_client.get_client()
            
            result = dbx.files_list_folder("", recursive=False)
            files = []
            
            for entry in result.entries:
                if hasattr(entry, 'path_display'):
                    files.append({
                        'name': entry.name,
                        'path': entry.path_display,
                        'is_folder': isinstance(entry, files.FolderMetadata),
                        'size': getattr(entry, 'size', 0),
                        'modified': getattr(entry, 'server_modified', None)
                    })
            
            files.sort(key=lambda x: (not x['is_folder'], x['name'].lower()))
            
            self.file_tree.clear()
            for file_info in files:
                icon = "📁" if file_info['is_folder'] else "📄"
                item_text = f"{icon} {file_info['name']}"
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, file_info)
                self.file_tree.addItem(item)
            
            self.status_label.setText(f"Loaded {len(files)} items")
            
        except Exception as e:
            self.status_label.setText(f"Error loading files: {str(e)}")
            self.file_tree.addItem("Error loading files from Dropbox")

    def filter_files(self, search_text):
        """Filter files based on search text."""
        for i in range(self.file_tree.count()):
            item = self.file_tree.item(i)
            file_info = item.data(Qt.ItemDataRole.UserRole)
            if file_info and search_text.lower() in file_info['name'].lower():
                item.setHidden(False)
            else:
                item.setHidden(True)

    def on_file_selected(self, item):
        """Handle file selection in the tree."""
        file_info = item.data(Qt.ItemDataRole.UserRole)
        if not file_info:
            return
        
        self.selected_file = file_info
        self.file_info_label.setText(f"Selected: {file_info['name']}")
        
        # Enable relevant buttons
        self.analyze_btn.setEnabled(True)
        self.chunk_btn.setEnabled(True)
        self.compliance_btn.setEnabled(True)
        self.download_btn.setEnabled(True)
        
        # Load file preview if it's a text-based file
        if not file_info['is_folder']:
            self.load_file_preview(file_info)

    def load_file_preview(self, file_info):
        """Load and display file preview."""
        try:
            self.status_label.setText("Loading file preview...")
            
            text_extensions = {'.txt', '.md', '.py', '.js', '.html', '.css', '.json', '.xml', '.csv'}
            file_ext = os.path.splitext(file_info['name'])[1].lower()
            
            if file_ext in text_extensions:
                dbx = self.dropbox_client.get_client()
                temp_path = f"temp_{file_info['name']}"
                
                with open(temp_path, 'wb') as f:
                    metadata, response = dbx.files_download(file_info['path'])
                    f.write(response.content)
                
                with open(temp_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                os.remove(temp_path)
                
                preview_content = content[:1000]
                if len(content) > 1000:
                    preview_content += f"\n\n... (showing first 1000 characters of {len(content)} total)"
                
                self.preview_text.setPlainText(preview_content)
                self.status_label.setText("File preview loaded")
            else:
                self.preview_text.setPlainText(f"Preview not available for {file_ext} files.\nFile size: {file_info['size']} bytes")
                self.status_label.setText("Preview not available for this file type")
                
        except Exception as e:
            self.preview_text.setPlainText(f"Error loading file preview: {str(e)}")
            self.status_label.setText(f"Error: {str(e)}")

    def analyze_document(self):
        """Analyze the selected document."""
        if not self.selected_file:
            return
        
        try:
            self.status_label.setText("Analyzing document...")
            self.results_display.setPlainText("Analysis in progress...")
            
            content = self.preview_text.toPlainText()
            if content and not content.startswith("Preview not available"):
                word_count = len(content.split())
                line_count = len(content.split('\n'))
                char_count = len(content)
                
                analysis_result = f"""Document Analysis Results:
                
File: {self.selected_file['name']}
Size: {self.selected_file['size']} bytes
Characters: {char_count}
Words: {word_count}
Lines: {line_count}
Average words per line: {word_count/line_count:.1f if line_count > 0 else 0}

Content Summary:
{content[:200]}..."""
                
                self.results_display.setPlainText(analysis_result)
                self.status_label.setText("Analysis complete")
            else:
                self.results_display.setPlainText("Cannot analyze: No text content available")
                
        except Exception as e:
            self.results_display.setPlainText(f"Analysis error: {str(e)}")
            self.status_label.setText(f"Error: {str(e)}")

    def generate_chunks(self):
        """Generate text chunks from the document."""
        if not self.selected_file:
            return
        
        try:
            self.status_label.setText("Generating chunks...")
            content = self.preview_text.toPlainText()
            
            if content and not content.startswith("Preview not available"):
                paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
                chunk_result = "Generated Chunks:\n\n"
                for i, chunk in enumerate(paragraphs[:5], 1):  # Limit to first 5 for preview
                    chunk_result += f"Chunk {i}: {chunk[:100]}...\n\n"
                if len(paragraphs) > 5:
                    chunk_result += f"... and {len(paragraphs) - 5} more chunks"
                self.results_display.setPlainText(chunk_result)
                self.status_label.setText("Chunks generated")
            else:
                self.results_display.setPlainText("Cannot generate chunks: No text content available")
                
        except Exception as e:
            self.results_display.setPlainText(f"Chunk generation error: {str(e)}")
            self.status_label.setText(f"Error: {str(e)}")

    def run_compliance_check(self):
        """Placeholder for compliance check."""
        self.results_display.setPlainText("Compliance check not implemented yet.")

    def download_file(self):
        """Download the selected file from Dropbox."""
        if not self.selected_file or self.selected_file['is_folder']:
            return
        
        try:
            self.status_label.setText("Downloading file...")
            dbx = self.dropbox_client.get_client()
            
            save_path, _ = QFileDialog.getSaveFileName(
                self, "Save File As", self.selected_file['name'], "All Files (*)"
            )
            if save_path:
                with open(save_path, 'wb') as f:
                    metadata, response = dbx.files_download(self.selected_file['path'])
                    f.write(response.content)
                self.status_label.setText("File downloaded successfully")
        except Exception as e:
            self.status_label.setText(f"Error downloading file: {str(e)}")

    def refresh_files(self):
        """Refresh the file list."""
        self.load_dropbox_files()
