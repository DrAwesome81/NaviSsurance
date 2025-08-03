import sys
import os
import json
from llama_cpp import Llama

# Add parent directory (root) to sys.path to import config.py
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from config import base_system_message

def main():
    model_path = "C:/Users/adamo/.cache/huggingface/hub/models--bartowski--Meta-Llama-3-8B-Instruct-GGUF/snapshots/2c3f8d7f3db06e3f9e8c4c6b6e6c7f3f8d9e4c6/Meta-Llama-3-8B-Instruct-Q4_K_M.gguf"
    print("Worker: Before Llama init", file=sys.stderr)
    sys.stderr.flush()
    try:
        llm = Llama(
            model_path=model_path,
            n_gpu_layers=33,
            n_ctx=2048,
            n_threads=4,
            verbose=True,
            chat_format="llama-3"
        )
        print("Worker: After Llama init", file=sys.stderr)
        sys.stderr.flush()
        print("MODEL_LOADED", file=sys.stderr)
        sys.stderr.flush()
    except Exception as e:
        print(f"LOAD_ERROR:{str(e)}", file=sys.stderr)
        sys.stderr.flush()
        sys.exit(1)

    # Normalize system message
    system_content = base_system_message["content"].replace("\n", " ").strip()

    for line in sys.stdin:
        try:
            data = json.loads(line.strip())
            messages = data["messages"]
            session_id = data["session_id"]
            # Prepend system message
            all_messages = [{"role": "system", "content": system_content}] + messages
            response = llm.create_chat_completion(
                messages=all_messages,
                max_tokens=100,
                temperature=0.9,
                top_p=0.9
            )
            content = response['choices'][0]['message']['content'].strip()
            print(json.dumps({"response": content}), flush=True)
        except Exception as e:
            print(json.dumps({"error": str(e)}), flush=True)

if __name__ == "__main__":
    main()