"""Exception hierarchy for minilang."""


class MiniLangError(Exception):
    """Base class. ``str(err)`` is the plain message; ``position`` is a 0-based offset or None."""

    def __init__(self, message, position=None):
        super().__init__(message)
        self.message = message
        self.position = position


class LexError(MiniLangError):
    """Raised for malformed input characters or tokens."""


class ParseError(MiniLangError):
    """Raised when the token stream does not match the grammar."""


class EvalError(MiniLangError):
    """Raised when evaluation fails (type errors, undefined names, etc.)."""
