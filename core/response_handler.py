import os
import subprocess
import json
import logging
import threading
import sys
from datetime import datetime
import requests
import re
from dateutil import parser
os.environ["TORCH_DYNAMO_DISABLE"] = "1"
from config import PROJECT_ROOT
# Dropbox indexing removed - using RAG index instead
from core.local_llm import session_profile
from core.task_command_contract import AddTaskCommand, normalize_mmddyyyy, parse_actions
from core.user_memory import auto_store_user_memory, build_user_memory_context, store_teach_navi_memory

logger = logging.getLogger(__name__)

class ResponseHandler:
    _ADD_TASK_CMD_RE = re.compile(
        r"ADD_TASK:\s*(?P<desc>.*?)\s*\|\s*(?P<due>.*?)(?=(?:\s+ADD_TASK:)|\Z)",
        re.IGNORECASE | re.DOTALL,
    )

    def __init__(self, chat_handler, chat_window=None):
        self.chat_handler = chat_handler
        self.chat_window = chat_window  # Reference to ChatWindow for accessing tasks_tab
        self.process = None
        self.model_loaded = False
        # Ensure only one thread talks to the worker at a time
        self.worker_lock = threading.Lock()

        self._start_worker()

    def _start_worker(self):
        self.process = None
        self.model_loaded = False
        try:
            logger.info("Starting llama_worker.py subprocess...")
            worker_path = os.path.join(PROJECT_ROOT, "core", "llama_worker.py")
            self.process = subprocess.Popen(
                [sys.executable, "-u", worker_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="ignore",
                creationflags=0x08000000  # CREATE_NO_WINDOW to prevent console popup
            )
            logger.info(f"Subprocess started with PID: {self.process.pid}")
            start = datetime.now()
            while (datetime.now() - start).total_seconds() < 60:
                line = self.process.stderr.readline().strip()
                if line:
                    logger.info(f"Worker output: {line}")
                if line == "MODEL_LOADED":
                    self.model_loaded = True
                    logger.info("Model loaded successfully in worker.")
                    break
                if line.startswith("LOAD_ERROR:"):
                    raise Exception(line[len("LOAD_ERROR:"):])
            if not self.model_loaded:
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
            self.model_loaded = False

    def _stop_worker(self):
        if not self.process:
            return
        try:
            self.process.terminate()
            self.process.wait(timeout=5)
        except Exception:
            try:
                self.process.kill()
            except Exception:
                pass
        finally:
            self.process = None
            self.model_loaded = False

    def _restart_worker(self):
        logger.warning("Restarting llama worker after communication failure.")
        self._stop_worker()
        self._start_worker()

    def __del__(self):
        self._stop_worker()

    def chat_with_llama(self, messages, session_id):
        """Send a single request to the llama worker in a thread-safe, robust way."""
        if not self.process or not self.model_loaded:
            return "Model not loaded."
        profile = session_profile(session_id)
        logger.info(
            "Routing local request via llama worker: session_id=%s class=%s max_tokens=%s",
            session_id,
            profile.get("class"),
            profile.get("max_tokens"),
        )

        # Only one thread at a time can talk to the worker subprocess
        with self.worker_lock:
            for attempt in range(3):
                try:
                    if not self.process or not self.model_loaded or self.process.poll() is not None:
                        raise RuntimeError("Worker process is unavailable.")

                    payload = json.dumps({"messages": messages, "session_id": session_id})
                    self.process.stdin.write(payload + "\n")
                    self.process.stdin.flush()

                    while True:
                        line = self.process.stdout.readline()
                        if not line:
                            raise Exception("No response from worker (empty stdout line).")

                        line = line.strip()
                        if not line:
                            continue

                        try:
                            response = json.loads(line)
                            break
                        except json.JSONDecodeError as e:
                            logger.error(f"Invalid JSON from worker: {e}; line (truncated): {line[:200]}")
                            continue

                    if "error" in response:
                        logger.error(f"Worker error: {response['error']}")
                        return f"Error: {response['error']}"

                    return response.get("response", "")

                except Exception as e:
                    logger.error(f"Worker communication error: {e}")
                    if attempt < 2:
                        self._restart_worker()
                        continue
                    return "Local AI's acting up—try again."

    def perform_grok_search(self, query):
        """Perform a web search using Grok via xAI SDK (web_search tool)."""
        try:
            from core.grok_client import MODEL_FAST, grok_web_search
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
            result = grok_web_search(user_prompt, model=MODEL_FAST)
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
            teach_response = store_teach_navi_memory(self.chat_handler.db, message)
            if teach_response:
                return teach_response

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
                formatted_briefing = self.hybrid_wrapper(
                    [
                        {
                            "role": "user",
                            "content": (
                                "Turn this briefing into a concise, helpful rundown in Navi's tone (direct, professional, calm; no snark). "
                                "Use <br><br> between sections and keep it skimmable. "
                                "Suggest concrete next actions for urgent items. "
                                f"Briefing:\n\n{briefing}"
                            ),
                        }
                    ],
                    "briefing_session",
                )
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
            # Give Navi visibility into tasks and projects for planning/priorities (same as Mason)
            navi_context = self._get_navi_tasks_projects_context()
            user_memory_context = build_user_memory_context(self.chat_handler.db, message, limit=5, recent_limit=2)
            system_messages = []
            if navi_context:
                system_messages.append(
                    {
                        "role": "system",
                        "content": "Current tasks and projects (use for planning and priorities when the user asks):\n" + navi_context,
                    }
                )
            if user_memory_context:
                system_messages.append({"role": "system", "content": user_memory_context})
            messages_for_llm = system_messages + list(conversation_history) if system_messages else conversation_history
            grok_response = self.hybrid_wrapper(messages_for_llm, session_id)
            print(f"DEBUG: hybrid_wrapper returned: {grok_response[:200] if grok_response else 'None'}...")
            added_tasks = []
            extracted = []
            if isinstance(grok_response, str) and grok_response.strip():
                extracted = list(self._ADD_TASK_CMD_RE.finditer(grok_response))
            print(
                f"DEBUG: ADD_TASK matches: {len(extracted)}, has ADD_TASK: {('ADD_TASK:' in (grok_response or ''))}"
            )
            # 1) Preferred: parse canonical action lines (same contract as CoS/Mason Tasks tab).
            created: list[tuple[str, str | None, str]] = []  # (desc, due, category)
            seen_keys: set[tuple[str, str | None, str]] = set()
            if isinstance(grok_response, str) and grok_response.strip():
                for cmd in parse_actions(grok_response):
                    if not isinstance(cmd, AddTaskCommand):
                        continue
                    key = (cmd.description.casefold(), cmd.due_date, cmd.category)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    try:
                        task_id = self.chat_handler.db.add_task(
                            "chat_task_capture",
                            cmd.description,
                            cmd.due_date,
                            category=cmd.category,
                            recurrence=cmd.recurrence,
                            completed=0,
                            cos_project_id=cmd.project_id,
                        )
                        if cmd.priority is not None or cmd.next_action_date is not None:
                            try:
                                self.chat_handler.db.update_task_by_id(
                                    int(task_id),
                                    priority=cmd.priority
                                    if cmd.priority is not None
                                    else self.chat_handler.db._UNSET,  # type: ignore[attr-defined]
                                    next_action_date=cmd.next_action_date
                                    if cmd.next_action_date is not None
                                    else self.chat_handler.db._UNSET,  # type: ignore[attr-defined]
                                )
                            except Exception:
                                pass
                        created.append((cmd.description, cmd.due_date, cmd.category))
                    except Exception as e:
                        logger.warning("ResponseHandler ADD_TASK apply failed: %s", e)

            # 2) Backward-compatible: parse legacy simple ADD_TASK:<desc>|<due> commands (no category).
            if extracted:
                from datetime import datetime

                for m in extracted:
                    task_description = (m.group("desc") or "").strip()
                    due_raw = (m.group("due") or "").strip()
                    if not task_description:
                        continue
                    if "|" in task_description:
                        task_description = task_description.split("|", 1)[0].strip()
                    if not task_description:
                        continue

                    due_date: str | None
                    if due_raw.lower() in {"none", "null", "n/a", "na", "unknown", ""}:
                        due_date = None
                    else:
                        ok_due, norm = normalize_mmddyyyy(due_raw)
                        if ok_due:
                            due_date = norm
                        else:
                            try:
                                due_date_obj = parser.parse(due_raw, default=datetime.now())
                                due_date = due_date_obj.strftime("%m-%d-%Y")
                            except Exception:
                                due_date = None

                    key = (task_description.casefold(), due_date, "Business")
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    try:
                        self.chat_handler.db.add_task(
                            "chat_task_capture",
                            task_description,
                            due_date,
                            category="Business",
                            recurrence="None",
                            completed=0,
                        )
                        created.append((task_description, due_date, "Business"))
                    except Exception as e:
                        logger.warning("ResponseHandler legacy ADD_TASK apply failed: %s", e)

            for desc, due, cat in created:
                due_s = due or "none"
                added_tasks.append(f"'{desc}' ({cat}) due {due_s}")
            if isinstance(grok_response, str) and grok_response.strip():
                auto_store_user_memory(
                    self.chat_handler.db,
                    user_message=message,
                    assistant_message=grok_response,
                    llm_callable=self.chat_with_llama,
                    session_id=session_id,
                    route="legacy_response_handler",
                )
            # Return the processed response, not the raw grok_response
            if added_tasks:
                print(f"DEBUG: Returning processed tasks: {added_tasks}")
                return f"Added {', '.join(added_tasks)}"
            else:
                # If no tasks were added but ADD_TASK was in response, we need to handle it
                # Don't return raw ADD_TASK: string - ChatThread will try to parse it for old system
                if "ADD_TASK:" in (grok_response or ""):
                    print("DEBUG: ADD_TASK found but no tasks parsed - likely parse error")
                    logger.warning("ADD_TASK: found in response but no tasks were parsed")
                    # Return a message instead of raw ADD_TASK to prevent ChatThread from parsing it
                    return "I received a task creation request, but couldn't parse it. Please try again with a clearer task description and due date."
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
        """Fast deterministic detection for task-list questions."""
        text = str(message or "").strip().lower()
        if not text:
            return False
        direct_terms = (
            "task",
            "tasks",
            "todo",
            "to-do",
            "deadline",
            "deadlines",
            "assignment",
            "assignments",
            "overdue",
            "next action",
        )
        if any(term in text for term in direct_terms):
            return True
        question_starts = (
            "what is due",
            "what's due",
            "what do i have due",
            "what do i need to do",
            "what is on my plate",
            "what's on my plate",
            "what should i work on",
            "what should i focus on",
            "what do i have this week",
        )
        return any(text.startswith(prefix) for prefix in question_starts)

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

    def _get_navi_tasks_projects_context(self):
        """Build a read-only snapshot of tasks and projects for Navi (planning/priorities)."""
        try:
            db = self.chat_handler.db
            tasks = db.list_tasks_rich(
                include_completed=False,
                include_snoozed=False,
                limit=100,
            )
            lines = ["Tasks (id, text, priority P0–P5, due, next action, category):"]
            if not tasks:
                lines.append("  (none)")
            else:
                for t in tasks:
                    tid = t.get("id") or ""
                    text = (str(t.get("task_text") or "").strip() or "(no text)")[:80]
                    prio = t.get("priority", 0)
                    due = t.get("due_date") or "—"
                    next_act = t.get("next_action_date") or "—"
                    cat = t.get("category") or "—"
                    lines.append(f"  {tid}: {text} | P{prio} | due {due} | next {next_act} | {cat}")
            try:
                proj_rows = db.cos_get_projects() or []
                lines.append("")
                lines.append("Projects (id, name, client, status, deadline):")
                if not proj_rows:
                    lines.append("  (none)")
                else:
                    for row in proj_rows:
                        pid, name, client = row[0], row[1] or "", row[2] or ""
                        status = (row[4] or "") if len(row) > 4 else "—"
                        deadline = (str(row[6] or "")[:10]) if len(row) > 6 and row[6] else "—"
                        lines.append(f"  {pid}: {name} | {client} | {status} | {deadline}")
            except Exception:
                pass
            return "\n".join(lines)
        except Exception as e:
            logger.debug("Navi tasks/projects context failed: %s", e)
            return ""
    
    def _handle_vikunja_task_creation(self, *args, **kwargs):
        """
        Deprecated: Vikunja integration has been removed.
        Tasks are stored locally in SQLite and created via the CoS/Dashboard flows.
        """
        return "Vikunja integration has been removed. Tasks are now stored locally in NaviSsurance."
    
    def handle_task_added(self, task_text, due_date):
        """Handle task added signal (for backward compatibility with old task system).
        
        This method is called when a task is added via the old task system.
        Tasks are persisted locally in SQLite via DatabaseManager.
        """
        try:
            text = str(task_text or "").strip()
            if not text:
                return
            due = str(due_date or "").strip()
            try:
                if not due or due.lower() in {"none", "unknown", "n/a"}:
                    due = datetime.now().strftime("%m-%d-%Y")
                else:
                    due = parser.parse(due, default=datetime.now()).strftime("%m-%d-%Y")
            except Exception:
                due = datetime.now().strftime("%m-%d-%Y")
            self.chat_handler.db.add_task("chat_task_capture", text, due, category="Business", recurrence="None", completed=0)
        except Exception as e:
            logger.warning("handle_task_added failed: %s", e)