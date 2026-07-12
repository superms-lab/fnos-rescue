class RescueError(RuntimeError):
    """Base exception for an expected recovery workflow failure."""


class SafetyError(RescueError):
    """Raised when a safety invariant is not satisfied."""


class ToolMissingError(RescueError):
    """Raised when a required native tool is unavailable."""


class JobControlRequested(RescueError):
    """Raised after a running native process is stopped by pause or cancel."""

    def __init__(self, action: str):
        super().__init__(f"job control requested: {action}")
        self.action = action
