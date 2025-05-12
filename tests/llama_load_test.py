from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
import torch
import logging
from typing import List, Dict, Optional
import json

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DocumentProcessor:
    def __init__(self):
        self.model_name = "meta-llama/Llama-2-70b-hf"
        self.quantization_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
            llm_int8_enable_fp32_cpu_offload=True  # This is the correct parameter for CPU offloading
        )
        self.tokenizer = None
        self.model = None
        self.max_length = 4096  # Increased context window
        
    def initialize_model(self):
        """Initialize the LLaMA model with proper error handling"""
        try:
            logger.info("Loading tokenizer...")
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_name,
                token="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"
            )
            logger.info("Tokenizer loaded successfully")
            
            # Create custom device map
            device_map = {
                'model.embed_tokens': 'cuda:0',  # Keep embeddings on GPU
                'model.norm': 'cuda:0',          # Keep normalization on GPU
                'lm_head': 'cuda:0',             # Keep language model head on GPU
            }
            
            # Distribute transformer layers
            n_layers = 80  # LLaMA-70B has 80 layers
            gpu_layers = n_layers // 3  # Put ~1/3 of layers on GPU
            
            logger.info(f"Configuring device map for {n_layers} layers")
            logger.info(f"Placing {gpu_layers} layers on GPU")
            
            # First third of attention layers on GPU
            for i in range(gpu_layers):
                device_map[f'model.layers.{i}'] = 'cuda:0'
                if i % 10 == 0:  # Log every 10 layers
                    logger.info(f"Configured layer {i} for GPU")
            
            # Rest on CPU
            for i in range(gpu_layers, n_layers):
                device_map[f'model.layers.{i}'] = 'cpu'
                if i % 10 == 0:  # Log every 10 layers
                    logger.info(f"Configured layer {i} for CPU")
            
            logger.info("Device map configuration complete")
            logger.info("Starting model loading...")
            
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                quantization_config=self.quantization_config,
                device_map=device_map,  # Use our custom device map
                token="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"
            )
            logger.info("LLaMA-2-70B-4bit loaded successfully!")
            
        except Exception as e:
            logger.error(f"Error loading model: {str(e)}")
            raise

    def process_document(self, 
                        template: str, 
                        context: Optional[List[str]] = None,
                        parameters: Optional[Dict] = None) -> str:
        """
        Process a document template with optional context and parameters
        
        Args:
            template: The document template to fill
            context: Optional list of reference documents
            parameters: Optional dictionary of parameters to fill in template
            
        Returns:
            Generated document text
        """
        if not self.model or not self.tokenizer:
            raise RuntimeError("Model not initialized. Call initialize_model() first.")
            
        try:
            # Prepare the prompt
            prompt = self._prepare_prompt(template, context, parameters)
            
            # Tokenize and generate
            inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
            outputs = self.model.generate(
                **inputs,
                max_length=self.max_length,
                temperature=0.7,
                top_p=0.9,
                do_sample=True,
                pad_token_id=self.tokenizer.eos_token_id
            )
            
            # Decode and clean up
            generated_text = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
            return self._post_process(generated_text)
            
        except Exception as e:
            logger.error(f"Error processing document: {str(e)}")
            raise

    def _prepare_prompt(self, 
                       template: str, 
                       context: Optional[List[str]] = None,
                       parameters: Optional[Dict] = None) -> str:
        """Prepare the prompt with context and parameters"""
        prompt = "You are a medical device documentation expert. Generate a professional document based on the following template and context.\n\n"
        
        if context:
            prompt += "Reference Documents:\n"
            for doc in context:
                prompt += f"- {doc}\n"
            prompt += "\n"
            
        if parameters:
            prompt += "Parameters:\n"
            for key, value in parameters.items():
                prompt += f"{key}: {value}\n"
            prompt += "\n"
            
        prompt += f"Template:\n{template}\n\nGenerate the document:"
        return prompt

    def _post_process(self, text: str) -> str:
        """Clean up and format the generated text"""
        # Remove any remaining template markers
        text = text.replace("{{", "").replace("}}", "")
        # Ensure proper spacing
        text = " ".join(text.split())
        return text

def main():
    # Test the document processor
    processor = DocumentProcessor()
    processor.initialize_model()
    
    # Example usage
    template = """
    Risk Management Plan
    
    Device Name: {{device_name}}
    Manufacturer: {{manufacturer}}
    
    Risk Analysis:
    1. Identify Hazards
    2. Estimate Risk
    3. Control Measures
    
    Risk Evaluation:
    - Probability of Occurrence
    - Severity of Harm
    - Risk Level
    """
    
    parameters = {
        "device_name": "Smart Insulin Pump",
        "manufacturer": "NaviMedical Inc."
    }
    
    try:
        result = processor.process_document(template, parameters=parameters)
        print("\nGenerated Document:")
        print(result)
    except Exception as e:
        logger.error(f"Test failed: {str(e)}")

if __name__ == "__main__":
    main()