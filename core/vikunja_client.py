"""
Vikunja API Client for task and project management.

This client provides methods to interact with a Vikunja instance (self-hosted or cloud)
for managing projects and tasks.
"""
import requests
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class VikunjaClient:
    """Client for interacting with Vikunja API."""
    
    def __init__(self, base_url: str):
        """
        Initialize Vikunja client.
        
        Args:
            base_url: Base URL of Vikunja instance (e.g., "http://localhost:3456")
        """
        # Ensure base_url doesn't end with trailing slash
        self.base_url = base_url.rstrip('/')
        self.api_base = f"{self.base_url}/api/v1"
        self.token: Optional[str] = None
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
    
    def _get_headers(self) -> Dict[str, str]:
        """Get headers with authentication token if available."""
        headers = {}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        return headers
    
    def _request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """
        Make an API request.
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint (relative to /api/v1)
            **kwargs: Additional arguments for requests.request()
        
        Returns:
            Response object
        
        Raises:
            requests.RequestException: If request fails
        """
        url = f"{self.api_base}{endpoint}"
        headers = self._get_headers()
        if 'headers' in kwargs:
            headers.update(kwargs.pop('headers'))
        
        try:
            response = self.session.request(
                method=method,
                url=url,
                headers=headers,
                **kwargs
            )
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            logger.error(f"Vikunja API request failed: {method} {url} - {e}")
            raise
    
    def test_connection(self) -> bool:
        """
        Test connection to Vikunja API.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            # Try to access a public endpoint (info endpoint if available, or just check if server responds)
            response = self.session.get(f"{self.api_base}/info", timeout=5)
            # If we get any response (even 401/403), the server is reachable
            return response.status_code in (200, 401, 403)
        except requests.exceptions.RequestException:
            # If we can't connect at all, return False
            return False
    
    def login(self, username: str, password: str) -> None:
        """
        Login to Vikunja and store authentication token.
        
        Args:
            username: Username
            password: Password
        
        Raises:
            requests.RequestException: If login fails
            ValueError: If credentials are invalid
        """
        try:
            # Vikunja API login endpoint - note: it's /login, not /auth/login
            response = self.session.post(
                f"{self.api_base}/login",
                json={
                    'username': username,
                    'password': password
                },
                timeout=10
            )
            
            # Check response status - Vikunja returns 403 for wrong credentials, 401 for other auth issues
            if response.status_code in (401, 403):
                # Try to get more details from error response
                try:
                    error_data = response.json()
                    error_msg = error_data.get('message', 'Invalid username or password')
                    logger.error(f"Login failed with {response.status_code}: {error_msg}. Full response: {error_data}")
                    raise ValueError(f"Invalid username or password: {error_msg}")
                except ValueError:
                    # If we already raised ValueError, re-raise it
                    raise
                except Exception:
                    # If response isn't JSON or other error, use generic message
                    logger.error(f"Login failed with {response.status_code}. Response text: {response.text[:200]}")
                    raise ValueError("Invalid username or password")
            
            response.raise_for_status()
            
            data = response.json()
            # Vikunja may return token in different fields depending on version
            # Try common field names: 'token', 'access_token', 'accessToken'
            self.token = (
                data.get('token') or 
                data.get('access_token') or 
                data.get('accessToken') or
                (data.get('data', {}).get('token') if isinstance(data.get('data'), dict) else None)
            )
            
            # Also check if token is in cookies (some Vikunja versions use cookie-based auth)
            if not self.token and self.session.cookies:
                # Check for token in cookies
                for cookie in self.session.cookies:
                    if 'token' in cookie.name.lower() or 'auth' in cookie.name.lower():
                        self.token = cookie.value
                        break
            
            if not self.token:
                # Log the actual response for debugging
                logger.error(f"Login response did not contain token. Response: {data}")
                raise ValueError(f"Login response did not contain token. Server response: {data.get('message', 'Unknown error')}")
            
            logger.info(f"Successfully logged in as {username}")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                raise ValueError("Invalid username or password")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Login failed: {e}")
            raise
    
    def register(self, username: str, email: str, password: str) -> None:
        """
        Register a new user and automatically login.
        
        Args:
            username: Username
            email: Email address
            password: Password
        
        Raises:
            requests.RequestException: If registration fails
            ValueError: If registration data is invalid
        """
        try:
            # Vikunja API registration endpoint - note: it's /register, not /auth/register
            response = self.session.post(
                f"{self.api_base}/register",
                json={
                    'username': username,
                    'email': email,
                    'password': password
                },
                timeout=10
            )
            response.raise_for_status()
            
            # After registration, automatically login
            self.login(username, password)
            logger.info(f"Successfully registered and logged in as {username}")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 400:
                error_data = e.response.json() if e.response.content else {}
                error_msg = error_data.get('message', 'Registration failed')
                raise ValueError(error_msg)
            elif e.response.status_code == 401:
                # 401 on registration might mean registration is disabled
                error_data = e.response.json() if e.response.content else {}
                error_msg = error_data.get('message', 'Registration failed - registration may be disabled on this Vikunja instance')
                raise ValueError(f"Registration not allowed: {error_msg}. You may need to enable registration in Vikunja settings or use an existing account.")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Registration failed: {e}")
            raise
    
    def get_projects(self) -> List[Dict[str, Any]]:
        """
        Get all projects.
        
        Returns:
            List of project dictionaries
        
        Raises:
            requests.RequestException: If request fails
            ValueError: If not authenticated
        """
        if not self.token:
            raise ValueError("Not authenticated. Please login first.")
        
        response = self._request('GET', '/projects')
        data = response.json()
        
        # Vikunja returns projects in 'projects' field or as a list
        if isinstance(data, dict) and 'projects' in data:
            return data['projects']
        elif isinstance(data, list):
            return data
        else:
            return []
    
    def create_project(
        self,
        title: str,
        description: Optional[str] = None,
        hex_color: Optional[str] = None,
        parent_project_id: Optional[int] = None,
        is_favorite: bool = False,
        is_archived: bool = False,
        position: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Create a new project.
        
        Args:
            title: Project title (required)
            description: Project description
            hex_color: Hex color code (e.g., "#ff0000")
            parent_project_id: ID of parent project for nesting
            is_favorite: Whether project is favorited
            is_archived: Whether project is archived
            position: Position/order of project
        
        Returns:
            Created project dictionary
        
        Raises:
            requests.RequestException: If request fails
            ValueError: If not authenticated
        """
        if not self.token:
            raise ValueError("Not authenticated. Please login first.")
        
        payload = {
            'title': title
        }
        
        # Add optional fields if provided
        if description is not None:
            payload['description'] = description
        if hex_color is not None:
            payload['hex_color'] = hex_color
        if parent_project_id is not None:
            payload['parent_project_id'] = parent_project_id
        if is_favorite is not None:
            payload['is_favorite'] = is_favorite
        if is_archived is not None:
            payload['is_archived'] = is_archived
        if position is not None:
            payload['position'] = position
        
        response = self._request('POST', '/projects', json=payload)
        return response.json()
    
    def get_tasks(self, project_id: int) -> List[Dict[str, Any]]:
        """
        Get all tasks for a project.
        
        Args:
            project_id: ID of the project
        
        Returns:
            List of task dictionaries
        
        Raises:
            requests.RequestException: If request fails
            ValueError: If not authenticated
        """
        if not self.token:
            raise ValueError("Not authenticated. Please login first.")
        
        response = self._request('GET', f'/projects/{project_id}/tasks')
        data = response.json()
        
        # Vikunja returns tasks in 'tasks' field or as a list
        if isinstance(data, dict) and 'tasks' in data:
            return data['tasks']
        elif isinstance(data, list):
            return data
        else:
            return []
    
    def create_task(
        self,
        project_id: int,
        title: str,
        description: Optional[str] = None,
        due_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        priority: int = 0,
        hex_color: Optional[str] = None,
        percent_done: int = 0,
        is_favorite: bool = False,
        done: bool = False,
        bucket_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Create a new task in a project.
        
        Args:
            project_id: ID of the project
            title: Task title (required)
            description: Task description
            due_date: Due date (ISO 8601 format)
            start_date: Start date (ISO 8601 format)
            end_date: End date (ISO 8601 format)
            priority: Priority level (0-5, where 0 is no priority)
            hex_color: Hex color code
            percent_done: Completion percentage (0-100)
            is_favorite: Whether task is favorited
            done: Whether task is completed
            bucket_id: ID of bucket to add task to
        
        Returns:
            Created task dictionary
        
        Raises:
            requests.RequestException: If request fails
            ValueError: If not authenticated
        """
        if not self.token:
            raise ValueError("Not authenticated. Please login first.")
        
        payload = {
            'title': title
        }
        # Note: project_id is in the URL path, not in the payload
        
        # Add optional fields if provided
        if description is not None:
            payload['description'] = description
        if due_date is not None:
            payload['due_date'] = due_date
        if start_date is not None:
            payload['start_date'] = start_date
        if end_date is not None:
            payload['end_date'] = end_date
        if priority is not None:
            payload['priority'] = priority
        if hex_color is not None:
            payload['hex_color'] = hex_color
        if percent_done is not None:
            payload['percent_done'] = percent_done
        if is_favorite is not None:
            payload['is_favorite'] = is_favorite
        if done is not None:
            payload['done'] = done
        if bucket_id is not None:
            payload['bucket_id'] = bucket_id
        
        logger.debug(f"Creating task in project {project_id} with payload: {payload}")
        response = self._request('POST', f'/projects/{project_id}/tasks', json=payload)
        return response.json()
    
    def update_task(
        self,
        task_id: int,
        title: Optional[str] = None,
        description: Optional[str] = None,
        due_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        priority: Optional[int] = None,
        hex_color: Optional[str] = None,
        percent_done: Optional[int] = None,
        is_favorite: Optional[bool] = None,
        done: Optional[bool] = None,
        bucket_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Update an existing task.
        
        Args:
            task_id: ID of the task to update
            title: Task title
            description: Task description
            due_date: Due date (ISO 8601 format)
            start_date: Start date (ISO 8601 format)
            end_date: End date (ISO 8601 format)
            priority: Priority level (0-5)
            hex_color: Hex color code
            percent_done: Completion percentage (0-100)
            is_favorite: Whether task is favorited
            done: Whether task is completed
            bucket_id: ID of bucket
        
        Returns:
            Updated task dictionary
        
        Raises:
            requests.RequestException: If request fails
            ValueError: If not authenticated
        """
        if not self.token:
            raise ValueError("Not authenticated. Please login first.")
        
        payload = {}
        
        # Add only provided fields
        if title is not None:
            payload['title'] = title
        if description is not None:
            payload['description'] = description
        if due_date is not None:
            payload['due_date'] = due_date
        if start_date is not None:
            payload['start_date'] = start_date
        if end_date is not None:
            payload['end_date'] = end_date
        if priority is not None:
            payload['priority'] = priority
        if hex_color is not None:
            payload['hex_color'] = hex_color
        if percent_done is not None:
            payload['percent_done'] = percent_done
        if is_favorite is not None:
            payload['is_favorite'] = is_favorite
        if done is not None:
            payload['done'] = done
        if bucket_id is not None:
            payload['bucket_id'] = bucket_id
        
        response = self._request('PUT', f'/tasks/{task_id}', json=payload)
        return response.json()
    
    def toggle_task_done(self, task_id: int, done: bool) -> None:
        """
        Toggle task completion status.
        
        Args:
            task_id: ID of the task
            done: True to mark as done, False to mark as not done
        
        Raises:
            requests.RequestException: If request fails
            ValueError: If not authenticated
        """
        if not self.token:
            raise ValueError("Not authenticated. Please login first.")
        
        self.update_task(task_id, done=done)
    
    def delete_task(self, task_id: int) -> None:
        """
        Delete a task.
        
        Args:
            task_id: ID of the task to delete
        
        Raises:
            requests.RequestException: If request fails
            ValueError: If not authenticated
        """
        if not self.token:
            raise ValueError("Not authenticated. Please login first.")
        
        self._request('DELETE', f'/tasks/{task_id}')

