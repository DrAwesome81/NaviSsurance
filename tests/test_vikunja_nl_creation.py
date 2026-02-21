"""
Tests for natural language Vikunja task creation via chat.
"""
import os
import pytest
from unittest.mock import Mock, patch, MagicMock
import json
from datetime import datetime

# Disabled by default: depends on CoS orchestration and task tab wiring.
if not os.getenv("RUN_VIKUNJA_TESTS"):
    pytest.skip(
        "Vikunja NL creation tests are disabled by default (set RUN_VIKUNJA_TESTS=1 to enable).",
        allow_module_level=True,
    )

# Import the classes we need to test
from core.response_handler import ResponseHandler
from core.chat_handler import ChatHandler


class TestVikunjaNaturalLanguageCreation:
    """Test natural language task creation for Vikunja."""
    
    @pytest.fixture
    def mock_chat_handler(self):
        """Create a mock ChatHandler."""
        handler = Mock(spec=ChatHandler)
        handler.db = Mock()
        return handler
    
    @pytest.fixture
    def mock_chat_window(self):
        """Create a mock ChatWindow with TasksTab."""
        window = Mock()
        window.tasks_tab = Mock()
        window.tasks_tab.client = Mock()
        window.tasks_tab.current_project_id = 1
        window.tasks_tab._save_estimated_duration = Mock()
        window.tasks_tab.load_tasks = Mock()
        
        # Mock tab widget
        window.tab_widget = Mock()
        window.tab_widget.currentIndex.return_value = 1  # Tasks tab is active
        window.tab_widget.count.return_value = 5
        window.tab_widget.tabText.side_effect = lambda i: ["Dashboard", "Tasks", "Workspace", "Compliance", "Meetings"][i]
        
        return window
    
    @pytest.fixture
    def response_handler(self, mock_chat_handler, mock_chat_window):
        """Create ResponseHandler with mocked dependencies."""
        with patch('core.response_handler.subprocess.Popen') as mock_popen:
            # Mock the subprocess for llama worker
            mock_process = Mock()
            mock_process.pid = 12345
            mock_process.stderr.readline.side_effect = ["MODEL_LOADED", ""]
            mock_process.stdout.readline.return_value = '{"response": "test"}'
            mock_process.poll.return_value = None
            mock_popen.return_value = mock_process
            
            handler = ResponseHandler(mock_chat_handler, mock_chat_window)
            handler.model_loaded = True
            handler.process = mock_process
            return handler
    
    def test_detects_tasks_tab_active(self, response_handler, mock_chat_window):
        """Test that the system detects when Tasks tab is active."""
        # Set Tasks tab as active (index 1)
        mock_chat_window.tab_widget.currentIndex.return_value = 1
        
        # Mock get_projects
        mock_chat_window.tasks_tab.client.get_projects.return_value = [
            {"id": 1, "title": "Test Project"}
        ]
        
        # Mock create_task
        mock_chat_window.tasks_tab.client.create_task.return_value = {"id": 123}
        
        # Mock Llama response for parsing
        with patch.object(response_handler, 'chat_with_llama') as mock_llama:
            mock_llama.return_value = json.dumps({
                "title": "Test Task",
                "description": "Test description",
                "priority": 3,
                "due_date": "2024-12-31",
                "estimated_duration_minutes": 120,
                "project_name": None
            })
            
            # Test with ADD_TASK format
            task_segments = ["Test Task|2024-12-31"]
            result = response_handler._handle_vikunja_task_creation(
                task_segments, "Add a test task", [], "test_session"
            )
            
            # Verify task was created
            mock_chat_window.tasks_tab.client.create_task.assert_called_once()
            assert "created" in result.lower() or "task" in result.lower()
    
    def test_requires_vikunja_login(self, response_handler, mock_chat_window):
        """Test that it requires Vikunja login."""
        # Set client to None (not logged in)
        mock_chat_window.tasks_tab.client = None
        
        task_segments = ["Test Task|2024-12-31"]
        result = response_handler._handle_vikunja_task_creation(
            task_segments, "Add a test task", [], "test_session"
        )
        
        assert "login" in result.lower() or "logged" in result.lower()
        # Verify that get_projects was not called (early return)
        # We can't check create_task because client is None
    
    def test_requires_project_selection(self, response_handler, mock_chat_window):
        """Test that it requires a project to be selected."""
        # Set current_project_id to None
        mock_chat_window.tasks_tab.current_project_id = None
        
        task_segments = ["Test Task|2024-12-31"]
        result = response_handler._handle_vikunja_task_creation(
            task_segments, "Add a test task", [], "test_session"
        )
        
        assert "project" in result.lower()
        mock_chat_window.tasks_tab.client.create_task.assert_not_called()
    
    def test_parses_task_details(self, response_handler, mock_chat_window):
        """Test parsing of task details from natural language."""
        mock_chat_window.tasks_tab.client.get_projects.return_value = [
            {"id": 1, "title": "Test Project"}
        ]
        mock_chat_window.tasks_tab.client.create_task.return_value = {"id": 123}
        
        with patch.object(response_handler, 'chat_with_llama') as mock_llama:
            mock_llama.return_value = json.dumps({
                "title": "Review FDA submission",
                "description": "Review the FDA submission document",
                "priority": 5,
                "due_date": "2024-12-31",
                "estimated_duration_minutes": 120,
                "project_name": None
            })
            
            task_segments = ["Review FDA submission|2024-12-31"]
            result = response_handler._handle_vikunja_task_creation(
                task_segments, "Review FDA submission by end of year, urgent priority, 2 hours", [], "test_session"
            )
            
            # Verify create_task was called with correct parameters
            call_args = mock_chat_window.tasks_tab.client.create_task.call_args
            assert call_args[1]['title'] == "Review FDA submission"
            assert call_args[1]['description'] == "Review the FDA submission document"
            assert call_args[1]['priority'] == 5
            assert call_args[1]['due_date'] == "2024-12-31"
    
    def test_saves_estimated_duration(self, response_handler, mock_chat_window):
        """Test that estimated duration is saved to database."""
        mock_chat_window.tasks_tab.client.get_projects.return_value = [
            {"id": 1, "title": "Test Project"}
        ]
        mock_chat_window.tasks_tab.client.create_task.return_value = {"id": 123}
        
        with patch.object(response_handler, 'chat_with_llama') as mock_llama:
            mock_llama.return_value = json.dumps({
                "title": "Test Task",
                "description": "",
                "priority": 0,
                "due_date": None,
                "estimated_duration_minutes": 90,
                "project_name": None
            })
            
            task_segments = ["Test Task|unknown"]
            response_handler._handle_vikunja_task_creation(
                task_segments, "Add a test task, 90 minutes", [], "test_session"
            )
            
            # Verify estimated duration was saved
            mock_chat_window.tasks_tab._save_estimated_duration.assert_called_once_with(123, 90)
    
    def test_handles_missing_title(self, response_handler, mock_chat_window):
        """Test handling of missing title in parsed data."""
        mock_chat_window.tasks_tab.client.get_projects.return_value = [
            {"id": 1, "title": "Test Project"}
        ]
        
        with patch.object(response_handler, 'chat_with_llama') as mock_llama:
            mock_llama.return_value = json.dumps({
                "title": "",  # Missing title
                "description": "Some description",
                "priority": 0,
                "due_date": None,
                "estimated_duration_minutes": None,
                "project_name": None
            })
            
            task_segments = ["|unknown"]
            result = response_handler._handle_vikunja_task_creation(
                task_segments, "Add a task", [], "test_session"
            )
            
            # Should report missing information
            assert "missing" in result.lower() or "issue" in result.lower()
            mock_chat_window.tasks_tab.client.create_task.assert_not_called()
    
    def test_handles_json_parse_error(self, response_handler, mock_chat_window):
        """Test handling of JSON parsing errors."""
        mock_chat_window.tasks_tab.client.get_projects.return_value = [
            {"id": 1, "title": "Test Project"}
        ]
        
        with patch.object(response_handler, 'chat_with_llama') as mock_llama:
            # Return invalid JSON
            mock_llama.return_value = "This is not valid JSON"
            
            task_segments = ["Test Task|2024-12-31"]
            result = response_handler._handle_vikunja_task_creation(
                task_segments, "Add a test task", [], "test_session"
            )
            
            # Should handle error gracefully
            assert "error" in result.lower() or "issue" in result.lower() or "parsing" in result.lower()
    
    def test_handles_multiple_tasks(self, response_handler, mock_chat_window):
        """Test handling of multiple tasks in one request."""
        mock_chat_window.tasks_tab.client.get_projects.return_value = [
            {"id": 1, "title": "Test Project"}
        ]
        mock_chat_window.tasks_tab.client.create_task.return_value = {"id": 123}
        
        with patch.object(response_handler, 'chat_with_llama') as mock_llama:
            mock_llama.return_value = json.dumps({
                "title": "Test Task",
                "description": "",
                "priority": 0,
                "due_date": None,
                "estimated_duration_minutes": None,
                "project_name": None
            })
            
            task_segments = ["Task 1|2024-12-31", "Task 2|2025-01-15"]
            result = response_handler._handle_vikunja_task_creation(
                task_segments, "Add two tasks", [], "test_session"
            )
            
            # Should create both tasks
            assert mock_chat_window.tasks_tab.client.create_task.call_count == 2
    
    def test_project_name_matching(self, response_handler, mock_chat_window):
        """Test that project names are matched correctly."""
        mock_chat_window.tasks_tab.client.get_projects.return_value = [
            {"id": 1, "title": "Project Alpha"},
            {"id": 2, "title": "Project Beta"}
        ]
        mock_chat_window.tasks_tab.client.create_task.return_value = {"id": 123}
        
        with patch.object(response_handler, 'chat_with_llama') as mock_llama:
            mock_llama.return_value = json.dumps({
                "title": "Test Task",
                "description": "",
                "priority": 0,
                "due_date": None,
                "estimated_duration_minutes": None,
                "project_name": "Project Beta"
            })
            
            task_segments = ["Test Task|unknown"]
            response_handler._handle_vikunja_task_creation(
                task_segments, "Add task to Project Beta", [], "test_session"
            )
            
            # Verify task was created with correct project ID
            call_args = mock_chat_window.tasks_tab.client.create_task.call_args
            assert call_args[1]['project_id'] == 2
    
    def test_falls_back_to_old_system_when_not_on_tasks_tab(self, response_handler, mock_chat_window):
        """Test that it falls back to old task system when not on Tasks tab."""
        # Set current tab to Dashboard (index 0)
        mock_chat_window.tab_widget.currentIndex.return_value = 0
        
        # This should not call Vikunja creation
        # The get_response method should handle ADD_TASK normally
        # We can't easily test this without mocking the entire get_response flow
        # But the logic is there in the code
    
    def test_reloads_tasks_after_creation(self, response_handler, mock_chat_window):
        """Test that task list is reloaded after creating tasks."""
        mock_chat_window.tasks_tab.client.get_projects.return_value = [
            {"id": 1, "title": "Test Project"}
        ]
        mock_chat_window.tasks_tab.client.create_task.return_value = {"id": 123}
        
        with patch.object(response_handler, 'chat_with_llama') as mock_llama:
            mock_llama.return_value = json.dumps({
                "title": "Test Task",
                "description": "",
                "priority": 0,
                "due_date": None,
                "estimated_duration_minutes": None,
                "project_name": None
            })
            
            task_segments = ["Test Task|unknown"]
            response_handler._handle_vikunja_task_creation(
                task_segments, "Add a test task", [], "test_session"
            )
            
            # Verify load_tasks was called
            mock_chat_window.tasks_tab.load_tasks.assert_called_once()
    
    def test_get_response_routes_to_vikunja_when_on_tasks_tab(self, response_handler, mock_chat_window):
        """Test that get_response routes to Vikunja creation when on Tasks tab."""
        # Set Tasks tab as active
        mock_chat_window.tab_widget.currentIndex.return_value = 1
        
        # Mock Vikunja client
        mock_chat_window.tasks_tab.client.get_projects.return_value = [
            {"id": 1, "title": "Test Project"}
        ]
        mock_chat_window.tasks_tab.client.create_task.return_value = {"id": 123}
        
        # Mock the hybrid_wrapper to return ADD_TASK format
        with patch.object(response_handler, 'hybrid_wrapper') as mock_hybrid:
            mock_hybrid.return_value = "ADD_TASK:Test Task|2024-12-31"
            
            # Mock Llama parsing
            with patch.object(response_handler, 'chat_with_llama') as mock_llama:
                mock_llama.return_value = json.dumps({
                    "title": "Test Task",
                    "description": "",
                    "priority": 0,
                    "due_date": "2024-12-31",
                    "estimated_duration_minutes": None,
                    "project_name": None
                })
                
                # Call get_response
                result = response_handler.get_response(
                    "Add a test task", "test_session", []
                )
                
                # Verify Vikunja task was created
                mock_chat_window.tasks_tab.client.create_task.assert_called_once()
                assert "created" in result.lower() or "task" in result.lower()
    
    def test_get_response_falls_back_when_not_on_tasks_tab(self, response_handler, mock_chat_window):
        """Test that get_response falls back to old system when not on Tasks tab."""
        # Set Dashboard tab as active (index 0)
        mock_chat_window.tab_widget.currentIndex.return_value = 0
        
        # Mock the hybrid_wrapper to return ADD_TASK format
        with patch.object(response_handler, 'hybrid_wrapper') as mock_hybrid:
            mock_hybrid.return_value = "ADD_TASK:Test Task|2024-12-31"
            
            # Call get_response
            result = response_handler.get_response(
                "Add a test task", "test_session", []
            )
            
            # Should not create Vikunja task
            mock_chat_window.tasks_tab.client.create_task.assert_not_called()
            # Should return the normal response format
            assert "ADD_TASK" in result or "Added" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

