"""
Tests for the Tasks Tab (Vikunja integration).

This test suite covers:
- Connection testing and authentication
- Project management (loading, creating)
- Task management (loading, creating, toggling)
- UI initialization and error handling
"""
import pytest
import sys
import os
from unittest.mock import Mock, patch, MagicMock
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from gui.tasks_tab import TasksTab, VIKUNJA_AVAILABLE


@pytest.fixture(scope="module")
def qapp():
    """Create QApplication instance for tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def mock_vikunja_client():
    """Create a mock VikunjaClient."""
    # Create a mock client without importing the actual class
    client = Mock()
    client.test_connection = Mock(return_value=True)
    client.login = Mock(return_value=None)
    client.register = Mock(return_value=None)
    client.get_projects = Mock(return_value=[
        {"id": 1, "title": "Project 1"},
        {"id": 2, "title": "Project 2"}
    ])
    client.get_tasks = Mock(return_value=[
        {"id": 1, "title": "Task 1", "priority": 3, "done": False},
        {"id": 2, "title": "Task 2", "priority": 1, "done": True}
    ])
    client.create_project = Mock(return_value={"id": 3, "title": "New Project"})
    client.create_task = Mock(return_value={"id": 3, "title": "New Task"})
    client.toggle_task_done = Mock(return_value=None)
    return client


@pytest.fixture
def tasks_tab(qapp, mock_vikunja_client):
    """Create a TasksTab instance for testing."""
    with patch('gui.tasks_tab.VikunjaClient', return_value=mock_vikunja_client):
        with patch('gui.tasks_tab.VIKUNJA_AVAILABLE', True):
            tab = TasksTab()
            return tab


class TestTasksTabInitialization:
    """Test TasksTab initialization."""
    
    def test_init_creates_widget(self, qapp):
        """Test that TasksTab initializes correctly."""
        with patch('gui.tasks_tab.VikunjaClient'):
            with patch('gui.tasks_tab.VIKUNJA_AVAILABLE', True):
                tab = TasksTab()
                assert tab is not None
                assert tab.client is None
                assert tab.current_project_id is None
    
    def test_init_sets_default_url(self, qapp):
        """Test that default URL is set."""
        with patch('gui.tasks_tab.VikunjaClient'):
            with patch('gui.tasks_tab.VIKUNJA_AVAILABLE', True):
                tab = TasksTab()
                assert tab.url_input.text() == "http://localhost:3456"
    
    def test_init_ui_creates_widgets(self, qapp):
        """Test that UI widgets are created."""
        with patch('gui.tasks_tab.VikunjaClient'):
            with patch('gui.tasks_tab.VIKUNJA_AVAILABLE', True):
                tab = TasksTab()
                assert tab.url_input is not None
                assert tab.username_input is not None
                assert tab.password_input is not None
                assert tab.email_input is not None
                assert tab.test_btn is not None
                assert tab.login_btn is not None
                assert tab.register_btn is not None
                assert tab.project_combo is not None
                assert tab.task_table is not None


class TestConnection:
    """Test connection functionality."""
    
    def test_test_connection_success(self, tasks_tab, mock_vikunja_client):
        """Test successful connection test."""
        tasks_tab.url_input.setText("http://localhost:3456")
        mock_vikunja_client.test_connection.return_value = True
        
        with patch('gui.tasks_tab.VikunjaClient', return_value=mock_vikunja_client):
            with patch('PyQt6.QtWidgets.QMessageBox.information') as mock_info:
                tasks_tab.test_connection()
                mock_info.assert_called_once()
                assert "Connection OK" in tasks_tab.conn_status.text()
    
    def test_test_connection_failure(self, tasks_tab, mock_vikunja_client):
        """Test failed connection test."""
        tasks_tab.url_input.setText("http://localhost:3456")
        mock_vikunja_client.test_connection.return_value = False
        
        with patch('gui.tasks_tab.VikunjaClient', return_value=mock_vikunja_client):
            with patch('PyQt6.QtWidgets.QMessageBox.warning') as mock_warn:
                tasks_tab.test_connection()
                mock_warn.assert_called_once()
                assert "Connection failed" in tasks_tab.conn_status.text()
    
    def test_test_connection_no_url(self, tasks_tab):
        """Test connection test with no URL."""
        tasks_tab.url_input.clear()
        
        with patch('PyQt6.QtWidgets.QMessageBox.warning') as mock_warn:
            tasks_tab.test_connection()
            mock_warn.assert_called_once()
    
    def test_test_connection_exception(self, tasks_tab, mock_vikunja_client):
        """Test connection test with exception."""
        tasks_tab.url_input.setText("http://localhost:3456")
        
        # Make VikunjaClient instantiation raise an exception
        with patch('gui.tasks_tab.VikunjaClient', side_effect=Exception("Connection error")):
            with patch('PyQt6.QtWidgets.QMessageBox.critical') as mock_critical:
                tasks_tab.test_connection()
                mock_critical.assert_called_once()


class TestLogin:
    """Test login functionality."""
    
    def test_login_success(self, tasks_tab, mock_vikunja_client):
        """Test successful login."""
        tasks_tab.url_input.setText("http://localhost:3456")
        tasks_tab.username_input.setText("testuser")
        tasks_tab.password_input.setText("testpass")
        
        with patch('gui.tasks_tab.VikunjaClient', return_value=mock_vikunja_client):
            tasks_tab.login()
            mock_vikunja_client.login.assert_called_once_with("testuser", "testpass")
            assert tasks_tab.client is not None
            assert "Connected as testuser" in tasks_tab.conn_status.text()
            assert tasks_tab.refresh_btn.isEnabled()
            assert tasks_tab.new_project_btn.isEnabled()
            assert tasks_tab.create_task_btn.isEnabled()
            # No success popup expected - only errors are shown
    
    def test_login_missing_fields(self, tasks_tab):
        """Test login with missing fields."""
        tasks_tab.url_input.setText("")
        tasks_tab.username_input.setText("")
        tasks_tab.password_input.setText("")
        
        with patch('PyQt6.QtWidgets.QMessageBox.warning') as mock_warn:
            tasks_tab.login()
            mock_warn.assert_called_once()
    
    def test_login_failure(self, tasks_tab, mock_vikunja_client):
        """Test login failure."""
        tasks_tab.url_input.setText("http://localhost:3456")
        tasks_tab.username_input.setText("testuser")
        tasks_tab.password_input.setText("wrongpass")
        mock_vikunja_client.login.side_effect = Exception("Invalid credentials")
        
        with patch('gui.tasks_tab.VikunjaClient', return_value=mock_vikunja_client):
            with patch('PyQt6.QtWidgets.QMessageBox.critical') as mock_critical:
                tasks_tab.login()
                mock_critical.assert_called_once()


class TestRegister:
    """Test registration functionality."""
    
    def test_register_success(self, tasks_tab, mock_vikunja_client):
        """Test successful registration."""
        tasks_tab.url_input.setText("http://localhost:3456")
        tasks_tab.username_input.setText("newuser")
        tasks_tab.email_input.setText("newuser@example.com")
        tasks_tab.password_input.setText("newpass")
        
        with patch('gui.tasks_tab.VikunjaClient', return_value=mock_vikunja_client):
            tasks_tab.register()
            mock_vikunja_client.register.assert_called_once_with("newuser", "newuser@example.com", "newpass")
            assert tasks_tab.client is not None
            assert "Connected as newuser" in tasks_tab.conn_status.text()
            # No success popup expected - only errors are shown
    
    def test_register_missing_fields(self, tasks_tab):
        """Test registration with missing fields."""
        tasks_tab.url_input.setText("")
        tasks_tab.username_input.setText("")
        tasks_tab.email_input.setText("")
        tasks_tab.password_input.setText("")
        
        with patch('PyQt6.QtWidgets.QMessageBox.warning') as mock_warn:
            tasks_tab.register()
            mock_warn.assert_called_once()
    
    def test_register_failure(self, tasks_tab, mock_vikunja_client):
        """Test registration failure."""
        tasks_tab.url_input.setText("http://localhost:3456")
        tasks_tab.username_input.setText("newuser")
        tasks_tab.email_input.setText("newuser@example.com")
        tasks_tab.password_input.setText("newpass")
        mock_vikunja_client.register.side_effect = Exception("Registration failed")
        
        with patch('gui.tasks_tab.VikunjaClient', return_value=mock_vikunja_client):
            with patch('PyQt6.QtWidgets.QMessageBox.critical') as mock_critical:
                tasks_tab.register()
                mock_critical.assert_called_once()


class TestProjectManagement:
    """Test project management functionality."""
    
    def test_load_projects_success(self, tasks_tab, mock_vikunja_client):
        """Test loading projects successfully."""
        tasks_tab.client = mock_vikunja_client
        mock_vikunja_client.get_projects.return_value = [
            {"id": 1, "title": "Project 1"},
            {"id": 2, "title": "Project 2"}
        ]
        
        tasks_tab.load_projects()
        
        assert tasks_tab.project_combo.count() == 2
        assert tasks_tab.project_combo.itemText(0) == "Project 1"
        assert tasks_tab.project_combo.itemData(0) == 1
        assert tasks_tab.project_combo.itemText(1) == "Project 2"
        assert tasks_tab.project_combo.itemData(1) == 2
    
    def test_load_projects_no_client(self, tasks_tab):
        """Test loading projects without client."""
        tasks_tab.client = None
        tasks_tab.load_projects()
        # Should not crash
    
    def test_load_projects_exception(self, tasks_tab, mock_vikunja_client):
        """Test loading projects with exception."""
        tasks_tab.client = mock_vikunja_client
        mock_vikunja_client.get_projects.side_effect = Exception("API error")
        
        with patch('gui.tasks_tab.QMessageBox.critical') as mock_critical:
            tasks_tab.load_projects()
            mock_critical.assert_called_once()
    
    def test_create_project_success(self, tasks_tab, mock_vikunja_client):
        """Test creating a project successfully."""
        tasks_tab.client = mock_vikunja_client
        
        with patch('PyQt6.QtWidgets.QInputDialog.getText', return_value=("New Project", True)):
            with patch('PyQt6.QtWidgets.QMessageBox.information') as mock_info:
                tasks_tab.create_project()
                mock_vikunja_client.create_project.assert_called_once_with("New Project")
                mock_info.assert_called_once()
    
    def test_create_project_cancelled(self, tasks_tab, mock_vikunja_client):
        """Test cancelling project creation."""
        tasks_tab.client = mock_vikunja_client
        
        with patch('PyQt6.QtWidgets.QInputDialog.getText', return_value=("", False)):
            tasks_tab.create_project()
            mock_vikunja_client.create_project.assert_not_called()
    
    def test_create_project_no_client(self, tasks_tab):
        """Test creating project without client."""
        tasks_tab.client = None
        
        with patch('PyQt6.QtWidgets.QInputDialog.getText', return_value=("New Project", True)):
            tasks_tab.create_project()
            # Should not crash
    
    def test_create_project_exception(self, tasks_tab, mock_vikunja_client):
        """Test creating project with exception."""
        tasks_tab.client = mock_vikunja_client
        mock_vikunja_client.create_project.side_effect = Exception("API error")
        
        with patch('PyQt6.QtWidgets.QInputDialog.getText', return_value=("New Project", True)):
            with patch('PyQt6.QtWidgets.QMessageBox.critical') as mock_critical:
                tasks_tab.create_project()
                mock_critical.assert_called_once()


class TestTaskManagement:
    """Test task management functionality."""
    
    def test_load_tasks_success(self, tasks_tab, mock_vikunja_client):
        """Test loading tasks successfully."""
        tasks_tab.client = mock_vikunja_client
        tasks_tab.project_combo.addItem("Project 1", 1)
        tasks_tab.project_combo.setCurrentIndex(0)
        
        mock_vikunja_client.get_tasks.return_value = [
            {"id": 1, "title": "Task 1", "priority": 3, "done": False},
            {"id": 2, "title": "Task 2", "priority": 1, "done": True}
        ]
        
        tasks_tab.load_tasks()
        
        assert tasks_tab.task_table.rowCount() == 2
        assert tasks_tab.task_table.item(0, 1).text() == "Task 1"
        assert tasks_tab.task_table.item(1, 1).text() == "Task 2"
        assert tasks_tab.current_project_id == 1
    
    def test_load_tasks_no_client(self, tasks_tab):
        """Test loading tasks without client."""
        tasks_tab.client = None
        tasks_tab.load_tasks()
        # Should not crash
    
    def test_load_tasks_no_project(self, tasks_tab, mock_vikunja_client):
        """Test loading tasks with no project selected."""
        tasks_tab.client = mock_vikunja_client
        tasks_tab.project_combo.clear()
        
        tasks_tab.load_tasks()
        
        assert tasks_tab.task_table.rowCount() == 0
    
    def test_load_tasks_exception(self, tasks_tab, mock_vikunja_client):
        """Test loading tasks with exception."""
        tasks_tab.client = mock_vikunja_client
        tasks_tab.project_combo.addItem("Project 1", 1)
        tasks_tab.project_combo.setCurrentIndex(0)
        mock_vikunja_client.get_tasks.side_effect = Exception("API error")
        
        with patch('gui.tasks_tab.QMessageBox.critical') as mock_critical:
            tasks_tab.load_tasks()
            mock_critical.assert_called_once()
    
    def test_create_task_success(self, tasks_tab, mock_vikunja_client):
        """Test creating a task successfully."""
        tasks_tab.client = mock_vikunja_client
        tasks_tab.current_project_id = 1
        tasks_tab.task_title_input.setText("New Task")
        tasks_tab.priority_spin.setValue(2)
        
        tasks_tab.create_task()
        mock_vikunja_client.create_task.assert_called_once_with(1, "New Task", priority=2)
        assert tasks_tab.task_title_input.text() == ""
        # No success popup expected - only errors are shown
    
    def test_create_task_no_client(self, tasks_tab):
        """Test creating task without client."""
        tasks_tab.client = None
        tasks_tab.current_project_id = 1
        
        with patch('gui.tasks_tab.QMessageBox.warning') as mock_warn:
            tasks_tab.create_task()
            mock_warn.assert_called_once()
    
    def test_create_task_no_project(self, tasks_tab, mock_vikunja_client):
        """Test creating task with no project selected."""
        tasks_tab.client = mock_vikunja_client
        tasks_tab.current_project_id = None
        
        with patch('gui.tasks_tab.QMessageBox.warning') as mock_warn:
            tasks_tab.create_task()
            mock_warn.assert_called_once()
    
    def test_create_task_no_title(self, tasks_tab, mock_vikunja_client):
        """Test creating task with no title."""
        tasks_tab.client = mock_vikunja_client
        tasks_tab.current_project_id = 1
        tasks_tab.task_title_input.clear()
        
        with patch('gui.tasks_tab.QMessageBox.warning') as mock_warn:
            tasks_tab.create_task()
            mock_warn.assert_called_once()
    
    def test_create_task_exception(self, tasks_tab, mock_vikunja_client):
        """Test creating task with exception."""
        tasks_tab.client = mock_vikunja_client
        tasks_tab.current_project_id = 1
        tasks_tab.task_title_input.setText("New Task")
        mock_vikunja_client.create_task.side_effect = Exception("API error")
        
        with patch('gui.tasks_tab.QMessageBox.critical') as mock_critical:
            tasks_tab.create_task()
            mock_critical.assert_called_once()
    
    def test_toggle_task_success(self, tasks_tab, mock_vikunja_client):
        """Test toggling task done status successfully."""
        tasks_tab.client = mock_vikunja_client
        
        tasks_tab.toggle_task(1, True)
        
        mock_vikunja_client.toggle_task_done.assert_called_once_with(1, True)
    
    def test_toggle_task_no_client(self, tasks_tab):
        """Test toggling task without client."""
        tasks_tab.client = None
        tasks_tab.toggle_task(1, True)
        # Should not crash
    
    def test_toggle_task_exception(self, tasks_tab, mock_vikunja_client):
        """Test toggling task with exception."""
        tasks_tab.client = mock_vikunja_client
        mock_vikunja_client.toggle_task_done.side_effect = Exception("API error")
        
        with patch('gui.tasks_tab.QMessageBox.critical') as mock_critical:
            tasks_tab.toggle_task(1, True)
            mock_critical.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

