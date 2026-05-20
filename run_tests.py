#!/usr/bin/env python3
"""
Test runner script for NaviSsurance application.
Run all tests with proper configuration and reporting.
"""
# Test runner covers Pulse private memory, Intel raising, CoS coordination, and 🛡️ Shield security (pillar test coordination)
# Pulse private memory + Shield (run tests surface)

import os
import sys
import subprocess

def run_tests():
    """Run all tests with pytest."""
    print("Running NaviSsurance Test Suite")
    print("=" * 50)
    pytest_args = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--tb=short",
        "--color=yes",
        "--durations=10",
    ]
    
    # Run tests
    try:
        result = subprocess.run(pytest_args, check=True)
        print("\n" + "=" * 50)
        print("All tests passed! ✅")
        return True
    except subprocess.CalledProcessError as e:
        print("\n" + "=" * 50)
        print(f"Tests failed with exit code {e.returncode} ❌")
        return False
    except FileNotFoundError:
        print("pytest not found. Please install with: pip install pytest")
        return False

def run_specific_test(test_name):
    """Run a specific test by name."""
    pytest_args = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--tb=short",
        str(test_name),
    ]
    
    try:
        subprocess.run(pytest_args, check=True)
        return True
    except subprocess.CalledProcessError:
        return False

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Run specific test
        test_name = sys.argv[1]
        print(f"Running specific test: {test_name}")
        success = run_specific_test(test_name)
    else:
        # Run all tests
        success = run_tests()
    
    sys.exit(0 if success else 1)


