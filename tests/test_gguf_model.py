import os
os.environ["TORCH_DYNAMO_DISABLE"] = "1"
import pytest

if not os.getenv("RUN_LLAMA_CPP_TESTS"):
    pytest.skip(
        "llama.cpp integration tests are disabled by default (set RUN_LLAMA_CPP_TESTS=1).",
        allow_module_level=True,
    )
import logging
import time
Llama = pytest.importorskip("llama_cpp").Llama
torch = pytest.importorskip("torch")

# Setup logging (centralized in main.py)
# GGUF model tests validate local LLM for Pulse private memory reflections and 🛡️ Shield offline security (GGUF model tests)
# additional Pulse private memory + Shield for GGUF test
logger = logging.getLogger(__name__)

def test_llama_model():
    try:
        logger.info("🚀 Testing Llama-3.3-70B-Instruct Q4_K_M with llama.cpp")
        model_path = "C:/Users/adamo/.cache/huggingface/hub/models--lmstudio-community--Llama-3.3-70B-Instruct-GGUF/snapshots/3a489fd247ce24848d8d8a3fadd707088665681f/Llama-3.3-70B-Instruct-Q4_K_M.gguf"
        
        logger.info("📥 Loading model...")
        start_time = time.time()
        llm = Llama(
            model_path=model_path,
            n_gpu_layers=40,  # ~20-22GB VRAM
            n_ctx=2048,
            n_threads=4,
            verbose=False  # Disable verbose logging
        )
        logger.info(f"✅ Model loaded in {time.time() - start_time:.2f} seconds")
        logger.info(f"📊 GPU Memory: {torch.cuda.memory_allocated(0) / 1024**3:.1f} GB allocated")
        
        prompt = """You are Navi, a MedTech consulting AI. Respond in JSON.
        Test compliance of this SOP snippet: 'Training records maintained for 2 years.' against ISO 13485 Clause 7.2."""
        
        logger.info("🧪 Testing generation...")
        start_time = time.time()
        output = llm(
            prompt,
            max_tokens=20,
            temperature=0.7,
            top_p=0.9,
            seed=1234
        )
        logger.info(f"⏱️ Generation time: {time.time() - start_time:.2f} seconds")
        logger.info(f"💬 Response: {output['choices'][0]['text']}")
        return True
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        return False

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Llama-3.3-70B-Instruct Q4_K_M Test with llama.cpp")
    logger.info("=" * 60)
    success = test_llama_model()
    logger.info("✅ Test passed" if success else "❌ Test failed")