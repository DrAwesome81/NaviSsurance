import re

def _add_task_from_chat(self, task_text, due_date, session_id):
        if self.task_added_signal:
            self.task_added_signal.emit(task_text, due_date)  # Emit the task-added signal
        else:
            return f"I've added the task '{task_text}' with a due date of {due_date}."
        
def _process_task_response(self, grok_response):
        task_pattern = r"I've added the task '(.*?)' for '(\d{2}-\d{2}-\d{4})'\."
        match = re.search(task_pattern, grok_response)

        if match:
            task_text = match.group(1)
            due_date = match.group(2)

            if self.task_added_signal:
                self.task_added_signal.emit(task_text, due_date)
        else:
            print("No task found in Navi's response")