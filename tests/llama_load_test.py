from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
import torch

model_name = "meta-llama/Llama-2-13b-hf"
quantization_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_compute_dtype=torch.float16  # Match input to compute
)
tokenizer = AutoTokenizer.from_pretrained(model_name, token="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")
model = AutoModelForCausalLM.from_pretrained(
    model_name,
    quantization_config=quantization_config,
    device_map="cuda:0",
    token="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"
)
print("LLaMA-2-13B-4bit loaded on GPU 0!")
inputs = tokenizer("Hello, Navi!", return_tensors="pt").to("cuda:0")
outputs = model.generate(**inputs, max_length=50)
print(tokenizer.decode(outputs[0], skip_special_tokens=True))