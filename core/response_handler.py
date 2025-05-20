import requests
import json
import re
from dateutil import parser
from datetime import datetime
from config import headers, API_ENDPOINT, base_system_message
from core.file_handler import search_dropbox_index

class ResponseHandler:
    def __init__(self, chat_handler):
        self.chat_handler = chat_handler

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

            if "daily briefing" in message.lower():
                print("Manual briefing requested")
                briefing = self.chat_handler.daily_briefing()
                # Format it with snark via Grok, like startup
                briefing_message = {
                    "role": "user",
                    "content": f"Here's your daily briefing data, Dr. Odeh:\n{briefing}\n"
                            f"Turn this into a snarky, conversational rundown—use <br><br> between sections, keep it punchy. "
                            f"For unreplied emails or scheduling hints, suggest replies or calls—flag urgent ones (e.g., 'urgent', 'ASAP')."
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

            # For regular messages, only use recent context
            grok_response = self.chat_with_grok(conversation_history[-5:], session_id)  # Only last 5 messages
            print(f"Grok response: {grok_response}")
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

    def chat_with_grok(self, messages, session_id):
        # Only use recent context for regular messages
        all_messages = [base_system_message] + messages
        data = {
            "messages": all_messages,
            "model": "grok-2-latest",
            "stream": False
        }
        try:
            response = requests.post(API_ENDPOINT, headers=headers, data=json.dumps(data))
            response.raise_for_status()
            return response.json()['choices'][0]['message']['content']
        except requests.exceptions.RequestException as e:
            print(f"API call failed: {e}")
            return "Server's sulking—try again later."