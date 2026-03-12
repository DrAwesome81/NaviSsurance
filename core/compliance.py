import requests
from bs4 import BeautifulSoup
import json
import logging
import re
from core.file_handler import extract_text_from_file
from core.grok_client import grok_available, grok_completion

logger = logging.getLogger(__name__)


def _extract_text_from_url(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; NaviSsurance/1.0; +https://navisure.com)"
    }
    response = requests.get(url, timeout=20, headers=headers)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    text = soup.get_text("\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _looks_like_worker_failure(response_text: str) -> bool:
    text = (response_text or "").strip().lower()
    return (
        not text
        or "local ai's acting up" in text
        or "model not loaded" in text
        or text.startswith("error:")
    )


def _repair_key_alignments_json_shape(json_str: str) -> str:
    """
    Repair a common malformed model output shape where ``key_alignments`` is
    emitted as multiple adjacent quoted strings instead of one JSON value:

    {"key_alignments":"item 1","item 2","item 3","improvements":[...]}

    We collapse those strings into a single newline-separated string so the
    payload becomes valid JSON.
    """
    key_marker = '"key_alignments"'
    next_marker = '"improvements"'
    key_idx = json_str.find(key_marker)
    next_idx = json_str.find(next_marker, key_idx + len(key_marker))
    if key_idx < 0 or next_idx < 0:
        return json_str

    colon_idx = json_str.find(":", key_idx + len(key_marker))
    if colon_idx < 0 or colon_idx > next_idx:
        return json_str

    middle = json_str[colon_idx + 1:next_idx]
    decoder = json.JSONDecoder()
    strings = []
    pos = 0
    while pos < len(middle):
        while pos < len(middle) and middle[pos] in " \t\r\n,":
            pos += 1
        if pos >= len(middle):
            break
        if middle[pos] != '"':
            return json_str
        try:
            value, consumed = decoder.raw_decode(middle[pos:])
        except json.JSONDecodeError:
            return json_str
        if not isinstance(value, str):
            return json_str
        strings.append(value)
        pos += consumed

    if not strings:
        return json_str

    joined = "\n".join(s for s in strings if s.strip())
    rebuilt = (
        json_str[:key_idx]
        + f'{key_marker}: '
        + json.dumps(joined, ensure_ascii=False)
        + ", "
        + json_str[next_idx:]
    )
    return rebuilt


def _parse_compliance_json_response(response_text: str) -> dict:
    cleaned_response = re.sub(r"```json|```", "", response_text).strip()

    start = cleaned_response.find("{")
    json_str = None
    if start >= 0:
        depth = 0
        for i in range(start, len(cleaned_response)):
            c = cleaned_response[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    json_str = cleaned_response[start:i + 1]
                    break
    if not json_str:
        raise ValueError("No JSON object found in response")

    logger.info("Extracted JSON string: %s", json_str)
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        repaired = _repair_key_alignments_json_shape(json_str)
        if repaired != json_str:
            logger.info("Repaired malformed key_alignments JSON shape")
            return json.loads(repaired)
        raise

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

    def check_compliance(self, ref_items, assess_items, session_id, conversation_history):
        """
        Backward-compatible entry point used by the UI thread wrapper.

        Some callers still invoke ``check_compliance(...)`` while the primary
        implementation lives in ``run_compliance_check(...)``.
        """
        return self.run_compliance_check(ref_items, assess_items, session_id, conversation_history)

    def _request_analysis(self, prompt: str, session_id: str, conversation_history):
        """
        Prefer Grok directly for long structured compliance prompts.
        Fall back to the existing chat handler only if Grok is unavailable.
        """
        try:
            ok, _msg = grok_available()
            if ok:
                response = grok_completion(
                    system=(
                        "You are a medical device QA/compliance reviewer. "
                        "Return only a valid JSON object with keys: "
                        "overview, key_alignments, improvements, recommendations."
                    ),
                    user=prompt,
                    model="grok-4-1-fast-reasoning-latest",
                )
                if response and not _looks_like_worker_failure(response):
                    return response
        except Exception as e:
            logger.warning("Direct Grok compliance analysis failed, falling back: %s", e)

        if self.chat_handler:
            return self.chat_handler.get_response(prompt, session_id, conversation_history)
        return ""
    
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
                    text = _extract_text_from_url(item)
                    if not text:
                        raise ValueError("No readable text could be extracted from URL")
                    documents.append({"type": "url", "content": text, "source": item})
                except Exception as e:
                    return {
                        "success": False,
                        "error": f"Error fetching URL {item}: {str(e)}"
                    }
            else:
                try:
                    text = extract_text_from_file(item)
                    if not text or not text.strip():
                        raise ValueError("Unsupported file type or no readable text extracted")
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
            response = self._request_analysis(prompt, session_id, conversation_history)
            if _looks_like_worker_failure(response):
                return {
                    "success": False,
                    "error": "Compliance analysis model did not return a usable response.",
                    "raw_response": response,
                }
            
            # Parse JSON response
            try:
                results = _parse_compliance_json_response(response)
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
            except Exception as e:
                # Fallback to text extraction if no valid JSON could be parsed.
                try:
                    logger.info("JSON parsing failed - attempting post-processing extraction")
                    extracted = self.extract_from_text(response)
                    if extracted:
                        return {
                            "success": True,
                            "data": {"overview": "", "key_alignments": "", "improvements": extracted, "recommendations": ""},
                            "raw_response": response
                        }
                except Exception:
                    pass
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