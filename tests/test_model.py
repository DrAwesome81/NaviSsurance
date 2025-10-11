import os
os.environ["TORCH_DYNAMO_DISABLE"] = "1"

#!/usr/bin/env python3
"""
Simple test script for LLaMA-3.3-70B-Instruct model with 4-bit quantization
"""

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
import logging
import time
import sys

# Setup logging (centralized in main.py)
logger = logging.getLogger(__name__)

def test_llama_model():
    """Test the LLaMA-3.3-70B-Instruct model with 4-bit quantization"""
    
    model_name = "meta-llama/Llama-3.3-70B-Instruct"
    
    try:
        logger.info("🚀 Starting LLaMA-3.3-70B-Instruct model test with 4-bit quantization")
        
        # Check CUDA availability
        if not torch.cuda.is_available():
            logger.error("❌ CUDA is not available. Please ensure CUDA is properly installed.")
            return False
            
        logger.info(f"✅ CUDA available: {torch.cuda.get_device_name(0)}")
        logger.info(f"📊 GPU Memory: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")
        
        # Configure 4-bit quantization
        quantization_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
        )
        
        logger.info("📥 Loading tokenizer...")
        start_time = time.time()
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        logger.info(f"✅ Tokenizer loaded in {time.time() - start_time:.2f} seconds")
        
        # Create device map for GPU/CPU distribution
        device_map = {
            'model.embed_tokens': 'cuda:0',
            'model.norm': 'cuda:0',
            'lm_head': 'cuda:0',
        }
        for i in range(50):  # 50 layers on GPU
            device_map[f'model.layers.{i}'] = 'cuda:0'
        for i in range(50, 80):  # 30 on CPU
            device_map[f'model.layers.{i}'] = 'cpu'
        quantization_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
            llm_int8_enable_fp32_cpu_offload=True
        )
        
       
        
        logger.info("📥 Loading model (this may take a few minutes)...")
        start_time = time.time()
        
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            quantization_config=quantization_config,
            device_map=device_map,
            low_cpu_mem_usage=True
        )
        
        load_time = time.time() - start_time
        logger.info(f"✅ Model loaded successfully in {load_time:.2f} seconds")
        
        # Memory usage info
        gpu_memory = torch.cuda.memory_allocated('cuda:0') / 1024**3
        gpu_reserved = torch.cuda.memory_reserved('cuda:0') / 1024**3
        logger.info(f"📊 GPU Memory Usage: {gpu_memory:.2f} GB allocated, {gpu_reserved:.2f} GB reserved")
        
        # Llama 3.3 has 80 layers like Llama 2, but let's verify the layer count
        logger.info(f"🔍 Model architecture: {model.config.model_type}")
        logger.info(f"🔍 Number of layers: {model.config.num_hidden_layers}")
        
        # Test generation
        logger.info("🧪 Testing model generation...")
        
        # First, test with a very simple prompt
        logger.info("🧪 Simple test first...")
        simple_prompt = "Hello"
        logger.info(f"📝 Simple test: {simple_prompt}")
        
        start_time = time.time()
        inputs = tokenizer(simple_prompt, return_tensors="pt").to('cuda:0')
        
        with torch.inference_mode():
            outputs = model.generate(
                **inputs,
                max_new_tokens=50,  # Just 10 tokens
                temperature=0.7,
                do_sample=True,
                pad_token_id=tokenizer.eos_token_id
            )
        
        response = tokenizer.decode(outputs[0], skip_special_tokens=True)
        generation_time = time.time() - start_time
        logger.info(f"⏱️  Simple test time: {generation_time:.2f} seconds")
        logger.info(f"💬 Simple response: {response}")
        logger.info("-" * 50)
        
        test_prompts = [
            "Hello, how are you today?",
            "Explain quantum computing in simple terms:",
            "Write a short poem about artificial intelligence:"
        ]
        
        for i, prompt in enumerate(test_prompts, 1):
            logger.info(f"📝 Test {i}: {prompt}")
            
            start_time = time.time()
            
            # Tokenize and generate with more conservative settings
            logger.info("🔧 Tokenizing input...")
            inputs = tokenizer(prompt, return_tensors="pt").to('cuda:0')
            logger.info(f"🔧 Input tokens: {inputs['input_ids'].shape}")
            
            logger.info("🔧 Starting generation...")
            with torch.inference_mode():
                outputs = model.generate(
                    **inputs,
                    max_new_tokens=50,  # Generate only 50 new tokens
                    temperature=0.7,
                    top_p=0.9,
                    do_sample=True,
                    pad_token_id=tokenizer.eos_token_id,
                    eos_token_id=tokenizer.eos_token_id,
                    use_cache=True
                )
            
            logger.info("🔧 Decoding response...")
            response = tokenizer.decode(outputs[0], skip_special_tokens=True)
            generation_time = time.time() - start_time
            
            logger.info(f"⏱️  Generation time: {generation_time:.2f} seconds")
            logger.info(f"💬 Response: {response}")
            logger.info("-" * 50)
        
        logger.info("🎉 Model test completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error during model test: {str(e)}")
        return False

def main():
    """Main function to run the test"""
    logger.info("=" * 60)
    logger.info("LLaMA-3.3-70B-Instruct Model Test with 4-bit Quantization")
    logger.info("=" * 60)
    
    success = test_llama_model()
    
    if success:
        logger.info("✅ All tests passed! Your model is working correctly.")
        sys.exit(0)
    else:
        logger.error("❌ Tests failed. Please check the error messages above.")
        sys.exit(1)

if __name__ == "__main__":
    main() 