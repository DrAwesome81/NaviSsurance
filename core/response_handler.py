import requests
import json
import re
import logging
from dateutil import parser
from datetime import datetime
from config import headers, API_ENDPOINT, base_system_message #CLAUDE_API_KEY
from core.file_handler import search_dropbox_index
#from anthropic import Anthropic

logger = logging.getLogger(__name__)

class ResponseHandler:
    def __init__(self, chat_handler):
        self.chat_handler = chat_handler
        #self.claude_client = Anthropic(api_key=CLAUDE_API_KEY)

    # def perform_web_search(self, query):
    #     """Perform a web search using Claude 3.7 Sonnet."""
    #     try:
    #         response = self.claude_client.messages.create(
    #             model="claude-3-7-sonnet-20250219",
    #             max_tokens=1000,
    #             system="You are a research assistant. Search the web for accurate, up-to-date information about the query. Return a detailed, factual response with relevant information. Include sources when possible.",
    #             messages=[{
    #                 "role": "user",
    #                 "content": f"Please search for information about: {query}"
    #             }],
    #             tools=[{
    #                 "type": "web_search_20250305",
    #                 "name": "web_search"
    #             }]
    #         )
    #         return response.content[0].text
    #     except Exception as e:
    #         print(f"Error performing web search: {e}")
    #         return None

    def get_response(self, message, session_id, conversation_history):
        conversation_history.append({"role": "user", "content": message})
        try:
            # Check for history lookup command
            if message.lower().startswith("!history"):
                # Parse date range from command
                try:
                    # Example: !history last thursday
                    date_query = message[8:].strip()
                    # Get historical messages for the specified date range
                    historical_messages = self.chat_handler.get_chat_history_by_date_range(session_id, date_query)
                    if historical_messages:
                        return f"Here's what we discussed on {date_query}:\n" + "\n".join([f"{role}: {content}" for role, content, _ in historical_messages])
                    else:
                        return f"I couldn't find any conversations from {date_query}."
                except Exception as e:
                    print(f"Error processing history request: {e}")
                    return "I had trouble retrieving that history. Try being more specific about the date."

            # Check for conversation search
            if message.lower().startswith("!search"):
                try:
                    # Example: !search Genesys press release
                    search_terms = message[7:].strip()
                    # Get messages matching the search terms
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
                # Format it with snark via Grok, like startup
                briefing_message = {
                    "role": "user",
                    "content": f"Here's your daily briefing data, Dr. Odeh:\n{briefing}\n"
                            f"Turn this into a snarky, conversational rundown—use <br><br> between sections, keep it punchy. "
                            f"For unreplied emails or scheduling hints, suggest replies or calls—flag urgent ones (e.g., 'urgent', 'ASAP')."
                            f"Be sure to consider NaviSure's business sector and function when determining what to present."
                }
                formatted_briefing = self.chat_with_grok([briefing_message], "daily_briefing_session")
                # Post-process formatting (from chat_handler.py:daily_briefing)
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
                return formatted_briefing  # Return it for ChatThread to emit

            # For regular messages, use full conversation history
            grok_response = self.chat_with_deepseek(conversation_history, session_id)
            print(f"Grok response: {grok_response}")
            
            # Check if Grok requested a web search
            if "WEB_SEARCH:" in grok_response:
                format_prompt = [{"role": "user", "content": f"Refine this as a precise web search query: {grok_response.split('WEB_SEARCH:')[1].strip()}"}]
                formatted_query = self.chat_with_deepseek(format_prompt, session_id)
                search_query = formatted_query.strip()
                search_query = grok_response.split("WEB_SEARCH:")[1].strip()
                search_results = self.perform_web_search(search_query)
                if search_results:
                    # Add search results to conversation history
                    conversation_history.append({
                        "role": "system",
                        "content": f"Here are the search results for your query:\n{search_results}\n\nPlease summarize these results in a conversational way, maintaining your personality and tone."
                    })
                    # Get Grok's response to the search results
                    grok_response = self.chat_with_deepseek(conversation_history, session_id)

            task_segments = [seg for seg in grok_response.split("ADD_TASK:") if seg.strip()]
            added_tasks = []
            if task_segments and "ADD_TASK:" in grok_response:
                for segment in task_segments:
                    task_info = segment.split("|", 1)
                    if len(task_info) != 2:
                        print(f"Skipping malformed segment: {segment}")
                        continue
                    task_description = task_info[0].strip()
                    try:
                        due_date_obj = parser.parse(task_info[1].strip(), default=datetime.now())
                        due_date = due_date_obj.strftime("%m-%d-%Y")
                    except ValueError:
                        print(f"Failed to parse date: {task_info[1]}")
                        due_date = "unknown"
                    # Let ChatThread handle the task addition
                    added_tasks.append(f"'{task_description}' due on {due_date}")
            # Add more response parsing (Dropbox search, doc generation) as needed
            return grok_response if not added_tasks else f"Added {', '.join(added_tasks)}"
        except Exception as e:
            print(f"Error in get_response: {e}")
            return "I encountered an issue—try again, doc!"

    def chat_with_deepseek(self, messages, session_id):
        all_messages = [base_system_message] + messages
        data = {
            "model": "deepseek-r1:32b",
            "messages": all_messages,
            "stream": False
        }
        try:
            response = requests.post("http://localhost:11434/api/chat", json=data, timeout=120)
            response.raise_for_status()
            content = response.json()['message']['content']
            content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
            return content
        except requests.exceptions.RequestException as e:
            print(f"DeepSeek call failed: {e}")
            return "Local AI's acting up—try again."