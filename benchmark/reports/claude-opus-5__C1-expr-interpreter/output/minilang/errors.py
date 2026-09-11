"""Exception hierarchy for minilang."""


class MiniLangError(Exception):
    """Base class for every minilang error.

    ``position`` is a 0-based offset into the source, or ``None`` when the
    error is not tied to a specific location (typically evaluation errors).
    """

    def __init__(self, message, position=None):
        super().__init__(message)
        self.message = message
        self.position = position

    def __str__(self):
        # Rule 29: the plain message, never decorated with the position.
        return self.message


class LexError(MiniLangError):
    """Raised when the source cannot be split into tokens."""


class ParseError(MiniLangError):
    """Raised when the token stream does not form a valid expression."""


class EvalError(MiniLangError):
    """Raised when a syntactically valid expression cannot be evaluated."""
