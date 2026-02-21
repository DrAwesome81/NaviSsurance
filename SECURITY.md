# Security Guidelines for NaviSsurance Application

## Overview
This document outlines the security measures implemented to protect sensitive information such as API keys, tokens, and credentials from being exposed in logs or code.

## Security Measures Implemented

### 1. Secure Logging System

#### **Core Secure Logging Module** (`core/secure_logging.py`)
- **Automatic Sanitization**: Automatically masks sensitive data in logs
- **Secure Function Decorator**: Sets logging level to WARNING for sensitive operations
- **Pattern Recognition**: Identifies and masks tokens, keys, and secrets using regex patterns

#### **Supported Sensitive Data Types**:
- API keys (OpenAI, Anthropic, etc.)
- Access tokens (Dropbox, OAuth, JWT)
- Refresh tokens
- Client secrets
- Passwords and credentials
- Bearer tokens
- JWT tokens

### 2. Environment Variable Usage

#### **Before (Insecure)**:
```python
# Hardcoded tokens in source code
token = "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"
```

#### **After (Secure)**:
```python
# Environment variables
token = os.getenv("HUGGINGFACE_TOKEN", "")
```

### 3. Secure Function Decorators

#### **Usage Example**:
```python
from core.secure_logging import secure_function_logger, safe_log

@secure_function_logger
def refresh_dropbox_token():
    """This function automatically uses WARNING level logging"""
    safe_log(logger, logging.INFO, "Refreshing token...")
    # Token data is automatically sanitized
```

### 4. Centralized Logging Configuration

#### **Main Configuration** (`main.py`):
- Single `logging.basicConfig()` call
- All logs go to `logs/app.log`
- Consistent format across all modules
- No conflicting logging configurations

## Files Updated for Security

### **Core Files**:
- `core/api.py`: Secure Dropbox token refresh
- `core/data_fetch.py`: Secure email token handling
- `core/secure_logging.py`: New secure logging utilities

### **Test Files**:
- `tests/llama_load_test.py`: Removed hardcoded HuggingFace token
- `tests/llama_inference_test.py`: Removed hardcoded HuggingFace token

### **Other Files**:
- `build_rag_index.py`: Removed conflicting logging configuration
- `search_rag_index.py`: Removed conflicting logging configuration
- All test files: Standardized logging setup

## Environment Variables Required

Add these to your `.env` file:

```bash
# HuggingFace
HUGGINGFACE_TOKEN=your_huggingface_token_here

# Dropbox (already configured)
DROPBOX_ACCESS_TOKEN=your_dropbox_access_token
DROPBOX_REFRESH_TOKEN=your_dropbox_refresh_token
DROPBOX_APP_KEY=your_dropbox_app_key
DROPBOX_APP_SECRET=your_dropbox_app_secret

# Other API keys
ANTHROPIC_API_KEY=your_anthropic_key
GROK_API_KEY=your_grok_key
```

## Security Best Practices

### **1. Never Log Sensitive Data**:
```python
# BAD
logger.info(f"Token: {access_token}")

# GOOD
safe_log(logger, logging.INFO, "Token refreshed successfully")
```

### **2. Use Secure Decorators for Sensitive Functions**:
```python
@secure_function_logger
def handle_oauth_token():
    # This function automatically uses secure logging
    pass
```

### **3. Environment Variables Only**:
```python
# BAD
api_key = "sk-1234567890abcdef"

# GOOD
api_key = os.getenv("API_KEY", "")
```

### **4. Sanitize User Input**:
```python
# Automatic sanitization
safe_log(logger, logging.INFO, f"Processing data: {user_data}")
```

## Log Output Examples

### **Before (Insecure)**:
```
2024-01-15 10:30:00 - INFO - Token: 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
2024-01-15 10:30:01 - INFO - API Key: sk-1234567890abcdef
```

### **After (Secure)**:
```
2024-01-15 10:30:00 - INFO - Token refreshed successfully
2024-01-15 10:30:01 - INFO - API authentication completed
```

## Monitoring and Maintenance

### **Regular Security Checks**:
1. Search codebase for hardcoded tokens: `grep -r "sk-\|hf_\|pk_" .`
2. Check for direct logging calls: `grep -r "logging\." .`
3. Verify environment variables are used: `grep -r "os.getenv" .`

### **Log File Security**:
- Log files are stored in `logs/` directory
- Ensure proper file permissions (600 or 644)
- Regular log rotation to prevent disk space issues
- Consider encrypting log files in production

## Compliance Notes

- **No sensitive data in logs**: All tokens, keys, and secrets are automatically masked
- **Audit trail**: Secure logging maintains audit trail without exposing credentials
- **Environment isolation**: Sensitive data only in environment variables
- **Function-level security**: Sensitive functions automatically use secure logging

## Emergency Procedures

### **If Credentials Are Compromised**:
1. Immediately revoke/regenerate all affected tokens
2. Update environment variables
3. Check logs for any exposed data
4. Review codebase for other hardcoded credentials

### **Log File Analysis**:
- Use `grep -i "redacted\|token\|key" logs/app.log` to check for potential leaks
- Monitor for any unexpected log entries
- Regular security audits of log files

This security implementation ensures that your application follows industry best practices for credential management and logging security.


