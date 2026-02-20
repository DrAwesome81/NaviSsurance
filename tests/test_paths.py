"""
Test script to verify centralized path configuration.
"""

import os
import sys

# Add the project root to Python path (script lives in tests/)
_script_dir = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_script_dir)
sys.path.insert(0, PROJECT_ROOT)

CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")
DATABASE_PATH = os.path.join(PROJECT_ROOT, "naviSsurance_index.db")
ENV_FILE = os.path.join(CONFIG_DIR, ".env")

def test_centralized_paths():
    """Test that all centralized paths are correctly configured."""
    print("=== Testing Centralized Path Configuration ===")
    print()
    
    # Test PROJECT_ROOT
    print(f"PROJECT_ROOT: {PROJECT_ROOT}")
    print(f"  Exists: {os.path.exists(PROJECT_ROOT)}")
    print(f"  Is directory: {os.path.isdir(PROJECT_ROOT)}")
    print()
    
    # Test CONFIG_DIR
    print(f"CONFIG_DIR: {CONFIG_DIR}")
    print(f"  Exists: {os.path.exists(CONFIG_DIR)}")
    print(f"  Is directory: {os.path.isdir(CONFIG_DIR)}")
    print()
    
    # Test LOGS_DIR
    print(f"LOGS_DIR: {LOGS_DIR}")
    print(f"  Exists: {os.path.exists(LOGS_DIR)}")
    print(f"  Is directory: {os.path.isdir(LOGS_DIR)}")
    print()
    
    # Test DATABASE_PATH
    print(f"DATABASE_PATH: {DATABASE_PATH}")
    print(f"  Exists: {os.path.exists(DATABASE_PATH)}")
    print(f"  Is file: {os.path.isfile(DATABASE_PATH)}")
    print()
    
    # Test ENV_FILE
    print(f"ENV_FILE: {ENV_FILE}")
    print(f"  Exists: {os.path.exists(ENV_FILE)}")
    print(f"  Is file: {os.path.isfile(ENV_FILE)}")
    print()
    
    # Test path relationships
    print("=== Testing Path Relationships ===")
    
    # Verify CONFIG_DIR is inside PROJECT_ROOT
    config_relative = os.path.relpath(CONFIG_DIR, PROJECT_ROOT)
    print(f"CONFIG_DIR relative to PROJECT_ROOT: {config_relative}")
    print(f"  Correct: {config_relative == 'config'}")
    
    # Verify LOGS_DIR is inside PROJECT_ROOT
    logs_relative = os.path.relpath(LOGS_DIR, PROJECT_ROOT)
    print(f"LOGS_DIR relative to PROJECT_ROOT: {logs_relative}")
    print(f"  Correct: {logs_relative == 'logs'}")
    
    # Verify DATABASE_PATH is in PROJECT_ROOT
    db_relative = os.path.relpath(DATABASE_PATH, PROJECT_ROOT)
    print(f"DATABASE_PATH relative to PROJECT_ROOT: {db_relative}")
    print(f"  Correct: {db_relative == 'naviSsurance_index.db'}")
    
    # Verify ENV_FILE is in config folder
    env_relative = os.path.relpath(ENV_FILE, PROJECT_ROOT)
    print(f"ENV_FILE relative to PROJECT_ROOT: {env_relative}")
    print(f"  Correct: {env_relative == os.path.join('config', '.env')}")
    print()
    
    # Test path consistency
    print("=== Testing Path Consistency ===")
    
    # All paths should start with PROJECT_ROOT
    paths_to_check = [CONFIG_DIR, LOGS_DIR, DATABASE_PATH, ENV_FILE]
    all_consistent = all(path.startswith(PROJECT_ROOT) for path in paths_to_check)
    print(f"All paths start with PROJECT_ROOT: {all_consistent}")
    
    # Test that we can create relative paths
    test_config_path = os.path.join(PROJECT_ROOT, "config", ".env")
    test_logs_path = os.path.join(PROJECT_ROOT, "logs", "test.log")
    test_db_path = os.path.join(PROJECT_ROOT, "naviSsurance_index.db")
    
    print(f"Manual config path matches CONFIG_DIR: {os.path.dirname(test_config_path) == CONFIG_DIR}")
    print(f"Manual logs path matches LOGS_DIR: {os.path.dirname(test_logs_path) == LOGS_DIR}")
    print(f"Manual db path matches DATABASE_PATH: {test_db_path == DATABASE_PATH}")

if __name__ == "__main__":
    test_centralized_paths()
    print("\nPath configuration test completed!")
