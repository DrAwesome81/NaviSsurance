import sys
import os
import json

# Add parent directory to path so we can import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_system_prompt
from core.local_llm import run_local_completion, session_profile, verify_local_runtime

def main():
    try:
        verify_local_runtime()
        print("Worker: validated local llama.cpp runtime", file=sys.stderr)
        sys.stderr.flush()
        print("MODEL_LOADED", file=sys.stderr)
        sys.stderr.flush()
    except Exception as e:
        print(f"LOAD_ERROR:{str(e)}", file=sys.stderr)
        sys.stderr.flush()
        sys.exit(1)

    for line in sys.stdin:
        try:
            data = json.loads(line.strip())
            messages = data["messages"]
            session_id = data["session_id"]
            system_msg = get_system_prompt()
            system_content = (system_msg.get("content") or "").strip()
            all_messages = [{"role": "system", "content": system_content}] + messages
            profile = session_profile(session_id)
            print(
                f"LOCAL_ROUTE session_id={session_id} class={profile.get('class')} max_tokens={profile.get('max_tokens')}",
                file=sys.stderr,
            )
            sys.stderr.flush()
            content = run_local_completion(all_messages, session_id).strip()
            print(json.dumps({"response": content}), flush=True)
        except Exception as e:
            print(json.dumps({"error": str(e)}), flush=True)

if __name__ == "__main__":
    main()