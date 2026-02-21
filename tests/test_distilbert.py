import os
import pytest

if not os.getenv("RUN_ML_TESTS"):
    pytest.skip("ML tests are disabled by default (set RUN_ML_TESTS=1 to enable).", allow_module_level=True)

transformers = pytest.importorskip("transformers")
torch = pytest.importorskip("torch")


def test_distilbert_loads_from_hf_cache():
    model_path = os.getenv("DISTILBERT_MODEL_PATH")
    if not model_path or not os.path.exists(model_path):
        pytest.skip("Set DISTILBERT_MODEL_PATH to a local model snapshot to run this test.")

    model = transformers.DistilBertForSequenceClassification.from_pretrained(model_path)
    tokenizer = transformers.DistilBertTokenizer.from_pretrained(model_path)
    assert model is not None
    assert tokenizer is not None