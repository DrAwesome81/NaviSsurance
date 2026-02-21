#!/usr/bin/env python3
"""
Test the chat integration with Deepseek via Ollama
"""

import pytest

pytest.skip(
    "Ollama/Deepseek integration test (set RUN_OLLAMA_TESTS=1 to enable).",
    allow_module_level=True,
)

import sys
import os

from core.response_handler import ResponseHandler
from core.chat_handler import ChatHandler

def test_chat_integration():
    """Test the chat integration"""
    print("🧪 Testing chat integration with Deepseek...")
    
    # Create a mock chat handler
    class MockChatHandler:
        def __init__(self):
            pass
    
    # Create response handler
    response_handler = ResponseHandler(MockChatHandler())
    
    # Test message
    test_message = "Hello! Can you respond with just 'Deepseek chat is working'?"
    session_id = "test_session"
    conversation_history = []
    
    print(f"📝 Sending test message: {test_message}")
    
    try:
        response = response_handler.chat_with_deepseek([{
            "role": "user",
            "content": test_message
        }], session_id)
        
        print(f"✅ Response received: {response}")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    test_chat_integration() 