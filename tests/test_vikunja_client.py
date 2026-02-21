"""
Tests for the VikunjaClient API implementation.

This test suite covers:
- Client initialization
- Connection testing
- Authentication (login, register)
- Project management (get, create)
- Task management (get, create, update, toggle, delete)
- Error handling
"""
import pytest
import sys
import os
from unittest.mock import Mock, patch, MagicMock
import requests
from requests.exceptions import HTTPError, RequestException

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.vikunja_client import VikunjaClient


@pytest.fixture
def client():
    """Create a VikunjaClient instance for testing."""
    return VikunjaClient(base_url="http://localhost:3456")


@pytest.fixture
def mock_response():
    """Create a mock response object."""
    response = Mock(spec=requests.Response)
    response.status_code = 200
    response.json.return_value = {}
    response.raise_for_status = Mock()
    return response


class TestVikunjaClientInitialization:
    """Test VikunjaClient initialization."""
    
    def test_init_with_base_url(self):
        """Test client initialization with base URL."""
        client = VikunjaClient(base_url="http://localhost:3456")
        assert client.base_url == "http://localhost:3456"
        assert client.api_base == "http://localhost:3456/api/v1"
        assert client.token is None
    
    def test_init_removes_trailing_slash(self):
        """Test that trailing slashes are removed from base URL."""
        client = VikunjaClient(base_url="http://localhost:3456/")
        assert client.base_url == "http://localhost:3456"
        assert client.api_base == "http://localhost:3456/api/v1"
    
    def test_init_creates_session(self, client):
        """Test that a requests session is created."""
        assert client.session is not None
        assert 'Content-Type' in client.session.headers
        assert client.session.headers['Content-Type'] == 'application/json'


class TestConnection:
    """Test connection functionality."""
    
    @patch('core.vikunja_client.requests.Session.get')
    def test_test_connection_success(self, mock_get, client):
        """Test successful connection test."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response
        
        result = client.test_connection()
        assert result is True
        mock_get.assert_called_once()
    
    @patch('core.vikunja_client.requests.Session.get')
    def test_test_connection_unauthorized(self, mock_get, client):
        """Test connection test with 401 (server reachable but not authenticated)."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response
        
        result = client.test_connection()
        assert result is True  # Server is reachable
    
    @patch('core.vikunja_client.requests.Session.get')
    def test_test_connection_forbidden(self, mock_get, client):
        """Test connection test with 403 (server reachable but not authenticated)."""
        mock_response = Mock()
        mock_response.status_code = 403
        mock_get.return_value = mock_response
        
        result = client.test_connection()
        assert result is True  # Server is reachable
    
    @patch('core.vikunja_client.requests.Session.get')
    def test_test_connection_failure(self, mock_get, client):
        """Test connection test failure."""
        mock_get.side_effect = RequestException("Connection failed")
        
        result = client.test_connection()
        assert result is False


class TestAuthentication:
    """Test authentication functionality."""
    
    @patch('core.vikunja_client.requests.Session.post')
    def test_login_success(self, mock_post, client):
        """Test successful login."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'token': 'test_token_123'}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        client.login('testuser', 'testpass')
        
        assert client.token == 'test_token_123'
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == 'http://localhost:3456/api/v1/login'
        assert call_args[1]['json']['username'] == 'testuser'
        assert call_args[1]['json']['password'] == 'testpass'
    
    @patch('core.vikunja_client.requests.Session.post')
    def test_login_invalid_credentials(self, mock_post, client):
        """Test login with invalid credentials."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = HTTPError(response=mock_response)
        mock_post.return_value = mock_response
        
        with pytest.raises(ValueError, match="Invalid username or password"):
            client.login('testuser', 'wrongpass')
    
    @patch('core.vikunja_client.requests.Session.post')
    def test_login_no_token_in_response(self, mock_post, client):
        """Test login when response doesn't contain token."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}  # No token
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        with pytest.raises(ValueError, match="Login response did not contain token"):
            client.login('testuser', 'testpass')
    
    @patch('core.vikunja_client.VikunjaClient.login')
    @patch('core.vikunja_client.requests.Session.post')
    def test_register_success(self, mock_post, mock_login, client):
        """Test successful registration."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        # Mock login to avoid actual login call
        mock_login.return_value = None
        
        client.register('newuser', 'newuser@example.com', 'newpass')
        
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == 'http://localhost:3456/api/v1/register'
        assert call_args[1]['json']['username'] == 'newuser'
        assert call_args[1]['json']['email'] == 'newuser@example.com'
        assert call_args[1]['json']['password'] == 'newpass'
        # Login should be called after registration
        mock_login.assert_called_once_with('newuser', 'newpass')
    
    @patch('core.vikunja_client.requests.Session.post')
    def test_register_failure(self, mock_post, client):
        """Test registration failure."""
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.json.return_value = {'message': 'Username already exists'}
        mock_response.raise_for_status.side_effect = HTTPError(response=mock_response)
        mock_post.return_value = mock_response
        
        with pytest.raises(ValueError, match="Username already exists"):
            client.register('existinguser', 'existing@example.com', 'pass')


class TestProjectManagement:
    """Test project management functionality."""
    
    def test_get_projects_not_authenticated(self, client):
        """Test getting projects without authentication."""
        with pytest.raises(ValueError, match="Not authenticated"):
            client.get_projects()
    
    @patch('core.vikunja_client.VikunjaClient._request')
    def test_get_projects_success_list(self, mock_request, client):
        """Test getting projects when API returns a list."""
        client.token = 'test_token'
        mock_response = Mock()
        mock_response.json.return_value = [
            {'id': 1, 'title': 'Project 1'},
            {'id': 2, 'title': 'Project 2'}
        ]
        mock_request.return_value = mock_response
        
        projects = client.get_projects()
        
        assert len(projects) == 2
        assert projects[0]['id'] == 1
        assert projects[1]['id'] == 2
        mock_request.assert_called_once_with('GET', '/projects')
    
    @patch('core.vikunja_client.VikunjaClient._request')
    def test_get_projects_success_dict(self, mock_request, client):
        """Test getting projects when API returns a dict with 'projects' key."""
        client.token = 'test_token'
        mock_response = Mock()
        mock_response.json.return_value = {
            'projects': [
                {'id': 1, 'title': 'Project 1'},
                {'id': 2, 'title': 'Project 2'}
            ]
        }
        mock_request.return_value = mock_response
        
        projects = client.get_projects()
        
        assert len(projects) == 2
        assert projects[0]['id'] == 1
    
    @patch('core.vikunja_client.VikunjaClient._request')
    def test_create_project_minimal(self, mock_request, client):
        """Test creating project with minimal fields."""
        client.token = 'test_token'
        mock_response = Mock()
        mock_response.json.return_value = {'id': 1, 'title': 'New Project'}
        mock_request.return_value = mock_response
        
        result = client.create_project('New Project')
        
        assert result['id'] == 1
        assert result['title'] == 'New Project'
        mock_request.assert_called_once()
        call_args = mock_request.call_args
        assert call_args[0] == ('POST', '/projects')
        assert call_args[1]['json']['title'] == 'New Project'
    
    @patch('core.vikunja_client.VikunjaClient._request')
    def test_create_project_with_all_fields(self, mock_request, client):
        """Test creating project with all optional fields."""
        client.token = 'test_token'
        mock_response = Mock()
        mock_response.json.return_value = {'id': 1, 'title': 'New Project'}
        mock_request.return_value = mock_response
        
        result = client.create_project(
            title='New Project',
            description='Project description',
            hex_color='#ff0000',
            parent_project_id=5,
            is_favorite=True,
            is_archived=False,
            position=1
        )
        
        assert result['id'] == 1
        call_args = mock_request.call_args
        payload = call_args[1]['json']
        assert payload['title'] == 'New Project'
        assert payload['description'] == 'Project description'
        assert payload['hex_color'] == '#ff0000'
        assert payload['parent_project_id'] == 5
        assert payload['is_favorite'] is True
        assert payload['is_archived'] is False
        assert payload['position'] == 1


class TestTaskManagement:
    """Test task management functionality."""
    
    def test_get_tasks_not_authenticated(self, client):
        """Test getting tasks without authentication."""
        with pytest.raises(ValueError, match="Not authenticated"):
            client.get_tasks(project_id=1)
    
    @patch('core.vikunja_client.VikunjaClient._request')
    def test_get_tasks_success_list(self, mock_request, client):
        """Test getting tasks when API returns a list."""
        client.token = 'test_token'
        mock_response = Mock()
        mock_response.json.return_value = [
            {'id': 1, 'title': 'Task 1', 'priority': 3, 'done': False},
            {'id': 2, 'title': 'Task 2', 'priority': 1, 'done': True}
        ]
        mock_request.return_value = mock_response
        
        tasks = client.get_tasks(project_id=1)
        
        assert len(tasks) == 2
        assert tasks[0]['id'] == 1
        assert tasks[1]['id'] == 2
        mock_request.assert_called_once_with('GET', '/projects/1/tasks')
    
    @patch('core.vikunja_client.VikunjaClient._request')
    def test_get_tasks_success_dict(self, mock_request, client):
        """Test getting tasks when API returns a dict with 'tasks' key."""
        client.token = 'test_token'
        mock_response = Mock()
        mock_response.json.return_value = {
            'tasks': [
                {'id': 1, 'title': 'Task 1'}
            ]
        }
        mock_request.return_value = mock_response
        
        tasks = client.get_tasks(project_id=1)
        
        assert len(tasks) == 1
        assert tasks[0]['id'] == 1
    
    @patch('core.vikunja_client.VikunjaClient._request')
    def test_create_task_minimal(self, mock_request, client):
        """Test creating task with minimal fields."""
        client.token = 'test_token'
        mock_response = Mock()
        mock_response.json.return_value = {'id': 1, 'title': 'New Task', 'project_id': 1}
        mock_request.return_value = mock_response
        
        result = client.create_task(project_id=1, title='New Task')
        
        assert result['id'] == 1
        mock_request.assert_called_once()
        call_args = mock_request.call_args
        assert call_args[0] == ('POST', '/projects/1/tasks')
        payload = call_args[1]['json']
        assert payload['title'] == 'New Task'
        # project_id is part of the URL path in Vikunja API, not the JSON payload
    
    @patch('core.vikunja_client.VikunjaClient._request')
    def test_create_task_with_priority(self, mock_request, client):
        """Test creating task with priority."""
        client.token = 'test_token'
        mock_response = Mock()
        mock_response.json.return_value = {'id': 1, 'title': 'New Task'}
        mock_request.return_value = mock_response
        
        result = client.create_task(project_id=1, title='New Task', priority=3)
        
        call_args = mock_request.call_args
        payload = call_args[1]['json']
        assert payload['priority'] == 3
    
    @patch('core.vikunja_client.VikunjaClient.update_task')
    def test_toggle_task_done(self, mock_update, client):
        """Test toggling task done status."""
        client.token = 'test_token'
        client.toggle_task_done(task_id=1, done=True)
        
        mock_update.assert_called_once_with(1, done=True)
    
    @patch('core.vikunja_client.VikunjaClient._request')
    def test_update_task(self, mock_request, client):
        """Test updating a task."""
        client.token = 'test_token'
        mock_response = Mock()
        mock_response.json.return_value = {'id': 1, 'title': 'Updated Task', 'done': True}
        mock_request.return_value = mock_response
        
        result = client.update_task(task_id=1, title='Updated Task', done=True)
        
        assert result['done'] is True
        mock_request.assert_called_once()
        call_args = mock_request.call_args
        assert call_args[0] == ('PUT', '/tasks/1')
        payload = call_args[1]['json']
        assert payload['title'] == 'Updated Task'
        assert payload['done'] is True
    
    @patch('core.vikunja_client.VikunjaClient._request')
    def test_delete_task(self, mock_request, client):
        """Test deleting a task."""
        client.token = 'test_token'
        mock_response = Mock()
        mock_request.return_value = mock_response
        
        client.delete_task(task_id=1)
        
        mock_request.assert_called_once_with('DELETE', '/tasks/1')


class TestRequestHandling:
    """Test request handling and error management."""
    
    def test_get_headers_with_token(self, client):
        """Test that headers include token when authenticated."""
        client.token = 'test_token'
        headers = client._get_headers()
        
        assert 'Authorization' in headers
        assert headers['Authorization'] == 'Bearer test_token'
    
    def test_get_headers_without_token(self, client):
        """Test that headers don't include token when not authenticated."""
        headers = client._get_headers()
        
        assert 'Authorization' not in headers
    
    @patch('core.vikunja_client.requests.Session.request')
    def test_request_success(self, mock_request, client):
        """Test successful API request."""
        client.token = 'test_token'
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response
        
        response = client._request('GET', '/projects')
        
        assert response == mock_response
        mock_request.assert_called_once()
        call_kwargs = mock_request.call_args[1]
        assert 'Authorization' in call_kwargs['headers']
        assert call_kwargs['headers']['Authorization'] == 'Bearer test_token'
    
    @patch('core.vikunja_client.requests.Session.request')
    def test_request_http_error(self, mock_request, client):
        """Test request with HTTP error."""
        client.token = 'test_token'
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = HTTPError(response=mock_response)
        mock_request.return_value = mock_response
        
        with pytest.raises(HTTPError):
            client._request('GET', '/projects/999')
    
    @patch('core.vikunja_client.requests.Session.request')
    def test_request_connection_error(self, mock_request, client):
        """Test request with connection error."""
        client.token = 'test_token'
        mock_request.side_effect = RequestException("Connection failed")
        
        with pytest.raises(RequestException):
            client._request('GET', '/projects')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

