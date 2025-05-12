from transformers import DistilBertForSequenceClassification, DistilBertTokenizer
import torch
import os

model_path = r"C:/Users/adamo/.cache/huggingface/hub/models--distilbert-base-uncased/snapshots/12040accade4e8a0f71eabdb258fecc2e7e948be"
if not os.path.exists(model_path):
    print(f"Error: Directory {model_path} does not exist")
    exit(1)
try:
    model = DistilBertForSequenceClassification.from_pretrained(model_path, num_labels=2)
    tokenizer = DistilBertTokenizer.from_pretrained(model_path)
    print("Model and tokenizer loaded!")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    print(f"Model on {device}")
    text = "Kat from Qualio, urgent FDA compliance"
    inputs = tokenizer(text, return_tensors="pt", truncation=True, padding=True, max_length=128)
    inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch.no_grad():
        outputs = model(**inputs)
    logits = outputs.logits
    print("Classification logits:", logits)
except Exception as e:
    print(f"Error: {e}")