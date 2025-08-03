from transformers import AutoModelForCausalLM, AutoTokenizer

# Download Llama 3.1 8B Instruct model (matching chat_with_navi.py)
model_name = "meta-llama/Meta-Llama-3-8B-Instruct"
tokenizer = AutoTokenizer.from_pretrained(model_name, token="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")
model = AutoModelForCausalLM.from_pretrained(model_name, device_map="auto", token="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")

