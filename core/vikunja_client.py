"""
Vikunja API client for NaviSsurance.
Handles authentication, projects, and tasks.
"""
import requests
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class VikunjaClient:
    """Simple Vikunja API client."""
    
    def __init__(self, base_url: str = "http://localhost:3456", token: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.session = requests.Session()
        if self.token:
            self.session.headers.update({"Authorization": f"Bearer {self.token}"})
    
    def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make an authenticated API request."""
        # Clean endpoint - remove leading slash if present
        clean_endpoint = endpoint.lstrip('/')
        url = f"{self.base_url}/api/v1/{clean_endpoint}"
        try:
            resp = self.session.request(method, url, timeout=10, **kwargs)
            resp.raise_for_status()
            return resp.json() if resp.content else {}
        except requests.exceptions.HTTPError as e:
            if e.response is not None:
                logger.error(f"Vikunja API HTTP error: {e.response.status_code} {e.response.reason} for {url}")
                logger.error(f"Response body: {e.response.text[:500]}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Vikunja API error: {e}")
            raise
    
    def test_connection(self) -> bool:
        """Test if the Vikunja instance is reachable."""
        try:
            self._request("GET", "/info")
            return True
        except Exception:
            return False
    
    def login(self, username: str, password: str) -> str:
        """Login and return API token."""
        try:
            data = {"username": username, "password": password}
            # Login endpoint doesn't require auth, so make direct request
            clean_endpoint = "/login".lstrip('/')
            url = f"{self.base_url}/api/v1/{clean_endpoint}"
            resp = self.session.request("POST", url, json=data, timeout=10)
            resp.raise_for_status()
            result = resp.json() if resp.content else {}
            
            # Try different possible token locations in response
            self.token = result.get("token") or result.get("access_token") or result.get("accessToken") or ""
            if not self.token and isinstance(result, dict):
                # Sometimes token is nested
                if "data" in result and isinstance(result["data"], dict):
                    self.token = result["data"].get("token") or result["data"].get("access_token", "")
            
            if not self.token:
                logger.warning(f"Vikunja login response: {result}")
                raise ValueError("No token received in login response")
            
            self.session.headers.update({"Authorization": f"Bearer {self.token}"})
            logger.info(f"Vikunja login successful, token length: {len(self.token)}")
            return self.token
        except Exception as e:
            logger.error(f"Vikunja login failed: {e}")
            raise
    
    def register(self, username: str, email: str, password: str) -> str:
        """Register a new user and return API token."""
        try:
            data = {"username": username, "email": email, "password": password}
            # Register endpoint doesn't require auth, so make direct request
            clean_endpoint = "/register".lstrip('/')
            url = f"{self.base_url}/api/v1/{clean_endpoint}"
            resp = self.session.request("POST", url, json=data, timeout=10)
            resp.raise_for_status()
            result = resp.json() if resp.content else {}
            
            logger.debug(f"Registration response: {result}")
            
            # Try different possible token locations in response
            self.token = result.get("token") or result.get("access_token") or result.get("accessToken") or ""
            if not self.token and isinstance(result, dict):
                # Sometimes token is nested
                if "data" in result and isinstance(result["data"], dict):
                    self.token = result["data"].get("token") or result["data"].get("access_token", "")
            
            # If no token from registration, try logging in instead
            if not self.token:
                logger.info("No token in registration response, attempting login...")
                return self.login(username, password)
            
            self.session.headers.update({"Authorization": f"Bearer {self.token}"})
            logger.info(f"Vikunja registration successful, token length: {len(self.token)}")
            return self.token
        except Exception as e:
            logger.error(f"Vikunja registration failed: {e}")
            raise
    
    def get_projects(self) -> List[Dict[str, Any]]:
        """Get all projects (Vikunja v1.0.0+ uses 'lists' for projects)."""
        try:
            # Vikunja v1.0.0+ uses /lists endpoint
            result = self._request("GET", "/lists")
            # Vikunja API might return lists in different formats
            if isinstance(result, list):
                return result
            elif isinstance(result, dict):
                # Check common response wrapper formats
                if "lists" in result:
                    return result["lists"]
                elif "namespaces" in result:
                    return result["namespaces"]
                elif "projects" in result:
                    return result["projects"]
                elif "data" in result:
                    data = result["data"]
                    if isinstance(data, list):
                        return data
                    elif isinstance(data, dict):
                        if "lists" in data:
                            return data["lists"]
                        elif "namespaces" in data:
                            return data["namespaces"]
                        elif "projects" in data:
                            return data["projects"]
                elif "items" in result:
                    return result["items"]
            logger.warning(f"Unexpected response format from /lists: {result}")
            return []
        except Exception as e:
            logger.error(f"Failed to fetch projects: {e}")
            return []
    
    def create_project(self, title: str, description: str = "") -> Dict[str, Any]:
        """Create a new project (list in Vikunja v1.0.0+)."""
        data = {"title": title, "description": description}
        # Vikunja v1.0.0+ uses /lists endpoint
        return self._request("POST", "/lists", json=data)
    
    def get_tasks(self, project_id: int) -> List[Dict[str, Any]]:
        """Get all tasks for a project (list in Vikunja v1.0.0+)."""
        try:
            # Vikunja v1.0.0+ uses /lists/{id}/tasks
            return self._request("GET", f"/lists/{project_id}/tasks")
        except Exception as e:
            logger.error(f"Failed to fetch tasks for project {project_id}: {e}")
            return []
    
    def create_task(self, project_id: int, title: str, description: str = "", 
                   due_date: Optional[datetime] = None, priority: int = 0) -> Dict[str, Any]:
        """Create a new task in a project (list in Vikunja v1.0.0+)."""
        data = {
            "title": title,
            "description": description,
            "priority": priority,
        }
        if due_date:
            data["due_date"] = due_date.isoformat()
        
        # Vikunja v1.0.0+ uses /lists/{id}/tasks
        return self._request("PUT", f"/lists/{project_id}/tasks", json=data)
    
    def update_task(self, task_id: int, **kwargs) -> Dict[str, Any]:
        """Update a task."""
        return self._request("POST", f"/tasks/{task_id}", json=kwargs)
    
    def toggle_task_done(self, task_id: int, done: bool = True) -> Dict[str, Any]:
        """Mark a task as done or undone."""
        return self.update_task(task_id, done=done)
    
    def delete_task(self, task_id: int) -> None:
        """Delete a task."""
        self._request("DELETE", f"/tasks/{task_id}")

