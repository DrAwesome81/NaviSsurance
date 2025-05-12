from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
import torch
import logging
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_inference():
    try:
        # Initialize model and tokenizer
        model_name = "meta-llama/Llama-2-70b-hf"
        
        # Configure 4-bit quantization
        quantization_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
            llm_int8_enable_fp32_cpu_offload=True  # Re-enable CPU offload for quantization to handle memory constraints
        )
        
        logger.info("Note: Even with 4-bit quantization, LLaMA-70B may require ~35GB, slightly over 32GB VRAM limit. Monitoring memory usage.")
        logger.info("Note: Adding detailed debugging logs to identify hanging issue during inference. VRAM and RAM not maxing out as per user observation (VRAM: 28.4/32GB, RAM: 51.9/64GB).")
        
        logger.info("Loading tokenizer...")
        start_time_tokenizer = time.time()
        tokenizer = AutoTokenizer.from_pretrained(
            model_name,
            token="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"
        )
        logger.info(f"Tokenizer loaded in {time.time() - start_time_tokenizer:.2f} seconds")
        
        # Create custom device map with more layers on GPU
        device_map = {
            'model.embed_tokens': 'cuda:0',
            'model.norm': 'cuda:0',
            'lm_head': 'cuda:0',
        }
        
        # Distribute transformer layers - put more on GPU
        n_layers = 80  # LLaMA-70B has 80 layers
        gpu_layers = 60  # Put 60 layers on GPU, only 20 on CPU
        
        logger.info(f"Configuring device map for {n_layers} layers")
        logger.info(f"Placing {gpu_layers} layers on GPU")
        
        # First 60 attention layers on GPU
        for i in range(gpu_layers):
            device_map[f'model.layers.{i}'] = 'cuda:0'
            if i % 10 == 0:  # Log every 10 layers
                logger.info(f"Configured layer {i} for GPU")
        
        # Last 20 on CPU
        for i in range(gpu_layers, n_layers):
            device_map[f'model.layers.{i}'] = 'cpu'
            if i % 10 == 0:  # Log every 10 layers
                logger.info(f"Configured layer {i} for CPU")
        
        logger.info("Device map configuration complete")
        logger.info("Starting model loading...")
        start_time_model = time.time()
        logger.info("Step 1: Initializing model loading with AutoModelForCausalLM.from_pretrained")
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            quantization_config=quantization_config,
            device_map=device_map,
            token="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",
            low_cpu_mem_usage=True  # Optimize CPU memory usage during loading
        )
        load_time = time.time() - start_time_model
        logger.info(f"Step 2: Model loading completed in {load_time:.2f} seconds")
        
        # Simple prompt to test generation
        prompt = "The following is a conversation between a human and an AI assistant. The assistant is helpful, creative, clever, and very friendly.\n\nHuman: Hello, who are you?\nAssistant:"
        
        logger.info("Generating response...")
        # Generate response with proper tensor handling
        logger.info("Debug Step 1: Tokenizing input prompt")
        start_time_tokenize = time.time()
        inputs = tokenizer(prompt, return_tensors="pt")
        logger.info(f"Debug Step 2: Tokenization completed in {time.time() - start_time_tokenize:.2f} seconds")
        logger.info("Debug Step 3: Moving inputs to GPU")
        start_time_move_inputs = time.time()
        inputs = {k: v.to('cuda:0') for k, v in inputs.items()}
        logger.info(f"Debug Step 4: Inputs moved to GPU in {time.time() - start_time_move_inputs:.2f} seconds")
        
        # Clear GPU cache before generation
        torch.cuda.empty_cache()
        logger.info(f"Debug Step 5: GPU cache cleared")
        logger.info(f"GPU memory allocated: {torch.cuda.memory_allocated('cuda:0') / 1024**3:.2f} GB")
        logger.info(f"GPU memory reserved: {torch.cuda.memory_reserved('cuda:0') / 1024**3:.2f} GB")
        
        logger.info("Starting generation step for technical document content...")
        logger.info("Debug Step 6: Entering torch.inference_mode context")
        start_time_inference = time.time()
        with torch.inference_mode():
            # Generate with optimized settings for longer outputs
            logger.info("Debug Step 7: Beginning model.generate call")
            start_time_generate = time.time()
            logger.info("Debug Step 7.1: Preparing model inputs for generation")
            logger.info(f"Debug Step 7.2: Input tensor shapes: {[inputs[k].shape for k in inputs]}")
            logger.info("Debug Step 7.3: Starting generation loop")
            outputs = model.generate(
                **inputs,
                max_length=1000,  # Increased for technical document generation
                temperature=0.7,
                top_p=0.9,
                do_sample=True,
                pad_token_id=tokenizer.eos_token_id,
                use_cache=True,  # Enable KV cache for efficiency
                return_dict_in_generate=True,  # More efficient memory handling
                output_scores=False  # Don't compute scores to save memory
            )
            logger.info(f"Debug Step 8: model.generate call completed in {time.time() - start_time_generate:.2f} seconds")
        logger.info(f"Debug Step 9: Inference mode exited, total inference time: {time.time() - start_time_inference:.2f} seconds")
        logger.info("Generation completed.")
        
        # Decode and print
        response = tokenizer.decode(outputs.sequences[0], skip_special_tokens=True)
        print("\nModel Response:")
        print(response)
        
        logger.info("Note: Adjusted device map to place 60 layers on GPU to minimize CPU-GPU transfers, testing if this resolves hang at set_module_tensor_to_device.")
        logger.info("Recommendation: Ensure accelerate, transformers, and PyTorch are up-to-date and compatible with CUDA version on RTX 5090.")
        
    except Exception as e:
        logger.error(f"Error during inference: {str(e)}")
        raise

if __name__ == "__main__":
    test_inference() 