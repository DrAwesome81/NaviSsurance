"""
Test script to demonstrate the improved system prompt functionality.
Shows how to test with mock dates and verify prompt generation.
"""

from datetime import datetime, timedelta
from config import get_system_prompt

def test_system_prompt_with_current_date():
    """Test system prompt generation with current date."""
    print("=== Testing with Current Date ===")
    prompt = get_system_prompt()
    
    print(f"Role: {prompt['role']}")
    print(f"Content length: {len(prompt['content'])} characters")
    print(f"Contains date: {'Today is' in prompt['content']}")
    
    # Extract date from prompt
    content = prompt['content']
    date_start = content.find("Today is ") + 9
    date_end = content.find(".", date_start)
    extracted_date = content[date_start:date_end]
    print(f"Extracted date: {extracted_date}")
    print()

def test_system_prompt_with_mock_date():
    """Test system prompt generation with a specific mock date."""
    print("=== Testing with Mock Date (New Year's Day) ===")
    mock_date = datetime(2024, 1, 1)  # New Year's Day
    prompt = get_system_prompt(mock_date)
    
    content = prompt['content']
    date_start = content.find("Today is ") + 9
    date_end = content.find(".", date_start)
    extracted_date = content[date_start:date_end]
    
    print(f"Mock date used: {mock_date.strftime('%B %d, %Y')}")
    print(f"Date in prompt: {extracted_date}")
    print(f"Dates match: {extracted_date == mock_date.strftime('%B %d, %Y')}")
    print()

def test_system_prompt_with_yesterday():
    """Test system prompt generation with yesterday's date."""
    print("=== Testing with Yesterday's Date ===")
    yesterday = datetime.now() - timedelta(days=1)
    prompt = get_system_prompt(yesterday)
    
    content = prompt['content']
    date_start = content.find("Today is ") + 9
    date_end = content.find(".", date_start)
    extracted_date = content[date_start:date_end]
    
    print(f"Yesterday used: {yesterday.strftime('%B %d, %Y')}")
    print(f"Date in prompt: {extracted_date}")
    print()

def test_prompt_content_sections():
    """Test that all required sections are present in the prompt."""
    print("=== Testing Prompt Content Sections ===")
    prompt = get_system_prompt()
    content = prompt['content']
    
    required_sections = [
        "You are Navi",
        "NaviSure Consulting",
        "Dr. Adam Odeh",
        "ADD_TASK:",
        "WEB_SEARCH:",
        "DROPBOX_SEARCH:",
        "Task Management:",
        "Search Commands:",
        "Response Formatting:"
    ]
    
    print("Checking for required sections:")
    for section in required_sections:
        present = section in content
        status = "✓" if present else "✗"
        print(f"  {status} {section}")
    
    print()

def test_prompt_length_and_structure():
    """Test prompt length and basic structure."""
    print("=== Testing Prompt Structure ===")
    prompt = get_system_prompt()
    content = prompt['content']
    
    print(f"Total length: {len(content)} characters")
    print(f"Line count: {content.count(chr(10)) + 1}")
    print(f"Has proper role: {prompt.get('role') == 'system'}")
    print(f"Content starts with date: {content.startswith('Today is')}")
    print()

if __name__ == "__main__":
    print("System Prompt Testing Suite")
    print("=" * 50)
    print()
    
    test_system_prompt_with_current_date()
    test_system_prompt_with_mock_date()
    test_system_prompt_with_yesterday()
    test_prompt_content_sections()
    test_prompt_length_and_structure()
    
    print("All tests completed!")
