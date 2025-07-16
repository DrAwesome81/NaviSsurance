#!/usr/bin/env python3
"""
Simple test script to verify Ollama is running and Deepseek model is accessible
"""

import requests
import json
import sys

def test_ollama_connection():
    """Test if Ollama server is running"""
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code == 200:
            print("✅ Ollama server is running")
            return True
        else:
            print(f"❌ Ollama server responded with status code: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Cannot connect to Ollama server: {e}")
        print("Make sure Ollama is running on your machine")
        return False

def list_available_models():
    """List all available models in Ollama"""
    try:
        response = requests.get("http://localhost:11434/api/tags")
        response.raise_for_status()
        data = response.json()
        models = [model['name'] for model in data.get('models', [])]
        print(f"📋 Available models: {', '.join(models)}")
        return models
    except Exception as e:
        print(f"❌ Failed to list models: {e}")
        return []

def test_deepseek_model():
    """Test if Deepseek model is available and can generate a response"""
    try:
        # Simple test message
        test_payload = {
            "model": "deepseek-r1:32b",
            "messages": [
                {
                    "role": "user",
                    "content": "Hello! Can you respond with just 'Deepseek is working'?"
                }
            ],
            "stream": False
        }
        
        print("🧪 Testing Deepseek model...")
        response = requests.post(
            "http://localhost:11434/api/chat",
            json=test_payload,
            timeout=120
        )
        response.raise_for_status()
        
        data = response.json()
        result = data.get('message', {}).get('content', '')
        print(f"✅ Deepseek response: {result}")
        return True
        
    except Exception as e:
        print(f"❌ Deepseek test failed: {e}")
        return False

def main():
    print("🔍 Testing Ollama and Deepseek integration...")
    print("=" * 50)
    
    # Test 1: Check if Ollama is running
    if not test_ollama_connection():
        print("\n💡 To start Ollama:")
        print("   - On Windows: Run 'ollama serve' in a terminal")
        print("   - Or start Ollama from your applications")
        sys.exit(1)
    
    # Test 2: List available models
    models = list_available_models()
    
    # Test 3: Check if Deepseek is available
    if not any('deepseek' in model.lower() for model in models):
        print("\n❌ Deepseek model not found in available models")
        print("💡 To download Deepseek:")
        print("   - Run: ollama pull deepseek-r1:32b")
        sys.exit(1)
    
    # Test 4: Test Deepseek functionality
    if test_deepseek_model():
        print("\n🎉 All tests passed! Ollama and Deepseek are working correctly.")
        print("Ready to integrate with NaviSsurance.")
    else:
        print("\n❌ Deepseek model test failed")
        sys.exit(1)

if __name__ == "__main__":
    main() 