"""
Secure logging utilities to prevent sensitive information from being exposed in logs.
"""

import logging
import re
from typing import Any, Dict, List, Union


def sanitize_sensitive_data(data: Any) -> Any:
    """
    Recursively sanitize sensitive data by masking tokens, keys, and secrets.
    
    Args:
        data: Data to sanitize (dict, list, string, or other types)
        
    Returns:
        Sanitized data with sensitive information masked
    """
    if isinstance(data, dict):
        return {key: _sanitize_dict_value(key, value) for key, value in data.items()}
    elif isinstance(data, list):
        return [sanitize_sensitive_data(item) for item in data]
    elif isinstance(data, str):
        return _sanitize_string(data)
    else:
        return data


def _sanitize_dict_value(key: str, value: Any) -> Any:
    """Sanitize dictionary values based on key names."""
    sensitive_keys = [
        'token', 'key', 'secret', 'password', 'passwd', 'pwd',
        'api_key', 'access_token', 'refresh_token', 'auth_token',
        'client_secret', 'client_id', 'private_key', 'credential',
        'authorization', 'bearer', 'oauth', 'jwt'
    ]
    
    key_lower = key.lower()
    if any(sensitive_key in key_lower for sensitive_key in sensitive_keys):
        return "[REDACTED]"
    
    return sanitize_sensitive_data(value)


def _sanitize_string(text: str) -> str:
    """Sanitize strings by masking potential tokens and keys."""
    if not text or len(text) < 8:
        return text
    
    # Common token patterns (adjust as needed)
    token_patterns = [
        r'[a-zA-Z0-9]{20,}',  # Long alphanumeric strings (potential tokens)
        r'Bearer\s+[a-zA-Z0-9\-_\.]+',  # Bearer tokens
        r'Basic\s+[a-zA-Z0-9+/=]+',  # Basic auth tokens
        r'eyJ[a-zA-Z0-9\-_\.]+',  # JWT tokens (start with eyJ)
        r'sk-[a-zA-Z0-9]{20,}',  # OpenAI API keys
        r'pk_[a-zA-Z0-9]{20,}',  # Stripe keys
        r'[a-zA-Z0-9]{32,}',  # Generic long tokens
    ]
    
    sanitized = text
    for pattern in token_patterns:
        sanitized = re.sub(pattern, '[REDACTED]', sanitized, flags=re.IGNORECASE)
    
    return sanitized


class SecureLogger:
    """Wrapper for logger that automatically sanitizes sensitive data."""
    
    def __init__(self, logger_name: str):
        self.logger = logging.getLogger(logger_name)
        self.original_level = self.logger.level
    
    def set_secure_level(self, level: int = logging.WARNING):
        """Set logging level to WARNING or higher for sensitive operations."""
        self.logger.setLevel(level)
    
    def restore_level(self):
        """Restore original logging level."""
        self.logger.setLevel(self.original_level)
    
    def secure_log(self, level: int, message: str, *args, **kwargs):
        """Log message with automatic sanitization of sensitive data."""
        # Sanitize any additional data passed as args or kwargs
        sanitized_args = [sanitize_sensitive_data(arg) for arg in args]
        sanitized_kwargs = {k: sanitize_sensitive_data(v) for k, v in kwargs.items()}
        
        self.logger.log(level, message, *sanitized_args, **sanitized_kwargs)
    
    def secure_info(self, message: str, *args, **kwargs):
        """Log INFO level message with sanitization."""
        self.secure_log(logging.INFO, message, *args, **kwargs)
    
    def secure_error(self, message: str, *args, **kwargs):
        """Log ERROR level message with sanitization."""
        self.secure_log(logging.ERROR, message, *args, **kwargs)
    
    def secure_warning(self, message: str, *args, **kwargs):
        """Log WARNING level message with sanitization."""
        self.secure_log(logging.WARNING, message, *args, **kwargs)


def secure_function_logger(func):
    """
    Decorator to automatically set secure logging level for sensitive functions.
    
    Usage:
        @secure_function_logger
        def refresh_token():
            # This function will use WARNING level logging
            pass
    """
    def wrapper(*args, **kwargs):
        # Get logger for the module containing the function
        module_name = func.__module__
        logger = logging.getLogger(module_name)
        
        # Store original level
        original_level = logger.level
        
        try:
            # Set to WARNING level for sensitive operations
            logger.setLevel(logging.WARNING)
            return func(*args, **kwargs)
        finally:
            # Restore original level
            logger.setLevel(original_level)
    
    return wrapper


# Convenience function for quick sanitization
def safe_log(logger: logging.Logger, level: int, message: str, *args, **kwargs):
    """Quick function to log with automatic sanitization."""
    sanitized_args = [sanitize_sensitive_data(arg) for arg in args]
    sanitized_kwargs = {k: sanitize_sensitive_data(v) for k, v in kwargs.items()}
    logger.log(level, message, *sanitized_args, **sanitized_kwargs)


