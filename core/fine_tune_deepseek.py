from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments, DataCollatorForLanguageModeling
from peft import LoraConfig, get_peft_model
from datasets import load_dataset
from transformers import BitsAndBytesConfig
import torch
import os
import json

# Use Llama 3.1 8B with 4-bit quantization (matching chat_with_navi.py)
model_name = "meta-llama/Meta-Llama-3-8B-Instruct"
quant_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16)
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForCausalLM.from_pretrained(model_name, quantization_config=quant_config, device_map="auto")

# Add LoRA adapters for Llama 3.1
lora_config = LoraConfig(
    r=32,  # Higher rank for better capacity
    lora_alpha=64,  # Higher alpha for better scaling
    target_modules=["q_proj", "v_proj", "k_proj", "o_proj"],  # More modules for better adaptation
    lora_dropout=0.1,  # Slightly higher dropout
    bias="none",
    task_type="CAUSAL_LM"
)
model = get_peft_model(model, lora_config)

# Load dataset
dataset = load_dataset("json", data_files="data\\fine_tune_formatted.jsonl", split="train")

# Tokenize function (for input/output structure)
def tokenize_function(examples):
    input_text = examples["input"]["sop_text"] + "\n\n" + examples["input"]["standard_text"]
    output_text = examples["output"]["overview"] + "\n\n" + examples["output"]["key_alignments"] + "\n\n" + json.dumps(examples["output"]["improvements"])
    full_text = input_text + "\n\n" + output_text + tokenizer.eos_token
    tokenized = tokenizer(
        full_text,
        padding="max_length",
        max_length=32768,  # Full inputs
        return_tensors="pt"
    )
    tokenized["labels"] = tokenized["input_ids"].clone()
    return {k: v.squeeze(0) for k, v in tokenized.items()}

tokenized_dataset = dataset.map(tokenize_function, batched=False, remove_columns=dataset.column_names)

data_collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)

# Output directory
cache_dir = os.path.expanduser("~\\.cache\\huggingface\\hub\\fine_tuned_deepseek")

training_args = TrainingArguments(
    output_dir=cache_dir,
    num_train_epochs=10,
    per_device_train_batch_size=1,
    gradient_accumulation_steps=1,
    learning_rate=1e-5,
    fp16=True,
    save_steps=10,
    logging_steps=1
)

trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=tokenized_dataset,
    data_collator=data_collator
)

trainer.train()
model.save_pretrained(cache_dir)
tokenizer.save_pretrained(cache_dir)