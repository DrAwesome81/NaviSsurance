from llama_cpp import Llama

def format_query(user_input):
    model_path = "C:/Users/adamo/.cache/huggingface/hub/models--bartowski--Meta-Llama-3-8B-Instruct-GGUF/snapshots/2c3f8d7f3db06e3f9e8c4c6b6e6c7f3f8d9e4c6/Meta-Llama-3-8B-Instruct-Q4_K_M.gguf"
    
    try:
        llm = Llama(
            model_path=model_path,
            n_gpu_layers=33,  # ~4-5GB VRAM
            n_ctx=2048,
            n_threads=4,
            verbose=False,
            chat_format="llama-3"  # Use Llama 3.1 chat template
        )
        
        response = llm.create_chat_completion(
            messages=[
                {"role": "system", "content": "You are a query refinement assistant. Convert user input into precise search queries."},
                {"role": "user", "content": f"Refine as precise search query: {user_input}"}
            ],
            max_tokens=1000,
            temperature=0.7,
            top_p=0.9
        )
        
        return response['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"Error in format_query: {e}")
        return user_input  # Fallback to original input