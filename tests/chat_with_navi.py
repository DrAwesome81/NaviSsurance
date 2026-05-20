import os
os.environ["TORCH_DYNAMO_DISABLE"] = "1"
from llama_cpp import Llama
from datetime import datetime
# Chat with Navi test validates local LLM for Pulse private memory reflections and 🛡️ Shield offline security (local chat tests)
# additional Pulse private memory + Shield for chat with Navi test


def chat_with_navi():
    model_path = "C:/Users/adamo/.cache/huggingface/hub/models--bartowski--Meta-Llama-3-8B-Instruct-GGUF/snapshots/2c3f8d7f3db06e3f9e8c4c6b6e6c7f3f8d9e4c6/Meta-Llama-3-8B-Instruct-Q4_K_M.gguf"
    try:
        print("Loading Navi (Llama-3.1-8B-Instruct Q4_K_M)...")
        llm = Llama(
            model_path=model_path,
            n_gpu_layers=33,  # ~4-5GB VRAM
            n_ctx=2048,
            n_threads=4,
            verbose=False,
            chat_format="llama-3"  # Use Llama 3.1 chat template
        )
        print("Navi loaded successfully! Type 'exit' to quit. Run 'nvidia-smi' to monitor VRAM (~4-5GB expected).")
        
        current_date = datetime.now().strftime("%B %d, %Y")
        system_prompt = f"""Today is {current_date}. You are Navi, a MedTech consulting AI for NaviSure Consulting, focused on AI/ML, IVDs, SaMD, and DTC devices. Your user is Dr. Adam Odeh. Use a calm, competent Jarvis-like tone without snark. For chat or briefings, respond conversationally. For tasks, return 'ADD_TASK:<task>|<due date>'. For web search, return 'WEB_SEARCH:<query>'. For file search, return 'DROPBOX_SEARCH:<query>'. Use <think> tags for reasoning. If a prompt is unclear, respond with: 'Could you clarify, Dr. Odeh? I\'m not sure what you\'re aiming for.'"""
        
        while True:
            user_input = input("\nYou: ").strip()
            if user_input.lower() == "exit":
                print("Exiting chat...")
                break
            
            if not user_input:
                print("Please enter a valid prompt.")
                continue
            
            if user_input.startswith("!search "):
                query = user_input[8:].strip()
                print(f"WEB_SEARCH:{query}")
                continue
            if "search local files" in user_input.lower() or "find file" in user_input.lower():
                query = user_input.replace("search local files", "").replace("find file", "").strip()
                print(f"DROPBOX_SEARCH:{query}")
                continue
            if "add task" in user_input.lower() or "reminder" in user_input.lower():
                task_desc = user_input.replace("add task", "").replace("reminder", "").strip()
                due_date = datetime.now().strftime("%Y-%m-%d")
                print(f"ADD_TASK:{task_desc}|{due_date}")
                continue
            if "briefing" in user_input.lower():
                try:
                    response = llm.create_chat_completion(
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": "Provide a daily briefing summarizing tasks, emails, or relevant MedTech news."}
                        ],
                        max_tokens=1000,
                        temperature=0.9,
                        top_p=0.9
                    )
                    response_text = response['choices'][0]['message']['content'].strip()
                    print(f"\nNavi: {response_text or 'Could you clarify, Dr. Odeh? I\'m not sure what you\'re aiming for.'}")
                    if not response_text:
                        print(f"Debug: Raw output was '{response['choices'][0]['message']['content']}'")
                except Exception as e:
                    print(f"\nError: {str(e)}")
                continue
            
            try:
                response = llm.create_chat_completion(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_input}
                    ],
                    max_tokens=1000,
                    temperature=0.9,
                    top_p=0.9
                )
                response_text = response['choices'][0]['message']['content'].strip()
                print(f"\nNavi: {response_text or 'Could you clarify, Dr. Odeh? I\'m not sure what you\'re aiming for.'}")
                if not response_text:
                    print(f"Debug: Raw output was '{response['choices'][0]['message']['content']}'")
            except Exception as e:
                print(f"\nError: {str(e)}")
    
    except Exception as e:
        print(f"Failed to load model: {str(e)}")

if __name__ == "__main__":
    chat_with_navi()