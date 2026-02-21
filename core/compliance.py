import PyPDF2
import requests
from bs4 import BeautifulSoup
import json
import logging
from pathlib import Path
import re

logger = logging.getLogger(__name__)

class ComplianceChecker:
    def __init__(self, chat_handler=None):
        self.chat_handler = chat_handler
    
    def extract_from_text(self, text):
        print(f"Extracting from text: length = {len(text)}")
        results = []
        # Clean excess newlines/space
        text = re.sub(r'\n{3,}', '\n\n', text).strip()
        
        # Pattern for "1. **Section:** details - bullet - bullet" or "**Section:** details"
        section_pattern = r'(?:\d+\.\s*)?\*\*(.*?):\*\*\s*(.*?)(?=(?:\d+\.\s*)?\*\*|\Z)'
        matches = re.findall(section_pattern, text, re.DOTALL | re.MULTILINE)
        
        for match in matches:
            section = match[0].strip()
            details = match[1].strip()
            
            # For improvements, parse sub-issues if present
            if "improvements" in section.lower():
                imp_pattern = r'\d+\.\s*(.*?)\s*-\s*(.*?)(?=\d+\.\s*|\Z)'
                imp_matches = re.findall(imp_pattern, details, re.DOTALL)
                for imp in imp_matches:
                    imp_section = imp[0].strip()
                    imp_details = imp[1].strip()
                    issue = re.search(r'Issue:\s*(.*?)(?=Correction:|$)', imp_details, re.DOTALL).group(1).strip() if re.search(r'Issue:', imp_details) else imp_details
                    fix = re.search(r'Correction:\s*(.*?)(?=$)', imp_details, re.DOTALL).group(1).strip() if re.search(r'Correction:', imp_details) else "No fix"
                    ref = re.search(r'\(.*?Clause (.*?)\)', imp_details).group(1).strip() if re.search(r'\(.*?Clause', imp_details) else "No reference"
                    results.append({"section": imp_section, "issue": issue, "fix": fix, "reference": ref})
            else:
                issue = details
                fix = "No specific fix suggested"
                reference = "No reference cited"
                results.append({
                    "section": section,
                    "issue": issue,
                    "fix": fix,
                    "reference": reference
                })
        
        logger.info(f"Extracted {len(results)} items from text")
        return results
    
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

        documents = []
        print("Starting document processing...")
        
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
                        print(f"Extracted text from {item}:length = {len(text)}")
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
            f"IMPORTANT: Output ONLY a valid JSON object and NOTHING ELSE. No text, no markdown, no code blocks, no explanations. Start with {{ and end with }}. ALWAYS compare assessed to reference docs. Base ALL on BOTH docs—use EXACT quotes/section names from BOTH for EVERY field. If no matching, 'Not Found'. No inventions—QUOTE BOTH DOCS ONLY.\n\n"
            f"EXAMPLE: {{ \"overview\": \"Assessed quotes 'X' aligns with reference 'Y quote'.\", \"key_alignments\": \"- Assessed 'quote' matches reference 'quote' (section Z).\", \"improvements\": [{{\"section\": \"Assessed exact section\", \"issue\": \"Assessed 'quote' vs reference 'quote'.\", \"fix\": \"Steps quoting both.\", \"reference\": \"Reference exact clause 'quote'.\"}}], \"recommendations\": \"Suggestions quoting both.\" }}\n\n"
            f"Repeat: ALWAYS quote/com pare BOTH docs extensively. No hallucinations.\n\n"
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
                # Extract full JSON object, ignoring code blocks
                # First, remove code block markers if present
                cleaned_response = re.sub(r'```json|```', '', response).strip()
                
                # Find outermost { ... } with balanced braces (handles nested objects/arrays)
                start = cleaned_response.find('{')
                json_str = None
                if start >= 0:
                    depth = 0
                    for i in range(start, len(cleaned_response)):
                        c = cleaned_response[i]
                        if c == '{':
                            depth += 1
                        elif c == '}':
                            depth -= 1
                            if depth == 0:
                                json_str = cleaned_response[start:i + 1]
                                break
                if json_str:
                    logger.info(f"Extracted JSON string: {json_str}")
                    results = json.loads(json_str)
                    logger.info(f"Parsed results: {results}")
                    
                    if not isinstance(results, dict):
                        raise ValueError("Extracted data is not a JSON object")
                    
                    # Validate required keys
                    if 'improvements' not in results or not isinstance(results['improvements'], list):
                        raise ValueError("Missing or invalid 'improvements' array")
                    
                    return {
                        "success": True,
                        "data": results,
                        "raw_response": response
                    }
                else:
                    # Fallback to text extraction if no JSON
                    logger.info("No JSON found - attempting post-processing extraction")
                    results = self.extract_from_text(response)
                    if results:
                        return {
                            "success": True,
                            "data": {"overview": "", "key_alignments": "", "improvements": results, "recommendations": ""},
                            "raw_response": response
                        }
                    else:
                        raise ValueError("No extractable data found in response")
            except Exception as e:
                logger.error(f"Error processing results: {e}")
                logger.error(f"Raw response: {response}")
                return {
                    "success": False,
                    "error": f"Error processing results: {str(e)}",
                    "raw_response": response
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