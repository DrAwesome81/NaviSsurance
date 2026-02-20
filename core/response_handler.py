import os
import subprocess
import json
import logging
import threading
from datetime import datetime
import requests
import re
from dateutil import parser
os.environ["TORCH_DYNAMO_DISABLE"] = "1"
from config import base_system_message
# Dropbox indexing removed - using RAG index instead

logger = logging.getLogger(__name__)

class ResponseHandler:
    def __init__(self, chat_handler, chat_window=None):
        self.chat_handler = chat_handler
        self.chat_window = chat_window  # Reference to ChatWindow for accessing tasks_tab
        self.process = None
        self.model_loaded = False
        # Ensure only one thread talks to the worker at a time
        self.worker_lock = threading.Lock()

        # Start the worker process with conda env Python
        try:
            logger.info("Starting llama_worker.py subprocess...")
            self.process = subprocess.Popen(
                ["c:/Users/adamo/Dropbox/_Consulting/NaviSsurance/cuda_env/Scripts/python.exe", "-u", "core/llama_worker.py"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="ignore",
                creationflags=0x08000000  # CREATE_NO_WINDOW to prevent console popup
            )
            logger.info(f"Subprocess started with PID: {self.process.pid}")
            # Wait for load confirmation
            start = datetime.now()
            while (datetime.now() - start).total_seconds() < 60:
                line = self.process.stderr.readline().strip()
                if line:
                    logger.info(f"Worker output: {line}")
                if line == "MODEL_LOADED":
                    self.model_loaded = True
                    logger.info("Model loaded successfully in worker.")
                    break
                elif line.startswith("LOAD_ERROR:"):
                    raise Exception(line[len("LOAD_ERROR:"):])
            if not self.model_loaded:
                # Check if process is still running
                if self.process.poll() is not None:
                    logger.error(f"Subprocess exited with code: {self.process.returncode}")
                    stderr_output = self.process.stderr.read()
                    if stderr_output:
                        logger.error(f"Subprocess stderr: {stderr_output}")
                    raise Exception("Subprocess failed or crashed.")
                raise TimeoutError("Model load timed out in worker.")
        except Exception as e:
            logger.error(f"Failed to start worker: {e}")
            self.process = None

    def __del__(self):
        if self.process:
            self.process.terminate()
            self.process.wait()

    def chat_with_llama(self, messages, session_id):
        """Send a single request to the llama worker in a thread-safe, robust way."""
        if not self.process or not self.model_loaded:
            return "Model not loaded."

        # Only one thread at a time can talk to the worker subprocess
        with self.worker_lock:
            try:
                payload = json.dumps({"messages": messages, "session_id": session_id})

                # Send input to worker
                self.process.stdin.write(payload + "\n")
                self.process.stdin.flush()

                # Read lines until we get a valid JSON object
                while True:
                    line = self.process.stdout.readline()
                    if not line:
                        # EOF or no response
                        raise Exception("No response from worker (empty stdout line).")

                    line = line.strip()
                    if not line:
                        # Skip blank lines
                        continue

                    try:
                        response = json.loads(line)
                        break
                    except json.JSONDecodeError as e:
                        # Log and keep reading – in case some stray output or partial line slipped through
                        logger.error(f"Invalid JSON from worker: {e}; line (truncated): {line[:200]}")
                        continue

                if "error" in response:
                    logger.error(f"Worker error: {response['error']}")
                    return f"Error: {response['error']}"

                # Normal success path
                return response.get("response", "")

            except Exception as e:
                logger.error(f"Worker communication error: {e}")
                return "Local AI's acting up—try again."

    def perform_grok_search(self, query):
        """Perform a web search using Grok via xAI SDK (web_search tool)."""
        try:
            from core.grok_client import grok_web_search
            from datetime import datetime, timedelta
            current_date = datetime.now()
            week_ago = current_date - timedelta(days=7)
            week_ago_str = week_ago.strftime("%Y-%m-%d")
            current_date_str = current_date.strftime("%Y-%m-%d")
            user_prompt = (
                f"Find specific MedTech news articles about: {query}. "
                f"Prefer articles from {week_ago_str} to {current_date_str}. "
                "For each article, provide the exact URL to the full article, not just the website homepage."
            )
            result = grok_web_search(user_prompt, model="grok-4-1-fast")
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Grok live search query: %s; result length: %s", query, len(result or ""))
            return result or None
        except Exception as e:
            logger.exception("Error performing Grok search: %s", e)
            return None

    def hybrid_wrapper(self, messages, session_id, needs_search=False):
        if needs_search:
            query = messages[-1]["content"]
            results = self.perform_grok_search(query)
            messages.append({"role": "system", "content": f"Results: {results}"})
        return self.chat_with_llama(messages, session_id)

    def get_response(self, message, session_id, conversation_history):
        print(f"DEBUG: ResponseHandler.get_response called with message: {message[:50]}..., session_id: {session_id}")
        conversation_history.append({"role": "user", "content": message})
        try:
            # Special-case: Notes tab should bypass task/news/!search routing
            if session_id == "notes_session" or str(session_id).startswith("notes_"):
                # For Notes, we just want a plain LLM response with no extra routing logic
                return self.hybrid_wrapper(conversation_history, session_id)

            if message.lower().startswith("!history"):
                try:
                    date_query = message[8:].strip()
                    historical_messages = self.chat_handler.get_chat_history_by_date_range(session_id, date_query)
                    if historical_messages:
                        return f"Here's what we discussed on {date_query}:\n" + "\n".join([f"{role}: {content}" for role, content, _ in historical_messages])
                    else:
                        return f"I couldn't find any conversations from {date_query}."
                except Exception as e:
                    print(f"Error processing history request: {e}")
                    return "I had trouble retrieving that history. Try being more specific about the date."
            if message.lower().startswith("!search"):
                try:
                    search_terms = message[7:].strip()
                    search_results = self.chat_handler.search_conversations(search_terms)
                    if search_results:
                        formatted_results = []
                        for role, content, timestamp in search_results:
                            date_str = datetime.fromisoformat(timestamp).strftime("%Y-%m-%d %H:%M")
                            formatted_results.append(f"[{date_str}] {role}: {content}")
                        return f"Here are the conversations about '{search_terms}':\n" + "\n".join(formatted_results)
                    else:
                        return f"I couldn't find any conversations about '{search_terms}'."
                except Exception as e:
                    print(f"Error processing search request: {e}")
                    return "I had trouble searching the conversations. Please try again."
            if "daily briefing" in message.lower():
                print("Manual briefing requested")
                briefing = self.chat_handler.daily_briefing()
                formatted_briefing = self.hybrid_wrapper([{"role": "user", "content": f"Turn this briefing into snarky rundown: {briefing} Use <br><br> sections, punchy. The emails have already been intelligently filtered by AI - focus on presenting them well and suggesting actions for urgent items. MedTech focus. For any empty sections, generate appropriate snarky commentary instead of leaving them blank."}], "briefing_session")
                formatted_briefing = re.sub(r'\n+', '\n', formatted_briefing)
                formatted_briefing = re.sub(
                    r'(\*\*([A-Za-z\s]+):?\*\*|\[SECTION:([A-Za-z\s]+)\])',
                    lambda m: f"<br><br><b><u>{m.group(2) or m.group(3)}</u></b><br>",
                    formatted_briefing
                )
                lines = formatted_briefing.split('\n')
                formatted_lines = []
                for line in lines:
                    match = re.match(r'^\s*-\s+(.+)', line.strip())
                    if match:
                        item_text = match.group(1).strip()
                        formatted_lines.append(f"- {item_text}")
                    else:
                        formatted_lines.append(line)
                formatted_briefing = '\n'.join(formatted_lines)
                formatted_briefing = formatted_briefing.replace('\n\n', '<br><br>').replace('\n', '<br>')
                formatted_briefing = re.sub(r'^<br><br>', '', formatted_briefing.strip())
                # News is handled separately by the news widget, no need to duplicate here
                return formatted_briefing
            
            # Handle task queries - natural language task list access
            # BUT skip this if the message is about creating a task (not querying)
            # Check for creation keywords first - if it's about creating, skip task query handler
            is_task_creation = any(keyword in message.lower() for keyword in ['add', 'create', 'new task', 'make a task', 'add a task'])
            if is_task_creation:
                print(f"DEBUG: Detected task creation request, skipping task query handler, continuing to ADD_TASK processing")
            elif self._is_task_query(message):
                print(f"DEBUG: Detected task query (not creation), routing to _handle_task_query")
                return self._handle_task_query(message)
            
            # Handle news queries specifically - ALWAYS require web search
            if "WEB_SEARCH:" in message or ("medtech" in message.lower() and "news" in message.lower()):
                print("News query detected - forcing web search")
                # Extract search query from WEB_SEARCH: prefix or use the message directly
                if "WEB_SEARCH:" in message:
                    search_query = message.split("WEB_SEARCH:")[1].strip()
                else:
                    search_query = message
                
                # Always perform web search for news using Grok live search
                search_results = self.perform_grok_search(search_query)
                if search_results:
                    # Grok live search returns real-time results with citations
                    # Format them into JSON for the news widget
                    from datetime import datetime, timedelta
                    current_date = datetime.now()
                    week_ago = current_date - timedelta(days=7)
                    current_date_str = current_date.strftime("%Y-%m-%d")
                    week_ago_str = week_ago.strftime("%Y-%m-%d")
                    
                    news_prompt = [{"role": "user", "content": f"Based on these REAL live search results from {week_ago_str} to {current_date_str}, create a JSON array of up-to-5 MedTech news items. Each item should have: title, content (summary), url, source, published_date. CRITICAL: Extract the FULL article URLs (like https://example.com/article-title) not just homepage URLs. Look for specific article links in the search results. Results: {search_results}"}]
                    grok_response = self.hybrid_wrapper(news_prompt, session_id)
                    return grok_response
                else:
                    from core.grok_client import grok_available
                    ok, msg = grok_available()
                    if not ok:
                        return f"News (Grok) unavailable: {msg}"
                    return "Unable to fetch current news. Please try again."
            grok_response = self.hybrid_wrapper(conversation_history, session_id)
            print(f"DEBUG: hybrid_wrapper returned: {grok_response[:200] if grok_response else 'None'}...")
            task_segments = [seg for seg in grok_response.split("ADD_TASK:") if seg.strip()]
            print(f"DEBUG: task_segments count: {len(task_segments)}, has ADD_TASK: {'ADD_TASK:' in grok_response}")
            added_tasks = []
            if task_segments and "ADD_TASK:" in grok_response:
                print(f"DEBUG: Found ADD_TASK in response, checking Vikunja routing...")
                # Check if we're on the Tasks tab and should create Vikunja tasks
                should_use_vikunja = False
                if self.chat_window and hasattr(self.chat_window, 'tasks_tab') and self.chat_window.tasks_tab:
                    tasks_tab = self.chat_window.tasks_tab
                    print(f"DEBUG: tasks_tab exists: {tasks_tab is not None}")
                    # Check if Tasks tab is currently active
                    if hasattr(self.chat_window, 'tab_widget'):
                        current_tab_index = self.chat_window.tab_widget.currentIndex()
                        tasks_tab_index = -1
                        for i in range(self.chat_window.tab_widget.count()):
                            if self.chat_window.tab_widget.tabText(i) == "Tasks":
                                tasks_tab_index = i
                                break
                        
                        has_client = tasks_tab.client is not None
                        has_project = tasks_tab.current_project_id is not None
                        print(f"DEBUG: Task creation check: current_tab={current_tab_index}, tasks_tab={tasks_tab_index}, has_client={has_client}, has_project={has_project}, project_id={tasks_tab.current_project_id}")
                        
                        if current_tab_index == tasks_tab_index and has_client and has_project:
                            # We're on Tasks tab and logged in - create Vikunja tasks
                            print(f"DEBUG: Routing to Vikunja task creation")
                            logger.info("Routing to Vikunja task creation")
                            should_use_vikunja = True
                        else:
                            print(f"DEBUG: Not using Vikunja: current_tab={current_tab_index}, tasks_tab={tasks_tab_index}, has_client={has_client}, has_project={has_project}")
                    else:
                        print(f"DEBUG: No tab_widget found on chat_window")
                else:
                    print(f"DEBUG: No chat_window or tasks_tab available")
                
                if should_use_vikunja:
                    result = self._handle_vikunja_task_creation(task_segments, message, conversation_history, session_id)
                    print(f"DEBUG: Vikunja task creation returned: {result}")
                    return result
                
                # Otherwise, use the old task system
                logger.debug("Using old task system (not on Tasks tab or Vikunja not available)")
                for segment in task_segments:
                    task_info = segment.split("|", 1)
                    if len(task_info) != 2:
                        continue
                    task_description = task_info[0].strip()
                    try:
                        from datetime import datetime
                        due_date_obj = parser.parse(task_info[1].strip(), default=datetime.now())
                        due_date = due_date_obj.strftime("%m-%d-%Y")
                    except ValueError:
                        due_date = "unknown"
                    added_tasks.append(f"'{task_description}' due on {due_date}")
            # Return the processed response, not the raw grok_response
            if added_tasks:
                print(f"DEBUG: Returning processed tasks: {added_tasks}")
                return f"Added {', '.join(added_tasks)}"
            else:
                # If no tasks were added but ADD_TASK was in response, we need to handle it
                # Don't return raw ADD_TASK: string - ChatThread will try to parse it for old system
                if "ADD_TASK:" in grok_response:
                    print(f"DEBUG: ADD_TASK found but no tasks parsed - this shouldn't happen if Vikunja path worked")
                    logger.warning("ADD_TASK: found in response but no tasks were parsed")
                    # Return a message instead of raw ADD_TASK to prevent ChatThread from parsing it
                    return "I received a task creation request, but couldn't process it. Please make sure you're logged into Vikunja and have a project selected if you're on the Tasks tab."
                print(f"DEBUG: Returning grok_response (no ADD_TASK): {grok_response[:100]}...")
                return grok_response
        except Exception as e:
            import traceback
            print(f"ERROR in get_response: {e}")
            traceback.print_exc()
            return "I encountered an issue—try again, doc!"

    def _load_llama_model(self):
        """Deprecated: Use subprocess worker instead."""
        return None

    def _is_task_query(self, message):
        """Use LLM to intelligently detect if the message is asking about tasks."""
        try:
            # Use the local LLM to determine if this is a task-related query
            detection_prompt = [
                {"role": "system", "content": "You are a task detection assistant. Determine if the user's message is asking about their task list, todos, deadlines, or assignments. Respond with only 'YES' if it's task-related, or 'NO' if it's not."},
                {"role": "user", "content": f"Is this message asking about tasks, todos, deadlines, or assignments? Message: '{message}'"}
            ]
            
            response = self.chat_with_llama(detection_prompt, "task_detection")
            return response.strip().upper() == "YES"
        except Exception as e:
            print(f"Error in task detection: {e}")
            # Fallback to simple keyword detection
            task_keywords = ['task', 'todo', 'due', 'deadline', 'assignment']
            return any(keyword in message.lower() for keyword in task_keywords)

    def _handle_task_query(self, message):
        """Use LLM to intelligently handle task queries with natural responses."""
        try:
            # Get all tasks from database
            all_tasks = self.chat_handler.db.get_tasks()
            
            if not all_tasks:
                return "You don't have any tasks in your list right now."
            
            # Format task data for the LLM
            task_data = self._format_tasks_for_llm(all_tasks)
            
            # Use LLM to generate a natural response based on the user's query and actual task data
            task_prompt = [
                {"role": "system", "content": f"""You are Navi, a helpful AI assistant. The user is asking about their task list. 

Here is their current task data:
{task_data}

Respond naturally and conversationally to their question. Be helpful, specific, and use the actual task information provided. If they're asking about specific days, dates, or timeframes, calculate and provide accurate information. Be concise but informative."""},
                {"role": "user", "content": message}
            ]
            
            response = self.chat_with_llama(task_prompt, "task_query")
            return response
            
        except Exception as e:
            print(f"Error handling task query: {e}")
            return "I had trouble accessing your task list. Please try again."

    def _format_tasks_for_llm(self, all_tasks):
        """Format task data for LLM consumption."""
        from datetime import datetime
        
        if not all_tasks:
            return "No tasks found."
        
        today = datetime.now().strftime('%m-%d-%Y')
        task_info = []
        
        for task in all_tasks:
            # get_tasks() returns: id, task_text, due_date, category, recurrence, completed (6 values)
            task_id, task_name, due_date, category, recurrence, completed = task
            status = "completed" if completed else "pending"
            
            # Calculate if overdue
            is_overdue = due_date and due_date < today and not completed
            
            task_info.append({
                "id": task_id,
                "name": task_name,
                "due_date": due_date,
                "status": status,
                "overdue": is_overdue
            })
        
        # Create a structured summary for the LLM
        pending_tasks = [t for t in task_info if t["status"] == "pending"]
        completed_tasks = [t for t in task_info if t["status"] == "completed"]
        overdue_tasks = [t for t in task_info if t["overdue"]]
        
        summary = f"""Task Summary:
- Total tasks: {len(all_tasks)}
- Pending: {len(pending_tasks)}
- Completed: {len(completed_tasks)}
- Overdue: {len(overdue_tasks)}

Current date: {today}

All Tasks:
"""
        
        for task in task_info:
            overdue_indicator = " (OVERDUE)" if task["overdue"] else ""
            summary += f"- {task['name']} (due: {task['due_date']}, status: {task['status']}{overdue_indicator})\n"
        
        return summary
    
    def _handle_vikunja_task_creation(self, task_segments, original_message, conversation_history, session_id):
        """Handle task creation for Vikunja when on Tasks tab."""
        try:
            tasks_tab = self.chat_window.tasks_tab
            
            # Check if user is logged into Vikunja
            if not tasks_tab.client or not tasks_tab.current_project_id:
                return "I need you to be logged into Vikunja and have a project selected to create tasks. Please log in and select a project first."
            
            # Get available projects for context
            try:
                projects = tasks_tab.client.get_projects()
                project_names = [p.get("title", "") for p in projects]
            except:
                project_names = []
            
            created_tasks = []
            missing_info = []
            
            for segment in task_segments:
                if "|" not in segment:
                    continue
                
                task_info = segment.split("|", 1)
                if len(task_info) != 2:
                    continue
                
                task_description = task_info[0].strip()
                due_date_raw = task_info[1].strip()
                
                # Use Llama to parse task details from the original message and task description
                parse_prompt = [
                    {"role": "system", "content": f"""You are parsing a task creation request. Extract task details and return a JSON object with:
- title: Task title (required)
- description: Task description (optional, can be empty string)
- priority: Priority level 0-5 (0 = no priority, 5 = urgent, default 0)
- due_date: Due date in ISO format YYYY-MM-DD (or null if not specified)
- estimated_duration_minutes: Estimated duration in minutes (or null if not specified)
- project_name: Project name to assign to (must match one of: {', '.join(project_names) if project_names else 'any available project'}, or null to use current project)

Available projects: {', '.join(project_names) if project_names else 'none'}
Current date: {datetime.now().strftime('%Y-%m-%d')}

Return ONLY valid JSON, no other text."""},
                    {"role": "user", "content": f"Original request: {original_message}\nTask: {task_description}\nDue date mentioned: {due_date_raw}"}
                ]
                
                try:
                    parse_response = self.chat_with_llama(parse_prompt, "task_parse")
                    print(f"DEBUG: Llama parse response: {parse_response[:200]}...")
                    # Extract JSON from response (might have extra text)
                    import json
                    import re
                    json_match = re.search(r'\{[^{}]*\}', parse_response, re.DOTALL)
                    if json_match:
                        task_data = json.loads(json_match.group(0))
                        print(f"DEBUG: Parsed task_data: {task_data}")
                    else:
                        # Fallback: try to parse the whole response
                        task_data = json.loads(parse_response)
                        print(f"DEBUG: Parsed task_data (fallback): {task_data}")
                    
                    # Validate required fields
                    if not task_data.get('title'):
                        missing_info.append(f"Task '{task_description}': missing title")
                        continue
                    
                    # Determine project
                    project_id = tasks_tab.current_project_id
                    print(f"DEBUG: Starting with project_id from current_project_id: {project_id}")
                    if task_data.get('project_name') and project_names:
                        # Try to find matching project
                        for proj in projects:
                            if proj.get("title", "").lower() == task_data.get('project_name', '').lower():
                                new_project_id = proj.get("id")
                                print(f"DEBUG: Matched project name '{task_data.get('project_name')}' to project_id: {new_project_id}")
                                project_id = new_project_id
                                break
                    
                    # Ensure project_id is valid
                    if not project_id:
                        print(f"DEBUG: ERROR - project_id is None or invalid!")
                        missing_info.append(f"Task '{task_description}': no project selected")
                        continue
                    
                    print(f"DEBUG: Final project_id before API call: {project_id} (type: {type(project_id)})")
                    
                    # Parse due date
                    due_date_iso = None
                    if task_data.get('due_date'):
                        try:
                            due_date_obj = parser.parse(task_data['due_date'], default=datetime.now())
                            due_date_iso = due_date_obj.strftime('%Y-%m-%d')
                        except:
                            pass
                    
                    # Create task in Vikunja
                    print(f"DEBUG: Calling create_task with project_id={project_id}, title='{task_data['title']}'")
                    task_result = tasks_tab.client.create_task(
                        project_id=project_id,
                        title=task_data['title'],
                        description=task_data.get('description', ''),
                        priority=task_data.get('priority', 0),
                        due_date=due_date_iso
                    )
                    
                    # Save estimated duration if provided
                    estimated_duration = task_data.get('estimated_duration_minutes')
                    if estimated_duration and estimated_duration > 0:
                        task_id = task_result.get('id') if isinstance(task_result, dict) else None
                        if task_id:
                            tasks_tab._save_estimated_duration(task_id, estimated_duration)
                    
                    # Reload tasks to show the new task
                    tasks_tab.load_tasks()
                    
                    created_tasks.append(task_data['title'])
                    
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse task JSON: {e}, response: {parse_response}")
                    missing_info.append(f"Task '{task_description}': parsing error")
                except Exception as e:
                    logger.error(f"Error creating Vikunja task: {e}")
                    missing_info.append(f"Task '{task_description}': {str(e)}")
            
            # Build response
            if created_tasks:
                response = f"I've created {len(created_tasks)} task(s) in Vikunja: {', '.join(created_tasks)}."
                if missing_info:
                    response += f"\n\nHowever, I had issues with: {', '.join(missing_info)}. Please provide more details."
                return response
            elif missing_info:
                return f"I couldn't create the task(s). Issues: {', '.join(missing_info)}. Please provide more details or check your Vikunja connection."
            else:
                return "I couldn't parse the task details. Please try again with more specific information."
                
        except Exception as e:
            logger.error(f"Error in Vikunja task creation: {e}")
            return f"I encountered an error creating the task: {str(e)}"
    
    def handle_task_added(self, task_text, due_date):
        """Handle task added signal (for backward compatibility with old task system).
        
        This method is called when a task is added via the old task system.
        The new system handles tasks through Vikunja or the get_response method.
        """
        # Tasks are now handled through Vikunja or get_response, so this is a no-op
        # Kept for backward compatibility with signal connections
        pass