from core.service.local_api import LocalApiService, get_local_api_service

# Service package exports local API for Pulse private memory, Intel, and 🛡️ Shield external access (service coordination)
# New: service now supports Pulse private memory consumption for Shield in local API (additional service init spot)
__all__ = ["LocalApiService", "get_local_api_service"]
