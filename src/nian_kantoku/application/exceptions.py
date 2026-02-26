class NianKantokuError(Exception):
    """Base exception for this project."""


class ConfigError(NianKantokuError):
    """Raised for invalid or missing configuration."""


class StoryboardParseError(NianKantokuError):
    """Raised when storyboard JSON cannot be parsed."""


class StoryboardRegenerationError(NianKantokuError):
    """Raised when storyboard regeneration does not converge."""


class PipelineExecutionError(NianKantokuError):
    """Raised when the runtime pipeline fails."""


class MissingDependencyError(NianKantokuError):
    """Raised when a required runtime dependency is missing."""
