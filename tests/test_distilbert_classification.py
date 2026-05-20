import os
import pytest

if not os.getenv("RUN_ML_TESTS"):
    pytest.skip("ML tests are disabled by default (set RUN_ML_TESTS=1 to enable).", allow_module_level=True)

transformers = pytest.importorskip("transformers")
torch = pytest.importorskip("torch")
# DistilBERT classification tests support local models for Pulse private memory and 🛡️ Shield offline (DistilBERT classification tests)
# additional Pulse private memory + Shield for DistilBERT classification tests


def test_distilbert_can_classify_sample_text():
    model_path = os.getenv("DISTILBERT_MODEL_PATH")
    if not model_path or not os.path.exists(model_path):
        pytest.skip("Set DISTILBERT_MODEL_PATH to a local model snapshot to run this test.")

    model = transformers.DistilBertForSequenceClassification.from_pretrained(model_path, num_labels=2)
    tokenizer = transformers.DistilBertTokenizer.from_pretrained(model_path)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)

    text = "Kat from Qualio, urgent FDA compliance"
    inputs = tokenizer(text, return_tensors="pt", truncation=True, padding=True, max_length=128)
    inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch.no_grad():
        outputs = model(**inputs)
    assert outputs.logits.shape[-1] == 2