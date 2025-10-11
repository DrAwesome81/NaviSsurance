import os
from anthropic import Anthropic
import logging
from dotenv import load_dotenv

# Load environment variables using centralized paths
from config import CONFIG_DIR
load_dotenv(os.path.join(CONFIG_DIR, '.env'))

# Setup logging (centralized in main.py)
logger = logging.getLogger(__name__)

def test_claude_api():
    try:
        # Initialize Claude client
        api_key = os.getenv('ANTHROPIC_API_KEY', '')
        if not api_key:
            logger.error("Anthropic API key not found.")
            return
        
        client = Anthropic(api_key=api_key)
        
        # Simple test message
        response = client.messages.create(
            model="claude-3-7-sonnet-20250219",
            max_tokens=100,
            messages=[{
                "role": "user",
                "content": "Say hello and confirm you can access the web search tool."
            }],
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search"
            }]
        )
        
        logger.info("API Response:")
        logger.info(f"Response type: {type(response)}")
        logger.info(f"Response content: {response.content}")
        
    except Exception as e:
        logger.error(f"Error testing Claude API: {e}")

if __name__ == "__main__":
    test_claude_api() 