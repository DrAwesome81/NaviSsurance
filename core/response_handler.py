import os
import subprocess
import json
import logging
from datetime import datetime
import requests
import re
from dateutil import parser
os.environ["TORCH_DYNAMO_DISABLE"] = "1"
from config import headers, API_ENDPOINT, base_system_message
from core.file_handler import search_dropbox_index
from core.deepseek_query_formatter import format_query

logger = logging.getLogger(__name__)

class ResponseHandler:
    def __init__(self, chat_handler):
        self.chat_handler = chat_handler
        self.process = None
        self.model_loaded = False

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
            while (datetime.now() - start).seconds < 60:
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
        if not self.process or not self.model_loaded:
            return "Model not loaded."
        try:
            # Send input to worker
            self.process.stdin.write(json.dumps({"messages": messages, "session_id": session_id}) + "\n")
            self.process.stdin.flush()
            # Read response
            line = self.process.stdout.readline().strip()
            response = json.loads(line)
            if "error" in response:
                logger.error(f"Worker error: {response['error']}")
                return f"Error: {response['error']}"
            return response["response"]
        except Exception as e:
            logger.error(f"Worker communication error: {e}")
            return "Local AI's acting up—try again."

    def perform_grok_search(self, query):
        """Perform a web search using Grok API with live search."""
        try:
            from datetime import datetime, timedelta
            current_date = datetime.now()
            week_ago = current_date - timedelta(days=7)
            
            # Format dates for Grok live search
            current_date_str = current_date.strftime("%Y-%m-%d")
            week_ago_str = week_ago.strftime("%Y-%m-%d")
            
            data = {
                "messages": [{"role": "user", "content": f"Find specific MedTech news articles about: {query}. For each article, provide the exact URL to the full article, not just the website homepage."}],
                "model": "grok-4-latest",
                "stream": False,
                "search_parameters": {
                    "mode": "on",
                    "from_date": week_ago_str,
                    "to_date": current_date_str,
                    "sources": [
                        {"type": "web"},
                        {"type": "news"}
                    ],
                    "return_citations": True
                }
            }
            response = requests.post(API_ENDPOINT, headers=headers, json=data)
            response.raise_for_status()
            result = response.json()['choices'][0]['message']['content']
            print(f"DEBUG: Grok live search query: {query}")
            print(f"DEBUG: Date range: {week_ago_str} to {current_date_str}")
            print(f"DEBUG: Grok search result length: {len(result)}")
            print(f"DEBUG: Grok search result preview: {result[:200]}...")
            return result
        except Exception as e:
            print(f"Error performing Grok search: {e}")
            return None

    def hybrid_wrapper(self, messages, session_id, needs_search=False):
        if needs_search:
            query = format_query(messages[-1]["content"])
            results = self.perform_grok_search(query)
            messages.append({"role": "system", "content": f"Results: {results}"})
        return self.chat_with_llama(messages, session_id)

    def get_response(self, message, session_id, conversation_history):
        conversation_history.append({"role": "user", "content": message})
        try:
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
                formatted_briefing = self.hybrid_wrapper([{"role": "user", "content": f"Turn this briefing into snarky rundown: {briefing} Use <br><br> sections, punchy. Suggest actions for unreplied (flag urgent). MedTech focus."}], "briefing_session")
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
                    return "Unable to fetch current news. Please try again."
            grok_response = self.hybrid_wrapper(conversation_history, session_id)
            task_segments = [seg for seg in grok_response.split("ADD_TASK:") if seg.strip()]
            added_tasks = []
            if task_segments and "ADD_TASK:" in grok_response:
                for segment in task_segments:
                    task_info = segment.split("|", 1)
                    if len(task_info) != 2:
                        continue
                    task_description = task_info[0].strip()
                    try:
                        due_date_obj = parser.parse(task_info[1].strip(), default=datetime.now())
                        due_date = due_date_obj.strftime("%m-%d-%Y")
                    except ValueError:
                        due_date = "unknown"
                    added_tasks.append(f"'{task_description}' due on {due_date}")
            return grok_response if not added_tasks else f"Added {', '.join(added_tasks)}"
        except Exception as e:
            print(f"Error in get_response: {e}")
            return "I encountered an issue—try again, doc!"

    def _load_llama_model(self):
        """Deprecated: Use subprocess worker instead."""
        return None