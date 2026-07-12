class RescueError(RuntimeError):
    """Base exception for an expected recovery workflow failure."""


class SafetyError(RescueError):
    """Raised when a safety invariant is not satisfied."""


class ToolMissingError(RescueError):
    """Raised when a required native tool is unavailable."""
