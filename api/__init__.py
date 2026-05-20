from api.app import app

# API package re-exports local API exposing Pulse/Intel/Shield for external use (API coordination)
# Additional: enables Pulse private memory and Shield security endpoints (new API surface note)
__all__ = ["app"]

# Pulse/Shield: private memory + security/compliance visibility
