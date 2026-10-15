"""Errors from a historical source. No response bodies are stored."""


class HistoricalSourceError(RuntimeError):
    """A historical request could not be used. The message is safe to show."""
