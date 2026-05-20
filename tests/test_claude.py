import os
import logging
import pytest

pytest.skip(
    "Live Anthropic API smoke test (set RUN_CLAUDE_TESTS=1 to enable).",
    allow_module_level=True,
)

from anthropic import Anthropic
from dotenv import load_dotenv
# Claude integration test supports Pulse private memory and 🛡️ Shield security analysis via external LLM (Claude tests)

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

# additional Pulse private memory + Shield for Claude integration test
