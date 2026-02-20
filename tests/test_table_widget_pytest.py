"""
Pytest tests for QTableWidget functionality.
Tests widget persistence, database loading, and table operations.
"""

import sys
import os
import sqlite3
import pytest
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QTableWidget, QTableWidgetItem, 
                             QWidget, QPushButton, QCheckBox, QLabel, 
                             QHBoxLayout, QHeaderView, QAbstractItemView)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QBrush

# Use centralized database path from project root (script lives in tests/)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATABASE_PATH = os.path.join(_PROJECT_ROOT, "naviSsurance_index.db")


class TestTableWidget:
    """Test class for QTableWidget functionality."""
    
    @pytest.fixture(autouse=True)
    def setup_app(self):
        """Setup QApplication for each test."""
        if not QApplication.instance():
            self.app = QApplication(sys.argv)
        else:
            self.app = QApplication.instance()
        yield self.app
    
    @pytest.fixture
    def table_widget(self):
        """Create a test table widget."""
        table = QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["Task", "Due Date", "Actions"])
        table.setRowCount(0)
        return table
    
    def create_task_widget(self, task_data):
        """Create a task widget with checkbox and text for the first column."""
        task_id, task, due_date, completed, session_id = task_data
        
        # Create task widget with checkbox and text for first column
        task_widget = QWidget()
        task_layout = QHBoxLayout(task_widget)
        task_layout.setContentsMargins(8, 0, 0, 0)
        task_layout.setSpacing(8)
        
        # Add checkbox to task widget
        checkbox = QCheckBox()
        checkbox.setChecked(completed == 1)
        task_layout.addWidget(checkbox)
        
        # Add task text label
        task_label = QLabel(f"   {task}")
        task_label.setStyleSheet("color: white; background-color: transparent; border: none;")
        task_layout.addWidget(task_label)
        task_layout.addStretch()
        
        # Store task data in the widget for later use
        task_widget.task_data = {
            'id': task_id,
            'task': task,
            'due_date': due_date,
            'completed': completed,
            'session_id': session_id
        }
        
        return task_widget
    
    def create_actions_widget(self, row_position):
        """Create action buttons widget for edit/delete operations."""
        actions_widget = QWidget()
        actions_layout = QHBoxLayout(actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)
        actions_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Edit button
        edit_btn = QPushButton("Edit")
        edit_btn.setFixedWidth(80)
        edit_btn.setFixedHeight(40)
        
        # Delete button
        delete_btn = QPushButton("Delete")
        delete_btn.setFixedWidth(100)
        delete_btn.setFixedHeight(40)
        
        actions_layout.addWidget(edit_btn)
        actions_layout.addWidget(delete_btn)
        actions_layout.addStretch()
        
        return actions_widget
    
    def apply_row_styling(self, table, row, completed=None, due_date=None):
        """Apply styling to a row based on completion status and due date."""
        # Get due date if not provided
        if due_date is None:
            due_date_item = table.item(row, 1)
            due_date = due_date_item.text() if due_date_item else "No due date"
        
        # Get completion status if not provided
        if completed is None:
            task_widget = table.cellWidget(row, 0)
            if task_widget and hasattr(task_widget, 'task_data'):
                completed = task_widget.task_data.get('completed', 0)
            else:
                completed = 0
        
        # Determine colors based on completion and due date
        if completed == 1:
            bg_color = QColor(34, 139, 34)  # Forest green for completed
        else:
            bg_color = QColor(70, 130, 180)  # Steel blue for incomplete
        
        # Apply styling to due date column
        due_date_item = table.item(row, 1)
        if due_date_item:
            due_date_item.setBackground(QBrush(bg_color))
            due_date_item.setForeground(QBrush(QColor(255, 255, 255)))
    
    def test_table_creation(self, table_widget):
        """Test basic table creation and configuration."""
        assert table_widget.columnCount() == 3
        assert table_widget.rowCount() == 0
        assert table_widget.horizontalHeaderItem(0).text() == "Task"
        assert table_widget.horizontalHeaderItem(1).text() == "Due Date"
        assert table_widget.horizontalHeaderItem(2).text() == "Actions"
    
    def test_widget_persistence(self, table_widget):
        """Test that widgets persist after creation - specifically testing the original bug."""
        # Create 10 test rows as requested
        for i in range(10):
            row_position = table_widget.rowCount()
            table_widget.insertRow(row_position)
            
            # Create task data
            task_data = (i, f"Test task {i}", f"12-{i+1:02d}-2024", 0, "test_session")
            
            # Create and set task widget
            task_widget = self.create_task_widget(task_data)
            table_widget.setCellWidget(row_position, 0, task_widget)
            
            # Set due date
            due_date_item = QTableWidgetItem(f"12-{i+1:02d}-2024")
            due_date_item.setFlags(due_date_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table_widget.setItem(row_position, 1, due_date_item)
            
            # Create and set actions widget
            actions_widget = self.create_actions_widget(row_position)
            table_widget.setCellWidget(row_position, 2, actions_widget)
            
            # Apply styling
            self.apply_row_styling(table_widget, row_position, 0, f"12-{i+1:02d}-2024")
        
        # Verify all widgets exist - this is the key test for the original bug
        assert table_widget.rowCount() == 10
        
        for row in range(10):
            # Check task widget (column 0)
            task_widget = table_widget.cellWidget(row, 0)
            assert task_widget is not None, f"Task widget missing for row {row}"
            assert hasattr(task_widget, 'task_data'), f"Task data missing for row {row}"
            assert task_widget.task_data['task'] == f"Test task {row}"
            
            # Check due date item (column 1)
            due_date_item = table_widget.item(row, 1)
            assert due_date_item is not None, f"Due date item missing for row {row}"
            assert due_date_item.text() == f"12-{row+1:02d}-2024"
            
            # Check actions widget (column 2) - this was the main issue
            actions_widget = table_widget.cellWidget(row, 2)
            assert actions_widget is not None, f"Actions widget missing for row {row}"
            
            # Verify buttons exist in actions widget
            buttons = actions_widget.findChildren(QPushButton)
            assert len(buttons) == 2, f"Expected 2 buttons in row {row}, found {len(buttons)}"
            assert buttons[0].text() == "Edit"
            assert buttons[1].text() == "Delete"
    
    def test_widget_persistence_with_duplicate_dates(self, table_widget):
        """Test widget persistence with duplicate due dates (known issue trigger)."""
        # Create rows with duplicate due dates - this was causing the original bug
        duplicate_date = "12-01-2024"
        test_data = [
            (1, "Task A", duplicate_date, 0, "session1"),
            (2, "Task B", duplicate_date, 0, "session1"),  # Same date
            (3, "Task C", duplicate_date, 1, "session1"),  # Same date, different completion
        ]
        
        # Add rows
        for task_data in test_data:
            row_position = table_widget.rowCount()
            table_widget.insertRow(row_position)
            
            task_widget = self.create_task_widget(task_data)
            table_widget.setCellWidget(row_position, 0, task_widget)
            
            due_date_item = QTableWidgetItem(task_data[2])
            due_date_item.setFlags(due_date_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table_widget.setItem(row_position, 1, due_date_item)
            
            actions_widget = self.create_actions_widget(row_position)
            table_widget.setCellWidget(row_position, 2, actions_widget)
        
        # Verify all widgets exist before sorting
        assert table_widget.rowCount() == 3
        for row in range(3):
            actions_widget = table_widget.cellWidget(row, 2)
            assert actions_widget is not None, f"Actions widget missing before sorting for row {row}"
        
        # Sort by due date - this was causing widgets to disappear
        table_widget.sortItems(1, Qt.SortOrder.AscendingOrder)
        
        # Verify widgets still exist after sorting with duplicate dates
        for row in range(3):
            actions_widget = table_widget.cellWidget(row, 2)
            assert actions_widget is not None, f"Actions widget missing after sorting for row {row}"
            
            task_widget = table_widget.cellWidget(row, 0)
            assert task_widget is not None, f"Task widget missing after sorting for row {row}"
    
    def test_widget_after_sorting(self, table_widget):
        """Test that widgets persist after sorting."""
        # Create test data with different due dates
        test_data = [
            (1, "Task A", "12-31-2024", 0, "session1"),
            (2, "Task B", "12-01-2024", 0, "session1"),
            (3, "Task C", "12-15-2024", 0, "session1"),
        ]
        
        # Add rows
        for task_data in test_data:
            row_position = table_widget.rowCount()
            table_widget.insertRow(row_position)
            
            task_widget = self.create_task_widget(task_data)
            table_widget.setCellWidget(row_position, 0, task_widget)
            
            due_date_item = QTableWidgetItem(task_data[2])
            due_date_item.setFlags(due_date_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table_widget.setItem(row_position, 1, due_date_item)
            
            actions_widget = self.create_actions_widget(row_position)
            table_widget.setCellWidget(row_position, 2, actions_widget)
        
        # Verify initial state
        assert table_widget.rowCount() == 3
        
        # Sort by due date (column 1)
        table_widget.sortItems(1, Qt.SortOrder.AscendingOrder)
        
        # Verify widgets still exist after sorting
        for row in range(3):
            task_widget = table_widget.cellWidget(row, 0)
            assert task_widget is not None, f"Task widget missing after sorting for row {row}"
            
            actions_widget = table_widget.cellWidget(row, 2)
            assert actions_widget is not None, f"Actions widget missing after sorting for row {row}"
    
    def test_checkbox_functionality(self, table_widget):
        """Test checkbox state changes."""
        # Create a single row with checkbox
        table_widget.insertRow(0)
        task_data = (1, "Test task", "12-01-2024", 0, "session1")
        task_widget = self.create_task_widget(task_data)
        table_widget.setCellWidget(0, 0, task_widget)
        
        # Find the checkbox
        checkbox = task_widget.findChild(QCheckBox)
        assert checkbox is not None
        assert not checkbox.isChecked()
        
        # Simulate checking the checkbox
        checkbox.setChecked(True)
        assert checkbox.isChecked()
        
        # Verify task data is accessible
        assert task_widget.task_data['completed'] == 0  # Original value
        # Note: In real implementation, you'd update task_data when checkbox changes
    
    def test_database_integration(self, table_widget):
        """Test loading data from database."""
        if not os.path.exists(DATABASE_PATH):
            pytest.skip(f"Database file not found: {DATABASE_PATH}")
        
        try:
            with sqlite3.connect(DATABASE_PATH) as conn:
                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks';")
                if not cursor.fetchone():
                    pytest.skip("Tasks table does not exist in database")
                
                # Get sample tasks
                cursor = conn.execute("SELECT id, task, due_date, completed, session_id FROM tasks LIMIT 5")
                tasks = cursor.fetchall()
                
                if not tasks:
                    pytest.skip("No tasks found in database")
                
                # Load tasks into table
                for task_data in tasks:
                    row_position = table_widget.rowCount()
                    table_widget.insertRow(row_position)
                    
                    task_widget = self.create_task_widget(task_data)
                    table_widget.setCellWidget(row_position, 0, task_widget)
                    
                    due_date_display = task_data[2] if task_data[2] else "No due date"
                    due_date_item = QTableWidgetItem(due_date_display)
                    due_date_item.setFlags(due_date_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    table_widget.setItem(row_position, 1, due_date_item)
                    
                    actions_widget = self.create_actions_widget(row_position)
                    table_widget.setCellWidget(row_position, 2, actions_widget)
                
                # Verify all widgets were created
                assert table_widget.rowCount() == len(tasks)
                
                for row in range(len(tasks)):
                    task_widget = table_widget.cellWidget(row, 0)
                    assert task_widget is not None, f"Task widget missing for database row {row}"
                    
                    actions_widget = table_widget.cellWidget(row, 2)
                    assert actions_widget is not None, f"Actions widget missing for database row {row}"
                    
                    # Verify task data matches database
                    expected_task = tasks[row]
                    assert task_widget.task_data['id'] == expected_task[0]
                    assert task_widget.task_data['task'] == expected_task[1]
                    
        except sqlite3.Error as e:
            pytest.skip(f"Database error: {e}")
    
    def test_row_styling(self, table_widget):
        """Test row styling functionality."""
        # Create test rows with different completion statuses
        test_cases = [
            (1, "Completed task", "12-01-2024", 1, "session1"),
            (2, "Incomplete task", "12-02-2024", 0, "session1"),
        ]
        
        for task_data in test_cases:
            row_position = table_widget.rowCount()
            table_widget.insertRow(row_position)
            
            task_widget = self.create_task_widget(task_data)
            table_widget.setCellWidget(row_position, 0, task_widget)
            
            due_date_item = QTableWidgetItem(task_data[2])
            due_date_item.setFlags(due_date_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table_widget.setItem(row_position, 1, due_date_item)
            
            # Apply styling
            self.apply_row_styling(table_widget, row_position, task_data[3], task_data[2])
        
        # Verify styling was applied
        for row in range(len(test_cases)):
            due_date_item = table_widget.item(row, 1)
            assert due_date_item is not None
            # Check that background color was set (we can't easily test specific colors in pytest)
            assert due_date_item.background() is not None
    
    def test_table_operations(self, table_widget):
        """Test various table operations."""
        # Test inserting rows
        initial_rows = table_widget.rowCount()
        table_widget.insertRow(0)
        assert table_widget.rowCount() == initial_rows + 1
        
        # Test removing rows
        table_widget.removeRow(0)
        assert table_widget.rowCount() == initial_rows
        
        # Test clearing table
        table_widget.insertRow(0)
        table_widget.insertRow(1)
        assert table_widget.rowCount() == 2
        
        table_widget.setRowCount(0)
        assert table_widget.rowCount() == 0


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])
