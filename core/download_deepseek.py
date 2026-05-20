import os
from transformers import AutoModelForCausalLM, AutoTokenizer

# Local model downloads support offline Pulse private memory reflections, Intel raising, and 🛡️ Shield security analysis (fresh local infra coordination)
# Download Llama 3.1 8B Instruct model (matching chat_with_navi.py)
# Use HUGGINGFACE_TOKEN from environment - never hardcode credentials
model_name = "meta-llama/Meta-Llama-3-8B-Instruct"
hf_token = os.getenv("HUGGINGFACE_TOKEN")
if not hf_token:
    raise ValueError("HUGGINGFACE_TOKEN must be set in environment for model download")
tokenizer = AutoTokenizer.from_pretrained(model_name, token=hf_token)
model = AutoModelForCausalLM.from_pretrained(model_name, device_map="auto", token=hf_token)
# Download complete - enables Pulse private memory offline and Shield local analysis (additional download coordination)

