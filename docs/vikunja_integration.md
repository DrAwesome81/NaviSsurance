# Vikunja Integration Guide

## Overview
NaviSsurance includes full integration with Vikunja, a self-hosted task management system. This allows professional task and project management with support for nested projects, comprehensive task fields, and natural language task creation.

## Features

### Connection Management
- **Server URL Configuration**: Enter Vikunja server URL (default: http://localhost:3456)
- **Connection Testing**: Test server connectivity before authentication
- **Login/Registration**: Authenticate with existing credentials or register new accounts
- **Persistent Credentials**: Username and password are saved using QSettings and remain populated across sessions
- **Enter Key Support**: Press Enter in username or password field to trigger login

### Project Management
- **Project Loading**: Automatically loads all projects after login
- **Hierarchical Display**: Nested projects are displayed with visual indentation in dropdown
- **Project Creation**: Create new projects with title and optional metadata
- **Project Selection**: Select project from dropdown to view its tasks

### Task Management

#### Task Display
The task table displays all available task fields:
- **ID** (hidden): Internal task identifier
- **Title**: Task title
- **Description**: Task description (truncated to 100 characters with "..." for long descriptions)
- **Priority**: Priority level (0-5, centered)
- **Due Date**: Due date in YYYY-MM-DD format
- **Start Date**: Start date in YYYY-MM-DD format
- **End Date**: End date in YYYY-MM-DD format
- **% Done**: Completion percentage (0-100%, centered)
- **Done**: Completion status ("Yes" if done, empty if not, centered)
- **Favorite**: Favorite status ("*" if favorited, empty if not, centered)
- **Est. Duration**: Estimated duration from local database (formatted as "Xh Ym" or "Xm", centered)
- **Actions**: Edit, Delete, and Toggle buttons

#### Task Creation
- **Manual Creation**: Create tasks via UI with:
  - Title (required)
  - Priority (0-5, default 0)
  - Estimated Duration (0-10080 minutes, optional)
- **Natural Language Creation**: Create tasks via chat window (when on Tasks tab):
  - Type natural language request (e.g., "Add a task to review FDA submission by next Friday, high priority, should take about 2 hours")
  - Llama model parses task details automatically
  - System prompts for missing required information
  - Auto-assigns to correct project based on context

#### Task Editing
- **Edit Dialog**: Full-featured dialog with:
  - Title
  - Description (multi-line text area)
  - Priority (0-5)
  - Due Date (calendar picker)
  - Completed status (checkbox)
  - Estimated Duration (0-10080 minutes)
- **Data Loading**: Existing task data and estimated duration are loaded from database
- **Updates**: Changes are saved to Vikunja API and local database

#### Task Deletion
- **Confirmation Dialog**: Confirms deletion before removing task
- **Cleanup**: Removes task from Vikunja and local cache

#### Task Toggling
- **Quick Toggle**: Toggle task completion status with one click
- **Real-time Updates**: Task list refreshes immediately after toggle

### Custom Fields

#### Estimated Duration
- **Storage**: Stored locally in SQLite (`vikunja_task_metadata` table)
- **Input**: Available in both task creation and editing dialogs
- **Display**: Shown in task table with smart formatting:
  - Minutes only: "45m"
  - Hours and minutes: "2h 30m"
  - Hours only: "3h"
- **Persistence**: Linked to Vikunja task ID for reliable association

### Natural Language Task Creation

When on the Tasks tab, natural language task requests in the chat window are automatically parsed and created in Vikunja.

#### How It Works
1. User types task request in chat (e.g., "Add task to review FDA submission by next Friday, high priority, 2 hours")
2. System detects `ADD_TASK:` format from Llama response
3. Checks if Tasks tab is active
4. If active, parses task details using Llama:
   - Extracts title, description, priority, due date, estimated duration, project name
5. Validates required fields (title)
6. Creates task in Vikunja with parsed details
7. Saves estimated duration to local database
8. Reloads task list to show new task

#### Parsed Fields
- **Title** (required): Task title
- **Description** (optional): Task description
- **Priority** (0-5): Priority level (default 0)
- **Due Date** (ISO format): Due date parsed from natural language
- **Estimated Duration** (minutes): Duration parsed from natural language
- **Project Name**: Project assignment (matches by name, falls back to current project)

#### Error Handling
- Missing title: Reports error and prompts for more information
- Not logged in: Prompts user to log in first
- No project selected: Prompts user to select a project
- JSON parse errors: Handles gracefully with error messages
- API errors: Provides clear error feedback

## Database Schema

### vikunja_task_metadata Table
Stores custom task fields not supported by Vikunja API:
```sql
CREATE TABLE vikunja_task_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vikunja_task_id INTEGER NOT NULL UNIQUE,
    estimated_duration_minutes INTEGER,
    custom_fields_json TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

## API Endpoints

All endpoints are relative to `/api/v1`:

- `GET /info` - Connection test
- `POST /login` - User authentication
- `POST /register` - User registration
- `GET /projects` - List all projects
- `POST /projects` - Create new project
- `GET /projects/{id}/tasks` - Get tasks for project
- `POST /projects/{id}/tasks` - Create task in project
- `PUT /tasks/{id}` - Update task
- `DELETE /tasks/{id}` - Delete task

## Setup Instructions

1. **Deploy Vikunja Instance**:
   ```bash
   cd vikunja
   docker-compose up -d
   ```

2. **Enable Registration** (if needed):
   - Edit `vikunja/docker-compose.yml`
   - Set `VIKUNJA_SERVICE_ENABLEREGISTRATION: "true"`
   - Restart container: `docker-compose restart`

3. **Configure in NaviSsurance**:
   - Open Tasks tab
   - Enter server URL (default: http://localhost:3456)
   - Click "Test Connection" to verify connectivity
   - Login or register new account
   - Credentials are automatically saved for next session

## Testing

Comprehensive automated test coverage:
- **75 tests passing** across:
  - VikunjaClient API methods (connection, auth, projects, tasks)
  - TasksTab UI components (connection, login, projects, tasks, editing, deletion)
  - Natural language task creation (parsing, validation, error handling)
  - Task table field visibility
  - Estimated duration storage and retrieval

Run tests:
```bash
pytest tests/test_vikunja_client.py tests/test_tasks_tab.py tests/test_vikunja_nl_creation.py -v
```

## Error Handling

- **Connection Errors**: Clear error messages for network issues
- **Authentication Errors**: Specific messages for invalid credentials (401/403)
- **Missing Information**: Prompts user for required fields
- **API Errors**: Graceful handling with user-friendly messages
- **No Success Popups**: Only error messages are shown (success is indicated by UI updates)

## Best Practices

1. **Always test connection** before attempting login
2. **Select a project** before creating tasks
3. **Use natural language** for complex task creation (when on Tasks tab)
4. **Set estimated duration** for better scheduling visibility
5. **Edit tasks** to update details after creation
6. **Delete tasks** carefully (confirmation required)

## Troubleshooting

- **Login fails**: Check server URL and ensure Vikunja is running
- **Registration fails**: Ensure registration is enabled in Vikunja settings
- **Tasks not showing**: Verify project is selected and refresh
- **Natural language not working**: Ensure you're on the Tasks tab when making request
- **Estimated duration not saving**: Check database permissions and connection



