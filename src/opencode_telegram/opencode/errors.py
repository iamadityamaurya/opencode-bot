class OpenCodeError(Exception):
    """Base exception for OpenCode API errors."""

class OpenCodeConnectionError(OpenCodeError):
    """Raised when connection to OpenCode server fails."""

class OpenCodeAuthError(OpenCodeError):
    """Raised on authentication failures."""

class OpenCodeResponseError(OpenCodeError):
    """Raised when OpenCode API returns an error response."""
    def __init__(self, status_code: int, message: str, details: str = ""):
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.message = message
        self.details = details

class OpenCodeSessionNotFoundError(OpenCodeError):
    """Raised when a requested session is not found."""
