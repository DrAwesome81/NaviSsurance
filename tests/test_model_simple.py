from llama_cpp import Llama
model_path = "C:/Users/adamo/.cache/huggingface/hub/models--lmstudio-community--Llama-3.3-70B-Instruct-GGUF/snapshots/3a489fd247ce24848d8d8a3fadd707088665681f/Llama-3.3-70B-Instruct-Q4_K_M.gguf"
llm = Llama(model_path=model_path, n_gpu_layers=40, n_ctx=2048, verbose=True)
print("GPU support enabled" if "CUDA0" in str(llm._model) else "GPU support not enabled")