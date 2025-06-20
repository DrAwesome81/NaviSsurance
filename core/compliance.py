import PyPDF2
import requests
from bs4 import BeautifulSoup
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class ComplianceChecker:
    def __init__(self, chat_handler=None):
        self.chat_handler = chat_handler
    
    def run_compliance_check(self, ref_items, assess_items, session_id, conversation_history):
        """
        Run compliance check on reference and assessed documents.
        
        Args:
            ref_items: List of reference document paths/URLs
            assess_items: List of assessed document paths/URLs
            session_id: Session ID for chat history
            conversation_history: Current conversation history
            
        Returns:
            dict: Results with success status and data/error message
        """
        if not ref_items or not assess_items:
            return {
                "success": False,
                "error": "Please add at least one reference and one assessed document."
            }

        try:
            documents = []
            
            # Process all documents (reference + assessed)
            for item in ref_items + assess_items:
                if item.startswith("http"):
                    try:
                        response = requests.get(item, timeout=10)
                        soup = BeautifulSoup(response.text, "html.parser")
                        text = soup.get_text()
                        documents.append({"type": "url", "content": text, "source": item})
                    except Exception as e:
                        return {
                            "success": False,
                            "error": f"Error fetching URL {item}: {str(e)}"
                        }
                else:
                    try:
                        with open(item, "rb") as f:
                            pdf = PyPDF2.PdfReader(f)
                            text = "".join(page.extract_text() for page in pdf.pages)
                            documents.append({"type": "file", "content": text, "source": item})
                    except Exception as e:
                        return {
                            "success": False,
                            "error": f"Error reading file {item}: {str(e)}"
                        }

            # Separate reference and assessed documents
            ref_docs = [d for d in documents if d["source"] in ref_items]
            assess_docs = [d for d in documents if d["source"] in assess_items]
            
            # Build prompt for analysis
            prompt = (
                f"Compare the following assessed documents against the reference documents. "
                f"Identify non-compliant sections or areas for improvement, citing specific clauses. "
                f"Return a JSON array: [{{\"section\": str, \"issue\": str, \"fix\": str, \"reference\": str}}].\n\n"
                f"Reference Documents:\n"
            )
            
            # Add reference document content
            for doc in ref_docs:
                prompt += f"\nDocument: {doc['source']}\nContent:\n{doc['content']}\n"
            
            prompt += f"\nAssessed Documents:\n"
            
            # Add assessed document content
            for doc in assess_docs:
                prompt += f"\nDocument: {doc['source']}\nContent:\n{doc['content']}\n"
            
            prompt += "\nIMPORTANT: Do not perform any Dropbox searches. Only analyze the documents provided above."

            # Call chat handler for analysis
            if self.chat_handler:
                response = self.chat_handler.get_response(prompt, session_id, conversation_history)
                
                # Parse JSON response
                try:
                    # Extract JSON from response
                    json_str = None
                    start_idx = response.find('[')
                    end_idx = response.rfind(']') + 1
                    if start_idx != -1 and end_idx > 0:
                        json_str = response[start_idx:end_idx]
                        logger.info(f"Found JSON string: {json_str}")
                        
                        # Clean up the JSON string
                        json_str = json_str.strip()
                        json_str = json_str.replace('```json', '').replace('```', '')
                        logger.info(f"Cleaned JSON string: {json_str}")
                        
                        results = json.loads(json_str)
                        logger.info(f"Parsed results: {results}")
                        
                        if not isinstance(results, list):
                            raise ValueError("Response is not a JSON array")
                    else:
                        raise ValueError("No JSON array found in response")
                    
                    return {
                        "success": True,
                        "data": results,
                        "raw_response": response
                    }
                    
                except Exception as e:
                    logger.error(f"Error processing results: {e}")
                    logger.error(f"Raw response: {response}")
                    return {
                        "success": False,
                        "error": f"Error processing results: {str(e)}",
                        "raw_response": response
                    }
            else:
                return {
                    "success": False,
                    "error": "Chat handler not available"
                }
                
        except Exception as e:
            logger.error(f"Compliance check error: {e}")
            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}"
            }

class DocumentGenerator:
    def __init__(self, chat_handler=None):
        self.chat_handler = chat_handler
    
    def generate_document(self, template_text, context_docs=None, parameters=None):
        """
        Generate a document based on template and context.
        
        Args:
            template_text: Document template
            context_docs: List of context documents
            parameters: Dictionary of parameters to fill in template
            
        Returns:
            dict: Results with success status and generated document/error
        """
        try:
            # Build prompt for document generation
            prompt = "Generate a professional document based on the following template and context.\n\n"
            
            if context_docs:
                prompt += "Reference Documents:\n"
                for doc in context_docs:
                    prompt += f"- {doc}\n"
                prompt += "\n"
            
            if parameters:
                prompt += "Parameters:\n"
                for key, value in parameters.items():
                    prompt += f"{key}: {value}\n"
                prompt += "\n"
            
            prompt += f"Template:\n{template_text}\n\nGenerate the document:"
            
            # Call chat handler for generation
            if self.chat_handler:
                response = self.chat_handler.get_response(prompt, "doc_gen", [])
                return {
                    "success": True,
                    "data": response
                }
            else:
                return {
                    "success": False,
                    "error": "Chat handler not available"
                }
                
        except Exception as e:
            logger.error(f"Document generation error: {e}")
            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}"
            } 