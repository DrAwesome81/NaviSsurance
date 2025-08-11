
import sys
import json
from llama_cpp import Llama

def main():
    model_path = "C:/Users/adamo/.cache/huggingface/hub/models--bartowski--Meta-Llama-3-8B-Instruct-GGUF/snapshots/2c3f8d7f3db06e3f9e8c4c6b6e6c7f3f8d9e4c6/Meta-Llama-3-8B-Instruct-Q4_K_M.gguf"
    try:
        print("Worker: Loading Llama model...", file=sys.stderr)
        llm = Llama(
            model_path=model_path,
            n_gpu_layers=33,
            n_ctx=8192,
            n_threads=4,
            verbose=True,
            chat_format="llama-3"
        )
        print("MODEL_LOADED", file=sys.stderr)
    except Exception as e:
        print(f"LOAD_ERROR:{str(e)}", file=sys.stderr)
        sys.exit(1)

    for line in sys.stdin:
        try:
            data = json.loads(line.strip())
            messages = data["messages"]
            response = llm.create_chat_completion(
                messages=messages,
                max_tokens=1000,
                temperature=0.9,
                top_p=0.9
            )
            content = response['choices'][0]['message']['content'].strip()
            print(json.dumps({"response": content}), flush=True)
        except Exception as e:
            print(json.dumps({"error": str(e)}), flush=True)

if __name__ == "__main__":
    main()
