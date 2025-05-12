from transformers import DistilBertForSequenceClassification, DistilBertTokenizer
import torch
import os

model_path = "C:\\Users\\adamo\\.cache\\huggingface\\hub\\models--distilbert-base-uncased\\snapshots\\12040accade4e8a0f71eabdb258fecc2e7e948be"
if not os.path.exists(model_path):
    print(f"Error: Directory {model_path} does not exist")
    exit(1)
try:
    model = DistilBertForSequenceClassification.from_pretrained(model_path)
    tokenizer = DistilBertTokenizer.from_pretrained(model_path)
    print("Model and tokenizer loaded!")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    print(f"Model on {device}")
except Exception as e:
    print(f"Error: {e}")